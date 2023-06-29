# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins module tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access


import re
import secrets
import typing
import unittest.mock
from functools import partial

import jenkinsapi.jenkins
import pytest
import requests
from ops.model import Container
from ops.pebble import ExecError, ExecProcess

import jenkins

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
    mock_container = unittest.mock.MagicMock(spec=Container)
    mock_container.exec.return_value = mock_proc

    with pytest.raises(jenkins.JenkinsPluginError):
        jenkins._install_plugins(mock_container)


def test__install_plugins(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked container with jenkins-plugin-manager executable.
    act: when _install_plugins is called.
    assert: No exceptions are raised.
    """
    jenkins._install_plugins(harness_container.container)


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
        jenkins.bootstrap(connectable_container=harness_container.container)


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

    jenkins.bootstrap(connectable_container=harness_container.container)

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


def test_get_node_secret_api_error(admin_credentials: jenkins.Credentials):
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
        jenkins.get_node_secret("jenkins-agent", admin_credentials, mock_jenkins_client)


def test_get_node_secret(admin_credentials: jenkins.Credentials):
    """
    arrange: given a mocked Jenkins client.
    act: when a groovy script getting a node secret is executed.
    assert: a secret for a given node is returned.
    """
    secret = secrets.token_hex()
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.run_groovy_script.return_value = secret

    node_secret = jenkins.get_node_secret("jenkins-agent", admin_credentials, mock_jenkins_client)

    assert secret == node_secret, "Secret value mismatch."


def test_add_agent_node_fail(admin_credentials: jenkins.Credentials):
    """
    arrange: given a mocked jenkins client that raises an API exception.
    act: when add_agent is called
    assert: the exception is re-raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins.add_agent_node(
            jenkins.AgentMeta("3", "x86_64", "localhost:8080"),
            admin_credentials,
            mock_jenkins_client,
        )


def test_add_agent_node_already_exists(admin_credentials: jenkins.Credentials):
    """
    arrange: given a mocked jenkins client that raises an Already exists exception.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.side_effect = jenkinsapi.custom_exceptions.AlreadyExists

    jenkins.add_agent_node(
        jenkins.AgentMeta("3", "x86_64", "localhost:8080"), admin_credentials, mock_jenkins_client
    )


def test_add_agent_node(admin_credentials: jenkins.Credentials):
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
        jenkins.AgentMeta("3", "x86_64", "localhost:8080"), admin_credentials, mock_jenkins_client
    )


@pytest.mark.parametrize(
    "invalid_meta,expected_err_message",
    [
        pytest.param(
            jenkins.AgentMeta(executors="", labels="abc", slavehost="http://sample-host:8080"),
            "Fields ['executors'] cannot be empty.",
        ),
        pytest.param(
            jenkins.AgentMeta(executors="abc", labels="abc", slavehost="http://sample-host:8080"),
            "Number of executors abc cannot be converted to type int.",
        ),
    ],
)
def test_agent_meta__validate(invalid_meta: jenkins.AgentMeta, expected_err_message: str):
    """
    arrange: given an invalid agent metadata tuple.
    act: when validate is called.
    assert: ValidationError is raised with error messages.
    """
    with pytest.raises(jenkins.ValidationError) as exc:
        invalid_meta.validate()

    assert expected_err_message in str(exc.value)


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
    monkeypatch.setattr(requests, "get", lambda *_, **__: mock_rss_response)

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
    monkeypatch.setattr(requests, "get", lambda *_, **__: mock_rss_response)

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
    monkeypatch.setattr(requests, "get", lambda *_, **__: mock_rss_response)

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
    monkeypatch.setattr(requests, "get", lambda *_, **__: mock_rss_response)

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
    connectable_container = unittest.mock.MagicMock(spec=Container)

    with pytest.raises(jenkins.JenkinsNetworkError):
        jenkins.download_stable_war(connectable_container, current_version)


def test_download_stable_war(monkeypatch: pytest.MonkeyPatch, current_version: str):
    """
    arrange: given a monkeypatched get request that returns a mocked war response.
    act: when download_stable_war is called.
    assert: The jenkins.war is pushed to the mocked container.
    """
    mock_download_response = unittest.mock.MagicMock(spec=requests.Response)
    mock_download_response.content = b"mock war content"
    monkeypatch.setattr(requests, "get", lambda *_, **__: mock_download_response)
    connectable_container = unittest.mock.MagicMock(spec=Container)

    jenkins.download_stable_war(connectable_container, current_version)

    connectable_container.push.assert_called_once_with(
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


def test_safe_restart_failure(admin_credentials: jenkins.Credentials):
    """
    arrange: given a mocked Jenkins API client that raises JenkinsAPIException.
    act: when safe_restart is called.
    assert: JenkinsError is raised.
    """
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.safe_restart.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()

    with pytest.raises(jenkins.JenkinsError):
        jenkins.safe_restart(admin_credentials, client=mock_client)


def test_safe_restart(admin_credentials: jenkins.Credentials, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a mocked Jenkins API client that does not raise an exception.
    act: when safe_restart is called.
    assert: No exception is raised.
    """
    monkeypatch.setattr(jenkins, "_wait_jenkins_job_shutdown", lambda *_args, **_kwargs: None)
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)

    jenkins.safe_restart(admin_credentials, client=mock_client)

    mock_client.safe_restart.assert_called_once_with(wait_for_reboot=False)
