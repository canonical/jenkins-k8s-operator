#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import ipaddress
import logging
import secrets
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

# The plugins that are required for Jenkins to work
REQUIRED_PLUGINS = [
    "instance-identity",  # required to connect agent nodes to server
    "prometheus",  # required for COS integration
    "monitoring",  # required for session invalidation
    "configuration-as-code",  # required for JCasC declarative config management
]


class ReconcileBlockedError(Exception):
    """Raised by sub-reconcilers to signal the charm should enter BlockedStatus.

    Attributes:
        message: The blocked status message.
    """

    def __init__(self, message: str):
        """Initialize ReconcileBlockedError.

        Args:
            message: The blocked status message to surface to the user.
        """
        self.message = message
        super().__init__(message)


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
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)
        self.framework.observe(self.on.rotate_credentials_action, self._on_rotate_credentials)

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

    def calculate_env(self, config_hash: str, admin_password: str = "") -> jenkins.Environment:
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
            CONFIGURATION_HASH=config_hash,
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

        try:
            # Storage ownership only needs correction on attach/upgrade events
            if isinstance(event, (ops.StorageAttachedEvent, ops.UpgradeCharmEvent)):
                self._reconcile_storage(container)

            # Reconcile jenkins configuration filesystem
            configuration_hash = self._reconcile_pre_startup_configurations(container, state)
            # pass in configuration hash to trigger pebble layer update
            admin_password = self._reconcile_admin(container, state)
            self._reconcile_pebble(container, state, configuration_hash, admin_password)

            # Post Jenkins server startup reconciliations
            self._reconcile_agents(event, state)
            self._reconcile_agent_discovery()
            self._reconcile_auth_proxy(event, state)
            self._reconcile_plugins(container, state)
        except ReconcileBlockedError as exc:
            self.unit.status = ops.BlockedStatus(exc.message)
            return

        self.unit.status = ops.ActiveStatus(self._agent_status_message)

    def _reconcile_storage(self, container: ops.Container) -> None:
        """Ensure storage permissions are correct.

        Args:
            container: The Jenkins workload container.
        """
        self.storage.reconcile_storage(container=container)

    def _reconcile_admin(self, container: ops.Container, charm_state: State) -> str:
        """Ensure the admin user is set up and return the admin password.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.
        
        Returns:
            The admin password for JCasC secret interpolation.
        """
        # Charm state fetches it using juju secrets.
        if charm_state.admin_password:
            return charm_state.admin_password
        
        # Backwards compatibility: fetch admin password from container and migrate to juju secrets.
        admin_setup = False
        try:
            password_or_token = jenkins.get_admin_credentials(container).password_or_token
            admin_setup = True
        except jenkins.JenkinsBootstrapError as exc:
            logger.debug("Admin password not yet setup, setting up admin user: %s", exc)

        # Generate admin password and set it using juju secrets if secret not yet configured.
        if not admin_setup:
            # Generate admin user secret using secrets.token_hex() and set it in the container
            password_or_token = secrets.token_hex(16)
        self.app.add_secret(content={"password": password_or_token}, label=self.app.name)
        return password_or_token


    def _reconcile_pebble(self, container: ops.Container, charm_state: State, configuration_hash: str, admin_password: str) -> None:
        """Ensure the Pebble layer matches desired state.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.
            configuration_hash: The hash of the JCasC configurations applied.
            admin_password: The admin password for JCasC secret interpolation.
        """
        self.jenkins.environment = self.calculate_env(config_hash=configuration_hash, admin_password=admin_password)
        desired_layer = pebble.get_pebble_layer(self.jenkins, charm_state)
        container.add_layer(JENKINS_SERVICE_NAME, desired_layer, combine=True)
        container.replan()
        self.jenkins.wait_ready()


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


    def _reconcile_pre_startup_configurations(self, container: ops.Container, charm_state: State) -> None:
        """Reconcile configurations that need to be in place before Jenkins starts up for the first time.

        This includes storage permissions and admin user setup, which are prerequisites for a successful
        Jenkins startup and JCasC application.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.

        Returns:
            The hash of the JCasC configurations applied.

        Raises:
            TimeoutError: if there was an error waiting for Jenkins service to come up.
            JenkinsBootstrapError: if there was an error installing Jenkins.
        """
        jenkins.unlock_wizard(container)
        jenkins.install_plugins(container, REQUIRED_PLUGINS, charm_state.proxy_config)
        return self._reconcile_jcasc_config(container, charm_state.jcasc_config, charm_state.proxy_config)


    def _reconcile_jcasc_config(
        self,
        container: ops.Container,
        jcasc_config: typing.Optional[typing.Dict[str, typing.Any]],
        proxy_config: typing.Optional[state.ProxyConfig],
    ) -> str:
        """Reconcile JCasC configuration to desired state.

        Builds the desired JCasC config by merging user-provided config with
        charm-managed sections (admin credentials, auth proxy), then delegates
        file I/O, validation, and reload to jenkins.sync_jcasc_config.

        Args:
            container: The Jenkins workload container.
            jcasc_config: The user-provided JCasC configuration.
            proxy_config: The proxy configuration for JCasC interpolation.

        Returns:
            The hash of the JCasC configuration applied.

        Raises:
            ReconcileBlockedError: if there was an error installing JCasC configuration.
        """
        if jcasc_config is None:
            return

        desired_config = jenkins.build_jcasc_config(jcasc_config, proxy_config)
        try:
            desired_yaml = yaml.dump(desired_config, default_flow_style=False, sort_keys=False)
        except yaml.YAMLError as exc:
            logger.error("Failed to serialize JCasC config, %s", exc)
            raise ReconcileBlockedError("Failed to serialize JCasC config.") from exc

        return jenkins.sync_jcasc_config(container, desired_yaml)


    def _reconcile_post_startup_configurations(self, container: ops.Container, charm_state: State) -> None:
        """Reconcile configurations that can only be applied after Jenkins has started up.

        This includes any configuration that requires Jenkins to be running to apply, such as plugin management
        and JCasC application.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.

        Raises:
            TimeoutError: if there was an error waiting for Jenkins service to come up.
            JenkinsBootstrapError: if there was an error installing Jenkins.
        """
        # setup admin user token

        pass

    def _bootstrap_jenkins(self, container: ops.Container, charm_state: State) -> None:
        """Bootstrap Jenkins on first pebble-ready.

        This performs the full install and version detection that only needs
        to happen once (or on upgrade).

        Args:
            container: The Jenkins workload container.
            charm_state: The charm state.
        Raises:
            TimeoutError: if there was an error waiting for Jenkins service to come up.
            JenkinsBootstrapError: if there was an error installing Jenkins.
            JenkinsError: if there was an error fetching Jenkins version.
        """
        jenkins_version = pebble.get_jenkins_version(container)
        self.unit.set_workload_version(jenkins_version)
        logger.info("Installing wizard bypass")
        jenkins.unlock_wizard(container, jenkins_version)
        logger.info("Installing admin user setup groovy script")
        admin_password = jenkins.prepare_admin_user(container, self)
        logger.info("Installing missing plugins")
        jenkins.install_plugins_if_missing(container, charm_state)
        logger.info("Installing Jenkins logging configuration")
        jenkins.install_logging_config(container=container)
        self.unit.set_workload_version(jenkins_version)
        self.unit.status = ops.ActiveStatus()


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
