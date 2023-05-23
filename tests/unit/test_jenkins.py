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

import jenkins
import state

from .helpers import ConnectionExceptionPatch
from .types_ import HarnessWithContainer


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

        Attrs:
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


@pytest.mark.parametrize(
    "admin_configured",
    [
        pytest.param(
            False,
            id="Admin not configured",
        ),
        pytest.param(
            True,
            id="Admin configured",
        ),
    ],
)
def test_calculate_env(admin_configured: bool):
    """
    arrange: given admin_configured boolean state variable.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    env = jenkins.calculate_env(admin_configured=admin_configured)

    assert env == {
        "JENKINS_HOME": str(jenkins.HOME_PATH),
        "ADMIN_CONFIGURED": "True" if admin_configured else "False",
    }


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
    jnlp_port = "1234"
    num_executors = 2
    jenkins._install_config(harness_container.container, jnlp_port, num_executors)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    executor_match = re.search(r"<numExecutors>(\d+)</numExecutors>", config_xml)
    assert executor_match, "Configuration for num executors not found."
    assert executor_match.group(1) == str(num_executors), "Number of executors mismatched."
    jnlp_match = re.search(r"<slaveAgentPort>(\d+)</slaveAgentPort>", config_xml)
    assert jnlp_match, "Configuration for jnlp port not found."
    assert jnlp_match.group(1) == jnlp_port


def test__install_plugins_fail(
    harness_container: HarnessWithContainer, invalid_plugins: typing.Iterable[str]
):
    """
    arrange: given a mocked container with jenkins-plugin-manager executable and invalid plugins.
    act: when _install_plugins is called.
    assert: JenkinsPluginError is raised.
    """
    with pytest.raises(jenkins.JenkinsPluginError):
        jenkins._install_plugins(harness_container.container, invalid_plugins)


def test__install_plugins(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked container with jenkins-plugin-manager executable.
    act: when _install_plugins is called.
    assert: No exceptions are raised.
    """
    jenkins._install_plugins(harness_container.container, ())


def test_bootstrap_fail(
    harness_container: HarnessWithContainer,
    invalid_plugins: typing.Iterable[str],
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """
    arrange: given mocked container, monkeypatched get_version function and invalid plugins to \
        install.
    act: when bootstrap is called.
    assert: JenkinsPluginError is raised.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: jenkins_version)

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.bootstrap(
            connectable_container=harness_container.container,
            jnlp_port="1234",
            num_master_executors=2,
            plugins=invalid_plugins,
        )


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

    jenkins.bootstrap(
        connectable_container=harness_container.container,
        jnlp_port="3000",
        num_master_executors=3,
        plugins=(),
    )

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
        client = jenkins.get_client(admin_credentials)

        assert client == expected_client
        # pylint doesn't understand that this is a patched implementation.
        jenkinsapi.jenkins.Jenkins.assert_called_with(  # pylint: disable=no-member
            baseurl=jenkins.WEB_URL,
            username=admin_credentials.username,
            password=admin_credentials.password,
            timeout=60,
        )


def test_get_node_secret_api_error():
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
        jenkins.get_node_secret(mock_jenkins_client, "jenkins-agent")


def test_get_node_secret():
    """
    arrange: given a mocked Jenkins client.
    act: when a groovy script getting a node secret is executed.
    assert: a secret for a given node is returned.
    """
    secret = secrets.token_hex()
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.run_groovy_script.return_value = secret

    node_secret = jenkins.get_node_secret(mock_jenkins_client, "jenkins-agent")

    assert secret == node_secret, "Secret value mismatch."


def test_add_agent_node_fail():
    """
    arrange: given a mocked jenkins client that raises an API exception.
    act: when add_agent is called
    assert: the exception is re-raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins.add_agent_node(
            mock_jenkins_client, state.AgentMeta("3", "x86_64", "localhost:8080")
        )


def test_add_agent_node_already_exists():
    """
    arrange: given a mocked jenkins client that raises an Already exists exception.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.side_effect = jenkinsapi.custom_exceptions.AlreadyExists

    jenkins.add_agent_node(mock_jenkins_client, state.AgentMeta("3", "x86_64", "localhost:8080"))


def test_add_agent_node():
    """
    arrange: given a mocked jenkins client.
    act: when add_agent is called.
    assert: no exception is raised.
    """
    mock_jenkins_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_jenkins_client.create_node.return_value = unittest.mock.MagicMock(
        spec=jenkinsapi.node.Node
    )

    jenkins.add_agent_node(mock_jenkins_client, state.AgentMeta("3", "x86_64", "localhost:8080"))
