# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm unit tests."""

from io import StringIO
from pathlib import Path
from secrets import token_hex
from typing import Any, BinaryIO, Optional, TextIO, Union
from unittest.mock import MagicMock

import pytest
import requests
import yaml
from ops.model import Container
from ops.testing import Harness

from charm import JenkinsK8SOperatorCharm
from jenkins import JENKINS_PASSWORD_FILE_PATH
from types_ import Credentials

from .helpers import make_relative_to_path
from .types_ import ContainerWithPath

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
    return str(ROCKCRAFT_YAML["parts"]["jenkins"]["build-environment"]["JENKINS_VERSION"])


@pytest.fixture(scope="function", name="mocked_get_request")
def mocked_get_request_fixture(jenkins_version: str):
    """Mock get request with given status code."""

    def mocked_get(_: str, status_code: int = 200, **__: Any):
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


@pytest.fixture(scope="function", name="container_tmppath")
def container_tmppath_fixture(tmp_path: Path, admin_credentials: Credentials) -> Path:
    """Temporary directory structure for Jenkins container."""
    # if the path is an absolute path starting at root / directory, we must make it relative
    # path, otherwise the overloaded path append operator (/) doesn't work.
    initial_password_path = make_relative_to_path(tmp_path, JENKINS_PASSWORD_FILE_PATH)
    initial_password_path.parent.mkdir(exist_ok=True, parents=True)
    initial_password_path.write_text(admin_credentials.password, encoding="utf-8", newline="\n")
    return tmp_path


@pytest.fixture(scope="function", name="mocked_container")
def mocked_container_fixture(
    container_tmppath: Path,
) -> Container:
    """Mock container that acts as a Jenkins container with Jenkins installed."""

    def mocked_container_pull(path: Path, *, encoding: Optional[str] = "utf-8"):
        """Mocked container pull function with predefined files from mocked container_tmpppath.

        Args:
            path: Path to pull from.
            encoding: Text encoding to read as.

        Returns:
            A StringIO buffer containing the text read from the path.

        Raises:
            ValueError: if the path does not exist.
        """
        path = make_relative_to_path(container_tmppath, path)
        read_path = container_tmppath / path
        if not read_path.exists():
            raise ValueError(
                f"Undefined mock read path {path}. "
                "Please define it in the container_tmppath_fixture."
            )
        return StringIO((container_tmppath / path).read_text(encoding=encoding), newline="\n")

    def mocked_container_push(
        path: Path,
        source: Union[bytes, str, BinaryIO, TextIO],
        *,
        encoding: str = "utf-8",
        **_,
    ) -> None:
        """Mocked container push function.

        Args:
            path: Path to push the files to.
            source: Content to write to given path.
            encoding: Encoding of the given source content.
        """
        # if the path is an absolute path starting at root / directory, we must make it relative
        # path, otherwise the overloaded path append operator (/) doesn't work.
        path = make_relative_to_path(container_tmppath, path)
        write_path = container_tmppath / path
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(str(source), encoding=encoding)

    mocked_container = MagicMock(spec=Container)
    mocked_container.pull = mocked_container_pull
    mocked_container.push = mocked_container_push

    return mocked_container


@pytest.fixture(scope="function", name="container_with_path")
def container_with_path_fixture(mocked_container: Container, container_tmppath: Path):
    """Mocked Jenkins container with it's file system path.

    This is used to package the mocked_container and container_tmppath together to reduce number
    of arguments.

    Args:
        mocked_container: The mocked Jenkins container.
        container_tmppath: The mocked temporary filesystem of given container.
    """
    return ContainerWithPath(container=mocked_container, path=container_tmppath)
