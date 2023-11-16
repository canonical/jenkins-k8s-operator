# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import jenkinsapi
import pytest
from juju.action import Action
from pytest_operator.plugin import OpsTest

from .helpers import install_plugins
from .substrings import assert_substrings_not_in_string
from .types_ import UnitWebClient


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
    libfaketime_env: typing.Iterable[str],
    update_status_env: typing.Iterable[str],
    unit_web_client: UnitWebClient,
):
    """
    arrange: given jenkins charm with frozen time to 15:00 UTC.
    act: when restart-time-range between 3AM to 5AM is applied.
    assert: the maintenance (plugins removal) does not take place.
    """
    extra_plugin = "oic-auth"
    await install_plugins(ops_test, unit_web_client.unit, unit_web_client.client, (extra_plugin,))
    ret_code, _, stderr = await ops_test.juju(
        "run",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(libfaketime_env)} {' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    assert unit_web_client.client.has_plugin(
        extra_plugin
    ), "additionally installed plugin cleanedup."


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
