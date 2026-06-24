# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pebble functionality."""

import logging
import typing
from pathlib import Path

import ops

import jenkins
from state import JENKINS_SERVICE_NAME, State

if typing.TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover

JENKINS_WAR_PATH = Path("/srv/jenkins/jenkins.war")

logger = logging.getLogger(__name__)


def compute_pebble_layer(
    jenkins_environment: dict[str, str], state: State
) -> ops.pebble.Layer:
    """Return a dictionary representing a Pebble layer.

    Args:
        jenkins_environment: the Jenkins environment variables.
        state: the charm state.

    Returns:
        The pebble layer defining Jenkins service layer.
    """
    system_props = " ".join(state.system_properties) if state.system_properties else ""
    layer: LayerDict = {
        "summary": "jenkins layer",
        "description": "pebble config layer for jenkins",
        "services": {
            JENKINS_SERVICE_NAME: {
                "override": "replace",
                "summary": "jenkins",
                "command": f"java -D{jenkins.SYSTEM_PROPERTY_HEADLESS} "
                f"-D{jenkins.SYSTEM_PROPERTY_LOGGING} "
                f"{system_props}"
                "-XX:MaxRAMPercentage=50.0 -XX:InitialRAMPercentage=50.0 "
                f"-jar {jenkins.EXECUTABLES_PATH}/jenkins.war "
                f"--prefix={jenkins_environment['JENKINS_PREFIX']}",
                "startup": "enabled",
                "environment": jenkins_environment,
                "user": jenkins.USER,
                "group": jenkins.GROUP,
            },
        },
        "checks": {
            jenkins.ONLINE_CHECK_NAME: {
                "override": "replace",
                "level": "ready",
                "http": {
                    "url": f"http://localhost:{jenkins.WEB_PORT}"
                    f"{jenkins_environment['JENKINS_PREFIX']}"
                },
                "period": "30s",
                "threshold": 5,
            }
        },
    }
    return ops.pebble.Layer(layer)


def get_jenkins_version(container: ops.Container) -> str:
    """Extract the Jenkins version from the WAR file.

    Args:
        container: The Jenkins workload container.

    Returns:
        The Jenkins version string.
    """
    process = container.exec(
        ["java", "-jar", str(JENKINS_WAR_PATH), "--version"],
        timeout=30,
        user=jenkins.USER,
        group=jenkins.GROUP,
    )
    stdout, _ = process.wait_output()
    return stdout.strip()
