# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Jenkins agent relation observer."""
import ipaddress
import logging
import socket
import typing
from dataclasses import dataclass

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppReadyEvent, IngressPerAppRevokedEvent

import ingress
import jenkins
from state import (
    AGENT_DISCOVERY_INGRESS_RELATION_NAME,
    AGENT_RELATION,
    JENKINS_SERVICE_NAME,
    AgentMeta,
    State,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngressObservers:
    """Wrapper for ingress observers.

    Attributes:
        agent_discovery: Agent discovery ingress observer instance.
        server: Jenkins server ingress observer instance.
    """

    agent_discovery: ingress.Observer
    server: ingress.Observer


class Observer(ops.Object):
    """The Jenkins agent relation observer.

    Attributes:
        agent_discovery_url: external hostname to be passed to agents for discovery.
    """

    def __init__(
        self,
        charm: ops.CharmBase,
        state: State,
        observers: IngressObservers,
        jenkins_instance: jenkins.Jenkins,
    ):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
            state: The charm state.
            jenkins_instance: The Jenkins instance.
            observers: The ingress observers.
        """
        super().__init__(charm, "agent-observer")
        self.charm = charm
        self.state = state
        self.jenkins = jenkins_instance
        self.agent_discovery_ingress_observer = observers.agent_discovery
        self.ingress_observer = observers.server

        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_joined, self._on_agent_relation_joined
        )
        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_departed, self._on_agent_relation_departed
        )
        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_changed, self._on_agent_relation_changed
        )
        # Event hooks for agent-discovery-ingress
        charm.framework.observe(
            observers.agent_discovery.ingress.on.ready,
            self._ingress_on_ready,
        )
        charm.framework.observe(
            observers.agent_discovery.ingress.on.revoked,
            self._ingress_on_revoked,
        )
        charm.framework.observe(
            observers.server.ingress.on.ready,
            self._ingress_on_ready,
        )
        charm.framework.observe(
            observers.server.ingress.on.revoked,
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
        # Check if an agent-discovery or Jenkins server ingress URL is available
        # 2025/09/05 If the public ingress is secured (e.g. Oathkeeper), the agents will fail to
        # register.
        if ingress_url := self.agent_discovery_ingress_observer.ingress.url:
            return ingress_url
        if ingress_url := self.ingress_observer.ingress.url:
            logger.warning(
                "Using public ingress with protected endpoints (e.g. oathkeeper)"
                "will result in agent discovery failure. Use %s for agents discovery.",
                AGENT_DISCOVERY_INGRESS_RELATION_NAME,
            )
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

    @property
    def _status_message(self) -> str:
        """Status message to set on agent relation joined."""
        if (
            self.ingress_observer.ingress.url
            and not self.agent_discovery_ingress_observer.ingress.url
        ):
            return (
                f"Consider separating ingress for agents ({AGENT_DISCOVERY_INGRESS_RELATION_NAME})"
            )
        return ""

    def reconcile_agents(self, event: ops.EventBase) -> None:
        """Reconcile agents from relation data.

        Args:
            event: The event that triggered the agent reconcile.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if (
            not jenkins.is_storage_ready(container)
            or not jenkins.is_jenkins_ready(container=container)
            or not self.state.agent_relation_meta
        ):
            logger.warning("Service not yet ready, agents not reconciled.")
            event.defer()
            return

        # Make sure Jenkins is fully up and running before interacting with it.
        self.jenkins.wait_ready()

        self.charm.unit.status = ops.MaintenanceStatus("Reconciling agent nodes.")
        agent_nodes = self.jenkins.list_agent_nodes(container=container)
        agent_node_names = [node.name for node in agent_nodes]

        self._add_agent_nodes_from_relation(
            agent_relation=self.state.agent_relation_meta,
            container=container,
            agent_node_names=agent_node_names,
        )
        self._remove_agent_nodes_not_in_relation(
            agent_relation=self.state.agent_relation_meta,
            container=container,
            agent_node_names=agent_node_names,
        )

        self.charm.unit.status = ops.ActiveStatus(self._status_message)

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
        logger.info("Processing agent relations: %s", agent_relation)
        for relation, agents in agent_relation.items():
            logger.info("Processing agent relations: %s", agent_relation)
            unregistered_agents = [agent for agent in agents if agent.name not in agent_node_names]
            for agent in unregistered_agents:
                try:
                    logger.info("Adding agent node: %s", agent)
                    self.jenkins.add_agent_node(agent_meta=agent, container=container)
                    logger.info("Added agent node: %s", agent)
                except jenkins.JenkinsError:
                    logger.exception("Failed to register agent node: %s", agent)
                    raise

            agent_relation_data: dict[str, str] = {"url": self.agent_discovery_url}
            for agent in agents:
                try:
                    logger.info("Fetching agent secret: %s", agent)
                    agent_relation_data[f"{agent.name}_secret"] = self.jenkins.get_node_secret(
                        node_name=agent.name, container=container
                    )
                    logger.info("Fetched agent secret: %s", agent)
                except jenkins.JenkinsError:
                    logger.exception("Failed to get secret for registered node: %s", agent)
                    raise
            logger.info("Relation data: %ss", agent_relation_data)
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
        for agent in agents_not_in_relation:
            try:
                logger.info("Removing agent node: %s", agent)
                self.jenkins.remove_agent_node(agent_name=agent, container=container)
                logger.info("Removed agent node: %s", agent)
            except jenkins.JenkinsError:
                logger.exception("Failed to remove registered node: %s", agent)
                raise

    def _on_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle agent relation joined event.

        Args:
            event: The event fired on agent relation joined.
        """
        self.reconcile_agents(event=event)

    def _on_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle agent relation departed event.

        Args:
            event: The event fired on agent relation departed.
        """
        self.reconcile_agents(event=event)

    def _on_agent_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle agent relation changed event.

        Args:
            event: The event fired on agent relation changed.
        """
        self.reconcile_agents(event=event)

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
