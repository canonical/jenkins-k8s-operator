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
    assert action.status == "completed", (
        f"Failed to execute update-status-hook, {action.data['message']}"
    )

    assert unit_web_client.client.has_plugin(extra_plugin), (
        "additionally installed plugin cleanedup."
    )


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


async def test_bootstrap_completion_marker_exists(unit: Unit):
    """
    arrange: a running Jenkins deployment.
    act: check for the charm bootstrap completion marker.
    assert: the marker exists under Jenkins home.
    """
    action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- test -f /var/lib/jenkins/.charm/bootstrap-complete"
    )
    await action.wait()
    assert action.results.get("return-code") == 0, (
        "Bootstrap completion marker missing at /var/lib/jenkins/.charm/bootstrap-complete"
    )


async def test_bootstrap_legacy_backfill_skips_runtime_rebootstrap(
    application: Application,
    unit: Unit,
):
    """
    arrange: a running Jenkins deployment with legacy bootstrap artifacts present.
    act: remove only the new bootstrap marker and restart Jenkins to trigger pebble-ready reconcile.
    assert: marker is backfilled and API token remains unchanged (runtime re-bootstrap skipped).
    """
    check_legacy_action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- sh -c "
        "'test -f /var/lib/jenkins/secrets/apiToken && "
        "test -f /var/lib/jenkins/jenkins.install.InstallUtil.lastExecVersion && "
        "test -f /var/lib/jenkins/jenkins.install.UpgradeWizard.state'"
    )
    await check_legacy_action.wait()
    assert check_legacy_action.results.get("return-code") == 0, (
        "Legacy bootstrap artifacts must exist before marker backfill test."
    )

    token_before_action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- cat /var/lib/jenkins/secrets/apiToken"
    )
    await token_before_action.wait()
    assert token_before_action.results.get("return-code") == 0
    token_before = str(token_before_action.results.get("stdout", "")).strip()
    assert token_before, "Expected existing Jenkins API token before marker backfill test."

    remove_marker_action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- rm -f /var/lib/jenkins/.charm/bootstrap-complete"
    )
    await remove_marker_action.wait()
    assert remove_marker_action.results.get("return-code") == 0

    restart_action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket /charm/bin/pebble restart jenkins"
    )
    await restart_action.wait()
    assert restart_action.status == "completed", f"Failed to restart jenkins: {restart_action.data}"

    model = unit.model
    await model.wait_for_idle(
        apps=[application.name],
        raise_on_error=False,
        status="active",
        raise_on_blocked=True,
        timeout=10 * 60,
        idle_period=30,
    )
    assert application.status == "active", (
        f"Jenkins failed to settle after legacy marker backfill trigger: {application.status}"
    )

    marker_backfilled_action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- test -f /var/lib/jenkins/.charm/bootstrap-complete"
    )
    await marker_backfilled_action.wait()
    assert marker_backfilled_action.results.get("return-code") == 0, (
        "Bootstrap marker was not backfilled after legacy artifact detection."
    )

    token_after_action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- cat /var/lib/jenkins/secrets/apiToken"
    )
    await token_after_action.wait()
    assert token_after_action.results.get("return-code") == 0
    token_after = str(token_after_action.results.get("stdout", "")).strip()
    assert token_after == token_before, "API token changed unexpectedly; runtime re-bootstrap likely ran."


async def test_bootstrap_after_restart(application: Application, unit: Unit):
    """
    arrange: a running Jenkins deployment.
    act: delete the API token file and restart the workload to re-trigger bootstrap.
    assert: the charm re-bootstraps successfully and returns to active status.

    This exercises the bootstrap code path (crumb fetch + token generation) on an
    already-initialized Jenkins instance, which is more likely to hit the crumb/session
    race because Jenkins's security subsystem restarts with existing state.
    """
    # Delete the API token to force re-bootstrap on next pebble-ready
    action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- rm -f /var/lib/jenkins/juju_api_token"
    )
    await action.wait()

    # Restart the jenkins service — triggers pebble-ready → bootstrap
    action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket /charm/bin/pebble restart jenkins"
    )
    await action.wait()
    assert action.status == "completed", f"Failed to restart jenkins: {action.data}"

    # Wait for the charm to re-settle — if crumb race hits, this will error/block
    model = unit.model
    await model.wait_for_idle(
        apps=[application.name],
        raise_on_error=False,
        status="active",
        raise_on_blocked=True,
        timeout=10 * 60,
        idle_period=30,
    )
    assert application.status == "active", (
        f"Jenkins failed to re-bootstrap after restart: {application.status}"
    )
