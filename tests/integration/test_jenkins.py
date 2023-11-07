# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import jenkinsapi
import pytest
from juju.action import Action
from juju.application import Application
from juju.client import client
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from .substrings import assert_substrings_not_in_string
from .types_ import ModelAppUnit, UnitWebClient


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


async def test_rotate_password_action(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins API session that is connected.
    act: when rotate password action is called.
    assert: the session is invalidated and new password is returned.
    """
    session = unit_web_client.client.requester.session
    session.get(f"{unit_web_client.web}/manage/")
    action: Action = await unit_web_client.unit.run_action("rotate-credentials")
    await action.wait()
    new_password: str = action.results["password"]

    assert unit_web_client.client.password != new_password, "Password not rotated"
    result = session.get(f"{unit_web_client.web}/manage/")
    assert result.status_code == 403, "Session not cleared"
    new_client = jenkinsapi.jenkins.Jenkins(unit_web_client.web, "admin", new_password)
    result = new_client.requester.get_url(f"{unit_web_client.web}/manage/")
    assert result.status_code == 200, "Invalid password"
