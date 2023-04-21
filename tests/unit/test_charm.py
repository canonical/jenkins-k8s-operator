# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# pylint:disable=protected-access

from functools import partial
from typing import Any, Callable, cast
from unittest.mock import MagicMock

import pytest
import requests
from ops.charm import PebbleReadyEvent
from ops.model import ActiveStatus, BlockedStatus, Container, StatusBase
from ops.testing import Harness

import jenkins as jenkins_src
from charm import LAST_EXEC, UPDATE_VERSION, JenkinsK8SOperatorCharm

from .helpers import make_relative_to_path
from .types_ import ContainerWithPath


def test__unlock_jenkins(
    harness: Harness,
    container_with_path: ContainerWithPath,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """
    arrange: given a mocked container and a monkeypatched Jenkins client.
    act: _unlock_jenkins is called.
    assert: files necessary to unlock Jenkins are written.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))
    harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness.charm)

    charm._unlock_jenkins(container_with_path.container)

    assert (
        make_relative_to_path(container_with_path.path, LAST_EXEC).read_text(encoding="utf-8")
        == jenkins_version
    )
    assert (
        make_relative_to_path(container_with_path.path, UPDATE_VERSION).read_text(encoding="utf-8")
        == jenkins_version
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
    # speed up waiting by changing default argument values
    monkeypatch.setattr(jenkins_src.wait_jenkins_ready, "__defaults__", (1, 1))
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
