# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=redefined-outer-name,unused-argument,duplicate-code

"""Integration test relation file."""

import logging

import jenkinsapi.jenkins
import ops
import requests
from juju.application import Application
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

import jenkins

from .constants import ALL_PLUGINS
from .helpers import get_model_jenkins_unit_address, install_plugins
from .types_ import UnitWebClient

LOGGER = logging.getLogger(__name__)
JENKINS_APP_NAME = "jenkins-k8s-upgrade"


async def test_jenkins_deploy_with_plugins(ops_test: OpsTest, model: Model):
    """
    arrange: given a juju model.
    act: deploy Jenkins, instantiate the Jenkins client and install the plugins.
    assert: the deployment has no errors.
    """
    application: Application = await model.deploy(
        "jenkins-k8s",
        application_name=JENKINS_APP_NAME,
        channel="edge",
    )
    await application.set_config({"allowed-plugins": ",".join(ALL_PLUGINS)})
    await model.wait_for_idle(status="active", timeout=30 * 60)
    address = await get_model_jenkins_unit_address(model, JENKINS_APP_NAME)
    jenkins_unit = application.units[0]
    ret, api_token, stderr = await ops_test.juju(
        "ssh",
        "--container",
        "jenkins",
        jenkins_unit.name,
        "cat",
        str(jenkins.API_TOKEN_PATH),
    )
    assert ret == 0, f"Failed to get Jenkins API token, {stderr}"
    jenkins_client = jenkinsapi.jenkins.Jenkins(
        f"http://{address}:{jenkins.WEB_PORT}", "admin", api_token, timeout=60 * 10
    )
    unit_web_client = UnitWebClient(
        unit=jenkins_unit, web=f"http://{address}:{jenkins.WEB_PORT}", client=jenkins_client
    )
    await install_plugins(unit_web_client, ALL_PLUGINS)


async def test_jenkins_upgrade_check_plugins(
    ops_test: OpsTest, jenkins_image: str, model: Model, charm: ops.CharmBase
):
    """
    arrange: given charm has been built, deployed and plugins have been installed.
    act: get Jenkins' version, upgrade the charm and if the versions differ, check plugins.
    assert: all the installed plugins are up and running.
    """
    application = model.applications[JENKINS_APP_NAME]
    address = await get_model_jenkins_unit_address(model, JENKINS_APP_NAME)
    response = requests.get(f"http://{address}:{jenkins.WEB_PORT}", timeout=60)
    old_version = response.headers["X-Jenkins"]
    await application.refresh(path=charm, resources={"jenkins-image": jenkins_image})
    await model.wait_for_idle(status="active", timeout=30 * 60)
    address = await get_model_jenkins_unit_address(model, JENKINS_APP_NAME)
    response = requests.get(f"http://{address}:{jenkins.WEB_PORT}", timeout=60)
    if old_version != response.headers["X-Jenkins"]:
        jenkins_unit: Unit = application.units[0]
        ret, api_token, stderr = await ops_test.juju(
            "ssh",
            "--container",
            "jenkins",
            jenkins_unit.name,
            "cat",
            str(jenkins.API_TOKEN_PATH),
        )
        assert ret == 0, f"Failed to get Jenkins API token, {stderr}"
        jenkins_client_new = jenkinsapi.jenkins.Jenkins(
            f"http://{address}:{jenkins.WEB_PORT}", "admin", api_token, timeout=60 * 10
        )
        unit_web_client_new = UnitWebClient(
            unit=jenkins_unit,
            web=f"http://{address}:{jenkins.WEB_PORT}",
            client=jenkins_client_new,
        )
        troubled_plugins = [
            plugin for plugin in ALL_PLUGINS if not unit_web_client_new.client.has_plugin(plugin)
        ]
        assert troubled_plugins == [], f"The following plugins have trouble: {troubled_plugins}"
