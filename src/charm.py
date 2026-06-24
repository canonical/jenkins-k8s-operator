#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import ipaddress
import itertools
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

    def calculate_env(self, config_hash: str, admin_password: str) -> jenkins.Environment:
        """Return a dictionary for Jenkins Pebble layer.

        Args:
            config_hash: The hash of the JCasC configurations applied.
            admin_password: The admin password for JCasC secret interpolation.

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
            event: The triggering Juju event (unused, present for observe callback compatibility).

        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        check_result = precondition.check(container=container, storages=self.model.storages)
        if not check_result.success:
            self.unit.status = ops.WaitingStatus(check_result.reason or "")
            return

        charm_state = self._get_state()
        if charm_state is None:
            return

        try:
            # Storage ownership only needs correction on attach/upgrade events
            logger.info("Reconciling storage")
            self._reconcile_storage(container)

            # Reconcile jenkins configuration filesystem
            configuration_hash = self._reconcile_pre_startup_configurations(container, charm_state)
            # pass in configuration hash to trigger pebble layer update
            logger.info("Reconciling admin user")
            admin_password = self._reconcile_admin(container, charm_state)
            jenkins_environment = self.calculate_env(configuration_hash, admin_password)
            logger.info("Reconciling pebble plan")
            self._reconcile_pebble(container, charm_state, jenkins_environment)

            logger.info("Waiting for Jenkins to come up")
            admin_client = jenkins.Jenkins(self._jenkins_prefix, admin_password, container)
            admin_client.wait_ready(api_ready=True)

            # Post Jenkins server startup reconciliations
            logger.info("Reconciling API Token")
            self._reconcile_api_token(admin_client=admin_client)
            logger.info("Reconciling agents")
            self._reconcile_agents(charm_state, client=admin_client)
            logger.info("Reconciling agent discovery")
            self._reconcile_agent_discovery()
            logger.info("Reconciling auth proxy")
            self._reconcile_auth_proxy(charm_state)
            logger.info("Reconciling plugins")
            self._reconcile_plugins(charm_state, admin_client, container)
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

    def _reconcile_api_token(self, admin_client: jenkins.Jenkins) -> None:
        """Ensure the admin user's API token is set up.

        Args:
            admin_client: The Jenkins client for the admin user.

        Returns:
            Jenkins API client.
        """
        try:
            admin_client.get_admin_api_client()
            return
        except jenkins.JenkinsBootstrapError:
            logger.info("Jenkins admin API client not yet available, generating API token.")

        try:
            admin_client.generate_admin_user_token()
        except jenkins.JenkinsBootstrapError:
            logger.error("Failed to generate Jenkins admin API token.")
            raise

    def _reconcile_pebble(
        self,
        container: ops.Container,
        charm_state: State,
        jenkins_environment: jenkins.Environment,
    ) -> None:
        """Ensure the Pebble layer matches desired state.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.
            jenkins_environment: The environment variables for the Jenkins service.
        """
        desired_layer = pebble.compute_pebble_layer(
            typing.cast(dict[str, str], jenkins_environment), charm_state
        )
        container.add_layer(JENKINS_SERVICE_NAME, desired_layer, combine=True)
        container.replan()

    def _reconcile_agents(self, state: State, client: jenkins.Jenkins) -> None:
        """Reconcile Jenkins agent nodes to match relation state.

        Args:
            state: The current charm state.
            client: Jenkins API client.
        """
        if not state.agent_relation_meta:
            return

        self.unit.status = ops.MaintenanceStatus("Reconciling agent nodes.")
        agent_nodes = client.list_agent_nodes()
        agent_node_names = [node.name for node in agent_nodes]

        self._add_agent_nodes_from_relation(
            agent_relation=state.agent_relation_meta,
            agent_node_names=agent_node_names,
            api_client=client,
        )
        self._remove_agent_nodes_not_in_relation(
            agent_relation=state.agent_relation_meta,
            agent_node_names=agent_node_names,
            api_client=client,
        )

    def _reconcile_agent_discovery(self) -> None:
        """Update the agent discovery URL in all connected agent relations."""
        for relation in self.model.relations[AGENT_RELATION]:
            relation_discovery_url = relation.data[self.model.unit].get("url")
            if relation_discovery_url and relation_discovery_url == self._agent_discovery_url:
                continue
            relation.data[self.model.unit].update({"url": self._agent_discovery_url})

    def _reconcile_auth_proxy(self, state: State) -> None:
        """Reconcile auth proxy configuration.

        Args:
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

    def _reconcile_plugins(
        self, state: State, admin_client: jenkins.Jenkins, container: ops.Container
    ) -> None:
        """Remove plugins that are installed but not allowed.

        Args:
            state: The current charm state.
            admin_client: The Jenkins admin client.
            container: The workload container.
        """
        if state.restart_time_range and not timerange.check_now_within_bound_hours(
            state.restart_time_range.start, state.restart_time_range.end
        ):
            return

        try:
            admin_client.remove_unlisted_plugins(
                plugins=itertools.chain(state.plugins or [], REQUIRED_PLUGINS),
                container=container,
            )
        except (jenkins.JenkinsPluginError, jenkins.JenkinsError) as exc:
            logger.error("Failed to remove unlisted plugin, %s", exc)
        except TimeoutError as exc:
            logger.error("Failed to remove plugins, %s", exc)

    @property
    def _jenkins_prefix(self) -> str:
        """Return the path prefix for Jenkins.

        Returns:
            The path prefix for Jenkins.
        """
        return self._get_ingress_path()

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
                return f"http://{unit_ip}:{jenkins.WEB_PORT}{self._jenkins_prefix}"
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
        agent_node_names: list[str],
        api_client: jenkins.Jenkins,
    ) -> None:
        """Add agent nodes from relation data.

        Args:
            agent_relation: Mapping of agent relation to agent metadata.
            agent_node_names: The node names of agents.
            api_client: The Jenkins API client.

        Raises:
            JenkinsError: if there was an error while registering agent nodes to Jenkins.
        """
        for relation, agents in agent_relation.items():
            unregistered_agents = [agent for agent in agents if agent.name not in agent_node_names]
            for unregistered_agent in unregistered_agents:
                try:
                    api_client.add_agent_node(agent_meta=unregistered_agent)
                except jenkins.JenkinsError:
                    logger.exception("Failed to register agent node: %s", unregistered_agent)
                    raise

            agent_relation_data: dict[str, str] = {"url": self._agent_discovery_url}
            for meta in agents:
                try:
                    agent_relation_data[f"{meta.name}_secret"] = api_client.get_node_secret(
                        node_name=meta.name
                    )
                except jenkins.JenkinsError:
                    logger.exception("Failed to get secret for registered node: %s", meta)
                    raise
            relation.data[self.model.unit].update(agent_relation_data)

    def _remove_agent_nodes_not_in_relation(
        self,
        agent_relation: typing.Mapping[ops.Relation, list[AgentMeta]],
        agent_node_names: list[str],
        api_client: jenkins.Jenkins,
    ) -> None:
        """Remove agent nodes not found in relation data.

        Args:
            agent_relation: Mapping of agent relation to agent metadata.
            agent_node_names: The agents registered on Jenkins server.
            api_client: The Jenkins API client.

        Raises:
            JenkinsError: if there was an error while removing agent nodes from Jenkins.
        """
        all_agent_names_from_relation = {
            agent.name for agents in agent_relation.values() for agent in agents
        }
        agents_not_in_relation = set(agent_node_names) - all_agent_names_from_relation
        for agent_name in agents_not_in_relation:
            try:
                api_client.remove_agent_node(agent_name=agent_name)
            except jenkins.JenkinsError:
                logger.exception("Failed to remove registered node: %s", agent_name)
                raise

    def _reconcile_pre_startup_configurations(
        self, container: ops.Container, charm_state: State
    ) -> str:
        """Reconcile configurations that need to be in place before Jenkins starts up.

        Unlock wizard, pre-install plugins and JCasC configuration before starting Jenkins service.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.

        Returns:
            The hash of the JCasC configurations applied.

        Raises:
            TimeoutError: if there was an error waiting for Jenkins service to come up.
            JenkinsBootstrapError: if there was an error installing Jenkins.
        """
        logger.info("Getting jenkins version")
        version = pebble.get_jenkins_version(container)
        logger.info("Unlocking wizard")
        jenkins.unlock_wizard(container, version)
        logger.info("Installing plugins")
        jenkins.install_plugins(container, REQUIRED_PLUGINS, charm_state.proxy_config)
        logger.info("Reconciling JCasC configuration")
        jenkins.install_logging_config(container)
        return self._reconcile_jcasc_config(container, charm_state)

    def _reconcile_jcasc_config(
        self,
        container: ops.Container,
        charm_state: State,
    ) -> str:
        """Reconcile JCasC configuration to desired state.

        Builds the desired JCasC config by merging user-provided config with
        charm-managed sections (admin credentials, auth proxy), then delegates
        file I/O, validation, and reload to jenkins.sync_jcasc_config.

        Args:
            container: The Jenkins workload container.
            charm_state: The current charm state.

        Returns:
            The hash of the JCasC configuration applied.

        Raises:
            ReconcileBlockedError: if there was an error installing JCasC configuration.
        """
        if charm_state.jcasc_config is None:
            return ""

        desired_config = jenkins.build_jcasc_config(
            charm_state.jcasc_config,
            charm_state.proxy_config,
            charm_state.auth_proxy_integrated,
        )
        try:
            desired_yaml = yaml.dump(desired_config, default_flow_style=False, sort_keys=False)
        except yaml.YAMLError as exc:
            logger.error("Failed to serialize JCasC config, %s", exc)
            raise ReconcileBlockedError("Failed to serialize JCasC config.") from exc

        return jenkins.sync_jcasc_config(container, desired_yaml)

    def _on_get_admin_password(self, event: ops.ActionEvent) -> None:
        """Handle get-admin-password event.

        Args:
            event: The event fired from get-admin-password action.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            event.fail("Jenkins storage not yet mounted.")
            return
        charm_state = self._get_state()
        if not charm_state:
            event.fail("Jenkins charm is not yet ready.")
            return

        if charm_state.admin_password:
            event.set_results({"password": charm_state.admin_password})
            return

        credentials = jenkins.get_admin_credentials(container)
        event.set_results({"password": credentials.password_or_token})
        return

    def _on_rotate_credentials(self, event: ops.ActionEvent) -> None:
        """Invalidate all sessions and reset admin account password.

        Args:
            event: The rotate credentials event.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            event.fail("Jenkins storage not yet mounted.")
            return
        charm_state = self._get_state()
        if not charm_state:
            event.fail("Jenkins charm is not yet ready.")
            return

        current_password = charm_state.admin_password
        try:
            if not current_password:
                current_password = jenkins.get_admin_credentials(container).password_or_token
        except jenkins.JenkinsBootstrapError as exc:
            logger.error("Failed to get admin credentials, %s", exc)
            event.fail("Jenkins has not yet bootstrapped.")
            return

        admin_client = jenkins.Jenkins(self._jenkins_prefix, current_password, container)
        try:
            admin_client.wait_ready(api_ready=True)
        except TimeoutError as exc:
            logger.warning(
                "phase=rotate_credentials wait_ready_timeout unit=%s app=%s jenkins_prefix=%s error=%s",
                self.unit.name,
                self.app.name,
                self._jenkins_prefix,
                exc,
            )
            event.fail("Jenkins service is not yet ready.")
            return

        try:
            password = admin_client.rotate_credentials(container)
        except jenkins.JenkinsError:
            event.fail("Error invalidating user sessions. See logs.")
            return

        try:
            secret = self.model.get_secret(label=self.app.name)
            secret.set_content({"password": password})
        except ops.SecretNotFoundError:
            self.app.add_secret(content={"password": password}, label=self.app.name)

        event.set_results({"password": password})


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
