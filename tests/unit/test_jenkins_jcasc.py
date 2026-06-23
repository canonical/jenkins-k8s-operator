# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins JCasC and config-install unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import re
from functools import partial
from unittest.mock import MagicMock

import jenkinsapi
import ops
import pytest
import requests

import jenkins

from .types_ import HarnessWithContainer


def _jenkins_instance(container: ops.Container) -> jenkins.Jenkins:
    """Create Jenkins client wrapper for tests."""
    return jenkins.Jenkins("/", "admin-password", container)


def test__unlock_wizard(
    harness_container: HarnessWithContainer,
    mocked_get_request,
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """unlock_wizard writes both wizard bypass version files."""
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))

    jenkins.unlock_wizard(harness_container.container, jenkins_version)

    assert (
        harness_container.container.pull(jenkins.LAST_EXEC_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )
    assert (
        harness_container.container.pull(jenkins.WIZARD_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )


def test__unlock_wizard_raises_exception(
    mocked_get_request,
    monkeypatch: pytest.MonkeyPatch,
):
    """unlock_wizard raises JenkinsError on container push failure."""
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsError):
        jenkins.unlock_wizard(mock_container, "2.401.1")


def test_install_config(harness_container: HarnessWithContainer):
    """_install_configs writes Jenkins config file with default JNLP port."""
    jenkins._install_configs(harness_container.container, jenkins.DEFAULT_JENKINS_CONFIG)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    jnlp_match = re.search(r"<slaveAgentPort>(\d+)</slaveAgentPort>", config_xml)
    assert jnlp_match, "Configuration for jnlp port not found."
    assert jnlp_match.group(1) == "50000", "jnlp not set as default port."


def test_install_config_raises_exception():
    """_install_configs raises JenkinsBootstrapError on write failure."""
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins._install_configs(mock_container, jenkins.DEFAULT_JENKINS_CONFIG)


def test_install_auth_proxy_config(harness_container: HarnessWithContainer):
    """install_auth_proxy_config writes unsecured Jenkins config."""
    jenkins.install_auth_proxy_config(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    assert "<useSecurity>false</useSecurity>" in config_xml


def test_install_auth_proxy_config_raises_exception():
    """install_auth_proxy_config raises JenkinsBootstrapError on write failure."""
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.install_auth_proxy_config(mock_container)


def test_install_defalt_config(harness_container: HarnessWithContainer):
    """install_default_config writes secured Jenkins config."""
    jenkins.install_default_config(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    assert "<useSecurity>true</useSecurity>" in config_xml


def test_install_default_config_raises_exception():
    """install_default_config raises JenkinsBootstrapError on write failure."""
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.install_default_config(mock_container)


def test__set_jenkins_system_message_error(mock_client: MagicMock):
    """_set_jenkins_system_message raises JenkinsError on groovy API failure."""
    mock_client.run_groovy_script.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins._set_jenkins_system_message("test", mock_client)


def test__set_jenkins_system_message(mock_client: MagicMock):
    """_set_jenkins_system_message sends groovy script to client."""
    message = "hello world!"
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    jenkins._set_jenkins_system_message(message, mock_client)

    mock_groovy_script.assert_called()
