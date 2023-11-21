# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm unit tests."""

import textwrap
import typing
import unittest.mock
from pathlib import Path
from secrets import token_hex

import jenkinsapi.jenkins
import pytest
import requests
import yaml
from ops.charm import CharmBase
from ops.model import Container
from ops.pebble import ExecError
from ops.testing import Harness

import jenkins
import state
from charm import JenkinsK8sOperatorCharm

from .helpers import combine_root_paths
from .types_ import HarnessWithContainer

ROCKCRAFT_YAML = yaml.safe_load(Path("jenkins_rock/rockcraft.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="function", name="harness")
def harness_fixture():
    """Enable ops test framework harness."""
    harness = Harness(JenkinsK8sOperatorCharm)
    yield harness
    harness.cleanup()


@pytest.fixture(scope="function", name="jenkins_version")
def jenkins_version_fixture():
    """Jenkins version fixture."""
    return str(ROCKCRAFT_YAML["parts"]["jenkins"]["build-environment"][0])


@pytest.fixture(scope="function", name="mocked_get_request")
def mocked_get_request_fixture(jenkins_version: str):
    """Mock get request with given status code."""

    def mocked_get(_: str, status_code: int = 200, **_kwargs: typing.Any):
        """Mock get request with predefined status code.

        Args:
            status_code: Status code of the returned response.

        Returns:
            Mocked response.
        """
        response = requests.Response()
        response.status_code = status_code
        response.headers["X-Jenkins"] = jenkins_version
        return response

    return mocked_get


@pytest.fixture(scope="function", name="admin_credentials")
def admin_credentials_fixture() -> jenkins.Credentials:
    """Admin credentials for Jenkins."""
    return jenkins.Credentials(username="admin", password_or_token=token_hex(16))


@pytest.fixture(scope="function", name="mock_client")
def mock_client_fixture(monkeypatch: pytest.MonkeyPatch) -> unittest.mock.MagicMock:
    """Mock Jenkins API client."""
    mock_client = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    monkeypatch.setattr(jenkins, "_get_client", lambda *_args, **_kwargs: mock_client)
    return mock_client


def inject_register_command_handler(monkeypatch: pytest.MonkeyPatch, harness: Harness):
    """A helper function for injecting an implementation of the register_command_handler method.

    Args:
        monkeypatch: The pytest monkeypatch object.
        harness: The testing harness.
    """
    handler_table: dict[str, typing.Callable[[list[str]], tuple[int, str, str]]] = {}

    # This is a stub implementation only.
    class ExecProcessStub:  # pylint: disable=too-few-public-methods
        """A mock object that simulates the execution of a process in the container."""

        def __init__(self, command: list[str], exit_code: int, stdout: str, stderr: str):
            """Initialize the ExecProcessStub object.

            Args:
                command: The command that was executed.
                exit_code: Exit code of the executed process.
                stdout: Standard output of the executed process.
                stderr: Standard error otuput of the executed process.
            """
            self._command = command
            self._exit_code = exit_code
            self._stdout = stdout
            self._stderr = stderr

        def wait_output(self):
            """Simulate the wait_output method of the container object.

            Returns:
                The tuple consisting of standard output and standard input.

            Raises:
                ExecError: if the exit code is none 0.
            """
            if self._exit_code == 0:
                return self._stdout, self._stderr
            raise ExecError(
                command=self._command,
                exit_code=self._exit_code,
                stdout=self._stdout,
                stderr=self._stderr,
            )

    def exec_stub(command: list[str], **_kwargs: typing.Any):
        """A mock implementation of the `exec` method of the container object.

        Args:
            command: The command to execute.

        Returns:
            The ExecProcessStub that mimics the ops.model.pebble.ExecProcess object.
        """
        executable = command[0]
        handler = handler_table[executable]
        exit_code, stdout, stderr = handler(command)
        return ExecProcessStub(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)

    def register_command_handler(
        container: Container | str,
        executable: str,
        handler=typing.Callable[[list[str]], typing.Tuple[int, str, str]],
    ):
        """Registers a handler for a specific executable command.

        Args:
            container: The container to register the handler to.
            executable: An executable to handle command.
            handler: The callback handler to register to a particular executable.
        """
        container = (
            harness.model.unit.get_container(container)
            if isinstance(container, str)
            else container
        )
        handler_table[executable] = handler
        monkeypatch.setattr(container, "exec", exec_stub)

    monkeypatch.setattr(
        harness, "register_command_handler", register_command_handler, raising=False
    )


@pytest.fixture(scope="function", name="container")
def container_fixture(
    harness: Harness,
    admin_credentials: jenkins.Credentials,
    monkeypatch: pytest.MonkeyPatch,
    proxy_config: state.ProxyConfig,
) -> Container:
    """Harness Jenkins workload container that acts as a Jenkins container."""
    jenkins_root = harness.get_filesystem_root("jenkins")
    password_file_path = combine_root_paths(jenkins_root, jenkins.PASSWORD_FILE_PATH)
    password_file_path.parent.mkdir(parents=True, exist_ok=True)
    password_file_path.write_text(admin_credentials.password_or_token, encoding="utf-8")
    api_token_file_path = combine_root_paths(jenkins_root, jenkins.API_TOKEN_PATH)
    api_token_file_path.write_text(admin_credentials.password_or_token, encoding="utf-8")

    def cmd_handler(argv: list[str]) -> tuple[int, str, str]:
        """Handle the python command execution inside the Flask container.

        Args:
            argv: The command to execute.

        Returns:
            The result of command execution.

        Raises:
            RuntimeError: if the handler for a command has not yet been registered.
        """
        required_plugins = " ".join(set(jenkins.REQUIRED_PLUGINS))
        # type cast since the fixture contains no_proxy values
        no_proxy_hosts = "|".join(typing.cast(str, proxy_config.no_proxy).split(","))
        # assert for types that cannot be None.
        assert proxy_config.http_proxy, "Http proxy fixture should not be None."
        assert proxy_config.https_proxy, "Https proxy fixture should not be None."
        match argv:
            # Ignore R0801: Similar lines in 2 files because this is a required stub
            # implementation of executed command.
            # pylint: disable=R0801
            case _ if [
                "java",
                "-jar",
                "jenkins-plugin-manager-2.12.13.jar",
                "-w",
                "jenkins.war",
                "-d",
                str(jenkins.PLUGINS_PATH),
                "-p",
                required_plugins,
            ] == argv:
                return (0, "", "Done")
            case _ if [
                "java",
                f"-Dhttp.proxyHost={proxy_config.http_proxy.host}",
                f"-Dhttp.proxyPort={proxy_config.http_proxy.port}",
                f"-Dhttp.proxyUser={proxy_config.http_proxy.user}",
                f"-Dhttp.proxyPassword={proxy_config.http_proxy.password}",
                f"-Dhttps.proxyHost={proxy_config.https_proxy.host}",
                f"-Dhttps.proxyPort={proxy_config.https_proxy.port}",
                f"-Dhttps.proxyUser={proxy_config.https_proxy.user}",
                f"-Dhttps.proxyPassword={proxy_config.https_proxy.password}",
                f'-Dhttp.nonProxyHosts="{no_proxy_hosts}"',
                "-jar",
                "jenkins-plugin-manager-2.12.13.jar",
                "-w",
                "jenkins.war",
                "-d",
                str(jenkins.PLUGINS_PATH),
                "-p",
                required_plugins,
            ] == argv:
                return (0, "", "Done")
            # pylint: enable=R0801
            case _:
                raise RuntimeError(f"unknown command: {argv}")
        # A non-reacheable return statement to satisfy mypy's Missing return statement
        return (0, "", "")

    inject_register_command_handler(monkeypatch, harness)
    container = harness.model.unit.get_container("jenkins")
    harness.set_can_connect(container, True)
    harness.register_command_handler(  # type: ignore # pylint: disable=no-member
        container=container, executable="java", handler=cmd_handler
    )

    return container


@pytest.fixture(scope="function", name="harness_container")
def harness_container_fixture(harness: Harness, container: Container) -> HarnessWithContainer:
    """Named tuple containing Harness with container."""
    return HarnessWithContainer(harness=harness, container=container)


@pytest.fixture(scope="function", name="raise_exception_mock")
def raise_exception_mock_fixture():
    """The mock function for patching."""

    def raise_exception_mock(exception: Exception):
        """Raise exception function for monkeypatching.

        Args:
            exception: The exception to raise.

        Returns:
            A magic mock that raises an exception when called.
        """
        mock = unittest.mock.MagicMock()
        mock.side_effect = exception
        return mock

    return raise_exception_mock


@pytest.fixture(scope="function", name="get_relation_data")
def get_relation_data_fixture():
    """The agent relation data required to register agent."""

    def get_relation_data(relation: str):
        """Return a valid relation data matching the relation interface.

        Args:
            relation: The relation name.

        Returns:
            A valid test relation data.
        """
        if relation == state.DEPRECATED_AGENT_RELATION:
            return {
                "executors": "2",
                "labels": "x84_64",
                "slavehost": "jenkins-agent-0",
            }
        return {
            "executors": "2",
            "labels": "x84_64",
            "name": "jenkins-agent-0",
        }

    return get_relation_data


@pytest.fixture(scope="function", name="current_version")
def current_version_fixture():
    """The current Jenkins version."""
    return "2.401.1"


@pytest.fixture(scope="function", name="patched_version")
def patched_version_fixture():
    """The patched Jenkins version."""
    return "2.401.2"


@pytest.fixture(scope="function", name="minor_updated_version")
def minor_update_version_fixture():
    """The Jenkins version with incremented minor version."""
    return "2.503.1"


@pytest.fixture(scope="function", name="rss_feed")
def rss_feed_fixture(current_version: str, patched_version: str, minor_updated_version: str):
    """The Jenkins stable release RSS feed."""
    return f"""<rss version='2.0' xmlns:atom='http://www.w3.org/2005/Atom'
        xmlns:content='https://purl.org/rss/1.0/modules/content/'>
        <channel>
            <title>
                Jenkins LTS Changelog
            </title>
            <link>
                https://jenkins.io/changelog-stable
            </link>
            <atom:link href='https://www.jenkins.io/changelog-stable/rss.xml' rel='self'
                type='application/rss+xml'></atom:link>
            <description>
                Changelog for Jenkins LTS releases
            </description>
            <lastBuildDate>
                Tue, 6 Jun 2023 00:00:00 +0000
            </lastBuildDate>
            <item>
                <title>Jenkins {minor_updated_version}</title>
                <link>
                https://jenkins.io/changelog-stable//#v{minor_updated_version}
                </link>
                <description>
                    current description
                </description>
                <guid isPermaLink='false'>
                    jenkins-{minor_updated_version}
                </guid>
                <pubDate>
                    Wed, 31 May 2023 00:00:00 +0000
                </pubDate>
            </item>
            <item>
                <title>Jenkins {patched_version}</title>
                <link>
                https://jenkins.io/changelog-stable//#v{patched_version}
                </link>
                <description>
                    patch description
                </description>
                <guid isPermaLink='false'>
                    jenkins-{patched_version}
                </guid>
                <pubDate>
                    Wed, 31 May 2023 00:00:00 +0000
                </pubDate>
            </item>
            <item>
                <title>Jenkins {current_version}</title>
                <link>
                https://jenkins.io/changelog-stable//#v{current_version}
                </link>
                <description>
                    current description
                </description>
                <guid isPermaLink='false'>
                    jenkins-{current_version}
                </guid>
                <pubDate>
                    Wed, 31 May 2023 00:00:00 +0000
                </pubDate>
            </item>
        </channel>
    </rss>
    """.encode(
        encoding="utf-8"
    )


@pytest.fixture(scope="function", name="partial_proxy_config")
def partial_proxy_config_fixture():
    """Proxy configuration with only hostname and port."""
    # Mypy doesn't understand str is supposed to be converted to HttpUrl by Pydantic.
    return state.ProxyConfig(
        http_proxy="http://httptest.internal:3127",  # type: ignore
        https_proxy="http://httpstest.internal:3127",  # type: ignore
        no_proxy=None,
    )


@pytest.fixture(scope="function", name="http_partial_proxy_config")
def http_partial_proxy_config_fixture():
    """Proxy configuration with only http proxy hostname and port."""
    # Mypy doesn't understand str is supposed to be converted to HttpUrl by Pydantic.
    return state.ProxyConfig(
        http_proxy="http://httptest.internal:3127",  # type: ignore
        no_proxy=None,
    )


@pytest.fixture(scope="function", name="proxy_config")
def proxy_config_fixture():
    """Proxy configuration with authentication and no_proxy values."""
    # Mypy doesn't understand str is supposed to be converted to HttpUrl by Pydantic.
    return state.ProxyConfig(
        http_proxy=f"http://testusername:{token_hex(16)}@httptest.internal:3127",  # type: ignore
        https_proxy=f"http://testusername:{token_hex(16)}@httpstest.internal:3127",  # type: ignore
        no_proxy="noproxy.host1,noproxy.host2",
    )


@pytest.fixture(scope="function", name="plugin_groovy_script_result")
def plugin_groovy_script_result_fixture():
    """A sample groovy script result from getting plugin and dependencies script."""
    return textwrap.dedent(
        """
        plugin-a (v0.0.1) => [dep-a-a (v0.0.1), dep-a-b (v0.0.1)]
        plugin-b (v0.0.2) => [dep-b-a (v0.0.2), dep-b-b (v0.0.2)]
        plugin-c (v0.0.5) => []
        dep-a-a (v0.0.3) => []
        dep-a-b (v0.0.3) => []
        dep-b-a (v0.0.4) => []
        dep-b-b (v0.0.4) => []
        """
    )


@pytest.fixture(scope="module", name="mock_charm")
def mock_charm_fixture():
    """A valid mock charm."""
    mock_charm = unittest.mock.MagicMock(spec=CharmBase)
    mock_charm.app.planned_units.return_value = 1
    return mock_charm
