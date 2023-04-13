#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
from time import sleep
from typing import TYPE_CHECKING

import requests
from jenkinsapi.jenkins import Jenkins
from ops.charm import CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus
from ops.pebble import Layer

from path import INITIAL_PASSWORD, JENKINS_HOME, LAST_EXEC, UPDATE_VERSION

if TYPE_CHECKING:
    from ops.pebble import LayerDict

logger = logging.getLogger(__name__)


class JenkinsK8SOperatorCharm(CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)

    def _get_pebble_layer(self, env: dict[str, str] | None = None) -> Layer:
        """Return a dictionary representing a Pebble layer."""
        default_env = {"JENKINS_HOME": str(JENKINS_HOME)}
        merged_env = default_env | env if env else default_env
        layer: LayerDict = {
            "summary": "jenkins layer",
            "description": "pebble config layer for jenkins",
            "services": {
                "jenkins": {
                    "override": "replace",
                    "summary": "jenkins",
                    "command": "java -Djava.awt.headless=true -jar /srv/jenkins/jenkins.war",
                    "startup": "enabled",
                    "environment": merged_env,
                }
            },
        }
        return Layer(layer)

    def _is_jenkins_ready(self) -> bool:
        """Check if Jenkins webserver is ready."""
        try:
            requests.get("http://localhost:8080/login", timeout=10).raise_for_status()
            return True
        except requests.HTTPError:
            return False

    def _wait_jenkins_ready(self) -> None:
        """Wait until Jenkins service is up.

        Raises:
            TimeoutError: if Jenkins status check did not pass within the timeout duration.
        """
        for _ in range(140):
            if self._is_jenkins_ready():
                return
            sleep(10)
        else:
            raise TimeoutError("Timed out waiting for Jenkins to become ready.")

    def _get_admin_credentials(self, container: Container):
        """Retrieve admin credentials.

        Args:
            container: The Jenkins container.
        """
        user = "admin"
        password = container.pull(INITIAL_PASSWORD, encoding="utf-8").read().strip()
        return (user, password)

    def _unlock_jenkins(self, container: Container) -> None:
        """Write to executed version and updated version file to bypass Jenkins setup wizard.

        Args:
            container: The Jenkins container.
        """
        (username, password) = self._get_admin_credentials(container)
        client = Jenkins("http://localhost:8080", username, password)
        container.push(LAST_EXEC, client.version, encoding="utf-8", make_dirs=True)
        container.push(UPDATE_VERSION, client.version, encoding="utf-8", make_dirs=True)

    def _on_jenkins_pebble_ready(self, event: PebbleReadyEvent):
        """Configure and start Jenkins server.

        Args:
            event: Event fired when pebble is ready.
        """
        container = event.workload
        if not container or not container.can_connect():
            event.defer()
            return

        self.unit.status = MaintenanceStatus("Configuring Jenkins.")
        container.add_layer("jenkins", self._get_pebble_layer(), combine=True)
        container.replan()
        try:
            self._wait_jenkins_ready()
            self._unlock_jenkins(container)
            # add environment variable to trigger replan
            container.add_layer(
                "jenkins", self._get_pebble_layer({"admin_configured": "true"}), combine=True
            )
            container.replan()
            self._wait_jenkins_ready()
        except TimeoutError as err:
            logger.error("Timed out waiting for Jenkins, %s", err)
            self.unit.status = BlockedStatus("Timed out waiting for Jenkins.")
            return

        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main(JenkinsK8SOperatorCharm)
