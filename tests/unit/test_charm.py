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
from ops.charm import ActionEvent, PebbleReadyEvent, UpdateStatusEvent
from ops.model import ActiveStatus, BlockedStatus, StatusBase

import jenkins
from charm import JenkinsK8SOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME
from .types_ import HarnessWithContainer, Versions


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
        lambda *_args, **_kwargs: raise_exception(jenkins.JenkinsBootstrapError()),
    )
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))

    harness_container.harness.begin_with_initial_hooks()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(requests.HTTPError, id="HTTPError"),
        pytest.param(requests.exceptions.Timeout, id="TimeoutError"),
        pytest.param(requests.exceptions.ConnectionError, id="ConnectionError"),
    ],
)
def test__on_jenkins_pebble_ready_get_version_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: Callable,
    exception: Exception,
):
    """
    arrange: given a patched jenkins.get_version function that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the unit status should be in BlockedStatus.
    """
    # speed up waiting by changing default argument values
    monkeypatch.setattr(jenkins, "get_version", lambda: raise_exception(exception))
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(jenkins, "bootstrap", lambda *_args: None)
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


def test__on_update_status_no_action(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch, current_version: str
):
    """
    arrange: given latest jenkins, monkeypatched jenkins that returns the latest patch version.
    act: when update_status action is triggered.
    assert: no action is taken and the charm remains active.
    """
    mock_download_func = MagicMock(spec=jenkins.download_stable_war)
    monkeypatch.setattr(jenkins, "get_version", lambda: current_version)
    monkeypatch.setattr(jenkins, "get_latest_patch_version", lambda *_, **__: current_version)
    monkeypatch.setattr(jenkins, "download_stable_war", mock_download_func)
    mock_event = MagicMock(spec=UpdateStatusEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(mock_event)

    mock_download_func.assert_not_called()
    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(requests.HTTPError, id="HTTPError"),
        pytest.param(requests.exceptions.Timeout, id="TimeoutError"),
        pytest.param(requests.exceptions.ConnectionError, id="ConnectionError"),
    ],
)
def test__on_update_status_get_version_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: Callable,
    exception: Exception,
):
    """
    arrange: given monkeypatched get_version that raises an HTTP exception.
    act: when update_status action is triggered.
    assert: the charm falls into BlockedStatus since Jenkins service is not functioning.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: raise_exception(exception))
    mock_event = MagicMock(spec=UpdateStatusEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(mock_event)

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(jenkins.JenkinsNetworkError, id="JenkinsNetworkError"),
        pytest.param(jenkins.ValidationError, id="ValidationError"),
    ],
)
def test__on_update_status_get_latest_patch_version_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: Callable,
    exception: Exception,
    versions: Versions,
):
    """
    arrange: given monkeypatched get_latest_patch_version that raises jenkins exceptions.
    act: when update_status action is triggered.
    assert: the charm falls into ActiveStatus since the service should still be functioning.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: versions.current)
    monkeypatch.setattr(
        jenkins, "get_latest_patch_version", lambda *_args, **_kwargs: raise_exception(exception)
    )
    mock_event = MagicMock(spec=UpdateStatusEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(mock_event)

    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME


def test__on_update_status_dowload_stable_war_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: Callable,
    versions: Versions,
):
    """
    arrange: given monkeypatched download_stable_war that raises a JenkinsNetworkError.
    act: when update_status action is triggered.
    assert: the charm falls into ActiveStatus since the service should still be functioning.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: versions.current)
    monkeypatch.setattr(
        jenkins, "get_latest_patch_version", lambda *_args, **_kwargs: versions.patched
    )
    monkeypatch.setattr(
        jenkins,
        "download_stable_war",
        lambda *_args, **_kwargs: raise_exception(jenkins.JenkinsNetworkError),
    )
    mock_event = MagicMock(spec=UpdateStatusEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(mock_event)

    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME


def test__on_update_status_safe_restart_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: Callable,
    versions: Versions,
):
    """
    arrange: given monkeypatched safe_restart that raises a JenkinsError exception.
    act: when update_status action is triggered.
    assert: the charm falls into BlockedStatus since the service is not functioning.
    """
    monkeypatch.setattr(jenkins, "get_version", lambda: versions.current)
    monkeypatch.setattr(
        jenkins, "get_latest_patch_version", lambda *_args, **_kwargs: versions.patched
    )
    monkeypatch.setattr(
        jenkins,
        "download_stable_war",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        jenkins,
        "safe_restart",
        lambda *_args, **_kwargs: raise_exception(jenkins.JenkinsError),
    )
    mock_event = MagicMock(spec=UpdateStatusEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(mock_event)

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME


def test__on_update_status_update(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    current_version: str,
    patched_version: str,
):
    """
    arrange: given monkeypatched jenkins that returns the unpatched version.
    act: when update_status action is triggered.
    assert: functions required to apply the patch are called.
    """
    mock_download = MagicMock(spec=jenkins.download_stable_war)
    mock_safe_restart = MagicMock(spec=jenkins.safe_restart)
    monkeypatch.setattr(jenkins, "get_version", lambda: current_version)
    monkeypatch.setattr(jenkins, "get_latest_patch_version", lambda *_, **__: patched_version)
    monkeypatch.setattr(jenkins, "download_stable_war", mock_download)
    monkeypatch.setattr(jenkins, "safe_restart", mock_safe_restart)
    mock_event = MagicMock(spec=UpdateStatusEvent)
    harness_container.harness.begin()

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(mock_event)

    mock_download.assert_called_once_with(harness_container.container, patched_version)
    mock_safe_restart.assert_called_once()
    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME
