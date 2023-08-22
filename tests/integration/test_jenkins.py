# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import jenkinsapi
from juju.client import client
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


async def test_jenkins_automatic_update_out_of_range(
    ops_test: OpsTest,
    timerange_model_app_unit: ModelAppUnit,
    libfaketime_env: typing.Iterable[str],
    update_status_env: typing.Iterable[str],
    jenkins_version: str,
):
    """
    arrange: given jenkins charm with frozen time to 15:00 UTC.
    act: when restart-time-range between 3AM to 5AM is applied.
    assert: the update does not take place.
    """
    ret_code, _, stderr = await ops_test.juju(
        "run",
        "--unit",
        timerange_model_app_unit.unit.name,
        "--",
        f"{' '.join(libfaketime_env)} {' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"

    # get patched application workload version
    model_status: client.FullStatus = await timerange_model_app_unit.model.get_status()
    app_status = model_status.applications.get(timerange_model_app_unit.app.name)
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
