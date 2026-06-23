# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins JCasC and config-install unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import re
from functools import partial
from typing import Callable
from unittest.mock import MagicMock

import jenkinsapi
import ops
import pytest
import requests

import jenkins

from .types_ import HarnessWithContainer


def _failing_container() -> ops.Container:
    """Return container mock failing on push()."""
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )
    return mock_container


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

    with pytest.raises(jenkins.JenkinsError):
        jenkins.unlock_wizard(_failing_container(), "2.401.1")


def test_install_config(harness_container: HarnessWithContainer):
    """_install_configs writes Jenkins config file with default JNLP port."""
    jenkins._install_configs(harness_container.container, jenkins.DEFAULT_JENKINS_CONFIG)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    jnlp_match = re.search(r"<slaveAgentPort>(\d+)</slaveAgentPort>", config_xml)
    assert jnlp_match, "Configuration for jnlp port not found."
    assert jnlp_match.group(1) == "50000", "jnlp not set as default port."


@pytest.mark.parametrize(
    "installer, expected_security_snippet",
    [
        pytest.param(
            jenkins.install_auth_proxy_config,
            "<useSecurity>false</useSecurity>",
            id="auth-proxy-config",
        ),
        pytest.param(
            jenkins.install_default_config,
            "<useSecurity>true</useSecurity>",
            id="default-config",
        ),
    ],
)
def test_install_security_configs(
    harness_container: HarnessWithContainer,
    installer: Callable[[ops.Container], None],
    expected_security_snippet: str,
):
    """Security config installers write expected <useSecurity> value."""
    installer(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )
    assert expected_security_snippet in config_xml


@pytest.mark.parametrize(
    "installer, install_args",
    [
        pytest.param(
            jenkins._install_configs,
            (jenkins.DEFAULT_JENKINS_CONFIG,),
            id="install-config",
        ),
        pytest.param(jenkins.install_auth_proxy_config, (), id="install-auth-proxy-config"),
        pytest.param(jenkins.install_default_config, (), id="install-default-config"),
    ],
)
def test_installers_raise_bootstrap_error_on_write_failure(
    installer: Callable[..., None],
    install_args: tuple,
):
    """Config installers raise JenkinsBootstrapError when container push fails."""
    with pytest.raises(jenkins.JenkinsBootstrapError):
        installer(_failing_container(), *install_args)


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
