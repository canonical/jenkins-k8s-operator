#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
import typing

from ops.charm import ActionEvent, CharmBase, PebbleReadyEvent, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus
from ops.pebble import Layer

import jenkins
import state

if typing.TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover


logger = logging.getLogger(__name__)


class AgentRelationData(typing.TypedDict):
    """Relation data required for adding the Jenkins agent.

    Attrs:
        url: The Jenkins server url.
        secret: The secret for agent node.
    """

    url: str
    secret: str


class JenkinsK8SOperatorCharm(CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args: typing.Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the char base.
        """
        super().__init__(*args)
        self.state = state.State.from_charm(self.model.config)

        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on["agent"].relation_joined, self._on_agent_relation_joined)
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)

    @property
    def _jenkins_container(self) -> Container:
        """The Jenkins workload container."""
        return self.unit.get_container("jenkins")

    def _get_pebble_layer(self, jenkins_env: jenkins.EnvironmentMap) -> Layer:
        """Return a dictionary representing a Pebble layer.

        Args:
            jenkins_env: Map of Jenkins environment variables.

        Returns:
            The pebble layer defining Jenkins service layer.
        """
        layer: LayerDict = {
            "summary": "jenkins layer",
            "description": "pebble config layer for jenkins",
            "services": {
                "jenkins": {
                    "override": "replace",
                    "summary": "jenkins",
                    "command": "java -Djava.awt.headless=true -jar /srv/jenkins/jenkins.war",
                    "startup": "enabled",
                    # TypedDict and Dict[str,str] are not compatible.
                    "environment": typing.cast(typing.Dict[str, str], jenkins_env),
                },
            },
            "checks": {
                "online": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": jenkins.WEB_URL},
                    "period": "30s",
                    "threshold": 5,
                }
            },
        }
        return Layer(layer)

    def _on_jenkins_pebble_ready(self, event: PebbleReadyEvent) -> None:
        """Configure and start Jenkins server.

        Args:
            event: The event fired when pebble is ready.
        """
        container = event.workload
        if not container or not container.can_connect():
            event.defer()
            return

        self.unit.status = MaintenanceStatus("Installing Jenkins.")
        # First Jenkins server start installs Jenkins server.
        container.add_layer(
            "jenkins",
            self._get_pebble_layer(jenkins.calculate_env(admin_configured=False)),
            combine=True,
        )
        container.replan()
        try:
            jenkins.wait_ready()
            self.unit.status = MaintenanceStatus("Configuring Jenkins.")
            jenkins.bootstrap(
                container,
                self.state.jnlp_port,
                self.state.num_master_executors,
                self.state.plugins,
            )
            # Second Jenkins server start restarts Jenkins to bypass Wizard setup.
            container.add_layer(
                "jenkins",
                self._get_pebble_layer(jenkins.calculate_env(admin_configured=True)),
                combine=True,
            )
            container.replan()
            jenkins.wait_ready()
        except TimeoutError as exc:
            logger.error("Timed out waiting for Jenkins, %s", exc)
            self.unit.status = BlockedStatus("Timed out waiting for Jenkins.")
            return
        except jenkins.JenkinsBootstrapError as exc:
            logger.error("Error installing plugins, %s", exc)
            self.unit.status = BlockedStatus("Error installling plugins.")
            return

        self.unit.status = ActiveStatus()

    def _on_agent_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle agent relation joined event.

        Args:
            event: The event fired from an agent joining the relationship.
        """
        if not (binding := self.model.get_binding("juju-info")):
            return
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
        agent_meta = state.AgentMeta(
            executors=event.relation.data[event.unit]["executors"],
            labels=event.relation.data[event.unit]["labels"],
            slavehost=event.relation.data[event.unit]["slavehost"],
        )
        try:
            agent_meta.validate()
        except state.ValidationError as exc:
            logger.error("Invalid agent relation data. %s", exc)
            self.unit.status = BlockedStatus("Invalid agent relation data.")
            return

        self.unit.status = MaintenanceStatus("Adding agent node.")
        credentials = jenkins.get_admin_credentials(self._jenkins_container)
        jenkins_client = jenkins.get_client(client_credentials=credentials)
        try:
            jenkins.add_agent_node(
                jenkins_client=jenkins_client,
                agent_meta=agent_meta,
            )
            secret = jenkins.get_node_secret(
                jenkins_client=jenkins_client, node_name=agent_meta.slavehost
            )
        except jenkins.JenkinsError as exc:
            self.unit.status = BlockedStatus(f"Jenkins API exception. {exc=!r}")
            return

        host = binding.network.bind_address
        event.relation.data[self.model.unit].update(
            AgentRelationData(url=f"http://{str(host)}:8080", secret=secret)
        )
        self.unit.status = ActiveStatus()

    def _on_get_admin_password(self, event: ActionEvent) -> None:
        """Handle get-admin-password event.

        Args:
            event: The event fired from get-admin-password action.
        """
        if not self._jenkins_container.can_connect():
            event.defer()
            return
        credentials = jenkins.get_admin_credentials(self._jenkins_container)
        event.set_results({"password": credentials.password})


if __name__ == "__main__":  # pragma: nocover
    main(JenkinsK8SOperatorCharm)
