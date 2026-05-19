#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import logging
import typing

import ops

import actions
import agent
import auth_proxy
import cos
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
        self.actions_observer = actions.Observer(self, self.jenkins)
        self.agent_observer = agent.Observer(
            charm=self,
            observers=agent.IngressObservers(
                agent_discovery=self.agent_discovery_ingress_observer,
                server=self.ingress_observer,
            ),
            jenkins_instance=self.jenkins,
        )
        self.cos_observer = cos.Observer(self)
        self.auth_proxy_observer = auth_proxy.Observer(
            self, self.ingress_observer.ingress, self.jenkins
        )
        self.framework.observe(
            self.on.jenkins_home_storage_attached,
            self._on_jenkins_home_storage_attached,
        )
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._upgrade_charm)
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

    def _on_jenkins_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure and start Jenkins server.

        Args:
            event: The event fired when pebble is ready.

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
        if state is None:
            return

        self.unit.status = ops.MaintenanceStatus("Installing Jenkins.")
        # First Jenkins server start installs Jenkins server.
        pebble.replan_jenkins(container, self.jenkins, state)
        try:
            version = self.jenkins.version
        except jenkins.JenkinsError as exc:
            logger.error("Failed to get Jenkins version, %s", exc)
            raise

        self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Apply configuration changes impacting Jenkins start flags.

        This replans the Pebble layer with any updated JVM system properties
        and restarts the Jenkins service.
        """
        state = self._get_state()
        if state is None:
            return

        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        check_result = precondition.check(container=container, storages=self.model.storages)
        if not check_result.success:
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            event.defer()
            return

        # Re-apply the layer and restart Jenkins to pick up new flags
        container.add_layer(
            JENKINS_SERVICE_NAME,
            pebble.get_pebble_layer(self.jenkins, state),
            combine=True,
        )
        container.replan()
        try:
            container.restart(JENKINS_SERVICE_NAME)
        except ops.pebble.APIError as exc:  # pragma: no cover - best-effort restart
            logger.warning("Failed to restart Jenkins on config-changed: %s", exc)

    def _remove_unlisted_plugins(
        self, container: ops.Container, state: typing.Optional[State] = None
    ) -> ops.StatusBase:
        """Remove plugins that are installed but not allowed.

        Args:
            container: The jenkins workload container.
            state: The current charm state.

        Returns:
            The unit status of the charm after the operation.
        """
        if state is None:
            state = self._get_state()
            if state is None:
                return self.unit.status

        original_status = self.unit.status.name
        try:
            self.jenkins.remove_unlisted_plugins(plugins=state.plugins, container=container)
        except (jenkins.JenkinsPluginError, jenkins.JenkinsError) as exc:
            logger.error("Failed to remove unlisted plugin, %s", exc)
            return ops.StatusBase.from_name(original_status, "Failed to remove unlisted plugin.")
        except TimeoutError as exc:
            logger.error("Failed to remove plugins, %s", exc)
            return ops.BlockedStatus("Failed to remove plugins.")
        return ops.ActiveStatus()

    def _on_update_status(self, event: ops.UpdateStatusEvent) -> None:
        """Handle update status event.

        On Update status:
        1. Remove plugins that are installed but are not allowed by plugins config value.
        2. Update Jenkins patch version if available and is within restart-time-range config value.

        Args:
            event: The update status hook event.
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

        if state.restart_time_range and not timerange.check_now_within_bound_hours(
            state.restart_time_range.start, state.restart_time_range.end
        ):
            return

        self.unit.status = self._remove_unlisted_plugins(container=container, state=state)

    def _on_jenkins_home_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
        """Correctly set permission when storage is attached.

        Args:
            event: The event fired when the storage is attached.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        check_result = precondition.check(container=container, storages=self.model.storages)
        if not check_result.success:
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            event.defer()
            return

        # There are no logical changes, this function will be refactored into part of th reconcile
        self.storage.reconcile_storage(container=container)  # pragma: nocover

    def _upgrade_charm(self, event: ops.UpgradeCharmEvent) -> None:
        """Correctly set permissions when charm is upgraded.

        Args:
            event: The event fired when the charm is upgraded.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        check_result = precondition.check(container=container, storages=self.model.storages)
        # There are no logical changes, this function will be refactored into part of th reconcile
        if not check_result.success:  # pragma: nocover
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            event.defer()
            return

        state = self._get_state()
        if state is None:  # pragma: nocover
            return

        self.storage.reconcile_storage(container=container)
        # Update the agent discovery address.
        # Updating the secret is not required since it's calculated using the agent's node name.
        self.agent_observer.reconfigure_agent_discovery(event)
        self.agent_observer.reconcile_agents(event, state)

    def _on_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle agent relation joined.

        Args:
            event: the event fired when an agent joins the relation.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconcile_agents(event, state)

    def _on_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle agent relation departed.

        Args:
            event: the event fired when an agent departs the relation.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconcile_agents(event, state)

    def _on_agent_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle agent relation changed.

        Args:
            event: the event fired when agent relation data changes.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconcile_agents(event, state)

    def _on_agent_discovery_ingress_ready(self, event: ops.EventBase) -> None:
        """Handle agent discovery ingress ready event.

        Args:
            event: the event fired when agent discovery ingress becomes ready.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconfigure_agent_discovery(event)

    def _on_agent_discovery_ingress_revoked(self, event: ops.EventBase) -> None:
        """Handle agent discovery ingress revoked event.

        Args:
            event: the event fired when agent discovery ingress is revoked.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconfigure_agent_discovery(event)

    def _on_server_ingress_ready(self, event: ops.EventBase) -> None:
        """Handle server ingress ready event.

        Args:
            event: the event fired when server ingress becomes ready.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconfigure_agent_discovery(event)
        self.auth_proxy_observer.on_ingress_ready(event, state)

    def _on_server_ingress_revoked(self, event: ops.EventBase) -> None:
        """Handle server ingress revoked event.

        Args:
            event: the event fired when server ingress is revoked.
        """
        state = self._get_state()
        if state is None:
            return
        self.agent_observer.reconfigure_agent_discovery(event)
        self.auth_proxy_observer.on_ingress_revoked(event, state)

    def _on_auth_proxy_relation_joined(self, event: ops.RelationCreatedEvent) -> None:
        """Handle auth proxy relation joined.

        Args:
            event: the event fired when the auth proxy relation is joined.
        """
        state = self._get_state()
        if state is None:
            return
        self.auth_proxy_observer.on_auth_proxy_relation_joined(event, state)

    def _on_auth_proxy_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle auth proxy relation departed.

        Args:
            event: the event fired when the auth proxy relation departs.
        """
        state = self._get_state()
        if state is None:
            return
        self.auth_proxy_observer.on_auth_proxy_relation_departed(event, state)


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
