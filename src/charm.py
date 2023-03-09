#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]


class JenkinsK8SOperatorCharm(CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)

    def _on_jenkins_pebble_ready(self, event):
        """Start Jenkins."""
        container = event.workload
        container.add_layer("jenkins", self._pebble_layer, combine=True)
        container.replan()
        self.unit.status = ActiveStatus()

    @property
    def _pebble_layer(self):
        """Return a dictionary representing a Pebble layer."""
        return {
            "summary": "jenkins layer",
            "description": "pebble config layer for jenkins",
            "services": {
                "jenkins": {
                    "override": "replace",
                    "summary": "jenkins",
                    "command": "/bin/bash -t",
                    "startup": "enabled",
                    "environment": {},
                }
            },
        }


if __name__ == "__main__":  # pragma: nocover
    main(JenkinsK8SOperatorCharm)
