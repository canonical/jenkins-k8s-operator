# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test for upgrading the Jenkins charm."""

import logging

import jubilant
import pytest
import requests

from .helpers import (
    gen_git_test_job_xml,
    generate_unit_web_client_from_application,
    get_model_unit_addresses,
)
from .types_ import JujuApplication

LOGGER = logging.getLogger(__name__)
JENKINS_APP_NAME = "jenkins-k8s-upgrade"
JOB_NAME = "test_job"


@pytest.fixture(scope="module")
def jenkins_upgrade_depl(model: jubilant.Juju) -> None:
    """Deploy Jenkins and create a job before refreshing the charm."""
    model.deploy(
        "jenkins-k8s",
        app=JENKINS_APP_NAME,
        channel="stable",
    )
    model.wait(
        lambda status: jubilant.all_active(status, JENKINS_APP_NAME),
        error=jubilant.any_error,
        timeout=10 * 60,
    )
    status = model.status().apps[JENKINS_APP_NAME]
    application = JujuApplication(
        name=JENKINS_APP_NAME,
        model=model,
        units=tuple(status.units),
    )
    unit_web_client = generate_unit_web_client_from_application(model, application)
    unit_web_client.client.create_job(JOB_NAME, gen_git_test_job_xml("k8s"))


@pytest.mark.usefixtures("jenkins_upgrade_depl")
def test_jenkins_upgrade_check_job(
    model: jubilant.Juju,
    jenkins_image: str,
    charm: str,
) -> None:
    """Verify a Jenkins job survives a charm refresh."""
    unit_ips = get_model_unit_addresses(model, JENKINS_APP_NAME)
    assert unit_ips, f"Unit IP address not found for {JENKINS_APP_NAME}"
    address = f"http://{unit_ips[0]}:8080"
    response = requests.get(address, timeout=60)
    old_version = response.headers["X-Jenkins"]

    model.refresh(
        JENKINS_APP_NAME,
        path=charm,
        resources={"jenkins-image": jenkins_image},
    )
    model.wait(
        lambda status: jubilant.all_active(status, JENKINS_APP_NAME),
        error=jubilant.any_error,
        timeout=10 * 60,
    )
    unit_ips = get_model_unit_addresses(model, JENKINS_APP_NAME)
    assert unit_ips, f"Unit IP address not found for {JENKINS_APP_NAME}"
    address = f"http://{unit_ips[0]}:8080"
    response = requests.get(address, timeout=60)
    if old_version != response.headers["X-Jenkins"]:
        status = model.status().apps[JENKINS_APP_NAME]
        application = JujuApplication(
            name=JENKINS_APP_NAME,
            model=model,
            units=tuple(status.units),
        )
        unit_web_client = generate_unit_web_client_from_application(model, application)
        job = unit_web_client.client.get_job(JOB_NAME)
        assert job.name == JOB_NAME
