#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import ipaddress
import logging
import socket
import typing
import urllib.error
import urllib.request
from urllib.parse import urlparse

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.oauth2_proxy_k8s.v0.auth_proxy import AuthProxyConfig, AuthProxyRequirer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_delay,
    wait_fixed,
)

import jenkins
import pebble
import precondition
import state
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


class JenkinsHealthCheckError(Exception):
    """Raised when Jenkins health check returns a non-success response."""


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
        for event in [
            self.on.start,
            self.on.jenkins_pebble_ready,
            self.on.jenkins_home_storage_attached,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on[AGENT_RELATION].relation_joined,
            self.on[AGENT_RELATION].relation_departed,
            self.on[AGENT_RELATION].relation_changed,
            self.agent_discovery_ingress.on.ready,
            self.agent_discovery_ingress.on.revoked,
            self.server_ingress.on.ready,
            self.server_ingress.on.revoked,
            self.on[AUTH_PROXY_RELATION].relation_joined,
            self.on[AUTH_PROXY_RELATION].relation_departed,
            self.on.update_status,
        ]:
            self.framework.observe(event, self._reconcile)
        self.framework.observe(
            self.on.get_admin_password_action, self._on_get_admin_password
        )
        self.framework.observe(
            self.on.rotate_credentials_action, self._on_rotate_credentials
        )

    def _get_state(self) -> typing.Optional[State]:
        """Derive the charm state fresh from current config and relation data.

        Returns:
            The current charm state, or None if config/units are invalid (unit set to
            BlockedStatus).

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

    def _reconcile_bootstrap(self, container: ops.Container, state: State) -> str:
        """Run the pre-start Jenkins bootstrap steps and return the admin password.

        Args:
            container: The Jenkins workload container.

        Returns:
            The Jenkins admin password.
        """
        jenkins_version = pebble.get_jenkins_version(container)
        self.unit.set_workload_version(jenkins_version)
        jenkins.unlock_wizard(container, jenkins_version)
        admin_password = jenkins.prepare_admin_user(container, self)
        jenkins.install_plugins_if_missing(container, state)
        return admin_password

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

    def calculate_env(self) -> jenkins.Environment:
        """Return a dictionary for Jenkins Pebble layer.

        Returns:
            The dictionary mapping of environment variables for the Jenkins service.
        """
        return jenkins.Environment(
            JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
            JENKINS_PREFIX=self._get_ingress_path(),
        )

    def _reconcile(self, event: ops.EventBase) -> None:
        """Single top-level reconcile method invoked by all event handlers.

        This ensures all subsystems are reconciled to the desired state on every event,
        making the charm converge regardless of event ordering.

        Args:
            event: The event that triggered reconciliation.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for Pebble")
            return

        check_result = precondition.check(
            container=container, storages=self.model.storages
        )
        if not check_result.success:
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            return

        state = self._get_state()
        if state is None:
            return

        if isinstance(event, (ops.StorageAttachedEvent, ops.UpgradeCharmEvent)):
            self._reconcile_storage(container)

        admin_password = self._reconcile_bootstrap(container, state)

        self.unit.status = ops.MaintenanceStatus("Configuring Jenkins")

        try:
            self._reconcile_pebble(container, state)
        except ops.pebble.Error as exc:
            self.unit.status = ops.BlockedStatus(f"Pebble error: {exc}")
            return

        jenkins_url = f"http://localhost:{jenkins.WEB_PORT}"
        if not self._wait_for_jenkins_healthy(jenkins_url, timeout_seconds=120):
            self.unit.status = ops.BlockedStatus(
                "Error: Jenkins failed to start within 120 seconds"
            )
            return

        try:
            jenkins.setup_user_token_if_missing(self, jenkins_url, admin_password)
            jenkins.cleanup_init_groovy(container, self)
        except Exception as exc:  # pylint: disable=broad-except
            self.unit.status = ops.BlockedStatus(f"Bootstrap error: {exc}")
            return

        self._reconcile_agents(event, state)
        self._reconcile_agent_discovery()
        self._reconcile_auth_proxy(event, state)
        if isinstance(event, ops.UpdateStatusEvent):
            self._reconcile_plugins(container, state)

        self.unit.status = ops.ActiveStatus(self._agent_status_message)

    def _wait_for_jenkins_healthy(self, jenkins_url: str, timeout_seconds: int) -> bool:
        """Block until Jenkins is healthy or timeout is reached.

        Args:
            jenkins_url: The Jenkins base URL.
            timeout_seconds: The number of seconds to wait before timing out.

        Returns:
            True if Jenkins responds successfully, False otherwise.
        """
        health_endpoint = f"{jenkins_url}/login"
        retrying = Retrying(
            stop=stop_after_delay(timeout_seconds),
            wait=wait_fixed(5),
            retry=retry_if_exception_type(
                (
                    urllib.error.HTTPError,
                    urllib.error.URLError,
                    ConnectionError,
                    TimeoutError,
                    JenkinsHealthCheckError,
                )
            ),
        )

        try:
            return retrying(self._check_jenkins_health, health_endpoint) == 200
        except RetryError:
            return False

    def _check_jenkins_health(self, health_endpoint: str) -> int:
        """Check Jenkins health once and return the response status."""
        req = urllib.request.Request(health_endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status != 200:
                raise JenkinsHealthCheckError(
                    f"Jenkins health check returned {response.status}"
                )
            return response.status

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
        pebble.replan_jenkins(container, self.jenkins, charm_state)

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
            if (
                relation_discovery_url
                and relation_discovery_url == self._agent_discovery_url
            ):
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
            self._auth_proxy.update_auth_proxy_config(
                auth_proxy_config=auth_proxy_config
            )

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
            self.jenkins.remove_unlisted_plugins(
                plugins=state.plugins, container=container
            )
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
                return (
                    f"http://{unit_ip}:{jenkins.WEB_PORT}{env_dict['JENKINS_PREFIX']}"
                )
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
                "Consider separating ingress for agents "
                f"({AGENT_DISCOVERY_INGRESS_RELATION_NAME})"
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
            unregistered_agents = [
                agent for agent in agents if agent.name not in agent_node_names
            ]
            for unregistered_agent in unregistered_agents:
                try:
                    self.jenkins.add_agent_node(
                        agent_meta=unregistered_agent, container=container
                    )
                except jenkins.JenkinsError:
                    logger.exception(
                        "Failed to register agent node: %s", unregistered_agent
                    )
                    raise

            agent_relation_data: dict[str, str] = {"url": self._agent_discovery_url}
            for meta in agents:
                try:
                    agent_relation_data[f"{meta.name}_secret"] = (
                        self.jenkins.get_node_secret(
                            node_name=meta.name, container=container
                        )
                    )
                except jenkins.JenkinsError:
                    logger.exception(
                        "Failed to get secret for registered node: %s", meta
                    )
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
                self.jenkins.remove_agent_node(
                    agent_name=agent_name, container=container
                )
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
        check_result = precondition.check(
            container=container, storages=self.model.storages
        )
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
        password = state.get_stored_admin_password(self, container)
        if password is None:
            event.fail("Jenkins admin password not yet available.")
            return
        event.set_results({"password": password})

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
