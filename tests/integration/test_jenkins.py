# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging
import os
from pathlib import Path
from secrets import token_hex
from urllib.parse import quote

import jenkinsapi
import jubilant
import pytest
import requests
import yaml

from .helpers import exec_in_container, gen_test_job_xml, install_plugins
from .types_ import JujuApplication, UnitWebClient

JENKINS_UID = "2000"
JENKINS_GID = "2000"
logger = logging.getLogger(__name__)


def test_jenkins_update_ui_disabled(
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify the Jenkins UI does not show an update suggestion."""
    response = jenkins_client.requester.get_url(f"{web_address}/manage")
    page_content = str(response.content, encoding="utf-8")
    assert "New version of Jenkins" not in page_content


@pytest.mark.usefixtures("app_with_restart_time_range", "libfaketime_unit")
def test_jenkins_automatic_update_out_of_range(
    model: jubilant.Juju,
    unit: str,
    libfaketime_env: tuple[str, ...],
    update_status_env: tuple[str, ...],
    unit_web_client: UnitWebClient,
) -> None:
    """Verify maintenance does not run outside the configured restart window."""
    extra_plugin = "oic-auth"
    install_plugins(unit_web_client, (extra_plugin,))
    command = f"{' '.join(libfaketime_env)} {' '.join(update_status_env)} ./dispatch"
    exec_in_container(model, unit, "charm", command)
    assert unit_web_client.client.has_plugin(extra_plugin), (
        "additionally installed plugin cleaned up."
    )


def test_rotate_password_action(
    model: jubilant.Juju,
    application: JujuApplication,
    unit: str,
    jenkins_user_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify rotating credentials invalidates the old session."""
    session = jenkins_user_client.requester.session
    session.auth = (jenkins_user_client.username, jenkins_user_client.password)
    result = session.get(f"{jenkins_user_client.baseurl}/manage")
    assert result.status_code == 200, "Unable to access Jenkins with initial credentials."

    action = model.run(unit, "rotate-credentials")
    assert action.success, f"rotate-credentials failed: {action.results}"
    new_password = action.results.get("password")
    assert new_password, f"rotate-credentials did not return password: {action.results}"
    assert jenkins_user_client.password != new_password, "Password not rotated"

    result = session.get(f"{jenkins_user_client.baseurl}/manage")
    assert result.status_code == 401, "Session not cleared"
    new_client = jenkinsapi.jenkins.Jenkins(
        jenkins_user_client.baseurl,
        "admin",
        new_password,
    )
    result = new_client.requester.get_url(f"{jenkins_user_client.baseurl}/manage/")
    assert result.status_code == 200, "Invalid password"


def _wait_for_unit_count(model: jubilant.Juju, application: str, count: int) -> None:
    """Wait until an application has exactly *count* units."""
    model.wait(
        lambda status: len(status.apps[application].units) == count
        and (count == 0 or jubilant.all_active(status, application)),
        error=jubilant.any_error,
        timeout=20 * 60,
    )


def test_storage_mount(
    model: jubilant.Juju,
    application: JujuApplication,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify Jenkins job configuration survives scaling the application."""
    test_job_name = token_hex(8)
    job_configuration = gen_test_job_xml("built-in")
    jenkins_client.create_job(test_job_name, job_configuration)

    model.cli("scale-application", application.name, "0")
    _wait_for_unit_count(model, application.name, 0)
    model.cli("scale-application", application.name, "1")
    _wait_for_unit_count(model, application.name, 1)

    jenkins_unit = next(iter(model.status().apps[application.name].units))
    command = f"cat /var/lib/jenkins/jobs/{test_job_name}/config.xml"
    output = exec_in_container(model, jenkins_unit, "jenkins", command)
    assert job_configuration.strip("\n") in output


def test_storage_mount_owner(
    model: jubilant.Juju,
    application: JujuApplication,
) -> None:
    """Verify jenkins_home belongs to the Jenkins user."""
    unit = next(iter(model.status().apps[application.name].units))
    output = exec_in_container(model, unit, "jenkins", 'stat -c "%u %g" /var/lib/jenkins')
    assert f"{JENKINS_UID} {JENKINS_GID}" in output


def test_bootstrap_after_restart(
    model: jubilant.Juju,
    application: JujuApplication,
) -> None:
    """Verify Jenkins reboots and re-bootstraps after its API token is removed."""
    unit = next(iter(model.status().apps[application.name].units))
    exec_in_container(
        model,
        unit,
        "charm",
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- rm -f /var/lib/jenkins/juju_api_token",
    )
    exec_in_container(
        model,
        unit,
        "charm",
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket /charm/bin/pebble restart jenkins",
    )
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=10 * 60,
    )
    assert model.status().apps[application.name].is_active, (
        "Jenkins failed to re-bootstrap after restart"
    )


def test_jcasc_default_config_applied(
    application: JujuApplication,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify the default JCasC configuration is applied."""
    response = jenkins_client.requester.post_url(f"{web_address}/configuration-as-code/export")
    assert response.status_code == 200, "JCasC export endpoint should be accessible"
    assert "jenkins" in response.text, "Exported JCasC should contain jenkins section"


def test_jcasc_custom_config_updates(
    model: jubilant.Juju,
    application: JujuApplication,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify changing jcasc-config updates the Jenkins system message."""
    custom_message = "Managed by JCasC integration test"
    custom_config = yaml.dump({"jenkins": {"systemMessage": custom_message, "numExecutors": 0}})
    model.config(application.name, {"jcasc-config": custom_config})
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=300,
    )
    exported_response = jenkins_client.requester.post_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert custom_message in exported_response.text


def test_jcasc_invalid_yaml_blocks(
    model: jubilant.Juju,
    application: JujuApplication,
) -> None:
    """Verify invalid JCasC YAML blocks the charm and can be recovered."""
    model.config(application.name, {"jcasc-config": "{{invalid yaml [["})
    model.wait(
        lambda status: jubilant.all_blocked(status, application.name),
        error=jubilant.any_error,
        timeout=120,
    )
    unit = next(iter(model.status().apps[application.name].units))
    assert (
        "Invalid jcasc-config YAML"
        in model.status().apps[application.name].units[unit].workload_status.message
    )

    default_config = yaml.dump({"jenkins": {"numExecutors": 0}})
    model.config(application.name, {"jcasc-config": default_config})
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=300,
    )


def test_jcasc_reload_without_restart(
    model: jubilant.Juju,
    application: JujuApplication,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify JCasC changes are applied without restarting Jenkins."""
    response = jenkins_client.requester.get_url(web_address)
    assert response.status_code == 200

    new_message = "JCasC hot-reload test"
    new_config = yaml.dump({"jenkins": {"systemMessage": new_message, "numExecutors": 0}})
    model.config(application.name, {"jcasc-config": new_config})
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=300,
    )
    exported_response = jenkins_client.requester.post_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert new_message in exported_response.text


def _working_branch() -> str | None:
    """Return the branch checked out by the test runner, when available."""
    if github_head_ref := os.environ.get("GITHUB_HEAD_REF"):
        return github_head_ref

    try:
        git_dir = Path(__file__).parent.parent.parent / ".git"
        head = (git_dir / "HEAD").read_text().strip()
        if head.startswith("ref: refs/heads/"):
            return head.removeprefix("ref: refs/heads/")
    except OSError:
        return None
    return None


def _remote_branch_exists(repository: str, branch: str) -> bool:
    """Return whether a branch exists in the configured JCasC repository."""
    repository_path = repository.removeprefix("https://github.com/").removesuffix(".git")
    branch_url = (
        f"https://api.github.com/repos/{repository_path}/git/ref/heads/{quote(branch, safe='')}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "jenkins-k8s-operator-integration-tests",
    }
    if github_token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        response = requests.get(branch_url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        logger.warning("Unable to probe JCasC repository branch: branch=%s error=%s", branch, exc)
        return False

    logger.info(
        "JCasC repository branch probe: repository=%s branch=%s available=%s status=%s",
        repository,
        branch,
        response.status_code == 200,
        response.status_code,
    )
    return response.status_code == 200


def _get_current_branch(repository: str) -> str:
    """Return the current branch when it exists in the configured repository."""
    branch = _working_branch()
    if branch and _remote_branch_exists(repository, branch):
        return branch

    logger.info(
        "Using JCasC repository fallback branch: repository=%s branch=main requested=%s",
        repository,
        branch or "none",
    )
    return "main"


def test_jcasc_repository_config_from_file(
    model: jubilant.Juju,
    application: JujuApplication,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    test_jcasc_repository: str,
) -> None:
    """Verify JCasC configuration loaded from the configured Git repository."""
    branch = _get_current_branch(test_jcasc_repository)
    repository_config = {
        "jcasc-config": "",
        "jcasc-repository": test_jcasc_repository,
        "jcasc-repository-branch": branch,
        "jcasc-repository-config-path": "tests/integration/data/jcasc",
    }
    logger.info(
        "Configuring JCasC repository: repository=%s branch=%s config_path=%s",
        repository_config["jcasc-repository"],
        repository_config["jcasc-repository-branch"],
        repository_config["jcasc-repository-config-path"],
    )
    model.config(application.name, repository_config)
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    response = jenkins_client.requester.post_url(f"{web_address}/configuration-as-code/export")
    assert response.status_code == 200, "JCasC export endpoint should be accessible"
    exported = response.text
    assert "jenkins" in exported, "Exported JCasC should contain jenkins section"
    assert "Jenkins Configuration as Code (JCasC) via Git Repository" in exported
    assert "numExecutors: 2" in exported
    assert "mode: NORMAL" in exported
    assert "unclassified:" in exported
    assert "location:" in exported
