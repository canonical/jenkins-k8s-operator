#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import ipaddress
import logging
import socket
import typing
from urllib.parse import urlparse

import ops
import yaml
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.oauth2_proxy_k8s.v0.auth_proxy import AuthProxyConfig, AuthProxyRequirer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import jenkins
import pebble
import precondition
import storage
import timerange
from state import (
    AGENT_DISCOVERY_INGRESS_RELATION_NAME,
    AGENT_RELATION,
    AUTH_PROXY_RELATION,
    INGRESS_RELATION_NAME,
    JENKINS_SERVICE_NAME,
    AgentMeta,
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
        self.agent_discovery_ingress = IngressPerAppRequirer(
            self,
            relation_name=AGENT_DISCOVERY_INGRESS_RELATION_NAME,
            port=jenkins.WEB_PORT,
        )
        self.server_ingress = IngressPerAppRequirer(
            self,
            relation_name=INGRESS_RELATION_NAME,
            port=jenkins.WEB_PORT,
        )
        self.jenkins = jenkins.Jenkins(self.calculate_env())
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
        self._auth_proxy = AuthProxyRequirer(self)

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
            self.agent_discovery_ingress.on.ready,
            self._on_agent_discovery_ingress_ready,
        )
        self.framework.observe(
            self.agent_discovery_ingress.on.revoked,
            self._on_agent_discovery_ingress_revoked,
        )
        self.framework.observe(
            self.server_ingress.on.ready,
            self._on_server_ingress_ready,
        )
        self.framework.observe(
            self.server_ingress.on.revoked,
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

    def _get_ingress_path(self) -> str:
        """Return the path in which Jenkins is expected to be listening.

        Returns:
            the path for the ingress URL.
        """
        if not self.server_ingress.url:
            return ""
        path = urlparse(self.server_ingress.url).path
        if path == "/":
            return ""
        return path

    def calculate_env(
        self, admin_password: str = ""
    ) -> jenkins.Environment:
        """Return a dictionary for Jenkins Pebble layer.

        Args:
            admin_password: The admin password for JCasC secret interpolation.
                Empty string if not yet available (e.g. during __init__).

        Returns:
            The dictionary mapping of environment variables for the Jenkins service.
        """
        return jenkins.Environment(
            JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
            JENKINS_PREFIX=self._get_ingress_path(),
            CASC_JENKINS_CONFIG=str(jenkins.JCASC_CONFIG_PATH),
            JENKINS_ADMIN_PASSWORD=admin_password,
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
        self._reconcile_jcasc(container, state)
        self._reconcile_agents(event, state)
        self._reconcile_agent_discovery()
        self._reconcile_auth_proxy(event, state)
        # Plugin removal only runs on update-status (matching original behaviour)
        if isinstance(event, ops.UpdateStatusEvent):
            self._reconcile_plugins(container, state)

        self.unit.status = ops.ActiveStatus(self._agent_status_message)

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
        # Recalculate environment to pick up changes (e.g. ingress prefix, admin password)
        admin_password = ""
        try:
            credentials = jenkins.get_admin_credentials(container)
            admin_password = credentials.password_or_token
        except (ops.pebble.PathError, FileNotFoundError):
            pass  # Password not yet available (first boot)
        self.jenkins.environment = self.calculate_env(admin_password=admin_password)
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

    def _reconcile_jcasc(self, container: ops.Container, state: State) -> None:
        """Reconcile JCasC configuration to desired state.

        Parses user-provided JCasC YAML, injects charm-managed sections (admin
        credentials, auth proxy), checks for conflicts, writes the config file,
        validates it, and reloads Jenkins.

        Args:
            container: The Jenkins workload container.
            state: The current charm state.
        """
        # Skip if Jenkins home directory is not ready (first boot before bootstrap)
        try:
            container.list_files(str(jenkins.JENKINS_HOME_PATH))
        except (ops.pebble.PathError, ops.pebble.APIError):
            return

        raw_config = state.jcasc_config

        # Block if empty
        if not raw_config.strip():
            self.unit.status = ops.BlockedStatus("jcasc-config must not be empty")
            return

        # Parse YAML
        try:
            user_config = yaml.safe_load(raw_config)
        except yaml.YAMLError as exc:
            logger.error("Invalid JCasC YAML: %s", exc)
            self.unit.status = ops.BlockedStatus(f"Invalid jcasc-config YAML: {exc}")
            return

        if not isinstance(user_config, dict):
            self.unit.status = ops.BlockedStatus(
                "jcasc-config must be a YAML mapping (dict)"
            )
            return

        jenkins_section = user_config.get("jenkins", {})

        # Conflict check: user provides securityRealm while auth_proxy is active
        if state.auth_proxy_integrated and "securityRealm" in jenkins_section:
            self.unit.status = ops.BlockedStatus(
                "JCasC conflict: 'securityRealm' is managed by auth_proxy relation, "
                "remove it from jcasc-config"
            )
            return

        # Inject admin credentials if securityRealm not provided by user
        if "securityRealm" not in jenkins_section:
            jenkins_section["securityRealm"] = {
                "local": {
                    "allowsSignup": False,
                    "users": [{"id": "admin", "password": "${JENKINS_ADMIN_PASSWORD}"}],
                }
            }
            user_config.setdefault("jenkins", {}).update(jenkins_section)

        # Write if changed
        desired_yaml = yaml.dump(user_config, default_flow_style=False, sort_keys=False)
        jcasc_path = str(jenkins.JCASC_CONFIG_PATH)
        try:
            current = container.pull(jcasc_path).read()
        except (ops.pebble.PathError, FileNotFoundError):
            current = ""

        if current == desired_yaml:
            return  # No change needed

        try:
            container.push(
                jcasc_path,
                desired_yaml,
                encoding="utf-8",
                user=jenkins.USER,
                group=jenkins.GROUP,
                make_dirs=True,
            )
        except ops.pebble.PathError:
            # Directory not ready yet — will be written on next reconcile
            return

        # Validate via live check endpoint if Jenkins is ready
        try:
            if not self.jenkins.check_jcasc(container, desired_yaml):
                logger.warning("JCasC validation failed, rolling back")
                self.unit.status = ops.BlockedStatus(
                    "JCasC validation failed — check juju debug-log"
                )
                # Rollback
                if current:
                    container.push(
                        jcasc_path,
                        current,
                        encoding="utf-8",
                        user=jenkins.USER,
                        group=jenkins.GROUP,
                        make_dirs=True,
                    )
                    self.jenkins.reload_jcasc(container)
                return
        except jenkins.JenkinsError:
            # Jenkins not ready yet or API token not available — skip validation
            # Config is on disk and will be picked up when Jenkins starts
            logger.info("JCasC validation skipped (Jenkins not ready)")
            return

        # Apply the new configuration
        try:
            self.jenkins.reload_jcasc(container)
        except jenkins.JenkinsError:
            logger.warning("JCasC reload failed, Jenkins will pick up config on next restart")

    def _reconcile_agents(self, event: ops.EventBase, state: State) -> None:
        """Reconcile Jenkins agent nodes to match relation state.

        Args:
            event: The triggering event (for deferral if Jenkins not ready).
            state: The current charm state.
        """
        if not state.agent_relation_meta:
            return

        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_jenkins_ready(container=container):
            self.unit.status = ops.WaitingStatus("Jenkins service not yet ready.")
            event.defer()
            return

        # Make sure Jenkins is fully up and running before interacting with it.
        self.jenkins.wait_ready()

        self.unit.status = ops.MaintenanceStatus("Reconciling agent nodes.")
        agent_nodes = self.jenkins.list_agent_nodes(container=container)
        agent_node_names = [node.name for node in agent_nodes]

        self._add_agent_nodes_from_relation(
            agent_relation=state.agent_relation_meta,
            container=container,
            agent_node_names=agent_node_names,
        )
        self._remove_agent_nodes_not_in_relation(
            agent_relation=state.agent_relation_meta,
            container=container,
            agent_node_names=agent_node_names,
        )

    def _reconcile_agent_discovery(self) -> None:
        """Update the agent discovery URL in all connected agent relations."""
        for relation in self.model.relations[AGENT_RELATION]:
            relation_discovery_url = relation.data[self.model.unit].get("url")
            if relation_discovery_url and relation_discovery_url == self._agent_discovery_url:
                continue
            relation.data[self.model.unit].update({"url": self._agent_discovery_url})

    def _reconcile_auth_proxy(self, event: ops.EventBase, state: State) -> None:
        """Reconcile auth proxy configuration.

        Args:
            event: The triggering event.
            state: The current charm state.
        """
        if state.auth_proxy_integrated:
            if self.server_ingress.url:
                auth_proxy_config = AuthProxyConfig(
                    protected_urls=[self.server_ingress.url],
                    allowed_endpoints=[],
                    headers=["X-Auth-Request-User"],
                )
            else:
                auth_proxy_config = AuthProxyConfig(
                    protected_urls=[],
                    allowed_endpoints=[],
                    headers=["X-Auth-Request-User"],
                )
            self._auth_proxy.update_auth_proxy_config(auth_proxy_config=auth_proxy_config)

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

    @property
    def _agent_discovery_url(self) -> str:
        """Return the external hostname to be passed to agents via the integration.

        If there is no ingress, use the pod IP as hostname. The pod IP is preferred
        over the pod name or a K8s service because those rely on the cluster's DNS
        service, while the IP address is sometimes routable from the outside.

        Returns:
            The charm's agent discovery url.
        """
        if ingress_url := self.agent_discovery_ingress.url:
            return ingress_url
        if ingress_url := self.server_ingress.url:
            logger.warning(
                "Using public ingress with protected endpoints (e.g. oathkeeper)"
                "will result in agent discovery failure. Use %s for agents discovery.",
                AGENT_DISCOVERY_INGRESS_RELATION_NAME,
            )
            return ingress_url

        # Fallback to pod IP
        if binding := self.model.get_binding("juju-info"):
            try:
                unit_ip = str(binding.network.bind_address)
                ipaddress.ip_address(unit_ip)
                env_dict = typing.cast(typing.Dict[str, str], self.jenkins.environment)
                return f"http://{unit_ip}:{jenkins.WEB_PORT}{env_dict['JENKINS_PREFIX']}"
            except ValueError as exc:
                logger.error(
                    "IP from juju-info is not valid: %s, we can still fall back to using fqdn",
                    exc,
                )

        # Fallback to using socket.fqdn
        return f"http://{socket.getfqdn()}:{jenkins.WEB_PORT}"

    @property
    def _agent_status_message(self) -> str:
        """Status message regarding agent discovery ingress configuration."""
        if self.server_ingress.url and not self.agent_discovery_ingress.url:
            return (
                f"Consider separating ingress for agents ({AGENT_DISCOVERY_INGRESS_RELATION_NAME})"
            )
        return ""

    def _add_agent_nodes_from_relation(
        self,
        agent_relation: typing.Mapping[ops.Relation, list[AgentMeta]],
        container: ops.Container,
        agent_node_names: list[str],
    ) -> None:
        """Add agent nodes from relation data.

        Args:
            agent_relation: Mapping of agent relation to agent metadata.
            container: The workload container.
            agent_node_names: The node names of agents.

        Raises:
            JenkinsError: if there was an error while registering agent nodes to Jenkins.
        """
        for relation, agents in agent_relation.items():
            unregistered_agents = [agent for agent in agents if agent.name not in agent_node_names]
            for unregistered_agent in unregistered_agents:
                try:
                    self.jenkins.add_agent_node(agent_meta=unregistered_agent, container=container)
                except jenkins.JenkinsError:
                    logger.exception("Failed to register agent node: %s", unregistered_agent)
                    raise

            agent_relation_data: dict[str, str] = {"url": self._agent_discovery_url}
            for meta in agents:
                try:
                    agent_relation_data[f"{meta.name}_secret"] = self.jenkins.get_node_secret(
                        node_name=meta.name, container=container
                    )
                except jenkins.JenkinsError:
                    logger.exception("Failed to get secret for registered node: %s", meta)
                    raise
            relation.data[self.model.unit].update(agent_relation_data)

    def _remove_agent_nodes_not_in_relation(
        self,
        agent_relation: typing.Mapping[ops.Relation, list[AgentMeta]],
        container: ops.Container,
        agent_node_names: list[str],
    ) -> None:
        """Remove agent nodes not found in relation data.

        Args:
            agent_relation: Mapping of agent relation to agent metadata.
            container: The Jenkins workload container.
            agent_node_names: The agents registered on Jenkins server.

        Raises:
            JenkinsError: if there was an error while removing agent nodes from Jenkins.
        """
        all_agent_names_from_relation = {
            agent.name for agents in agent_relation.values() for agent in agents
        }
        agents_not_in_relation = set(agent_node_names) - all_agent_names_from_relation
        for agent_name in agents_not_in_relation:
            try:
                self.jenkins.remove_agent_node(agent_name=agent_name, container=container)
            except jenkins.JenkinsError:
                logger.exception("Failed to remove registered node: %s", agent_name)
                raise

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
