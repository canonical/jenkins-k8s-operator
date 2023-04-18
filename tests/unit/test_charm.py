# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# pylint:disable=protected-access

from functools import partial
from pathlib import Path
from typing import Any, Callable, cast
from unittest.mock import MagicMock

import pytest
import requests
from ops.charm import PebbleReadyEvent
from ops.model import ActiveStatus, BlockedStatus, Container, StatusBase
from ops.testing import Harness

import charm as charm_src
from charm import LAST_EXEC, UPDATE_VERSION, JenkinsK8SOperatorCharm
from types_ import Credentials

from .helpers import make_relative_to_path
from .jenkins_mock import MockedJenkinsClient


@pytest.mark.parametrize(
    "status_code, expected_ready",
    [pytest.param(503, False, id="Service unavailable"), pytest.param(200, True, id="Success")],
)
def test__is_jenkins_ready(
    monkeypatch: pytest.MonkeyPatch,
    harness: Harness,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    status_code: int,
    expected_ready: bool,
):
    """
    arrange: given mocked requests that return a response with status_code.
    act: send a request to Jenkins login page.
    assert: return true if ready, false otherwise.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)

    ready = charm._is_jenkins_ready()

    assert ready == expected_ready


def test__wait_jenkins_ready_timeout(
    monkeypatch: pytest.MonkeyPatch,
    harness: Harness,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
):
    """
    arrange: given mocked requests that returns a 503 response.
    act: wait for jenkins to become ready.
    assert: a TimeoutError is raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=503))
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)

    with pytest.raises(TimeoutError):
        charm._wait_jenkins_ready(1, 1)


def test__wait_jenkins_ready(
    monkeypatch: pytest.MonkeyPatch,
    harness: Harness,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
):
    """
    arrange: given mocked requests that returns a 200 response.
    act: wait for jenkins to become ready.
    assert: No exceptions are raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)

    charm._wait_jenkins_ready(1, 1)


def test__get_admin_credentials(
    harness: Harness, mocked_container: Container, admin_credentials: Credentials
):
    """
    arrange: given a mocked container that returns the admin password file content.
    act: admin credentials are fetched over pebble.
    assert: correct admin credentials from the filesystem are returned.
    """
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)

    assert charm._get_admin_credentials(mocked_container) == Credentials(
        username="admin", password=admin_credentials.password
    )


def test__unlock_jenkins(
    harness: Harness,
    mocked_container: Container,
    container_tmppath: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a mocked container and a monkeypatched Jenkins client.
    act: _unlock_jenkins is called.
    assert: files necessary to unlock Jenkins are written.
    """
    monkeypatch.setattr(charm_src, "Jenkins", MockedJenkinsClient)
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)

    charm._unlock_jenkins(mocked_container)

    expected_version = MockedJenkinsClient().version
    assert (
        make_relative_to_path(container_tmppath, LAST_EXEC).read_text(encoding="utf-8")
        == expected_version
    )
    assert (
        make_relative_to_path(container_tmppath, UPDATE_VERSION).read_text(encoding="utf-8")
        == expected_version
    )


def test__on_jenkins_pebble_ready_no_container(harness: Harness):
    """
    arrange: given a pebble ready event with container unable to connect.
    act: when the Jenkins pebble ready event is fired.
    assert: the event should be deferred.
    """
    harness.set_can_connect(harness.model.unit.containers["jenkins"], False)
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)
    mock_event = MagicMock(spec=PebbleReadyEvent)
    mock_event.workload = None

    charm._on_jenkins_pebble_ready(mock_event)

    mock_event.defer.assert_called()


@pytest.mark.parametrize(
    "status_code,expected_status",
    [
        pytest.param(503, BlockedStatus, id="jenkins not ready"),
        pytest.param(200, ActiveStatus, id="jenkins ready"),
    ],
)
def test__on_jenkins_pebble_ready(  # pylint: disable=too-many-arguments
    harness: Harness,
    mocked_container: Container,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_status: StatusBase,
):
    """
    arrange: given a mocked jenkins client and a patched requests instance.
    act: when the Jenkins pebble ready event is fired.
    assert: the unit status should show expected status.
    """
    monkeypatch.setattr(charm_src, "Jenkins", MockedJenkinsClient)
    # speed up waiting by changing default argument values
    monkeypatch.setattr(
        charm_src.JenkinsK8SOperatorCharm._wait_jenkins_ready, "__defaults__", (1, 1)
    )
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)
    mock_event = MagicMock(spec=PebbleReadyEvent)
    mock_event.workload = mocked_container

    charm._on_jenkins_pebble_ready(mock_event)

    assert (
        harness.model.unit.status.name == expected_status.name
    ), f"unit should be in {expected_status}"
