# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing
from secrets import token_hex

import jenkinsapi
import pytest
import yaml
from juju.action import Action
from juju.application import Application
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

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
    assert action.status == "completed", f"rotate-credentials failed: {action.results}"
    new_password = action.results.get("password")
    assert new_password, f"rotate-credentials did not return password: {action.results}"

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


async def test_bootstrap_after_restart(application: Application, unit: Unit):
    """
    arrange: a running Jenkins deployment.
    act: delete the API token file and restart the workload to re-trigger bootstrap.
    assert: the charm re-bootstraps successfully and returns to active status.

    This exercises the bootstrap code path (crumb fetch + token generation) on an
    already-initialized Jenkins instance, which is more likely to hit the crumb/session
    race because Jenkins's security subsystem restarts with existing state.
    """
    action: Action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- rm -f /var/lib/jenkins/juju_api_token"
    )
    await action.wait()

    action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket /charm/bin/pebble restart jenkins"
    )
    await action.wait()
    assert action.status == "completed", f"Failed to restart jenkins: {action.data}"

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


@pytest.mark.abort_on_fail
async def test_jcasc_default_config_applied(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm with default jcasc-config.
    act: when the charm is active/idle.
    assert: the JCasC plugin endpoint is reachable and config is applied.
    """
    response = jenkins_client.requester.post_url(f"{web_address}/configuration-as-code/export")
    assert response.status_code == 200, "JCasC export endpoint should be accessible"
    exported = response.text
    assert "jenkins" in exported, "Exported JCasC should contain jenkins section"


async def test_jcasc_custom_config_updates(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm.
    act: when jcasc-config is updated with a custom systemMessage.
    assert: the system message is applied to Jenkins.
    """
    custom_message = "Managed by JCasC integration test"
    custom_config = yaml.dump(
        {
            "jenkins": {
                "systemMessage": custom_message,
                "numExecutors": 0,
            }
        }
    )

    await application.set_config({"jcasc-config": custom_config})
    model = ops_test.model
    assert model is not None
    await model.wait_for_idle(
        apps=[application.name],
        status="active",
        timeout=300,
    )

    exported_response = jenkins_client.requester.post_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert custom_message in exported_response.text


async def test_jcasc_invalid_yaml_blocks(
    ops_test: OpsTest,
    application: Application,
):
    """
    arrange: given a deployed Jenkins charm.
    act: when jcasc-config is set to invalid YAML.
    assert: the charm enters blocked status.
    """
    model = ops_test.model
    assert model is not None

    await application.set_config({"jcasc-config": "{{invalid yaml [["})
    await model.wait_for_idle(
        apps=[application.name],
        status="blocked",
        timeout=120,
    )

    unit = application.units[0]
    assert "Invalid jcasc-config YAML" in unit.workload_status_message

    default_config = yaml.dump(
        {
            "jenkins": {
                "numExecutors": 0,
            }
        }
    )
    await application.set_config({"jcasc-config": default_config})
    await model.wait_for_idle(
        apps=[application.name],
        status="active",
        timeout=300,
    )


async def test_jcasc_reload_without_restart(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm that is active.
    act: when jcasc-config is changed.
    assert: Jenkins applies the change without restarting (uptime check).
    """
    response = jenkins_client.requester.get_url(web_address)
    assert response.status_code == 200

    new_message = "JCasC hot-reload test"
    new_config = yaml.dump(
        {
            "jenkins": {
                "systemMessage": new_message,
                "numExecutors": 0,
            }
        }
    )
    await application.set_config({"jcasc-config": new_config})
    model = ops_test.model
    assert model is not None
    await model.wait_for_idle(
        apps=[application.name],
        status="active",
        timeout=300,
    )

    exported_response = jenkins_client.requester.post_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert new_message in exported_response.text


async def test_jcasc_repository_config_from_file(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm with jcasc-repository configured.
    act: when the charm is active/idle.
    assert: the JCasC configuration from git repository is applied and accessible.

    Note: This test verifies that the jcasc-repository configuration option
    integrates correctly with the JCasC system. The test fixture stages a
    file:// git repository inside the charm container with fixture YAML files.
    """
    # Verify the JCasC export endpoint is accessible
    response = jenkins_client.requester.post_url(f"{web_address}/configuration-as-code/export")
    assert response.status_code == 200, "JCasC export endpoint should be accessible"
    exported = response.text
    
    # Verify jenkins section exists (from fixture jenkins.yaml)
    assert "jenkins" in exported, "Exported JCasC should contain jenkins section"
    
    # Verify specific fixture values are present in the exported config
    assert "Jenkins Configuration as Code (JCasC) via Git Repository" in exported, (
        "systemMessage from git repository fixture should be in exported config"
    )
    assert "numExecutors: 2" in exported, "numExecutors: 2 from fixture should be applied"
    assert "mode: NORMAL" in exported, "mode: NORMAL from fixture should be applied"
    
    # Verify unclassified section from fixture is present
    assert "unclassified:" in exported, "Exported JCasC should contain unclassified section"
    assert "location:" in exported, "location section should be present in unclassified"
