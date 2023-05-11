#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
from typing import TYPE_CHECKING, Any, Dict, cast

from ops.charm import CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import Layer

from jenkins import JENKINS_WEB_URL, calculate_env, unlock_jenkins, wait_jenkins_ready
from types_ import JenkinsEnvironmentMap

if TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover


logger = logging.getLogger(__name__)


class JenkinsK8SOperatorCharm(CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args: Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the char base.
        """
        super().__init__(*args)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)

    def _get_pebble_layer(self, jenkins_env: JenkinsEnvironmentMap) -> Layer:
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
                    "environment": cast(Dict[str, str], jenkins_env),
                },
            },
            "checks": {
                "online": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": JENKINS_WEB_URL},
                    "period": "30s",
                    "threshold": 5,
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
            unlock_jenkins(container)
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
