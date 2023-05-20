# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm unit tests."""

from pathlib import Path
from secrets import token_hex
from typing import Any

import pytest
import requests
import yaml
from ops.model import Container
from ops.testing import Harness

from charm import JenkinsK8SOperatorCharm
from jenkins import PASSWORD_FILE_PATH, Credentials

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

    def mocked_get(_: str, status_code: int = 200, **_kwargs: Any):
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


@pytest.fixture(scope="function", name="container")
def container_fixture(harness: Harness, admin_credentials: Credentials) -> Container:
    """Harness Jenkins workload container that acts as a Jenkins container."""
    harness.set_can_connect("jenkins", True)
    container: Container = harness.model.unit.get_container("jenkins")
    container.push(
        PASSWORD_FILE_PATH, admin_credentials.password, encoding="utf-8", make_dirs=True
    )

    return container


@pytest.fixture(scope="function", name="harness_container")
def harness_container_fixture(harness: Harness, container: Container) -> HarnessWithContainer:
    """Named tuple containing Harness with container."""
    return HarnessWithContainer(harness=harness, container=container)
