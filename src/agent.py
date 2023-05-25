# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Jenkins agent relation observer."""
import logging
import typing

from ops.charm import CharmBase, RelationJoinedEvent
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus

import jenkins
from state import State

logger = logging.getLogger(__name__)


class AgentRelationData(typing.TypedDict):
    """Relation data required for adding the Jenkins agent.

    Attrs:
        url: The Jenkins server url.
        secret: The secret for agent node.
    """

    url: str
    secret: str


class Observer(Object):
    """The Jenkins agent relation observer."""

    def __init__(self, charm: CharmBase, state: State):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
            state: The charm state.
        """
        super().__init__(charm, "agent-observer")
        self.charm = charm
        self.state = state

        charm.framework.observe(charm.on["agent"].relation_joined, self._on_agent_relation_joined)

    @property
    def _jenkins_container(self) -> Container:
        """The Jenkins workload container."""
        return self.charm.unit.get_container(self.state.jenkins_service_name)

    def _on_agent_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle agent relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        if not self._jenkins_container.can_connect():
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
            slavehost=event.relation.data[event.unit]["slavehost"],
        )
        try:
            agent_meta.validate()
        except jenkins.ValidationError as exc:
            logger.error("Invalid agent relation data. %s", exc)
            self.charm.unit.status = BlockedStatus("Invalid agent relation data.")
            return

        self.charm.unit.status = MaintenanceStatus("Adding agent node.")
        credentials = jenkins.get_admin_credentials(self._jenkins_container)
        try:
            jenkins.add_agent_node(
                agent_meta=agent_meta,
                credentials=credentials,
            )
            secret = jenkins.get_node_secret(
                credentials=credentials, node_name=agent_meta.slavehost
            )
        except jenkins.JenkinsError as exc:
            self.charm.unit.status = BlockedStatus(f"Jenkins API exception. {exc=!r}")
            return

        # This is to avoid the None type.
        assert (binding := self.model.get_binding("juju-info"))  # nosec
        host = binding.network.bind_address
        event.relation.data[self.model.unit].update(
            AgentRelationData(url=f"http://{str(host)}:8080", secret=secret)
        )
        self.charm.unit.status = ActiveStatus()
