# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Jenkins agent relation observer."""
import logging
import typing

import ops

import jenkins
from state import AGENT_RELATION, DEPRECATED_AGENT_RELATION, JENKINS_SERVICE_NAME, AgentMeta, State

logger = logging.getLogger(__name__)


class AgentRelationData(typing.TypedDict):
    """Relation data required for adding the Jenkins agent.

    Attributes:
        url: The Jenkins server url.
        secret: The secret for agent node.
    """

    url: str
    secret: str


class Observer(ops.Object):
    """The Jenkins agent relation observer."""

    def __init__(self, charm: ops.CharmBase, state: State):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
            state: The charm state.
        """
        super().__init__(charm, "agent-observer")
        self.charm = charm
        self.state = state

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

    def _on_deprecated_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle deprecated agent relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not container.can_connect() or not self.state.is_storage_ready:
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
            event.defer()
            return

        self.charm.unit.status = ops.MaintenanceStatus("Adding agent node.")
        try:
            jenkins.add_agent_node(
                agent_meta=agent_meta,
                container=container,
            )
            secret = jenkins.get_node_secret(container=container, node_name=agent_meta.name)
        except jenkins.JenkinsError as exc:
            self.charm.unit.status = ops.BlockedStatus(f"Jenkins API exception. {exc=!r}")
            return

        # This is to avoid the None type.
        assert (binding := self.model.get_binding("juju-info"))  # nosec
        host = binding.network.bind_address
        event.relation.data[self.model.unit].update(
            AgentRelationData(url=f"http://{host}:{jenkins.WEB_PORT}", secret=secret)
        )
        self.charm.unit.status = ops.ActiveStatus()

    def _on_agent_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle agent relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not container.can_connect() or not self.state.is_storage_ready:
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
            event.defer()
            return

        self.charm.unit.status = ops.MaintenanceStatus("Adding agent node.")
        try:
            jenkins.add_agent_node(
                agent_meta=agent_meta,
                container=container,
            )
            secret = jenkins.get_node_secret(container=container, node_name=agent_meta.name)
        except jenkins.JenkinsError as exc:
            self.charm.unit.status = ops.BlockedStatus(f"Jenkins API exception. {exc=!r}")
            return

        # This is to avoid the None type.
        assert (binding := self.model.get_binding("juju-info"))  # nosec
        host = binding.network.bind_address
        event.relation.data[self.model.unit].update(
            {
                "url": f"http://{host}:{jenkins.WEB_PORT}",
                f"{agent_meta.name}_secret": secret,
            }
        )
        self.charm.unit.status = ops.ActiveStatus()

    def _on_deprecated_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle deprecated agent relation departed event.

        Args:
            event: The event fired when a unit in deprecated agent relation is departed.
        """
        # the event unit cannot be None.
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not container.can_connect() or not self.state.is_storage_ready:
            logger.warning("Relation departed before service ready.")
            return

        # The relation data is removed before this particular hook runs, making the name set by the
        # agent not available. Hence, we can try to infer the name of the unit.
        # See discussion: https://github.com/canonical/operator/issues/888
        # assert type since event unit cannot be None.
        agent_name = jenkins.get_agent_name(typing.cast(ops.Unit, event.unit).name)
        self.charm.unit.status = ops.MaintenanceStatus("Removing agent node.")
        try:
            jenkins.remove_agent_node(agent_name=agent_name, container=container)
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
        if not container.can_connect() or not self.state.is_storage_ready:
            logger.warning("Relation departed before service ready.")
            return

        # The relation data is removed before this particular hook runs, making the name set by the
        # agent not available. Hence, we can try to infer the name of the unit.
        # See discussion: https://github.com/canonical/operator/issues/888
        # assert type since event unit cannot be None.
        agent_name = jenkins.get_agent_name(typing.cast(ops.Unit, event.unit).name)
        self.charm.unit.status = ops.MaintenanceStatus("Removing agent node.")
        try:
            jenkins.remove_agent_node(agent_name=agent_name, container=container)
        except jenkins.JenkinsError as exc:
            logger.error("Failed to remove agent %s, %s", agent_name, exc)
            # There is no support for degraded status yet, however, this will not impact Jenkins
            # server operation.
            self.charm.unit.status = ops.ActiveStatus(f"Failed to remove {agent_name}")
            return
        self.charm.unit.status = ops.ActiveStatus()
