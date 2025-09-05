# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Jenkins agent relation observer."""
import ipaddress
import logging
import socket
import typing

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppReadyEvent, IngressPerAppRevokedEvent

import ingress
import jenkins
from state import AGENT_RELATION, DEPRECATED_AGENT_RELATION, JENKINS_SERVICE_NAME, AgentMeta, State

logger = logging.getLogger(__name__)


class Observer(ops.Object):
    """The Jenkins agent relation observer.

    Attributes:
        agent_discovery_url: external hostname to be passed to agents for discovery.
    """

    def __init__(
        self,
        charm: ops.CharmBase,
        state: State,
        ingress_observer: ingress.Observer,
        jenkins_instance: jenkins.Jenkins,
    ):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
            state: The charm state.
            jenkins_instance: The Jenkins instance.
            ingress_observer: The ingress observer responsible for agent discovery.
        """
        super().__init__(charm, "agent-observer")
        self.charm = charm
        self.state = state
        self.jenkins = jenkins_instance
        self.ingress_observer = ingress_observer

        charm.framework.observe(
            charm.on[DEPRECATED_AGENT_RELATION].relation_joined,
            self._on_deprecated_agent_relation_joined,
        )
        charm.framework.observe(
            charm.on[DEPRECATED_AGENT_RELATION].relation_departed,
            self._on_deprecated_agent_relation_departed,
        )
        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_joined, self._on_agent_relation_joined
        )
        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_departed, self._on_agent_relation_departed
        )
        # Event hooks for agent-discovery-ingress
        charm.framework.observe(
            ingress_observer.ingress.on.ready,
            self._ingress_on_ready,
        )
        charm.framework.observe(
            ingress_observer.ingress.on.revoked,
            self._ingress_on_revoked,
        )

    @property
    def agent_discovery_url(self) -> str:
        """Return the external hostname to be passed to agents via the integration.

        If we do not have an ingress, then use the pod ip as hostname.
        The reason to prefer this over the pod name (which is the actual
        hostname visible from the pod) or a K8s service, is that those
        are routable virtually exclusively inside the cluster as they rely
        on the cluster's DNS service, while the ip address is _sometimes_
        routable from the outside, e.g., when deploying on MicroK8s on Linux.

        Returns:
            The charm's agent discovery url.
        """
        # Check if an ingress URL is available
        if ingress_url := self.ingress_observer.ingress.url:
            return ingress_url

        # Fallback to pod IP
        if binding := self.charm.model.get_binding("juju-info"):
            unit_ip = str(binding.network.bind_address)
            try:
                ipaddress.ip_address(unit_ip)
                env_dict = typing.cast(typing.Dict[str, str], self.jenkins.environment)
                return f"http://{unit_ip}:{jenkins.WEB_PORT}{env_dict['JENKINS_PREFIX']}"
            except ValueError as exc:
                logger.error(
                    "IP from juju-info is not valid: %s, we can still fall back to using fqdn", exc
                )

        # Fallback to using socket.fqdn
        return f"http://{socket.getfqdn()}:{jenkins.WEB_PORT}"

    def _on_deprecated_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle deprecated agent relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not jenkins.is_jenkins_ready(
            container=container
        ):
            logger.warning("Service not yet ready. Deferring.")
            event.defer()
            return
        # The relation is joined, it cannot be None, hence the type casting.
        deprecated_agent_relation_meta = typing.cast(
            typing.Mapping[str, AgentMeta], self.state.deprecated_agent_relation_meta
        )
        # The event unit cannot be None.
        agent_meta = deprecated_agent_relation_meta[typing.cast(ops.Unit, event.unit).name]
        if not agent_meta:
            logger.warning("Relation data not ready yet. Deferring.")
            # The event needs to be retried until the agents have set it's side of relation data.
            event.defer()
            return

        self.charm.unit.status = ops.MaintenanceStatus("Adding agent node.")
        try:
            self.jenkins.add_agent_node(agent_meta=agent_meta, container=container)
            secret = self.jenkins.get_node_secret(container=container, node_name=agent_meta.name)
        except jenkins.JenkinsError as exc:
            self.charm.unit.status = ops.BlockedStatus(f"Jenkins API exception. {exc=!r}")
            return

        jenkins_url = self.agent_discovery_url
        event.relation.data[self.model.unit].update({"url": jenkins_url, "secret": secret})
        self.charm.unit.status = ops.ActiveStatus()

    def _on_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle agent relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not jenkins.is_jenkins_ready(
            container=container
        ):
            logger.warning("Service not yet ready. Deferring.")
            event.defer()
            return

        # The relation is joined, it cannot be None, hence the type casting.
        agent_relation_meta = typing.cast(
            typing.Mapping[str, AgentMeta], self.state.agent_relation_meta
        )
        # The event unit cannot be None.
        agent_meta = agent_relation_meta[typing.cast(ops.Unit, event.unit).name]
        if not agent_meta:
            logger.warning("Relation data not ready yet. Deferring.")
            # The event needs to be retried until the agents have set it's side of relation data.
            event.defer()
            return

        self.charm.unit.status = ops.MaintenanceStatus("Adding agent node.")
        try:
            self.jenkins.wait_ready()
            self.jenkins.add_agent_node(agent_meta=agent_meta, container=container)
            secret = self.jenkins.get_node_secret(container=container, node_name=agent_meta.name)
        except jenkins.JenkinsError as exc:
            self.charm.unit.status = ops.BlockedStatus(f"Jenkins API exception. {exc=!r}")
            return

        jenkins_url = self.agent_discovery_url
        event.relation.data[self.model.unit].update(
            {"url": jenkins_url, f"{agent_meta.name}_secret": secret}
        )
        self.charm.unit.status = ops.ActiveStatus()

    def _on_deprecated_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle deprecated agent relation departed event.

        Args:
            event: The event fired when a unit in deprecated agent relation is departed.
        """
        # the event unit cannot be None.
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not jenkins.is_jenkins_ready(
            container=container
        ):
            logger.warning("Relation departed before service ready.")
            return

        # The relation data is removed before this particular hook runs, making the name set by the
        # agent not available. Hence, we can try to infer the name of the unit.
        # See discussion: https://github.com/canonical/operator/issues/888
        # assert type since event unit cannot be None.
        agent_name = jenkins.get_agent_name(typing.cast(ops.Unit, event.unit).name)
        self.charm.unit.status = ops.MaintenanceStatus("Removing agent node.")
        try:
            self.jenkins.remove_agent_node(agent_name=agent_name, container=container)
        except jenkins.JenkinsError as exc:
            logger.error("Failed to remove agent %s, %s", agent_name, exc)
            # There is no support for degraded status yet, however, this will not impact Jenkins
            # server operation.
            self.charm.unit.status = ops.ActiveStatus(f"Failed to remove {agent_name}")
            return
        self.charm.unit.status = ops.ActiveStatus()

    def _on_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle agent relation departed event.

        Args:
            event: The event fired when a unit in agent relation is departed.
        """
        # the event unit cannot be None.
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not jenkins.is_jenkins_ready(
            container=container
        ):
            logger.warning("Relation departed before service ready.")
            return

        # The relation data is removed before this particular hook runs, making the name set by the
        # agent not available. Hence, we can try to infer the name of the unit.
        # See discussion: https://github.com/canonical/operator/issues/888
        # assert type since event unit cannot be None.
        agent_name = jenkins.get_agent_name(typing.cast(ops.Unit, event.unit).name)
        self.charm.unit.status = ops.MaintenanceStatus("Removing agent node.")
        try:
            self.jenkins.remove_agent_node(agent_name=agent_name, container=container)
        except jenkins.JenkinsError as exc:
            logger.error("Failed to remove agent %s, %s", agent_name, exc)
            # There is no support for degraded status yet, however, this will not impact Jenkins
            # server operation.
            self.charm.unit.status = ops.ActiveStatus(f"Failed to remove {agent_name}")
            return
        self.charm.unit.status = ops.ActiveStatus()

    def reconfigure_agent_discovery(self, _: ops.EventBase) -> None:
        """Update the agent discovery URL in each of the connected agent's integration data.

        Will cause agents to restart!!
        """
        for relation in self.model.relations[AGENT_RELATION]:
            relation_discovery_url = relation.data[self.model.unit].get("url")
            if relation_discovery_url and relation_discovery_url == self.agent_discovery_url:
                continue
            relation.data[self.model.unit].update({"url": self.agent_discovery_url})

    def _ingress_on_ready(self, event: IngressPerAppReadyEvent) -> None:
        """Handle ready event for agent-discovery-ingress.

        Args:
            event: The event fired.
        """
        self.reconfigure_agent_discovery(event)

    def _ingress_on_revoked(self, event: IngressPerAppRevokedEvent) -> None:
        """Handle revoked event for agent-discovery-ingress.

        Args:
            event: The event fired.
        """
        self.reconfigure_agent_discovery(event)
