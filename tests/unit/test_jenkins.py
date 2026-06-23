# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins module tests."""

# Need access to protected functions for testing
# All tests belong to single jenkins module
# pylint:disable=protected-access, too-many-lines

import re
import secrets
import textwrap
import typing
from functools import partial
from unittest.mock import MagicMock, PropertyMock, patch

import jenkinsapi
import ops
import pytest
import requests
from ops.pebble import ExecError, ExecProcess

import jenkins
import state

from .types_ import HarnessWithContainer


def test__unlock_wizard(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[..., requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a mocked container and a monkeypatched Jenkins client.
    act: unlock_jenkins is called.
    assert: files necessary to unlock Jenkins and bypass wizard are written.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))

    jenkins.Jenkins(mock_env)._unlock_wizard(harness_container.container)

    assert (
        harness_container.container.pull(jenkins.LAST_EXEC_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )
    assert (
        harness_container.container.pull(jenkins.WIZARD_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )


def test__unlock_wizard_raises_exception(
    mocked_get_request: typing.Callable[..., requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a container raising an exception and a monkeypatched Jenkins client.
    act: unlock_jenkins is called.
    assert: a JenkinsBootstrapError is raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.Jenkins(mock_env)._unlock_wizard(mock_container)


def test_install_config(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked uninitialized container.
    act: when _install_config is called.
    assert: jenkins configuration file is generated.
    """
    jenkins._install_configs(harness_container.container, jenkins.DEFAULT_JENKINS_CONFIG)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    jnlp_match = re.search(r"<slaveAgentPort>(\d+)</slaveAgentPort>", config_xml)
    assert jnlp_match, "Configuration for jnlp port not found."
    assert jnlp_match.group(1) == "50000", "jnlp not set as default port."


def test_install_config_raises_exception():
    """
    arrange: set up a container raising an exception.
    act: when _install_config is called.
    assert: a JenkinsBootstrapError is raised.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins._install_configs(mock_container, jenkins.DEFAULT_JENKINS_CONFIG)


def test_install_auth_proxy_config(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked uninitialized container.
    act: when install_auth_proxy_config is called.
    assert: jenkins configuration file is generated.
    """
    jenkins.install_auth_proxy_config(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    assert "<useSecurity>false</useSecurity>" in config_xml


def test_install_auth_proxy_config_raises_exception():
    """
    arrange: set up a container raising an exception.
    act: when install_auth_proxy_config is called.
    assert: a JenkinsBootstrapError is raised.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.install_auth_proxy_config(mock_container)


def test_install_defalt_config(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked uninitialized container.
    act: when install_default_config is called.
    assert: jenkins configuration file is generated.
    """
    jenkins.install_default_config(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    assert "<useSecurity>true</useSecurity>" in config_xml


def test_install_default_config_raises_exception():
    """
    arrange: set up a container raising an exception.
    act: when install_default_config is called.
    assert: a JenkinsBootstrapError is raised.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.install_default_config(mock_container)


@pytest.mark.parametrize(
    "proxy_config,expected_args",
    [
        pytest.param(
            # mypy doesn't understand pydantic converts string to HttpUrl.
            state.ProxyConfig(
                http_proxy="http://testing.internal",  # type: ignore
                https_proxy=None,
                no_proxy=None,
            ),
            ("-Dhttp.proxyHost=testing.internal", "-Dhttp.proxyPort=80"),
            id="http_proxy only",
        ),
        pytest.param(
            state.ProxyConfig(
                http_proxy=None,
                https_proxy="https://testing.internal",  # type: ignore
                no_proxy=None,
            ),
            ("-Dhttps.proxyHost=testing.internal", "-Dhttps.proxyPort=443"),
            id="https_proxy only",
        ),
        pytest.param(
            state.ProxyConfig(
                http_proxy="http://testing.internal",  # type: ignore
                https_proxy="https://testing.internal",  # type: ignore
                no_proxy=None,
            ),
            (
                "-Dhttp.proxyHost=testing.internal",
                "-Dhttp.proxyPort=80",
                "-Dhttps.proxyHost=testing.internal",
                "-Dhttps.proxyPort=443",
            ),
            id="both proxies",
        ),
        pytest.param(
            state.ProxyConfig(
                http_proxy="http://testing.internal",  # type: ignore
                https_proxy="https://testing.internal",  # type: ignore
                no_proxy="localhost",
            ),
            (
                "-Dhttp.proxyHost=testing.internal",
                "-Dhttp.proxyPort=80",
                "-Dhttps.proxyHost=testing.internal",
                "-Dhttps.proxyPort=443",
                '-Dhttp.nonProxyHosts="localhost"',
            ),
            id="full config",
        ),
    ],
)
def test__get_java_proxy_args(
    proxy_config: state.ProxyConfig, expected_args: typing.Iterable[str]
):
    """
    arrange: given a proxy configuration.
    act: when _get_java_proxy_args is called.
    assert: proper arguments from proxy configuration is generated.
    """
    assert tuple(jenkins._get_java_proxy_args(proxy_config)) == expected_args


def test__install_plugins_fail():
    """
    arrange: given a mocked container with a mocked failing process.
    act: when _install_plugins is called.
    assert: JenkinsBootstrapError is raised.
    """
    mock_proc = MagicMock(spec=ExecProcess)
    mock_proc.wait_output = MagicMock(
        side_effect=ExecError(["mock", "command"], 1, "", "Failed to install plugins.")
    )
    mock_container = MagicMock(spec=ops.Container)
    mock_container.exec.return_value = mock_proc

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins._install_plugins(mock_container)


def test__install_plugins(
    harness_container: HarnessWithContainer, proxy_config: state.ProxyConfig
):
    """
    arrange: given a mocked container with jenkins-plugin-manager executable.
    act: when _install_plugins is called.
    assert: No exceptions are raised.
    """
    jenkins._install_plugins(harness_container.container, proxy_config)


def test__configure_proxy_fail(
    harness_container: HarnessWithContainer,
    proxy_config: state.ProxyConfig,
    mock_client: MagicMock,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a test proxy config and a monkeypatched jenkins client that raises an exception.
    act: when _configure_proxy is called.
    assert: JenkinsBootstrapError is raised.
    """
    mock_client.run_groovy_script = MagicMock(
        side_effect=jenkinsapi.custom_exceptions.JenkinsAPIException
    )
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        with pytest.raises(jenkins.JenkinsBootstrapError) as exc:
            jenkins.Jenkins(mock_env)._configure_proxy(harness_container.container, proxy_config)

        assert exc.value.args[0] == "Proxy configuration failed."


def test__configure_proxy_partial(
    harness_container: HarnessWithContainer,
    partial_proxy_config: state.ProxyConfig,
    mock_client: MagicMock,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a test partial proxy config and a mock jenkins client.
    act: when _configure_proxy is called.
    assert: mock client is called with correct proxy arguments.
    """
    mock_run_groovy_script = MagicMock()
    mock_client.run_groovy_script = mock_run_groovy_script
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env)._configure_proxy(
            harness_container.container, partial_proxy_config
        )

        assert partial_proxy_config.https_proxy, (
            "Https value for proxy config fixture cannot be None."
        )
        mock_run_groovy_script.assert_called_once_with(
            f"proxy = new ProxyConfiguration('{partial_proxy_config.https_proxy.host}', "
            f"{partial_proxy_config.https_proxy.port}, '', '')\n"
            "proxy.save()"
        )


def test__configure_proxy_http(
    harness_container: HarnessWithContainer,
    http_partial_proxy_config: state.ProxyConfig,
    mock_client: MagicMock,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a test partial http proxy config and a mock jenkins client.
    act: when _configure_proxy is called.
    assert: mock client is called with correct proxy arguments.
    """
    mock_run_groovy_script = MagicMock()
    mock_client.run_groovy_script = mock_run_groovy_script
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env)._configure_proxy(
            harness_container.container, http_partial_proxy_config
        )

        assert http_partial_proxy_config.http_proxy, (
            "Http value for proxy config fixture cannot be None."
        )
        mock_run_groovy_script.assert_called_once_with(
            f"proxy = new ProxyConfiguration('{http_partial_proxy_config.http_proxy.host}', "
            f"{http_partial_proxy_config.http_proxy.port}, '', '')\n"
            "proxy.save()"
        )


def test__configure_proxy(
    harness_container: HarnessWithContainer,
    proxy_config: state.ProxyConfig,
    mock_client: MagicMock,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a test proxy config and a mock jenkins client.
    act: when _configure_proxy is called.
    assert: mock client is called with correct proxy arguments.
    """
    mock_run_groovy_script = MagicMock()
    mock_client.run_groovy_script = mock_run_groovy_script
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env)._configure_proxy(harness_container.container, proxy_config)

        # Assert for type not being None.
        assert proxy_config.https_proxy, "https proxy should not be None."
        mock_run_groovy_script.assert_called_once_with(
            f"proxy = new ProxyConfiguration('{proxy_config.https_proxy.host}', "
            f"{proxy_config.https_proxy.port}, "
            f"'{proxy_config.https_proxy.user}', '{proxy_config.https_proxy.password}', "
            f"'{proxy_config.no_proxy}')\n"
            "proxy.save()"
        )


def test_bootstrap_fail(
    monkeypatch: pytest.MonkeyPatch,
    harness_container: HarnessWithContainer,
    jenkins_version: str,
    mock_env: jenkins.Environment,
):
    """
    arrange: given mocked container, patched version and invalid plugins to \
        install.
    act: when bootstrap is called.
    assert: JenkinsBootstrapError is raised.
    """
    monkeypatch.setattr(
        jenkins,
        "_install_plugins",
        MagicMock(side_effect=jenkins.JenkinsBootstrapError),
    )

    with (
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
        patch.object(jenkins.Jenkins, "_setup_user_token"),
    ):
        version_mock.return_value = jenkins_version

        with pytest.raises(jenkins.JenkinsBootstrapError):
            jenkins.Jenkins(mock_env).bootstrap(
                harness_container.container, jenkins.DEFAULT_JENKINS_CONFIG
            )


def test_bootstrap(
    harness_container: HarnessWithContainer,
    jenkins_version: str,
    mock_env: jenkins.Environment,
):
    """
    arrange: given mocked container, monkeypatched get_version function and invalid plugins.
    act: when bootstrap is called.
    assert: files to unlock wizard are installed and necessary configs and plugins are installed.
    """
    with (
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
        patch.object(jenkins.Jenkins, "_setup_user_token"),
    ):
        version_mock.return_value = jenkins_version

        jenkins.Jenkins(mock_env).bootstrap(
            harness_container.container, jenkins.DEFAULT_JENKINS_CONFIG
        )

        assert harness_container.container.pull(
            jenkins.LAST_EXEC_VERSION_PATH, encoding="utf-8"
        ).read()
        assert harness_container.container.pull(
            jenkins.WIZARD_VERSION_PATH, encoding="utf-8"
        ).read()
        config_xml = str(
            harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
        )
        assert "<useSecurity>true</useSecurity>" in config_xml


def test_get_client(admin_credentials: jenkins.Credentials, mock_env: jenkins.Environment):
    """
    arrange: .
    act: when get_client is called with credentials.
    assert: the Jenkins API client is returned.
    """
    expected_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)

    with patch("jenkinsapi.jenkins.Jenkins", return_value=expected_client):
        jenkins_instance = jenkins.Jenkins(mock_env)
        client = jenkins_instance._get_api_client(admin_credentials)

        assert client == expected_client
        # pylint doesn't understand that this is a patched implementation.
        jenkinsapi.jenkins.Jenkins.assert_called_with(  # pylint: disable=no-member
            baseurl=jenkins_instance.web_url,
            username=admin_credentials.username,
            password=admin_credentials.password_or_token,
            timeout=60,
        )


def test_list_agent_nodes_error(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mock client that raises an API exception.
    act: when list_agent_nodes is called.
    assert: JenkinsError is raised.
    """
    mock_client.get_nodes.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client
        with pytest.raises(jenkins.JenkinsError):
            jenkins.Jenkins(mock_env).list_agent_nodes(container)


def test_list_agent_nodes(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mock client returns mock nodes.
    act: when list_agent_nodes is called.
    assert: expected nodes are returned.
    """
    mock_client.get_nodes.return_value = {"node": (mock_node := MagicMock())}
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client
        assert list(jenkins.Jenkins(mock_env).list_agent_nodes(container)) == [mock_node]


def test_get_node_secret_api_error(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked Jenkins client that raises an error.
    act: when a groovy script is executed through the client.
    assert: a Jenkins API exception is raised.
    """
    mock_client.run_groovy_script.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client
        with pytest.raises(jenkins.JenkinsError):
            jenkins.Jenkins(mock_env).get_node_secret("jenkins-agent", container)


def test_get_node_secret(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked Jenkins client.
    act: when a groovy script getting a node secret is executed.
    assert: a secret for a given node is returned.
    """
    secret = secrets.token_hex()
    mock_client.run_groovy_script.return_value = secret
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        node_secret = jenkins.Jenkins(mock_env).get_node_secret("jenkins-agent", container)

        assert secret == node_secret, "Secret value mismatch."


def test_add_agent_node_fail(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked jenkins client that raises an API exception.
    act: when add_agent is called
    assert: the exception is re-raised.
    """
    mock_client.create_node_with_config.side_effect = (
        jenkinsapi.custom_exceptions.JenkinsAPIException
    )
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        with pytest.raises(jenkins.JenkinsError):
            jenkins.Jenkins(mock_env).add_agent_node(
                state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
                container,
            )


def test_add_agent_node_already_exists(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked jenkins client that raises an Already exists exception.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_client.create_node_with_config.side_effect = jenkinsapi.custom_exceptions.AlreadyExists
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env).add_agent_node(
            state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
            container,
        )


def test_add_agent_node(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_client.create_node_with_config.return_value = MagicMock(spec=jenkins.Node)
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env).add_agent_node(
            state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
            container,
        )


def test_add_agent_node_websocket(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_client.create_node_with_config.return_value = MagicMock(spec=jenkins.Node)
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env).add_agent_node(
            state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
            container,
        )


def test_remove_agent_node_fail(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_client.delete_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        with pytest.raises(jenkins.JenkinsError):
            jenkins.Jenkins(mock_env).remove_agent_node("jekins-agent-0", container)


def test_remove_agent_node(
    container: ops.Container, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_delete = MagicMock(spec=jenkinsapi.jenkins.Jenkins.delete_node)
    mock_client.delete_node = mock_delete
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        jenkins.Jenkins(mock_env).remove_agent_node("jekins-agent-0", container)

        mock_delete.assert_called_once()


@pytest.mark.parametrize(
    "response_status",
    [
        pytest.param(200, id="Jenkins healthy"),
        pytest.param(404, id="Not found response"),
    ],
)
def test__wait_jenkins_job_shutdown_false(
    response_status: int, mock_client: MagicMock, mock_env: jenkins.Environment
):
    """
    arrange: given a mocked Jenkins client that returns any other status code apart from 503.
    act: when _is_shutdown is called.
    assert: False is returned.
    """
    mock_requester = MagicMock(spec=jenkinsapi.jenkins.Requester)
    mock_response = MagicMock(requests.Response)
    mock_client.requester = mock_requester
    mock_requester.get_url.return_value = mock_response
    mock_response.status_code = response_status

    assert not jenkins.Jenkins(mock_env)._is_shutdown(mock_client)


def test__is_shutdown_connection_error(mock_client: MagicMock, mock_env: jenkins.Environment):
    """
    arrange: given a mocked Jenkins client that raises a ConnectionError.
    act: when _is_shutdown is called.
    assert: True is returned.
    """
    mock_requester = MagicMock(spec=jenkinsapi.jenkins.Requester)
    mock_client.requester = mock_requester
    mock_requester.get_url.side_effect = requests.ConnectionError

    assert jenkins.Jenkins(mock_env)._is_shutdown(mock_client)


def test__is_shutdown_service_unavailable(mock_client: MagicMock, mock_env: jenkins.Environment):
    """
    arrange: given a mocked Jenkins client that raises a service unavailable status.
    act: when _is_shutdown is called.
    assert: True is returned.
    """
    mock_requester = MagicMock(spec=jenkinsapi.jenkins.Requester)
    mock_response = MagicMock(requests.Response)
    mock_client.requester = mock_requester
    mock_requester.get_url.return_value = mock_response
    mock_response.status_code = 503

    assert jenkins.Jenkins(mock_env)._is_shutdown(mock_client)


def test__wait_jenkins_job_shutdown_timeout(mock_env: jenkins.Environment):
    """
    arrange: given a patched _is_shutdown request that raises a TimeoutError.
    act: when _wait_jenkins_job_shutdown is called.
    assert: TimeoutError is raised.
    """
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    with patch.object(jenkins.Jenkins, "_is_shutdown") as is_shutdown_mock:
        is_shutdown_mock.side_effect = TimeoutError

        with pytest.raises(TimeoutError):
            jenkins.Jenkins(mock_env)._wait_jenkins_job_shutdown(mock_client)


def test__wait_jenkins_job_shutdown(mock_env: jenkins.Environment):
    """
    arrange: given a patched _is_shutdown request that returns True.
    act: when _wait_jenkins_job_shutdown is called.
    assert: No exceptions are raised.
    """
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    with patch.object(jenkins.Jenkins, "_is_shutdown"):
        jenkins.Jenkins(mock_env)._wait_jenkins_job_shutdown(mock_client)


def test_safe_restart_failure(
    harness_container: HarnessWithContainer,
    mock_client: MagicMock,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a mocked Jenkins API client that raises JenkinsAPIException.
    act: when safe_restart is called.
    assert: JenkinsError is raised.
    """
    mock_client.safe_restart.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()
    with patch.object(jenkins.Jenkins, "_get_client") as get_client_mock:
        get_client_mock.return_value = mock_client

        with pytest.raises(jenkins.JenkinsError):
            jenkins.Jenkins(mock_env).safe_restart(harness_container.container)


def test_safe_restart(
    harness_container: HarnessWithContainer,
    mock_client: MagicMock,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a mocked Jenkins API client that does not raise an exception.
    act: when safe_restart is called.
    assert: No exception is raised.
    """
    with (
        patch.object(jenkins.Jenkins, "_wait_jenkins_job_shutdown"),
        patch.object(jenkins.Jenkins, "_get_client") as get_client_mock,
    ):
        get_client_mock.return_value = mock_client
        jenkins.Jenkins(mock_env).safe_restart(harness_container.container)

        mock_client.safe_restart.assert_called_once_with(wait_for_reboot=False)


@pytest.mark.parametrize(
    "plugin_str",
    [
        pytest.param("", id="empty plugin name"),
        pytest.param(";;", id="invalid character"),
        pytest.param("too many whitespaces", id="too many whitespaces"),
        pytest.param("no-plugin-version", id="no version"),
        pytest.param("invalid-plugin-version", id="invalid version"),
    ],
)
def test__get_plugin_name_fail(plugin_str: str):
    """
    arrange: given a plugin string that is invalid.
    act: when _get_plugin_name is called.
    assert: ValidationError is raised.
    """
    with pytest.raises(jenkins.ValidationError):
        jenkins._get_plugin_name(plugin_str)


@pytest.mark.parametrize(
    "plugin_str, expected_name",
    [
        pytest.param("test-plugin (0.1.2)", "test-plugin", id="standard plugin string"),
        pytest.param(
            "test-plugin (any version string is ok)",
            "test-plugin",
            id="non-standard plugin version",
        ),
    ],
)
def test__get_plugin_name(plugin_str: str, expected_name: str):
    """
    arrange: given a plugin string that is valid.
    act: when _get_plugin_name is called.
    assert: expected plugin name is returned.
    """
    plugin_name = jenkins._get_plugin_name(plugin_str)

    assert plugin_name == expected_name


@pytest.mark.parametrize(
    "dependency_strs, expected_lookup",
    [
        pytest.param(
            [
                # dependency plugin versions do not necessarily match installed version
                # hence the difference in dependency version to installed version string.
                "plugin-a (v0.0.1) => [plugin-b (v0.0.1), plugin-c (v0.0.1)]",
                "plugin-b (v0.0.2) => [plugin-d (v0.0.1)]",
                "plugin-c (v0.0.3) => []",
                "plugin-d (v0.0.4) => []",
            ],
            {
                "plugin-a": ("plugin-b", "plugin-c"),
                "plugin-b": ("plugin-d",),
                "plugin-c": (),
                "plugin-d": (),
            },
            id="valid plugins",
        ),
        pytest.param(
            [
                "plugin-a (v0.0.1) => [plugin-b (v0.0.1), plugin-c (v0.0.1)]",
                "plugin-b (v0.0.2) => [plugin-d (v0.0.1)]",
                "plugin-c (v0.0.3) => []",
                "plugin-d (v0.0.4) => []",
                "skip-invalid-groovy-script-output",
                "invalid-deps (v0.0.01) => [invalid-dep]",
            ],
            {
                "plugin-a": ("plugin-b", "plugin-c"),
                "plugin-b": ("plugin-d",),
                "plugin-c": (),
                "plugin-d": (),
            },
            id="invalid plugin lines skipped",
        ),
    ],
)
def test__build_dependencies_lookup(
    dependency_strs: typing.Iterable[str],
    expected_lookup: typing.Mapping[str, typing.Iterable[str]],
):
    """
    arrange: given an iterable string of plugin to dependencies.
    act: when _build_dependencies_lookup is called.
    assert: the expected lookup table is built.
    """
    lookup = jenkins._build_dependencies_lookup(dependency_strs)

    assert lookup == expected_lookup


@pytest.mark.parametrize(
    "top_level_plugins, plugins_lookup, expected_allowed_plugins",
    [
        pytest.param((), {}, (), id="all empty"),
        pytest.param(("plugin-a",), {}, ("plugin-a",), id="single top level, no lookup"),
        pytest.param(
            ("plugin-a",),
            {"plugin-b": ()},
            ("plugin-a",),
            id="single top level, different lookup",
        ),
        pytest.param(
            ("plugin-a",),
            {"plugin-a": ()},
            ("plugin-a",),
            id="single top level, lookup with no dependencies",
        ),
        pytest.param(
            ("plugin-a",),
            {"plugin-a": ("plugin-a-a",), "plugin-a-a": ()},
            ("plugin-a", "plugin-a-a"),
            id="single top level, lookup with one dependency",
        ),
        pytest.param(
            ("plugin-a",),
            {
                "plugin-a": ("plugin-a-a",),
                "plugin-a-a": ("plugin-a-a-a",),
                "plugin-a-a-a": (),
            },
            ("plugin-a", "plugin-a-a", "plugin-a-a-a"),
            id="single top level, lookup with one nested dependency",
        ),
        pytest.param(
            ("plugin-a",),
            {
                "plugin-a": ("plugin-a-a", "plugin-a-b"),
                "plugin-a-a": (),
                "plugin-a-b": (),
            },
            ("plugin-a", "plugin-a-a", "plugin-a-b"),
            id="single top level, lookup with multiple dependencies",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {"plugin-a": (), "plugin-b": ()},
            ("plugin-a", "plugin-b"),
            id="two top levels, no dependencies",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {"plugin-a": ("plugin-a-a",), "plugin-b": (), "plugin-a-a": ()},
            ("plugin-a", "plugin-a-a", "plugin-b"),
            id="two top levels, plugin-a dependency exists",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {"plugin-a": (), "plugin-b": ("plugin-b-a",), "plugin-b-a": ()},
            ("plugin-a", "plugin-b", "plugin-b-a"),
            id="two top levels, plugin-b dependency exists",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("plugin-a-a",),
                "plugin-a-a": (),
                "plugin-b": ("plugin-b-a",),
                "plugin-b-a": (),
            },
            ("plugin-a", "plugin-a-a", "plugin-b", "plugin-b-a"),
            id="two top levels, both have single dependency",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("shared",),
                "plugin-b": ("shared",),
                "shared": (),
            },
            ("plugin-a", "shared", "plugin-b"),
            id="two top levels, both share a dependency",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("plugin-a-a", "plugin-a-b"),
                "plugin-b": ("plugin-b-a", "plugin-b-b"),
                "plugin-a-a": (),
                "plugin-a-b": (),
                "plugin-b-a": (),
                "plugin-b-b": (),
            },
            (
                "plugin-a",
                "plugin-a-a",
                "plugin-a-b",
                "plugin-b",
                "plugin-b-a",
                "plugin-b-b",
            ),
            id="two top levels, both have multiple dependencies",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("plugin-a-a", "shared"),
                "plugin-b": ("plugin-b-a", "shared"),
                "plugin-a-a": (),
                "plugin-b-a": (),
                "shared": (),
            },
            ("plugin-a", "plugin-a-a", "shared", "plugin-b", "plugin-b-a"),
            id="two top levels, both have multiple dependencies, single shared",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("shared-a", "shared-b"),
                "plugin-b": ("shared-a", "shared-b"),
                "shared-a": (),
                "shared-b": (),
            },
            ("plugin-a", "shared-a", "shared-b", "plugin-b"),
            id="two top levels, both have multiple dependencies, both shared",
        ),
    ],
)
def test__get_allowed_plugins(
    top_level_plugins: typing.Iterable[str],
    plugins_lookup: typing.Mapping[str, typing.Iterable[str]],
    expected_allowed_plugins: tuple[str, ...],
):
    """
    arrange: given a list of top level plugins (not a dependency to another plugin).
    act: when _get_allowed_plugins is called.
    assert: the plugin and its dependencies are yielded.
    """
    allowed_plugins = jenkins._get_allowed_plugins(top_level_plugins, plugins_lookup)

    assert tuple(allowed_plugins) == expected_allowed_plugins


@pytest.mark.parametrize(
    "all_plugins, plugins_lookup, expected_top_level_plugins",
    [
        pytest.param(
            ("plugin-a", "dep-a-a", "dep-a-b", "plugin-b", "dep-b-a", "dep-b-b"),
            {
                "plugin-a": ("dep-a-a", "dep-a-b"),
                "plugin-b": ("dep-b-a", "dep-b-b"),
                "dep-a-a": ("dep-a-b",),
                "dep-a-b": (),
                "dep-b-a": ("dep-b-b"),
                "dep-b-b": (),
            },
            {"plugin-a", "plugin-b"},
            id="plugins a, b",
        ),
    ],
)
def test__get_top_level_plugins(
    all_plugins: typing.Iterable[str],
    plugins_lookup: typing.Mapping[str, typing.Iterable[str]],
    expected_top_level_plugins: set[str],
):
    """
    arrange: given all the list of plugins installed plugins.
    act: when _get_top_level_plugins is called.
    assert: only the top level plugins (not a dependency to another plugin) are returned.
    """
    top_level_plugins = jenkins._filter_dependent_plugins(all_plugins, plugins_lookup)

    assert top_level_plugins == expected_top_level_plugins


def test__set_jenkins_system_message_error(mock_client: MagicMock):
    """
    arrange: given a monkeypatched yaml.safe_load function that returns an empty dictionary.
    act: when _set_jenkins_system_message is called.
    assert: a JenkinsError is raised.
    """
    mock_client.run_groovy_script.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins._set_jenkins_system_message("test", mock_client)


def test__set_jenkins_system_message(mock_client: MagicMock):
    """
    arrange: given a mock_client and a system message.
    act: when _set_jenkins_system_message is called.
    assert: the groovys script setting the Jenkins system message is called.
    """
    message = "hello world!"
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    jenkins._set_jenkins_system_message(message, mock_client)

    mock_groovy_script.assert_called()


def test__plugin_temporary_files_exist():
    """
    arrange: given a mock container that returns .tmp files.
    act: when _plugin_temporary_files_exist is called.
    assert: Truthy value is returned.
    """
    mock_container = MagicMock(spec=ops.Container)
    mock_container.list_files.return_value = [MagicMock(spec=ops.pebble.FileInfo)]

    assert jenkins._plugin_temporary_files_exist(container=mock_container)


def test_remove_unlisted_plugins_wait_plugins_install_timeout(
    monkeypatch: pytest.MonkeyPatch,
    container: ops.Container,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a mocked _wait_plugins_install that raises a timeout error.
    act: when remove_unlisted_plugins is called.
    assert: JenkinsPluginError is raised.
    """
    monkeypatch.setattr(jenkins, "_wait_plugins_install", MagicMock(side_effect=TimeoutError))

    with pytest.raises(jenkins.JenkinsPluginError):
        jenkins.Jenkins(mock_env).remove_unlisted_plugins(("plugin-a", "plugin-b"), container)


def test_remove_unlisted_plugins_delete_error(
    mock_client: MagicMock,
    container: ops.Container,
    plugin_groovy_script_result: str,
    mock_env: jenkins.Environment,
):
    """
    arrange: given a mocked client that raises an exception on delete_plugins call.
    act: when remove_unlisted_plugins is called.
    assert: JenkinsPluginError is raised.
    """
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    mock_groovy_script.return_value = plugin_groovy_script_result
    mock_client.delete_plugins.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()
    with (
        patch.object(jenkins.Jenkins, "safe_restart"),
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "_get_client") as get_client_mock,
    ):
        get_client_mock.return_value = mock_client

        with pytest.raises(jenkins.JenkinsPluginError):
            jenkins.Jenkins(mock_env).remove_unlisted_plugins(("plugin-a", "plugin-b"), container)


@pytest.mark.parametrize(
    "expected_exception",
    [
        pytest.param(jenkins.JenkinsError, id="JenkinsError"),
        pytest.param(TimeoutError, id="TimeoutError"),
    ],
)
# all arguments below are required
def test_remove_unlisted_plugins_restart_error(  # pylint: disable=too-many-arguments
    mock_client: MagicMock,
    container: ops.Container,
    plugin_groovy_script_result: str,
    mock_env: jenkins.Environment,
    expected_exception: Exception,
):
    """
    arrange: given a monkeypatched safe_restart call that raises an exception.
    act: when remove_unlisted_plugins is called.
    assert: exceptions are re-raised.
    """
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    mock_groovy_script.return_value = plugin_groovy_script_result
    with (
        patch.object(jenkins.Jenkins, "safe_restart") as safe_restart_mock,
        patch.object(jenkins.Jenkins, "_get_client") as get_client_mock,
    ):
        get_client_mock.return_value = mock_client
        safe_restart_mock.side_effect = expected_exception
        # mypy doesn't understand that Exception type can match TypeVar("E", bound=BaseException)
        with pytest.raises(expected_exception):  # type: ignore
            jenkins.Jenkins(mock_env).remove_unlisted_plugins(("plugin-a", "plugin-b"), container)


@pytest.mark.parametrize(
    "desired_plugins, groovy_script_output, expected_delete_plugins",
    [
        pytest.param(
            ("plugin-a", "plugin-b"),
            textwrap.dedent("""
                plugin-a (v0.0.1) => [dep-a-a (v0.0.1), dep-a-b (v0.0.1)]
                plugin-b (v0.0.2) => [dep-b-a (v0.0.2), dep-b-b (v0.0.2)]
                plugin-c (v0.0.5) => []
                dep-a-a (v0.0.3) => []
                dep-a-b (v0.0.3) => []
                dep-b-a (v0.0.4) => []
                dep-b-b (v0.0.4) => []
                Result: [Plugin:plugin-a, Plugin:plugin-b, Plugin:dep-a-a, \
                    Plugin:dep-a-b, Plugin:dep-b-a, Plugin:dep-b-b]
                """),
            {"plugin-c"},
            id="plugin-c not expected",
        ),
        pytest.param(
            ("plugin-a", "plugin-b", "plugin-c"),
            """
            plugin-a (v0.0.1) => [dep-a-a (v0.0.1), dep-a-b (v0.0.1)]
            plugin-b (v0.0.2) => [dep-b-a (v0.0.2), dep-b-b (v0.0.2)]
            plugin-c (v0.0.5) => []
            dep-a-a (v0.0.3) => []
            dep-a-b (v0.0.3) => []
            dep-b-a (v0.0.4) => []
            dep-b-b (v0.0.4) => []
            Result: [Plugin:plugin-a, Plugin:plugin-b, Plugin:dep-a-a, \
                Plugin:dep-a-b, Plugin:dep-b-a, Plugin:dep-b-b]
            """,
            set(),
            id="no undesired plugins",
        ),
        pytest.param(
            ("plugin-a", "plugin-b", "plugin-c"),
            """
            Result: []
            """,
            set(),
            id="no plugins installed",
        ),
        pytest.param(
            (),
            "",
            set(),
            id="plugins config not set (all allowed)",
        ),
    ],
)
# all arguments below are required
def test_remove_unlisted_plugins(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    mock_client: MagicMock,
    container: ops.Container,
    desired_plugins: tuple[str],
    groovy_script_output: str,
    expected_delete_plugins: set[str],
    mock_env: jenkins.Environment,
):
    """
    arrange: given a mocked client that returns a groovy script output of plugins and dependencies.
    act: when remove_unlisted_plugins is called.
    assert: delete function call is made with expected plugins.
    """
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    mock_groovy_script.return_value = groovy_script_output
    with (
        patch.object(jenkins.Jenkins, "safe_restart"),
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "_get_client") as get_client_mock,
    ):
        get_client_mock.return_value = mock_client
        jenkins.Jenkins(mock_env).remove_unlisted_plugins(desired_plugins, container)

        if expected_delete_plugins:
            mock_client.delete_plugins.assert_called_once_with(
                plugin_list=expected_delete_plugins, restart=False
            )
        else:
            mock_client.delete_plugins.assert_not_called()


def test_rotate_credentials_error(container: ops.Container, mock_env: jenkins.Environment):
    """
    arrange: given a monkeypatched _invalidate_sessions that raises JenkinsAPIException.
    act: when rotate_credentials is called.
    assert: JenkinsError is raised.
    """
    with patch.object(jenkins.Jenkins, "_invalidate_sessions") as invalidate_sessions_mock:
        invalidate_sessions_mock.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

        with pytest.raises(jenkins.JenkinsError):
            jenkins.Jenkins(mock_env).rotate_credentials(container)


def test_rotate_credentials(container: ops.Container, mock_env: jenkins.Environment):
    """
    arrange: given a monkeypatched _invalidate_sessions that returns no errors.
    act: when rotate_credentials is called.
    assert: password file is updated and newly generated password is returned.
    """
    with (
        patch.object(jenkins.Jenkins, "_invalidate_sessions"),
        patch.object(jenkins.Jenkins, "_set_new_password"),
    ):
        old_password = container.pull(jenkins.PASSWORD_FILE_PATH, encoding="utf-8").read()
        assert old_password != jenkins.Jenkins(mock_env).rotate_credentials(container), (
            "Password not newly generated"
        )
        assert old_password != container.pull(jenkins.PASSWORD_FILE_PATH, encoding="utf-8").read()
