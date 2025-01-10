# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing
from secrets import token_hex

import jenkinsapi
import pytest
from juju.action import Action
from juju.application import Application
from juju.unit import Unit

from .helpers import gen_test_job_xml, install_plugins
from .types_ import UnitWebClient

JENKINS_UID = "2000"
JENKINS_GID = "2000"


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
    assert "New version of Jenkins" not in page_content


@pytest.mark.usefixtures("app_with_restart_time_range", "libfaketime_unit")
async def test_jenkins_automatic_update_out_of_range(
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
    await install_plugins(unit_web_client, (extra_plugin,))
    action: Action = await unit_web_client.unit.run(
        f"-- {' '.join(libfaketime_env)} {' '.join(update_status_env)} ./dispatch"
    )
    await action.wait()
    assert (
        action.status == "completed"
    ), f"Failed to execute update-status-hook, {action.data['message']}"

    assert unit_web_client.client.has_plugin(
        extra_plugin
    ), "additionally installed plugin cleanedup."


async def test_rotate_password_action(jenkins_user_client: jenkinsapi.jenkins.Jenkins, unit: Unit):
    """
    arrange: given a jenkins API session that is connected.
    act: when rotate password action is called.
    assert: the session is invalidated and new password is returned.
    """
    session = jenkins_user_client.requester.session
    session.auth = (jenkins_user_client.username, jenkins_user_client.password)
    result = session.get(f"{jenkins_user_client.baseurl}/manage")
    assert result.status_code == 200, "Unable to access Jenkins with initial credentials."
    action: Action = await unit.run_action("rotate-credentials")
    await action.wait()
    new_password: str = action.results["password"]

    assert jenkins_user_client.password != new_password, "Password not rotated"
    result = session.get(f"{jenkins_user_client.baseurl}/manage")
    assert result.status_code == 401, "Session not cleared"
    new_client = jenkinsapi.jenkins.Jenkins(jenkins_user_client.baseurl, "admin", new_password)
    result = new_client.requester.get_url(f"{jenkins_user_client.baseurl}/manage/")
    assert result.status_code == 200, "Invalid password"


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


async def test_storage_mount_owner(application: Application):
    """
    arrange: after Jenkins charm has been deployed and storage mounted.
    act: get jenkins_home directory owner.
    assert: jenkins_home belongs to jenkins user.
    """
    jenkins_unit: Unit = application.units[0]
    command = 'stat -c "%u %g" /var/lib/jenkins'

    action: Action = await jenkins_unit.run(command=command, timeout=60)
    await action.wait()

    assert action.results.get("return-code") == 0
    assert f"{JENKINS_UID} {JENKINS_GID}" in str(action.results.get("stdout"))
