#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ops.charm import CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus
from ops.pebble import Layer

from jenkins_ import JENKINS_HOME, calculate_env, get_version, wait_jenkins_ready

if TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover


logger = logging.getLogger(__name__)

# Path to initial admin password file
INITIAL_PASSWORD = JENKINS_HOME / Path("secrets/initialAdminPassword")
# Path to last executed jenkins version file, required to override wizard installation
LAST_EXEC = JENKINS_HOME / Path("jenkins.install.InstallUtil.lastExecVersion")
# Path to jenkins version file, required to override wizard installation
UPDATE_VERSION = JENKINS_HOME / Path("jenkins.install.UpgradeWizard.state")


class JenkinsK8SOperatorCharm(CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args: Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the char base.
        """
        super().__init__(*args)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)

    def _unlock_jenkins(self, container: Container) -> None:
        """Write to executed version and updated version file to bypass Jenkins setup wizard.

        Args:
            container: The Jenkins container.
        """
        version = get_version()
        container.push(LAST_EXEC, version, encoding="utf-8", make_dirs=True)
        container.push(UPDATE_VERSION, version, encoding="utf-8", make_dirs=True)

    def _get_pebble_layer(self, env: dict[str, str]) -> Layer:
        """Return a dictionary representing a Pebble layer.

        Args:
            env: Map of Jenkins environment variables.

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
                    "environment": env,
                }
            },
        }
        return Layer(layer)

    def _on_jenkins_pebble_ready(self, event: PebbleReadyEvent) -> None:
        """Configure and start Jenkins server.

        Args:
            event: Event fired when pebble is ready.
        """
        container = event.workload
        if not container or not container.can_connect():
            event.defer()
            return

        self.unit.status = MaintenanceStatus("Configuring Jenkins.")
        container.add_layer(
            "jenkins", self._get_pebble_layer(calculate_env(admin_configured=False)), combine=True
        )
        container.replan()
        try:
            wait_jenkins_ready()
            self._unlock_jenkins(container)
            # add environment variable to trigger replan
            container.add_layer(
                "jenkins",
                self._get_pebble_layer(calculate_env(admin_configured=True)),
                combine=True,
            )
            container.replan()
            wait_jenkins_ready()
        except TimeoutError as err:
            logger.error("Timed out waiting for Jenkins, %s", err)
            self.unit.status = BlockedStatus("Timed out waiting for Jenkins.")
            return

        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(JenkinsK8SOperatorCharm)
