# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Jenkins agent relation observer."""
import logging
import typing

import ops

import jenkins
from state import AGENT_RELATION, SLAVE_RELATION, State

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
            charm.on[SLAVE_RELATION].relation_joined, self._on_slave_relation_joined
        )
        charm.framework.observe(
            charm.on[SLAVE_RELATION].relation_departed, self._on_slave_relation_departed
        )
        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_joined, self._on_agent_relation_joined
        )
        charm.framework.observe(
            charm.on[AGENT_RELATION].relation_departed, self._on_agent_relation_departed
        )

    def _on_slave_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Handle slave relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        container = self.charm.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            event.defer()
            return
        if not event.unit or not all(
            event.relation.data[event.unit].get(required_data)
            for required_data in ("executors", "labels", "slavehost")
        ):
            logger.warning("Relation data not ready yet. Deferring.")
            event.defer()
            return
        agent_meta = jenkins.AgentMeta(
            executors=event.relation.data[event.unit]["executors"],
            labels=event.relation.data[event.unit]["labels"],
            name=event.relation.data[event.unit]["slavehost"],
        )
        try:
            agent_meta.validate()
        except jenkins.ValidationError as exc:
            logger.error("Invalid agent relation data. %s", exc)
            self.charm.unit.status = ops.BlockedStatus("Invalid agent relation data.")
            return

        self.charm.unit.status = ops.MaintenanceStatus("Adding agent node.")
        credentials = jenkins.get_admin_credentials(container)
        try:
            jenkins.add_agent_node(
                agent_meta=agent_meta,
                credentials=credentials,
            )
            secret = jenkins.get_node_secret(credentials=credentials, node_name=agent_meta.name)
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
        container = self.charm.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            event.defer()
            return
        if not event.unit or not all(
            event.relation.data[event.unit].get(required_data)
            for required_data in ("executors", "labels", "name")
        ):
            logger.warning("Relation data not ready yet. Deferring.")
            event.defer()
            return
        agent_meta = jenkins.AgentMeta(
            executors=event.relation.data[event.unit]["executors"],
            labels=event.relation.data[event.unit]["labels"],
            name=event.relation.data[event.unit]["name"],
        )
        try:
            agent_meta.validate()
        except jenkins.ValidationError as exc:
            logger.error("Invalid agent relation data. %s", exc)
            self.charm.unit.status = ops.BlockedStatus("Invalid agent relation data.")
            return

        self.charm.unit.status = ops.MaintenanceStatus("Adding agent node.")
        credentials = jenkins.get_admin_credentials(container)
        try:
            jenkins.add_agent_node(
                agent_meta=agent_meta,
                credentials=credentials,
            )
            secret = jenkins.get_node_secret(credentials=credentials, node_name=agent_meta.name)
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

    def _on_slave_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle slave relation departed event.

        Args:
            event: The event fired when a unit in slave relation is departed.
        """
        # the event unit cannot be None.
        container = self.charm.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            return

        # The relation data is removed before this particular hook runs, making the name set by the
        # agent not available. Hence, we can try to infer the name of the unit.
        # See discussion: https://github.com/canonical/operator/issues/888
        # assert type since event unit cannot be None.
        agent_name = jenkins.get_agent_name(typing.cast(ops.Unit, event.unit).name)
        credentials = jenkins.get_admin_credentials(container)
        self.charm.unit.status = ops.MaintenanceStatus("Removing agent node.")
        try:
            jenkins.remove_agent_node(agent_name=agent_name, credentials=credentials)
        except jenkins.JenkinsError as exc:
            logger.error("Failed to remove agent %s, %s", agent_name, exc)
            # There is no support for degraded status yet, however, this will not impact Jenkins
            # server operation.
            self.charm.unit.status = ops.ActiveStatus(f"Failed to remove {agent_name}")
            return
        self.charm.unit.status = ops.ActiveStatus()

    def _on_agent_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle slave relation departed event.

        Args:
            event: The event fired when a unit in slave relation is departed.
        """
        # the event unit cannot be None.
        container = self.charm.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            return

        # The relation data is removed before this particular hook runs, making the name set by the
        # agent not available. Hence, we can try to infer the name of the unit.
        # See discussion: https://github.com/canonical/operator/issues/888
        # assert type since event unit cannot be None.
        agent_name = jenkins.get_agent_name(typing.cast(ops.Unit, event.unit).name)
        credentials = jenkins.get_admin_credentials(container)
        self.charm.unit.status = ops.MaintenanceStatus("Removing agent node.")
        try:
            jenkins.remove_agent_node(agent_name=agent_name, credentials=credentials)
        except jenkins.JenkinsError as exc:
            logger.error("Failed to remove agent %s, %s", agent_name, exc)
            # There is no support for degraded status yet, however, this will not impact Jenkins
            # server operation.
            self.charm.unit.status = ops.ActiveStatus(f"Failed to remove {agent_name}")
            return
        self.charm.unit.status = ops.ActiveStatus()
