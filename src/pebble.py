# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pebble functionality."""

import logging
import typing

import ops

import jenkins
from state import JENKINS_SERVICE_NAME, State

if typing.TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover

logger = logging.getLogger(__name__)


def replan_jenkins(
    container: ops.Container, jenkins_instance: jenkins.Jenkins, state: State
) -> None:
    """Replan the jenkins services.

    Args:
        container: the container for with to replan the services.
        jenkins_instance: the Jenkins instance.
        state: the charm state.

    Raises:
        JenkinsBootstrapError: if an error occurs while bootstrapping Jenkins.
    """
    container.add_layer("jenkins", _get_pebble_layer(jenkins_instance), combine=True)
    container.replan()
    try:
        jenkins_instance.wait_ready()
        # Tested in integration
        if state.auth_proxy_integrated:  # pragma: no cover
            logger.info("Replanning jenkins with no security")
            jenkins_instance.bootstrap(
                container, jenkins.AUTH_PROXY_JENKINS_CONFIG, state.proxy_config
            )
        else:  # pragma: no cover
            logger.info("Replanning jenkins with security")
            jenkins_instance.bootstrap(
                container, jenkins.DEFAULT_JENKINS_CONFIG, state.proxy_config
            )
        # Second Jenkins server start restarts Jenkins to bypass Wizard setup.
        container.restart(JENKINS_SERVICE_NAME)
        jenkins_instance.wait_ready()
    except TimeoutError as exc:
        logger.error("Timed out waiting for Jenkins, %s", exc)
        raise jenkins.JenkinsBootstrapError from exc
    except jenkins.JenkinsBootstrapError as exc:
        logger.error("Error installing Jenkins, %s", exc)
        raise


def _get_pebble_layer(jenkins_instance: jenkins.Jenkins) -> ops.pebble.Layer:
    """Return a dictionary representing a Pebble layer.

    Args:
        jenkins_instance: the Jenkins instance.

    Returns:
        The pebble layer defining Jenkins service layer.
    """
    # TypedDict and Dict[str,str] are not compatible.
    env_dict = typing.cast(typing.Dict[str, str], jenkins_instance.environment)
    layer: LayerDict = {
        "summary": "jenkins layer",
        "description": "pebble config layer for jenkins",
        "services": {
            JENKINS_SERVICE_NAME: {
                "override": "replace",
                "summary": "jenkins",
                "command": f"java -D{jenkins.SYSTEM_PROPERTY_HEADLESS} "
                f"-D{jenkins.SYSTEM_PROPERTY_LOGGING} "
                f"-jar {jenkins.EXECUTABLES_PATH}/jenkins.war "
                f"--prefix={env_dict['JENKINS_PREFIX']}",
                "startup": "enabled",
                "environment": env_dict,
                "user": jenkins.USER,
                "group": jenkins.GROUP,
            },
        },
        "checks": {
            "online": {
                "override": "replace",
                "level": "ready",
                "http": {"url": jenkins_instance.login_url},
                "period": "30s",
                "threshold": 5,
            }
        },
    }
    return ops.pebble.Layer(layer)
