# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins JCasC and config-install unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import re
from functools import partial
from typing import Callable
from unittest.mock import MagicMock, patch

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


def test_install_plugins_executes_plugin_manager_command():
    """install_plugins invokes jenkins plugin manager with expected command layout."""
    mock_container = MagicMock(spec=ops.Container)
    mock_process = MagicMock(spec=ops.pebble.ExecProcess)
    mock_process.wait_output.return_value = ("Done", "")
    mock_container.exec.return_value = mock_process

    jenkins.install_plugins(mock_container, ["plugin-a", "plugin-b"])

    executed_command = mock_container.exec.call_args.args[0]
    assert executed_command[0] == "java"
    assert "-jar" in executed_command
    assert (
        f"jenkins-plugin-manager-{jenkins.JENKINS_PLUGIN_MANAGER_VERSION}.jar" in executed_command
    )
    assert "--latest" in executed_command
    plugins_arg = executed_command[executed_command.index("-p") + 1]
    assert set(plugins_arg.split(" ")) == {"plugin-a", "plugin-b"}


def test_install_plugins_raises_bootstrap_error_on_exec_failure():
    """install_plugins raises JenkinsBootstrapError when command execution fails."""
    mock_container = MagicMock(spec=ops.Container)
    mock_process = MagicMock(spec=ops.pebble.ExecProcess)
    mock_process.wait_output.side_effect = ops.pebble.ExecError(
        command=["java"],
        exit_code=1,
        stdout="",
        stderr="failed",
    )
    mock_container.exec.return_value = mock_process

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.install_plugins(mock_container, ["plugin-a"])


def test_get_java_proxy_args_with_auth_and_no_proxy(proxy_config):
    """_get_java_proxy_args renders JVM flags for authenticated proxy with no_proxy list."""
    args = tuple(jenkins._get_java_proxy_args(proxy_config))

    assert any(flag.startswith("-Dhttp.proxyUser=") for flag in args)
    assert any(flag.startswith("-Dhttp.proxyPassword=") for flag in args)
    assert any(flag.startswith("-Dhttps.proxyUser=") for flag in args)
    assert any(flag.startswith("-Dhttps.proxyPassword=") for flag in args)
    assert any(flag.startswith("-Dhttp.nonProxyHosts=") for flag in args)


def test_get_java_proxy_args_without_credentials_omits_auth_flags(partial_proxy_config):
    """_get_java_proxy_args omits user/password flags when proxy credentials are absent."""
    args = tuple(jenkins._get_java_proxy_args(partial_proxy_config))

    assert not any(flag.startswith("-Dhttp.proxyUser=") for flag in args)
    assert not any(flag.startswith("-Dhttp.proxyPassword=") for flag in args)
    assert not any(flag.startswith("-Dhttps.proxyUser=") for flag in args)
    assert not any(flag.startswith("-Dhttps.proxyPassword=") for flag in args)


def test_get_groovy_proxy_args_uses_https_proxy_first(proxy_config):
    """_get_groovy_proxy_args prefers https proxy values when both proxies are present."""
    args = tuple(jenkins._get_groovy_proxy_args(proxy_config))

    assert args[0] == f"'{proxy_config.https_proxy.host}'"
    assert args[1] == f"{proxy_config.https_proxy.port}"
    assert args[2] == f"'{proxy_config.https_proxy.user}'"
    assert args[3] == f"'{proxy_config.https_proxy.password}'"
    assert args[4] == f"'{proxy_config.no_proxy}'"


def test_get_groovy_proxy_args_http_fallback_without_https(http_partial_proxy_config):
    """_get_groovy_proxy_args falls back to http proxy when https proxy is absent."""
    args = tuple(jenkins._get_groovy_proxy_args(http_partial_proxy_config))

    assert args == (
        f"'{http_partial_proxy_config.http_proxy.host}'",
        f"{http_partial_proxy_config.http_proxy.port}",
        "''",
        "''",
    )


@pytest.mark.parametrize(
    "status_code, expected",
    [
        pytest.param(200, True, id="valid-config"),
        pytest.param(400, False, id="invalid-config"),
    ],
)
def test_check_jcasc_returns_status_from_endpoint(
    status_code: int,
    expected: bool,
    harness_container: HarnessWithContainer,
):
    """check_jcasc returns True only when check endpoint responds with HTTP 200."""
    manager = jenkins.Jenkins("/", "admin-password", harness_container.container)
    mock_requester = MagicMock()
    mock_requester.post_url.return_value = MagicMock(status_code=status_code)
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.requester = mock_requester

    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        assert manager.check_jcasc("jenkins:\n  systemMessage: test\n") is expected


def test_check_jcasc_raises_jenkins_error_on_request_exception(
    harness_container: HarnessWithContainer,
):
    """check_jcasc converts request failures into JenkinsError."""
    manager = jenkins.Jenkins("/", "admin-password", harness_container.container)
    mock_requester = MagicMock()
    mock_requester.post_url.side_effect = requests.exceptions.RequestException("boom")
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.requester = mock_requester

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        pytest.raises(jenkins.JenkinsError, match="Failed to validate JCasC configuration"),
    ):
        manager.check_jcasc("jenkins:\n  systemMessage: test\n")


def test_reload_jcasc_posts_reload_endpoint(harness_container: HarnessWithContainer):
    """reload_jcasc posts to the JCasC reload endpoint."""
    manager = jenkins.Jenkins("/", "admin-password", harness_container.container)
    mock_requester = MagicMock()
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.requester = mock_requester

    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        manager.reload_jcasc()

    mock_requester.post_url.assert_called_once_with(
        f"{manager.web_url}/configuration-as-code/reload"
    )


def test_reload_jcasc_raises_jenkins_error_on_request_exception(
    harness_container: HarnessWithContainer,
):
    """reload_jcasc converts request failures into JenkinsError."""
    manager = jenkins.Jenkins("/", "admin-password", harness_container.container)
    mock_requester = MagicMock()
    mock_requester.post_url.side_effect = requests.exceptions.RequestException("boom")
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.requester = mock_requester

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        pytest.raises(jenkins.JenkinsError, match="Failed to reload JCasC configuration"),
    ):
        manager.reload_jcasc()
