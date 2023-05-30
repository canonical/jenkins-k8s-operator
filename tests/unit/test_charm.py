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
from ops.charm import ActionEvent, PebbleReadyEvent
from ops.model import ActiveStatus, BlockedStatus, StatusBase

import jenkins
from charm import JenkinsK8SOperatorCharm

from .helpers import BLOCKED_STATUS_NAME
from .types_ import HarnessWithContainer


def test__on_jenkins_pebble_ready_no_container(harness_container: HarnessWithContainer):
    """
    arrange: given a pebble ready event with container unable to connect.
    act: when the Jenkins pebble ready event is fired.
    assert: the event should be deferred.
    """
    harness_container.harness.begin()
    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    mock_event = MagicMock(spec=PebbleReadyEvent)
    mock_event.workload = None

    jenkins_charm._on_jenkins_pebble_ready(mock_event)

    mock_event.defer.assert_called()


def test__on_jenkins_pebble_ready_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: Callable,
):
    """
    arrange: given a patched jenkins bootstrap method that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the unit status should be in BlockedStatus.
    """
    # speed up waiting by changing default argument values
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(
        jenkins,
        "bootstrap",
        lambda *_args, **_kwargs: raise_exception(exception=jenkins.JenkinsBootstrapError()),
    )
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))

    harness_container.harness.begin_with_initial_hooks()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


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
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))

    harness_container.harness.begin_with_initial_hooks()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert (
        jenkins_charm.unit.status.name == expected_status.name
    ), f"unit should be in {expected_status}"


def test__on_get_admin_password_action_container_not_ready(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given a jenkins container that is not connectable.
    act: when get-admin-password action is run.
    assert: the event is deferred.
    """
    harness_container.harness.set_can_connect(
        harness_container.harness.model.unit.containers["jenkins"], False
    )
    mock_event = MagicMock(spec=ActionEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_get_admin_password(mock_event)

    assert mock_event.defer.called_once()


def test__on_get_admin_password_action(
    harness_container: HarnessWithContainer, admin_credentials: jenkins.Credentials
):
    """
    arrange: given a jenkins container.
    act: when get-admin-password action is run.
    assert: the correct admin password is returned.
    """
    mock_event = MagicMock(spec=ActionEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_get_admin_password(mock_event)

    mock_event.set_results.assert_called_once_with({"password": admin_credentials.password})
