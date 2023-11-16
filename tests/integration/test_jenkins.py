# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing
from secrets import token_hex

import jenkinsapi
import pytest
from juju.action import Action
from juju.application import Application
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from .helpers import gen_test_job_xml, install_plugins
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


async def test_storage_mount(
    application: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: a bare Jenkins charm.
    act: Add a job, scale the charm to 0 unit and scale back to 1.
    assert: The job configuration persists and is the same as the one used.
    """
    test_job_name = token_hex(8)
    job_configuration = gen_test_job_xml("built-in")
    jenkins_client.create_job(test_job_name, job_configuration)

    await application.scale(scale=0)
    await application.model.wait_for_idle(
        apps=[application.name],
        timeout=20 * 60,
        idle_period=30,
        wait_for_exact_units=0,
    )

    await application.scale(scale=1)
    await application.model.wait_for_idle(
        apps=[application.name],
        timeout=20 * 60,
        idle_period=30,
        wait_for_exact_units=1,
    )

    jenkins_unit: Unit = application.units[0]
    assert jenkins_unit
    command = f"cat /var/lib/jenkins/jobs/{test_job_name}/config.xml"
    action: Action = await jenkins_unit.run(command=command, timeout=60)
    await action.wait()
    assert action.results.get("return-code") == 0
    # Remove leading and trailing newline since jenkins client autoformat config
    assert job_configuration.strip("\n") in str(action.results.get("stdout"))
