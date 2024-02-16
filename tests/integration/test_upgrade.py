# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test relation file."""


import logging

import ops
import requests
from juju.application import Application
from juju.model import Model
from pytest_operator.plugin import OpsTest

import jenkins

from .helpers import (
    gen_git_test_job_xml,
    generate_client_from_application,
    get_model_jenkins_unit_address,
)

LOGGER = logging.getLogger(__name__)
JENKINS_APP_NAME = "jenkins-k8s-upgrade"
JOB_NAME = "test_job"


async def test_jenkins_deploy_with_job(ops_test: OpsTest, model: Model):
    """
    arrange: given a juju model.

    act: deploy Jenkins, instantiate the Jenkins client and define a job.

    assert: the deployment has no errors.
    """
    application: Application = await model.deploy(
        "jenkins-k8s",
        application_name=JENKINS_APP_NAME,
        channel="stable",
    )
    await model.wait_for_idle(status="active", timeout=30 * 60)
    unit_web_client = await generate_client_from_application(ops_test, model, application)
    unit_web_client.client.create_job(JOB_NAME, gen_git_test_job_xml("k8s"))


async def test_jenkins_upgrade_check_job(
    ops_test: OpsTest, jenkins_image: str, model: Model, charm: ops.CharmBase
):
    """
    arrange: given charm has been built, deployed and a job has been defined.

    act: get Jenkins' version and upgrade the charm.

    assert: if Jenkins versions differ, the job persists.
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
        unit_web_client = await generate_client_from_application(ops_test, model, application)
        job = unit_web_client.client.get_job(JOB_NAME)
        assert job.name == JOB_NAME
