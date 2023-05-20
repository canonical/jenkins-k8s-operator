# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm unit tests."""

import typing
from pathlib import Path
from secrets import token_hex
from unittest.mock import MagicMock

import pytest
import requests
import yaml
from ops.model import Container
from ops.pebble import ExecError, ExecProcess
from ops.testing import Harness

from charm import JenkinsK8SOperatorCharm
from jenkins import PASSWORD_FILE_PATH, PLUGINS_PATH, REQUIRED_PLUGINS, Credentials

from .types_ import HarnessWithContainer

ROCKCRAFT_YAML = yaml.safe_load(Path("jenkins_rock/rockcraft.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="function", name="harness")
def harness_fixture():
    """Enable ops test framework harness."""
    harness = Harness(JenkinsK8SOperatorCharm)
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
def admin_credentials_fixture() -> Credentials:
    """Admin credentials for Jenkins."""
    return Credentials(username="admin", password=token_hex(16))


def inject_register_command_handler(monkeypatch: pytest.MonkeyPatch, harness: Harness):
    """A helper function for injecting an implementation of the register_command_handler method."""
    handler_table: dict[str, typing.Callable[[list[str]], tuple[int, str, str]]] = {}

    class ExecProcessStub:
        """A mock object that simulates the execution of a process in the container."""

        def __init__(self, command: list[str], exit_code: int, stdout: str, stderr: str):
            """Initialize the ExecProcessStub object."""
            self._command = command
            self._exit_code = exit_code
            self._stdout = stdout
            self._stderr = stderr

        def wait_output(self):
            """Simulate the wait_output method of the container object."""
            if self._exit_code == 0:
                return self._stdout, self._stderr
            raise ExecError(
                command=self._command,
                exit_code=self._exit_code,
                stdout=self._stdout,
                stderr=self._stderr,
            )

    def exec_stub(command: list[str], **_kwargs: typing.Any):
        """A mock implementation of the `exec` method of the container object."""
        executable = command[0]
        handler = handler_table[executable]
        exit_code, stdout, stderr = handler(command)
        return ExecProcessStub(command=command, exit_code=exit_code, stdout=stdout, stderr=stderr)

    def register_command_handler(
        container: Container | str,
        executable: str,
        handler=typing.Callable[[list[str]], typing.Tuple[int, str, str]],
    ):
        """Registers a handler for a specific executable command."""
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
    harness: Harness, admin_credentials: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Container:
    """Harness Jenkins workload container that acts as a Jenkins container."""
    harness.set_can_connect("jenkins", True)
    container: Container = harness.model.unit.get_container("jenkins")
    container.push(
        PASSWORD_FILE_PATH, admin_credentials.password, encoding="utf-8", make_dirs=True
    )

    def cmd_handler(argv: list[str]) -> ExecProcess:
        """Handle the python command execution inside the Flask container."""
        mocked_exec_process = MagicMock(spec=ExecProcess)
        required_plugins = " ".join(REQUIRED_PLUGINS)
        match argv:
            case _ if [
                "java",
                "-jar",
                "jenkins-plugin-manager-2.12.11.jar",
                "-w",
                "jenkins.war",
                "-d",
                str(PLUGINS_PATH),
                "-p",
                required_plugins,
            ] == argv:
                return (0, "", "Done")
            case _:
                raise RuntimeError(f"unknown command: {argv}")

    inject_register_command_handler(monkeypatch, harness)
    harness.register_command_handler(  # type: ignore # pylint: disable=no-member
        container=container, executable="java", handler=cmd_handler
    )

    return container


@pytest.fixture(scope="function", name="harness_container")
def harness_container_fixture(harness: Harness, container: Container) -> HarnessWithContainer:
    """Named tuple containing Harness with container."""
    return HarnessWithContainer(harness=harness, container=container)
