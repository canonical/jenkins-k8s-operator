#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import logging
import typing

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

import agent
import auth_proxy
import ingress
import jenkins
import pebble
import precondition
import storage
import timerange
from state import (
    AGENT_RELATION,
    AUTH_PROXY_RELATION,
    INGRESS_RELATION_NAME,
    JENKINS_SERVICE_NAME,
    CharmConfigInvalidError,
    CharmIllegalNumUnitsError,
    CharmRelationDataInvalidError,
    State,
)

logger = logging.getLogger(__name__)


class JenkinsK8sOperatorCharm(ops.CharmBase):
    """Charmed Jenkins."""

    def __init__(self, *args: typing.Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the charm base.

        Raises:
            RuntimeError: if invalid state value was encountered from relation.
        """
        super().__init__(*args)

        self.storage = storage.Reconciler(charm=self)
        # Ingress dedicated to agent discovery
        self.agent_discovery_ingress_observer = ingress.Observer(
            self,
            "agent-discovery-ingress-observer",
            agent.AGENT_DISCOVERY_INGRESS_RELATION_NAME,
        )
        self.ingress_observer = ingress.Observer(self, "ingress-observer", INGRESS_RELATION_NAME)
        self.jenkins = jenkins.Jenkins(self.calculate_env())
        self.agent_observer = agent.Observer(
            charm=self,
            observers=agent.IngressObservers(
                agent_discovery=self.agent_discovery_ingress_observer,
                server=self.ingress_observer,
            ),
            jenkins_instance=self.jenkins,
        )
        self._loki = LogProxyConsumer(
            self,
            relation_name="logging",
            log_files=str(jenkins.LOGGING_PATH),
            container_name="jenkins",
        )
        self._prometheus = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "metrics_path": "/prometheus",
                    "static_configs": [{"targets": [f"*:{jenkins.WEB_PORT}"]}],
                }
            ],
        )
        self._grafana = GrafanaDashboardProvider(self)
        self.auth_proxy_observer = auth_proxy.Observer(
            self, self.ingress_observer.ingress, self.jenkins
        )

        # Register all events to funnel through reconcile
        self.framework.observe(
            self.on.jenkins_home_storage_attached,
            self._on_jenkins_home_storage_attached,
        )
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on[AGENT_RELATION].relation_joined, self._on_agent_relation_joined
        )
        self.framework.observe(
            self.on[AGENT_RELATION].relation_departed, self._on_agent_relation_departed
        )
        self.framework.observe(
            self.on[AGENT_RELATION].relation_changed, self._on_agent_relation_changed
        )
        self.framework.observe(
            self.agent_discovery_ingress_observer.ingress.on.ready,
            self._on_agent_discovery_ingress_ready,
        )
        self.framework.observe(
            self.agent_discovery_ingress_observer.ingress.on.revoked,
            self._on_agent_discovery_ingress_revoked,
        )
        self.framework.observe(
            self.ingress_observer.ingress.on.ready,
            self._on_server_ingress_ready,
        )
        self.framework.observe(
            self.ingress_observer.ingress.on.revoked,
            self._on_server_ingress_revoked,
        )
        self.framework.observe(
            self.on[AUTH_PROXY_RELATION].relation_joined, self._on_auth_proxy_relation_joined
        )
        self.framework.observe(
            self.on[AUTH_PROXY_RELATION].relation_departed,
            self._on_auth_proxy_relation_departed,
        )
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)
        self.framework.observe(self.on.rotate_credentials_action, self._on_rotate_credentials)

    def _get_state(self) -> typing.Optional[State]:
        """Derive the charm state fresh from current config and relation data.

        Returns:
            The current charm state, or None if config/units are invalid (unit set to BlockedStatus).

        Raises:
            RuntimeError: if invalid relation data was received.
        """
        try:
            return State.from_charm(self)
        except (CharmConfigInvalidError, CharmIllegalNumUnitsError) as exc:
            self.unit.status = ops.BlockedStatus(exc.msg)
            return None
        except CharmRelationDataInvalidError as exc:
            raise RuntimeError("Invalid relation data received.") from exc

    def calculate_env(self) -> jenkins.Environment:
        """Return a dictionary for Jenkins Pebble layer.

        Returns:
            The dictionary mapping of environment variables for the Jenkins service.
        """
        return jenkins.Environment(
            JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
            JENKINS_PREFIX=self.ingress_observer.get_path(),
        )

    def _reconcile(self, event: ops.EventBase) -> None:
        """Single top-level reconcile method invoked by all event handlers.

        This ensures all subsystems are reconciled to the desired state on every event,
        making the charm converge regardless of event ordering.

        Args:
            event: The event that triggered reconciliation.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        check_result = precondition.check(container=container, storages=self.model.storages)
        if not check_result.success:
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            event.defer()
            return

        state = self._get_state()
        if state is None:
            return

        # Storage ownership only needs correction on attach/upgrade events
        if isinstance(event, (ops.StorageAttachedEvent, ops.UpgradeCharmEvent)):
            self._reconcile_storage(container)

        self._reconcile_pebble(container, state)
        self._reconcile_agents(event, state)
        self._reconcile_agent_discovery()
        self._reconcile_auth_proxy(event, state)
        # Plugin removal only runs on update-status (matching original behaviour)
        if isinstance(event, ops.UpdateStatusEvent):
            self._reconcile_plugins(container, state)

        self.unit.status = ops.ActiveStatus()

    def _reconcile_storage(self, container: ops.Container) -> None:
        """Ensure storage permissions are correct.

        Args:
            container: The Jenkins workload container.
        """
        self.storage.reconcile_storage(container=container)

    def _reconcile_pebble(self, container: ops.Container, charm_state: State) -> None:
        """Ensure the Pebble layer matches desired state.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.
        """
        # Recalculate environment to pick up changes (e.g. ingress prefix)
        self.jenkins.environment = self.calculate_env()
        desired_layer = pebble.get_pebble_layer(self.jenkins, charm_state)
        try:
            current_services = container.get_plan().services
        except Exception:  # pylint: disable=broad-except
            current_services = {}
        desired_services = desired_layer.services

        # Only replan if the layer has changed
        if current_services != desired_services:
            container.add_layer(JENKINS_SERVICE_NAME, desired_layer, combine=True)
            container.replan()

    def _reconcile_agents(self, event: ops.EventBase, state: State) -> None:
        """Reconcile Jenkins agent nodes to match relation state.

        Args:
            event: The triggering event (for deferral if Jenkins not ready).
            state: The current charm state.
        """
        if not state.agent_relation_meta:
            return
        self.agent_observer.reconcile_agents(event, state)

    def _reconcile_agent_discovery(self) -> None:
        """Update the agent discovery URL in all connected agent relations."""
        for relation in self.model.relations[AGENT_RELATION]:
            relation_discovery_url = relation.data[self.model.unit].get("url")
            if (
                relation_discovery_url
                and relation_discovery_url == self.agent_observer.agent_discovery_url
            ):
                continue
            relation.data[self.model.unit].update({"url": self.agent_observer.agent_discovery_url})

    def _reconcile_auth_proxy(self, event: ops.EventBase, state: State) -> None:
        """Reconcile auth proxy configuration.

        Args:
            event: The triggering event.
            state: The current charm state.
        """
        if state.auth_proxy_integrated and self.ingress_observer.ingress.url:
            self.auth_proxy_observer._update_auth_proxy_config()

    def _reconcile_plugins(self, container: ops.Container, state: State) -> None:
        """Remove plugins that are installed but not allowed.

        Args:
            container: The Jenkins workload container.
            state: The current charm state.
        """
        if state.restart_time_range and not timerange.check_now_within_bound_hours(
            state.restart_time_range.start, state.restart_time_range.end
        ):
            return

        try:
            self.jenkins.remove_unlisted_plugins(plugins=state.plugins, container=container)
        except (jenkins.JenkinsPluginError, jenkins.JenkinsError) as exc:
            logger.error("Failed to remove unlisted plugin, %s", exc)
        except TimeoutError as exc:
            logger.error("Failed to remove plugins, %s", exc)

    def _bootstrap_jenkins(self, event: ops.EventBase) -> None:
        """Bootstrap Jenkins on first pebble-ready.

        This performs the full install and version detection that only needs
        to happen once (or on upgrade).

        Args:
            event: The event that triggered the bootstrap.

        Raises:
            TimeoutError: if there was an error waiting for Jenkins service to come up.
            JenkinsBootstrapError: if there was an error installing Jenkins.
            JenkinsError: if there was an error fetching Jenkins version.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        check_result = precondition.check(container=container, storages=self.model.storages)
        if not check_result.success:
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            event.defer()
            return

        state = self._get_state()
        if state is None:  # pragma: nocover
            return

        self.unit.status = ops.MaintenanceStatus("Installing Jenkins.")
        pebble.replan_jenkins(container, self.jenkins, state)
        try:
            version = self.jenkins.version
        except jenkins.JenkinsError as exc:
            logger.error("Failed to get Jenkins version, %s", exc)
            raise

        self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    def _on_jenkins_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure and start Jenkins server on first pebble ready.

        Args:
            event: The event fired when pebble is ready.
        """
        self._bootstrap_jenkins(event)

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle configuration changes.

        Args:
            event: The config-changed event.
        """
        self._reconcile(event)

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Handle update status event.

        Args:
            event: The update status hook event.
        """
        self._reconcile(event)

    def _on_jenkins_home_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
        """Handle storage attached.

        Args:
            event: The event fired when the storage is attached.
        """
        self._reconcile(event)

    def _on_upgrade_charm(self, event: ops.UpgradeCharmEvent) -> None:
        """Handle charm upgrade.

        Args:
            event: The event fired when the charm is upgraded.
        """
        self._reconcile(event)

    def _on_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle agent relation joined.

        Args:
            event: the event fired when an agent joins the relation.
        """
        self._reconcile(event)

    def _on_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle agent relation departed.

        Args:
            event: the event fired when an agent departs the relation.
        """
        self._reconcile(event)

    def _on_agent_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle agent relation changed.

        Args:
            event: the event fired when agent relation data changes.
        """
        self._reconcile(event)

    def _on_agent_discovery_ingress_ready(self, event: ops.EventBase) -> None:
        """Handle agent discovery ingress ready event.

        Args:
            event: the event fired when agent discovery ingress becomes ready.
        """
        self._reconcile(event)

    def _on_agent_discovery_ingress_revoked(self, event: ops.EventBase) -> None:
        """Handle agent discovery ingress revoked event.

        Args:
            event: the event fired when agent discovery ingress is revoked.
        """
        self._reconcile(event)

    def _on_server_ingress_ready(self, event: ops.EventBase) -> None:
        """Handle server ingress ready event.

        Args:
            event: the event fired when server ingress becomes ready.
        """
        self._reconcile(event)

    def _on_server_ingress_revoked(self, event: ops.EventBase) -> None:
        """Handle server ingress revoked event.

        Args:
            event: the event fired when server ingress is revoked.
        """
        self._reconcile(event)

    def _on_auth_proxy_relation_joined(self, event: ops.RelationCreatedEvent) -> None:
        """Handle auth proxy relation joined.

        Args:
            event: the event fired when the auth proxy relation is joined.
        """
        self._reconcile(event)

    def _on_auth_proxy_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle auth proxy relation departed.

        Args:
            event: the event fired when the auth proxy relation departs.
        """
        self._reconcile(event)

    def _on_get_admin_password(self, event: ops.ActionEvent) -> None:
        """Handle get-admin-password event.

        Args:
            event: The event fired from get-admin-password action.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            event.fail("Jenkins storage not yet mounted.")
            return
        credentials = jenkins.get_admin_credentials(container)
        event.set_results({"password": credentials.password_or_token})

    def _on_rotate_credentials(self, event: ops.ActionEvent) -> None:
        """Invalidate all sessions and reset admin account password.

        Args:
            event: The rotate credentials event.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            event.fail("Jenkins storage not yet mounted.")
            return
        if not jenkins.is_jenkins_ready(container):
            event.fail("Jenkins service is not yet ready.")
            return
        try:
            password = self.jenkins.rotate_credentials(container)
        except jenkins.JenkinsError:
            event.fail("Error invalidating user sessions. See logs.")
            return
        event.set_results({"password": password})


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
