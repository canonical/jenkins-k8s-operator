# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing
from secrets import token_hex

import jenkinsapi
import pytest
from juju.application import Application
from juju.client import client
from juju.client._definitions import FullStatus, UnitStatus
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from .substrings import assert_substrings_not_in_string
from .types_ import ModelAppUnit


async def test_jenkins_update_ui_disabled(
    web_address: str, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """
    arrange: a Jenkins deployment.
    act: -
    assert: The UI with update suggestion does not pop out
    """
    res = jenkins_client.requester.get_url(f"{web_address}/manage")

    page_content = str(res.content, encoding="utf-8")
    assert_substrings_not_in_string(
        ("New version of Jenkins", "is available", "download"), page_content
    )


@pytest.mark.usefixtures("app_with_restart_time_range", "libfaketime_unit")
async def test_jenkins_automatic_update_out_of_range(
    ops_test: OpsTest,
    application: Application,
    libfaketime_env: typing.Iterable[str],
    update_status_env: typing.Iterable[str],
    jenkins_version: str,
):
    """
    arrange: given jenkins charm with frozen time to 15:00 UTC.
    act: when restart-time-range between 3AM to 5AM is applied.
    assert: the update does not take place.
    """
    unit: Unit = application.units[0]
    ret_code, _, stderr = await ops_test.juju(
        "run",
        "--unit",
        unit.name,
        "--",
        f"{' '.join(libfaketime_env)} {' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"

    # get patched application workload version
    model_status: client.FullStatus = await application.model.get_status()
    app_status = model_status.applications.get(application.name)
    assert app_status, "application status not found."

    assert app_status.workload_version == jenkins_version, "Application should not have updated."


async def test_jenkins_automatic_update(
    ops_test: OpsTest,
    model_app_unit: ModelAppUnit,
    jenkins_version: str,
    update_status_env: typing.Iterable[str],
    latest_jenkins_lts_version: str,
):
    """
    arrange: a Jenkins deployment that has not yet been upgraded.
    act: update status hook is triggered.
    assert: The latest LTS Jenkins version is set as workload version.
    """
    # get original application workload version
    status: client.FullStatus = await model_app_unit.model.get_status()
    app_status = status.applications.get(model_app_unit.app.name)
    assert app_status, "application status not found."
    original_workload_version = app_status.workload_version
    assert (
        original_workload_version == jenkins_version
    ), "The Jenkins should not already be updated."

    ret_code, _, stderr = await ops_test.juju(
        "run",
        "--unit",
        model_app_unit.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    updated_status: client.FullStatus = await model_app_unit.model.get_status()
    updated_app_status = updated_status.applications.get(model_app_unit.app.name)
    assert updated_app_status, "updated application status not found."

    updated_workload_version = updated_app_status.workload_version
    assert updated_workload_version == latest_jenkins_lts_version, "The Jenkins should be updated."


async def test_jenkins_persist_jobs_on_restart(
    model_app_unit: ModelAppUnit,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    jenkins_new_job_configuration: str,
):
    """
    arrange: a bare Jenkins charm.
    act: Add a job, scale the charm to 0 unit and scale back to 1.
    assert: The job configuration persists.
    """
    test_job_name = token_hex(8)
    jenkins_client.create_job(test_job_name, jenkins_new_job_configuration)

    await model_app_unit.app.scale(scale=0)
    await model_app_unit.model.wait_for_idle(
        apps=[model_app_unit.app.name],
        timeout=20 * 60,
        idle_period=30,
        wait_for_exact_units=0,
    )

    await model_app_unit.app.scale(scale=1)
    await model_app_unit.model.wait_for_idle(
        apps=[model_app_unit.app.name],
        timeout=20 * 60,
        idle_period=30,
        wait_for_exact_units=1,
    )

    # Get the new unit's IP address, this is a hack until support for ingress is implemented
    status: FullStatus = await model_app_unit.model.get_status([model_app_unit.app.name])
    unit_status: UnitStatus = next(
        iter(status.applications[model_app_unit.app.name].units.values())
    )
    # Check if the new unit has a valid IP address
    assert unit_status.address, "Invalid unit address"
    client = jenkinsapi.jenkins.Jenkins(
        baseurl=f"http://{unit_status.address}:8080",
        username=jenkins_client.username,
        password=jenkins_client.password,
    )

    job = client.get_job(test_job_name)
    assert job.name == test_job_name
