#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
import typing

from ops.charm import ActionEvent, CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus
from ops.pebble import Layer

import agent
import jenkins
from state import State

if typing.TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover


logger = logging.getLogger(__name__)


class JenkinsK8SOperatorCharm(CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args: typing.Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the char base.
        """
        super().__init__(*args)
        self.state = State.from_charm(self.model.config)

        self.agent_observer = agent.Observer(self, self.state)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)

    @property
    def _jenkins_container(self) -> Container:
        """The Jenkins workload container."""
        return self.unit.get_container(self.state.jenkins_service_name)

    def _get_pebble_layer(self, jenkins_env: jenkins.Environment) -> Layer:
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
                self.state.jenkins_service_name: {
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
            jenkins.bootstrap(container, self.state.jnlp_port)
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
