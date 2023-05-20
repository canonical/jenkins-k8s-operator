# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

from functools import partial
from typing import Any, Callable, cast
from unittest.mock import MagicMock

import pytest
import requests
from ops.charm import PebbleReadyEvent
from ops.model import ActiveStatus, BlockedStatus, StatusBase
from ops.testing import Harness

import jenkins as jenkins_src
from charm import JenkinsK8SOperatorCharm

from .types_ import HarnessWithContainer


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
# there are too many dependent fixtures that cannot be merged.
def test__on_jenkins_pebble_ready(  # pylint: disable=too-many-arguments
    harness_container: HarnessWithContainer,
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
    monkeypatch.setattr(jenkins_src.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))
    harness_container.harness.begin()
    charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    mock_event = MagicMock(spec=PebbleReadyEvent)
    mock_event.workload = harness_container.container

    charm._on_jenkins_pebble_ready(mock_event)

    assert (
        harness_container.harness.model.unit.status.name == expected_status.name
    ), f"unit should be in {expected_status}"
