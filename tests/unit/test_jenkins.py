# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins module tests."""

# Need access to protected functions for testing
# All tests belong to single jenkins module
# pylint:disable=protected-access, too-many-lines


import re
import secrets
import textwrap
import typing
import unittest.mock
from functools import partial

import jenkinsapi.jenkins
import ops
import pytest
import requests
import yaml
from ops.pebble import ExecError, ExecProcess

import jenkins
import state

from .helpers import ConnectionExceptionPatch
from .types_ import HarnessWithContainer, Versions


def test__is_ready_connection_exception(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given mocked requests that raises a connection exception.
    act: send a request to Jenkins login page.
    assert: return false, denoting Jenkins is not ready.
    """
    monkeypatch.setattr(requests, "get", ConnectionExceptionPatch)

    ready = jenkins._is_ready()

    assert not ready


@pytest.mark.parametrize(
    "status_code, expected_ready",
    [pytest.param(503, False, id="Service unavailable"), pytest.param(200, True, id="Success")],
)
def test__is_ready(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    status_code: int,
    expected_ready: bool,
):
    """
    arrange: given mocked requests that return a response with status_code.
    act: send a request to Jenkins login page.
    assert: return true if ready, false otherwise.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))

    ready = jenkins._is_ready()

    assert ready == expected_ready


def test_wait_ready_timeout(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
):
    """
    arrange: given mocked requests that returns a 503 response.
    act: wait for jenkins to become ready.
    assert: a TimeoutError is raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=503))

    with pytest.raises(TimeoutError):
        jenkins.wait_ready(1, 1)


def test_wait_ready_last_successful_check(monkeypatch: pytest.MonkeyPatch, jenkins_version: str):
    """
    arrange: given mocked requests that returns a 200 response the third time it's called.
    act: wait for jenkins to become ready for 1 second with 1 second interval.
    assert: No exceptions are raised.
    """

    class MockedResponse(requests.Response):
        """Mocked requests.Response that returns successful status code on 3rd instantiation.

        Attributes:
            num_called: Number of times the class has been instantiated.
        """

        num_called = 0

        def __init__(self, *_args, **_kwargs) -> None:
            """Initialize the response and count the number of instantiations."""
            super().__init__()
            MockedResponse.num_called += 1

            self.status_code = 200 if MockedResponse.num_called == 3 else 503
            self.headers["X-Jenkins"] = jenkins_version

    monkeypatch.setattr(requests, "get", MockedResponse)

    jenkins.wait_ready(1, 1)


def test_wait_ready(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
):
    """
    arrange: given mocked requests that returns a 200 response.
    act: wait for jenkins to become ready.
    assert: No exceptions are raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))

    jenkins.wait_ready(1, 1)


def test_get_admin_credentials(
    harness_container: HarnessWithContainer, admin_credentials: jenkins.Credentials
):
    """
    arrange: given a mocked container that returns the admin password file content.
    act: admin credentials are fetched over pebble.
    assert: correct admin credentials from the filesystem are returned.
    """
    assert jenkins.get_admin_credentials(harness_container.container) == admin_credentials


def test_calculate_env():
    """
    arrange: given bootstrapped boolean state variable.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    env = jenkins.calculate_env()

    assert env == {
        "JENKINS_HOME": str(jenkins.HOME_PATH),
        "CASC_JENKINS_CONFIG": str(jenkins.JCASC_CONFIG_FILE_PATH),
    }


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(requests.exceptions.Timeout, id="Timeout"),
        pytest.param(requests.exceptions.ConnectionError, id="Connection"),
    ],
)
def test_get_version_error(
    monkeypatch: pytest.MonkeyPatch, raise_exception: typing.Callable, exception: Exception
):
    """
    arrange: given a monkeypatched request that raises exceptions.
    act: when a request is sent to Jenkins server.
    assert: JenkinsError exception is raised.
    """
    monkeypatch.setattr(
        jenkins.requests, "get", lambda *_args, **_kwargs: raise_exception(exception)
    )

    with pytest.raises(jenkins.JenkinsError):
        jenkins.get_version()


def test_get_version(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    jenkins_version: str,
):
    """
    arrange: given a monkeypatched request that returns Jenkins version in headers.
    act: when a request is sent to Jenkins server.
    assert: The Jenkins server version is returned.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))

    assert jenkins.get_version() == jenkins_version


def test__unlock_wizard(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """
    arrange: given a mocked container and a monkeypatched Jenkins client.
    act: unlock_jenkins is called.
    assert: files necessary to unlock Jenkins and bypass wizard are written.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))

    jenkins._unlock_wizard(harness_container.container)

    assert (
        harness_container.container.pull(jenkins.LAST_EXEC_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )
    assert (
        harness_container.container.pull(jenkins.WIZARD_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )


def test__install_config(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked uninitialized container.
    act: when _install_config is called.
    assert: jenkins configuration file is generated.
    """
    jenkins._install_configs(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    jnlp_match = re.search(r"<slaveAgentPort>(\d+)</slaveAgentPort>", config_xml)
    assert jnlp_match, "Configuration for jnlp port not found."
    assert jnlp_match.group(1) == "50000", "jnlp not set as default port."


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


def test__install_plugins_fail(raise_exception):
    """
    arrange: given a mocked container with a mocked failing process.
    act: when _install_plugins is called.
    assert: JenkinsPluginError is raised.
    """
    mock_proc = unittest.mock.MagicMock(spec=ExecProcess)
    mock_proc.wait_output.side_effect = lambda: raise_exception(
        exception=ExecError(["mock", "command"], 1, "", "Failed to install plugins.")
    )
    mock_container = unittest.mock.MagicMock(spec=ops.Container)
    mock_container.exec.return_value = mock_proc

    with pytest.raises(jenkins.JenkinsPluginError):
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
    raise_exception: typing.Callable,
):
    """
    arrange: given a test proxy config and a monkeypatched jenkins client that raises an exception.
    act: when _configure_proxy is called.
    assert: JenkinsProxyError is raised.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.run_groovy_script = lambda *_args, **_kwargs: raise_exception(
        exception=jenkinsapi.custom_exceptions.JenkinsAPIException
    )

    with pytest.raises(jenkins.JenkinsProxyError) as exc:
        jenkins._configure_proxy(harness_container.container, proxy_config, mock_client)

    assert exc.value.args[0] == "Proxy configuration failed."


def test__configure_proxy_partial(
    harness_container: HarnessWithContainer,
    partial_proxy_config: state.ProxyConfig,
):
    """
    arrange: given a test partial proxy config and a mock jenkins client.
    act: when _configure_proxy is called.
    assert: mock client is called with correct proxy arguments.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_run_groovy_script = unittest.mock.MagicMock()
    mock_client.run_groovy_script = mock_run_groovy_script

    jenkins._configure_proxy(harness_container.container, partial_proxy_config, mock_client)

    assert partial_proxy_config.https_proxy, "Https value for proxy config fixture cannot be None."
    mock_run_groovy_script.assert_called_once_with(
        f"proxy = new ProxyConfiguration('{partial_proxy_config.https_proxy.host}', "
        f"{partial_proxy_config.https_proxy.port}, '', '')\n"
        "proxy.save()"
    )


def test__configure_proxy_http(
    harness_container: HarnessWithContainer,
    http_partial_proxy_config: state.ProxyConfig,
):
    """
    arrange: given a test partial http proxy config and a mock jenkins client.
    act: when _configure_proxy is called.
    assert: mock client is called with correct proxy arguments.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_run_groovy_script = unittest.mock.MagicMock()
    mock_client.run_groovy_script = mock_run_groovy_script

    jenkins._configure_proxy(harness_container.container, http_partial_proxy_config, mock_client)

    assert (
        http_partial_proxy_config.http_proxy
    ), "Http value for proxy config fixture cannot be None."
    mock_run_groovy_script.assert_called_once_with(
        f"proxy = new ProxyConfiguration('{http_partial_proxy_config.http_proxy.host}', "
        f"{http_partial_proxy_config.http_proxy.port}, '', '')\n"
        "proxy.save()"
    )


def test__configure_proxy(
    harness_container: HarnessWithContainer,
    proxy_config: state.ProxyConfig,
):
    """
    arrange: given a test proxy config and a mock jenkins client.
    act: when _configure_proxy is called.
    assert: mock client is called with correct proxy arguments.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_run_groovy_script = unittest.mock.MagicMock()
    mock_client.run_groovy_script = mock_run_groovy_script

    jenkins._configure_proxy(harness_container.container, proxy_config, mock_client)

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
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
    raise_exception: typing.Callable,
):
    """
    arrange: given mocked container, monkeypatched get_version function and invalid plugins to \
        install.
    act: when bootstrap is called.
    assert: JenkinsPluginError is raised.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: jenkins_version)
    monkeypatch.setattr(
        jenkins,
        "_install_plugins",
        lambda *_args, **kwargs: raise_exception(exception=jenkins.JenkinsPluginError),
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.bootstrap(container=harness_container.container)


def test_bootstrap(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """
    arrange: given mocked container, monkeypatched get_version function and invalid plugins.
    act: when bootstrap is called.
    assert: files to unlock wizard are installed and necessary configs and plugins are installed.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: jenkins_version)

    jenkins.bootstrap(container=harness_container.container)

    assert harness_container.container.pull(
        jenkins.LAST_EXEC_VERSION_PATH, encoding="utf-8"
    ).read()
    assert harness_container.container.pull(jenkins.WIZARD_VERSION_PATH, encoding="utf-8").read()
    assert harness_container.container.pull(
        jenkins.CONFIG_FILE_PATH, encoding="utf-8"
    ).read(), "Configuration not found"


def test_get_client(admin_credentials: jenkins.Credentials):
    """
    arrange: .
    act: when get_client is called with credentials.
    assert: the Jenkins API client is returned.
    """
    expected_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)

    with unittest.mock.patch("jenkinsapi.jenkins.Jenkins", return_value=expected_client):
        client = jenkins._get_client(admin_credentials)

        assert client == expected_client
        # pylint doesn't understand that this is a patched implementation.
        jenkinsapi.jenkins.Jenkins.assert_called_with(  # pylint: disable=no-member
            baseurl=jenkins.WEB_URL,
            username=admin_credentials.username,
            password=admin_credentials.password,
            timeout=60,
        )


def test_get_node_secret_api_error(container: ops.Container):
    """
    arrange: given a mocked Jenkins client that raises an error.
    act: when a groovy script is executed through the client.
    assert: a Jenkins API exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.run_groovy_script.side_effect = (
        jenkinsapi.custom_exceptions.JenkinsAPIException()
    )

    with pytest.raises(jenkins.JenkinsError):
        jenkins.get_node_secret("jenkins-agent", container, mock_jenkins_client)


def test_get_node_secret(container: ops.Container):
    """
    arrange: given a mocked Jenkins client.
    act: when a groovy script getting a node secret is executed.
    assert: a secret for a given node is returned.
    """
    secret = secrets.token_hex()
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.run_groovy_script.return_value = secret

    node_secret = jenkins.get_node_secret("jenkins-agent", container, mock_jenkins_client)

    assert secret == node_secret, "Secret value mismatch."


def test_add_agent_node_fail(container: ops.Container):
    """
    arrange: given a mocked jenkins client that raises an API exception.
    act: when add_agent is called
    assert: the exception is re-raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins.add_agent_node(
            state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
            container,
            mock_jenkins_client,
        )


def test_add_agent_node_already_exists(container: ops.Container):
    """
    arrange: given a mocked jenkins client that raises an Already exists exception.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.side_effect = jenkinsapi.custom_exceptions.AlreadyExists

    jenkins.add_agent_node(
        state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
        container,
        mock_jenkins_client,
    )


def test_add_agent_node(container: ops.Container):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.return_value = unittest.mock.MagicMock(
        spec=jenkinsapi.node.Node
    )

    jenkins.add_agent_node(
        state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0"),
        container,
        mock_jenkins_client,
    )


def test_remove_agent_node_fail(admin_credentials: jenkins.Credentials):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.delete_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins.remove_agent_node("jekins-agent-0", admin_credentials, mock_jenkins_client)


def test_remove_agent_node(admin_credentials: jenkins.Credentials):
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_delete = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins.delete_node)
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.delete_node = mock_delete

    jenkins.remove_agent_node("jekins-agent-0", admin_credentials, mock_jenkins_client)

    mock_delete.assert_called_once()


@pytest.mark.parametrize(
    "version,expected_major_minor",
    [
        pytest.param("2.289.4", "2.289", id="semantic version"),
        pytest.param("2.289", "2.289", id="semantic version w/o patch version"),
    ],
)
def test_get_major_minor_version(version: str, expected_major_minor: str):
    """
    arrange: given valid version strings.
    act: when _get_major_minor_version is called.
    assert: the major and minor version is extracted.
    """
    result = jenkins._get_major_minor_version(version)

    assert expected_major_minor == result


def test_fetch_versions_from_rss_failure(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a failing request to the Jenkins RSS feed.
    act: when _fetch_versions_from_rss is called.
    assert: a JenkinsNetworkError is raised.
    """
    monkeypatch.setattr(requests, "get", ConnectionExceptionPatch)

    with pytest.raises(jenkins.JenkinsNetworkError):
        jenkins._fetch_versions_from_rss()


def test_fetch_versions_from_rss_proxy(
    monkeypatch: pytest.MonkeyPatch, rss_feed: bytes, proxy_config: state.ProxyConfig
):
    """
    arrange: given a monkeypatched request to the Jenkins RSS feed.
    act: when _fetch_versions_from_rss is called with proxy config.
    assert: requests is called with proxies.
    """
    mock_rss_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_rss_response.content = rss_feed
    mocked_get = unittest.mock.MagicMock(spec=requests.get)
    mocked_get.return_value = mock_rss_response
    monkeypatch.setattr(requests, "get", mocked_get)

    jenkins._fetch_versions_from_rss(proxy_config)

    mocked_get.assert_called_once_with(
        jenkins.RSS_FEED_URL,
        timeout=30,
        proxies={"http": str(proxy_config.http_proxy), "https": str(proxy_config.https_proxy)},
    )


def test_fetch_versions_from_rss(
    monkeypatch: pytest.MonkeyPatch, rss_feed: bytes, versions: Versions
):
    """
    arrange: given a mocked requests that returns a successful rss feed response.
    act: when _fetch_versions_from_rss is called.
    assert: Jenkins versions are extracted from the RSS feed.
    """
    mock_rss_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_rss_response.content = rss_feed
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: mock_rss_response)

    expected = [versions.minor_update, versions.patched, versions.current]
    result = list(jenkins._fetch_versions_from_rss())

    assert result == expected


def test_get_latest_patch_version_failure(monkeypatch: pytest.MonkeyPatch, current_version: str):
    """
    arrange: given a monkey patched _fetch_versions_from_rss function that raises an exception.
    act: when get_latest_patch_version is called
    assert: JenkinsNetworkError is re-raised.
    """
    mock_fetch_version = unittest.mock.MagicMock(spec=jenkins._fetch_versions_from_rss)
    mock_fetch_version.side_effect = jenkins.JenkinsNetworkError()
    monkeypatch.setattr(jenkins, "_fetch_versions_from_rss", mock_fetch_version)

    with pytest.raises(jenkins.JenkinsNetworkError):
        jenkins._get_latest_patch_version(current_version)


def test_get_latest_patch_version_invalid_rss(
    monkeypatch: pytest.MonkeyPatch, current_version: str
):
    """
    arrange: given monkeypatched _fetch_versions_from_rss that returns an invalid feed.
    act: when get_latest_patch_version is called.
    assert: ValidationError is raised.
    """
    mock_rss_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_rss_response.content = b"invalid rss"
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: mock_rss_response)

    with pytest.raises(jenkins.ValidationError):
        jenkins._get_latest_patch_version(current_version)


def test_get_latest_patch_version_missing_version_rss(
    monkeypatch: pytest.MonkeyPatch, current_version: str, minor_updated_version: str
):
    """
    arrange: given monkeypatched _fetch_versions_from_rss that returns a feed without current ver.
    act: when get_latest_patch_version is called.
    assert: ValidationError is raised.
    """
    mock_rss_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_rss_response.content = f"""<rss>
            <channel>
                <item><title>{minor_updated_version}</title></item>
            </channel>
        </rss>""".encode(
        encoding="utf-8"
    )
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: mock_rss_response)

    with pytest.raises(jenkins.ValidationError):
        jenkins._get_latest_patch_version(current_version)


def test__get_latest_patch_version(
    monkeypatch: pytest.MonkeyPatch, rss_feed: bytes, current_version: str, patched_version: str
):
    """
    arrange: given a monkeypatched requests that returns a mock rss feed results.
    act: when get_latest_patch_version is called.
    assert: the latest patch version is returned.
    """
    mock_rss_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_rss_response.content = rss_feed
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: mock_rss_response)

    result = jenkins._get_latest_patch_version(current_version)

    assert result == patched_version


def test_get_updatable_version_get_version_failure(
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
):
    """
    arrange: given a monkeypatched get_version that returns an exception.
    act: when get_update_version is called.
    assert: JenkinsUpdateError is raised.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: raise_exception(jenkins.JenkinsError))

    with pytest.raises(jenkins.JenkinsUpdateError):
        jenkins.get_updatable_version()


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(jenkins.JenkinsNetworkError, id="JenkinsNetworkError"),
        pytest.param(jenkins.ValidationError, id="ValidationError"),
    ],
)
def test_get_updatable_version__get_latest_patch_version_failure(
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
    exception: Exception,
    versions: Versions,
):
    """
    arrange: given a monkeypatched _get_latest_patch_version that returns an exception.
    act: when get_update_version is called.
    assert: JenkinsUpdateError is raised.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda *_args, **_kwargs: versions.current)
    monkeypatch.setattr(
        jenkins, "_get_latest_patch_version", lambda *_args, **_kwargs: raise_exception(exception)
    )

    with pytest.raises(jenkins.JenkinsUpdateError):
        jenkins.get_updatable_version()


def test_get_updatable_version_up_to_date(monkeypatch: pytest.MonkeyPatch, versions: Versions):
    """
    arrange: given monkeypatched version fetching functions that returns latest versions.
    act: when get_update_version is called.
    assert: no update value should be returned.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda *_args, **_kwargs: versions.patched)
    monkeypatch.setattr(
        jenkins, "_get_latest_patch_version", lambda *_args, **_kwargs: versions.patched
    )

    assert not jenkins.get_updatable_version(), "Updates should not be available."


def test_get_updatable_version(monkeypatch: pytest.MonkeyPatch, versions: Versions):
    """
    arrange: given monkeypatched _get_latest_patch_version that returns latest patch version.
    act: when get_update_version is called.
    assert: patched version should be returned.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda *_args, **_kwargs: versions.current)
    monkeypatch.setattr(
        jenkins, "_get_latest_patch_version", lambda *_args, **_kwargs: versions.patched
    )

    assert (
        jenkins.get_updatable_version() == versions.patched
    ), "Latest patch version should be returned."


def test_download_stable_war_failure(monkeypatch: pytest.MonkeyPatch, current_version: str):
    """
    arrange: given a monkeypatched requests that raises a ConnectionError.
    act: when download_stable_war is called.
    assert: JenkinsNetworkError is raised.
    """
    monkeypatch.setattr(requests, "get", ConnectionExceptionPatch)
    container = unittest.mock.MagicMock(spec=ops.Container)

    with pytest.raises(jenkins.JenkinsNetworkError):
        jenkins.download_stable_war(container, current_version)


def test_download_stable_war(monkeypatch: pytest.MonkeyPatch, current_version: str):
    """
    arrange: given a monkeypatched get request that returns a mocked war response.
    act: when download_stable_war is called.
    assert: The jenkins.war is pushed to the mocked container.
    """
    mock_download_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_download_response.content = b"mock war content"
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: mock_download_response)
    container = unittest.mock.MagicMock(spec=ops.Container)

    jenkins.download_stable_war(container, current_version)

    container.push.assert_called_once_with(
        jenkins.EXECUTABLES_PATH / "jenkins.war",
        mock_download_response.content,
        encoding="utf-8",
        user=jenkins.USER,
        group=jenkins.GROUP,
    )


@pytest.mark.parametrize(
    "response_status",
    [
        pytest.param(200, id="Jenkins healthy"),
        pytest.param(404, id="Not found response"),
    ],
)
def test__wait_jenkins_job_shutdown_false(response_status: int):
    """
    arrange: given a mocked Jenkins client that returns any other status code apart from 503.
    act: when _is_shutdown is called.
    assert: False is returned.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_requester = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Requester)
    mock_response = unittest.mock.MagicMock(requests.Response)
    mock_client.requester = mock_requester
    mock_requester.get_url.return_value = mock_response
    mock_response.status_code = response_status

    assert not jenkins._is_shutdown(mock_client)


def test__is_shutdown_connection_error():
    """
    arrange: given a mocked Jenkins client that raises a ConnectionError.
    act: when _is_shutdown is called.
    assert: True is returned.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_requester = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Requester)
    mock_client.requester = mock_requester
    mock_requester.get_url.side_effect = requests.ConnectionError

    assert jenkins._is_shutdown(mock_client)


def test__is_shutdown_service_unavailable():
    """
    arrange: given a mocked Jenkins client that raises a service unavailable status.
    act: when _is_shutdown is called.
    assert: True is returned.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_requester = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Requester)
    mock_response = unittest.mock.MagicMock(requests.Response)
    mock_client.requester = mock_requester
    mock_requester.get_url.return_value = mock_response
    mock_response.status_code = 503

    assert jenkins._is_shutdown(mock_client)


def test__wait_jenkins_job_shutdown_timeout(monkeypatch: pytest.MonkeyPatch, raise_exception):
    """
    arrange: given a patched _is_shutdown request that raises a TimeoutError.
    act: when _wait_jenkins_job_shutdown is called.
    assert: TimeoutError is raised.
    """
    monkeypatch.setattr(
        jenkins, "_is_shutdown", lambda *_args, **kwargs: raise_exception(TimeoutError)
    )
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)

    with pytest.raises(TimeoutError):
        jenkins._wait_jenkins_job_shutdown(mock_client)


def test__wait_jenkins_job_shutdown(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a patched _is_shutdown request that returns True.
    act: when _wait_jenkins_job_shutdown is called.
    assert: No exceptions are raised.
    """
    monkeypatch.setattr(jenkins, "_is_shutdown", lambda *_args, **kwargs: True)
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)

    jenkins._wait_jenkins_job_shutdown(mock_client)


def test_safe_restart_failure(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked Jenkins API client that raises JenkinsAPIException.
    act: when safe_restart is called.
    assert: JenkinsError is raised.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.safe_restart.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()

    with pytest.raises(jenkins.JenkinsError):
        jenkins.safe_restart(harness_container.container, client=mock_client)


def test_safe_restart(harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a mocked Jenkins API client that does not raise an exception.
    act: when safe_restart is called.
    assert: No exception is raised.
    """
    monkeypatch.setattr(jenkins, "_wait_jenkins_job_shutdown", lambda *_args, **_kwargs: None)
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)

    jenkins.safe_restart(harness_container.container, client=mock_client)

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
            ("plugin-a",), {"plugin-b": ()}, ("plugin-a",), id="single top level, different lookup"
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
            {"plugin-a": ("plugin-a-a",), "plugin-a-a": ("plugin-a-a-a",), "plugin-a-a-a": ()},
            ("plugin-a", "plugin-a-a", "plugin-a-a-a"),
            id="single top level, lookup with one nested dependency",
        ),
        pytest.param(
            ("plugin-a",),
            {"plugin-a": ("plugin-a-a", "plugin-a-b"), "plugin-a-a": (), "plugin-a-b": ()},
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
            ("plugin-a", "plugin-a-a", "plugin-a-b", "plugin-b", "plugin-b-a", "plugin-b-b"),
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
            set(("plugin-a", "plugin-b")),
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

    assert set(top_level_plugins) == expected_top_level_plugins


def test__set_jenkins_system_message(container: ops.Container):
    """
    arrange: given a container with jenkins.yaml (JCasC config file) and a system message.
    act: when _set_jenkins_system_message is called.
    assert: the jenkins.yaml file pushed to the container has systemMessage property defined.
    """
    message = "hello world!"
    jenkins._set_jenkins_system_message(message, container)

    contents = str(container.pull(jenkins.JCASC_CONFIG_FILE_PATH, encoding="utf-8").read())
    config = yaml.safe_load(contents)
    assert config["jenkins"]["systemMessage"] == message


def test_remove_unlisted_plugins_delete_error(
    monkeypatch: pytest.MonkeyPatch,
    container: ops.Container,
    plugin_groovy_script_result: str,
):
    """
    arrange: given a mocked client that raises an exception on delete_plugins call.
    act: when remove_unlisted_plugins is called.
    assert: JenkinsPluginError is raised.
    """
    monkeypatch.setattr(jenkins, "safe_restart", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(jenkins, "wait_ready", lambda *_args, **_kwargs: None)
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.run_groovy_script = (
        mock_groovy_script := unittest.mock.MagicMock(
            spec=jenkinsapi.jenkins.Jenkins.run_groovy_script
        )
    )
    mock_groovy_script.return_value = plugin_groovy_script_result
    mock_client.delete_plugins.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()

    with pytest.raises(jenkins.JenkinsPluginError):
        jenkins.remove_unlisted_plugins(("plugin-a", "plugin-b"), container, mock_client)


@pytest.mark.parametrize(
    "expected_exception",
    [
        pytest.param(jenkins.JenkinsError, id="JenkinsError"),
        pytest.param(TimeoutError, id="TimeoutError"),
    ],
)
def test_remove_unlisted_plugins_restart_error(
    monkeypatch: pytest.MonkeyPatch,
    container: ops.Container,
    plugin_groovy_script_result: str,
    raise_exception: typing.Callable,
    expected_exception: Exception,
):
    """
    arrange: given a monkeypatched safe_restart call that raises an exception.
    act: when remove_unlisted_plugins is called.
    assert: exceptions are re-raised.
    """
    monkeypatch.setattr(
        jenkins, "safe_restart", lambda *_args, **_kwargs: raise_exception(expected_exception)
    )
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.run_groovy_script = (
        mock_groovy_script := unittest.mock.MagicMock(
            spec=jenkinsapi.jenkins.Jenkins.run_groovy_script
        )
    )
    mock_groovy_script.return_value = plugin_groovy_script_result

    # mypy doesn't understand that Exception type can match TypeVar("E", bound=BaseException)
    with pytest.raises(expected_exception):  # type: ignore
        jenkins.remove_unlisted_plugins(("plugin-a", "plugin-b"), container, mock_client)


@pytest.mark.parametrize(
    "desired_plugins, groovy_script_output, expected_delete_plugins",
    [
        pytest.param(
            ("plugin-a", "plugin-b"),
            textwrap.dedent(
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
                """
            ),
            set(("plugin-c",)),
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
            set(()),
            id="no plugins installed",
        ),
        pytest.param(
            (),
            "",
            set(()),
            id="plugins config not set (all allowed)",
        ),
    ],
)
def test_remove_unlisted_plugins(
    monkeypatch: pytest.MonkeyPatch,
    container: ops.Container,
    desired_plugins: tuple[str],
    groovy_script_output: str,
    expected_delete_plugins: set[str],
):
    """
    arrange: given a mocked client that returns a groovy script output of plugins and dependencies.
    act: when remove_unlisted_plugins is called.
    assert: delete function call is made with expected plugins.
    """
    monkeypatch.setattr(jenkins, "safe_restart", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(jenkins, "wait_ready", lambda *_args, **_kwargs: None)
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.run_groovy_script = (
        mock_groovy_script := unittest.mock.MagicMock(
            spec=jenkinsapi.jenkins.Jenkins.run_groovy_script
        )
    )
    mock_groovy_script.return_value = groovy_script_output

    jenkins.remove_unlisted_plugins(desired_plugins, container, mock_client)

    if expected_delete_plugins:
        mock_client.delete_plugins.assert_called_once_with(
            plugin_list=expected_delete_plugins, restart=False
        )
    else:
        mock_client.delete_plugins.assert_not_called()
