# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import jenkinsapi
import pytest
from juju.application import Application
from juju.unit import Unit
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
