#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
import typing

from ops.charm import ActionEvent, CharmBase, PebbleReadyEvent, UpdateStatusEvent
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
        self.state = State.from_charm()

        self.agent_observer = agent.Observer(self, self.state)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)
        self.framework.observe(self.on.update_status, self._on_update_status)

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
                    "command": "java -Djava.awt.headless=true -Dhudson.model.UpdateCenter.never=true -jar /srv/jenkins/jenkins.war",
                    "startup": "enabled",
                    # TypedDict and Dict[str,str] are not compatible.
                    "environment": typing.cast(typing.Dict[str, str], jenkins_env),
                    "user": jenkins.USER,
                    "group": jenkins.GROUP,
                },
            },
            "checks": {
                "online": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": jenkins.LOGIN_URL},
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
            self._get_pebble_layer(jenkins.calculate_env()),
            combine=True,
        )
        container.replan()
        try:
            jenkins.wait_ready()
            self.unit.status = MaintenanceStatus("Configuring Jenkins.")
            jenkins.bootstrap(container)
            # Second Jenkins server start restarts Jenkins to bypass Wizard setup.
            container.restart(self.state.jenkins_service_name)
            jenkins.wait_ready()
        except TimeoutError as exc:
            logger.error("Timed out waiting for Jenkins, %s", exc)
            self.unit.status = BlockedStatus("Timed out waiting for Jenkins.")
            return
        except jenkins.JenkinsBootstrapError as exc:
            logger.error("Error installing plugins, %s", exc)
            self.unit.status = BlockedStatus("Error installling plugins.")
            return

        self.unit.set_workload_version(jenkins.get_version())
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

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status event.

        On Update status:
        1. Update Jenkins patch LTS version if available.
        2. Update apt packages if available.
        """
        self.unit.status = ActiveStatus("Checking for updates.")

        version = jenkins.get_version()
        latest_patch_version = jenkins.get_latest_patch_version(version)
        if latest_patch_version == version:
            self.unit.status = ActiveStatus()
            return

        self.unit.status = MaintenanceStatus("Updating Jenkins.")
        try:
            jenkins.download_stable_war(self._jenkins_container)
            credentials = jenkins.get_admin_credentials(self._jenkins_container)
            jenkins.safe_restart(credentials)
        except (jenkins.JenkinsNetworkError, jenkins.JenkinsError) as exc:
            logger.error(f"Failed to update Jenkins. {exc=!r}")

        self.unit.set_workload_version(latest_patch_version)
        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(JenkinsK8SOperatorCharm)
