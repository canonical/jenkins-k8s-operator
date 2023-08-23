# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import datetime
import functools
import typing
from unittest.mock import MagicMock

import ops
import pytest
import requests

import jenkins
import state
import status
import timerange
from charm import JenkinsK8sOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME
from .types_ import HarnessWithContainer


@pytest.mark.parametrize(
    "charm_config", [pytest.param({"restart-time-range": "-2"}, id="invalid restart-time-range")]
)
def test___init___invailid_config(
    harness_container: HarnessWithContainer, charm_config: dict[str, str]
):
    """
    arrange: given an invalid charm configuration.
    act: when the Jenkins charm is initialized.
    assert: the charm falls into blocked status.
    """
    harness_container.harness.update_config(charm_config)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


def test__on_jenkins_pebble_ready_no_container(harness_container: HarnessWithContainer):
    """
    arrange: given a pebble ready event with container unable to connect.
    act: when the Jenkins pebble ready event is fired.
    assert: the event should be deferred.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_event = MagicMock(spec=ops.PebbleReadyEvent)
    mock_event.workload = None

    jenkins_charm._on_jenkins_pebble_ready(mock_event)

    mock_event.defer.assert_called()


def test__on_jenkins_pebble_ready_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
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
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))

    harness_container.harness.begin_with_initial_hooks()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


def test__on_jenkins_pebble_ready_get_version_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
):
    """
    arrange: given a patched jenkins.get_version function that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the unit status should be in BlockedStatus.
    """
    # speed up waiting by changing default argument values
    monkeypatch.setattr(jenkins, "get_version", lambda: raise_exception(jenkins.JenkinsError))
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(jenkins, "bootstrap", lambda *_args: None)
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))

    harness_container.harness.begin_with_initial_hooks()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


@pytest.mark.parametrize(
    "status_code,expected_status",
    [
        pytest.param(503, ops.BlockedStatus, id="jenkins not ready"),
        pytest.param(200, ops.ActiveStatus, id="jenkins ready"),
    ],
)
# there are too many dependent fixtures that cannot be merged.
def test__on_jenkins_pebble_ready(  # pylint: disable=too-many-arguments
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_status: ops.StatusBase,
):
    """
    arrange: given a mocked jenkins client and a patched requests instance.
    act: when the Jenkins pebble ready event is fired.
    assert: the unit status should show expected status.
    """
    # monkeypatch environment variables because the test is running in self-hosted runners and juju
    # proxy environment is picked up, making the test fail.
    monkeypatch.setattr(state.os, "environ", {})
    # speed up waiting by changing default argument values
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(
        requests, "get", functools.partial(mocked_get_request, status_code=status_code)
    )

    harness_container.harness.begin_with_initial_hooks()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
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
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
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
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_get_admin_password(mock_event)

    mock_event.set_results.assert_called_once_with({"password": admin_credentials.password})


def test__update_jenkins_version_already_latest(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given latest jenkins, monkeypatched has_updates_for_lts that returns the None.
    act: when _update_jenkins_version is called.
    assert: original status is returned with no status message.
    """
    monkeypatch.setattr(jenkins, "has_updates_for_lts", lambda *_args, **_kwargs: None)
    mock_download_func = MagicMock(spec=jenkins._download_stable_war)
    monkeypatch.setattr(jenkins, "_download_stable_war", mock_download_func)
    harness, container = harness_container.harness, harness_container.container
    harness.begin()
    original_status = harness.charm.unit.status.name

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    returned_status = jenkins_charm._update_jenkins_version(container)

    mock_download_func.assert_not_called()
    assert returned_status.name == original_status
    assert not returned_status.message, "The status message should not exist."


def test__update_jenkins_version_has_updates_for_lts_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
):
    """
    arrange: given latest jenkins, monkeypatched has_updates_for_lts that raises exceptions.
    act: when _update_jenkins_version is called.
    assert: original status is returned with failed status message.
    """
    monkeypatch.setattr(
        jenkins,
        "has_updates_for_lts",
        lambda *_args, **_kwargs: raise_exception(jenkins.JenkinsUpdateError),
    )
    harness, container = harness_container.harness, harness_container.container
    harness.begin()
    original_status = harness.charm.unit.status.name

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    returned_status = jenkins_charm._update_jenkins_version(container)

    assert returned_status.name == original_status
    assert returned_status.message == "Failed to get Jenkins patch version."


def test__update_jenkins_version_jenkins_update_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
):
    """
    arrange: given monkeypatched update_jenkins that raises a JenkinsUpdateError.
    act: when _update_jenkins_version is called.
    assert: original status is returned with failed status message.
    """
    monkeypatch.setattr(jenkins, "has_updates_for_lts", lambda: True)
    monkeypatch.setattr(
        jenkins,
        "update_jenkins",
        lambda *_args, **_kwargs: raise_exception(jenkins.JenkinsUpdateError),
    )
    harness, container = harness_container.harness, harness_container.container
    harness.begin()
    original_status = harness.charm.unit.status.name

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    returned_status = jenkins_charm._update_jenkins_version(container)

    assert returned_status.name == original_status
    assert returned_status.message == "Failed to get update data."


def test__update_jenkins_version_jenkins_restart_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    raise_exception: typing.Callable,
):
    """
    arrange: given monkeypatched update_jenkins that raises a JenkinsRestartError exception.
    act: when _update_jenkins_version is called.
    assert: blocked status is returned with failed status message.
    """
    monkeypatch.setattr(jenkins, "has_updates_for_lts", lambda: True)
    monkeypatch.setattr(
        jenkins,
        "update_jenkins",
        lambda *_args, **_kwargs: raise_exception(jenkins.JenkinsRestartError),
    )
    harness, container = harness_container.harness, harness_container.container
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    returned_status = jenkins_charm._update_jenkins_version(container)

    assert returned_status.name == BLOCKED_STATUS_NAME
    assert returned_status.message == "Update restart failed."


def test__update_jenkins_version_update(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    patched_version: str,
):
    """
    arrange: given monkeypatched jenkins that returns the unpatched version.
    act: when _update_jenkins_version is called.
    assert: active status is returned with no message.
    """
    monkeypatch.setattr(jenkins, "has_updates_for_lts", lambda: True)
    monkeypatch.setattr(
        jenkins,
        "update_jenkins",
        lambda *_args, **_kwargs: patched_version,
    )
    harness, container = harness_container.harness, harness_container.container
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    returned_status = jenkins_charm._update_jenkins_version(container)

    assert returned_status.name == ACTIVE_STATUS_NAME
    assert returned_status.message == ""


@pytest.mark.parametrize(
    "exception, expected_status",
    [
        pytest.param(
            jenkins.JenkinsPluginError,
            ops.MaintenanceStatus("Failed to remove unlisted plugin."),
            id="plugin error",
        ),
        pytest.param(
            jenkins.JenkinsError,
            ops.MaintenanceStatus("Failed to remove unlisted plugin."),
            id="jenkins error",
        ),
        pytest.param(
            TimeoutError,
            ops.BlockedStatus("Failed to restart Jenkins after removing plugins"),
            id="jenkins error",
        ),
    ],
)
def test__remove_unlisted_plugins_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    raise_exception: typing.Callable,
    expected_status: ops.StatusBase,
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that raises exceptions.
    act: when _remove_unlisted_plugins is called.
    assert: ActiveStatus with error message is returned.
    """
    monkeypatch.setattr(
        jenkins, "remove_unlisted_plugins", lambda *_args, **_kwargs: raise_exception(exception)
    )
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    returned_status = jenkins_charm._remove_unlisted_plugins(harness_container.container)

    assert returned_status == expected_status


def test__remove_unlisted_plugins(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that succeeds.
    act: when _remove_unlisted_plugins is called.
    assert: ActiveStatus without error message is returned.
    """
    monkeypatch.setattr(jenkins, "remove_unlisted_plugins", lambda *_args, **_kwargs: None)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    returned_status = jenkins_charm._remove_unlisted_plugins(harness_container.container)

    assert returned_status.name == ACTIVE_STATUS_NAME
    assert returned_status.message == ""


def test__on_update_status_no_container(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm with container not yet ready to connect.
    act: when _on_update_status is called.
    assert: no further functions are called.
    """
    mock_get_priority_status = MagicMock(spec=status.get_priority_status)
    monkeypatch.setattr(status, "get_priority_status", mock_get_priority_status)
    harness, container = harness_container.harness, harness_container.container
    harness.set_can_connect(container, False)
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

    mock_get_priority_status.assert_not_called()


def test__on_update_status_not_in_time_range(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm with restart-time-range 0-23 and monkeypatched datetime with hour 23.
    act: when update_status action is triggered.
    assert: no further functions are called.
    """
    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 23)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    monkeypatch.setattr(
        status,
        "get_priority_status",
        mock_status_func := MagicMock(spec=status.get_priority_status),
    )
    harness_container.harness.update_config({"restart-time-range": "00-23"})
    harness_container.harness.begin()
    harness = harness_container.harness
    original_status = harness.charm.unit.status.name

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

    assert jenkins_charm.unit.status.name == original_status
    mock_status_func.assert_not_called()


# pylint doesn't quite understand walrus operators
# pylint: disable=unused-variable,undefined-variable,too-many-locals
@pytest.mark.parametrize(
    "remove_plugin_status, update_jenkins_status, expected_status",
    [
        pytest.param(
            expected_status := ops.ActiveStatus("Failed to remove unlisted plugin."),
            ops.ActiveStatus(),
            expected_status,
            id="Failed plugin remove status.",
        ),
        pytest.param(
            ops.ActiveStatus("Failed to remove unlisted plugin."),
            # walrus operator is initialized with another status, mypy complains about
            # incompatible types in assignment
            expected_status := ops.BlockedStatus(),  # type: ignore
            expected_status,
            id="Failed plugin remove status (blocked status).",
        ),
        pytest.param(
            ops.ActiveStatus("Failed to remove unlisted plugin."),
            expected_status := ops.MaintenanceStatus(),  # type: ignore
            expected_status,
            id="Failed plugin remove status (maintenance status).",
        ),
        pytest.param(
            ops.ActiveStatus(),
            expected_status := ops.WaitingStatus(),  # type: ignore
            expected_status,
            id="Failed update jenkins status (waiting status).",
        ),
        pytest.param(
            expected_status := ops.ActiveStatus("Failed to remove unlisted plugin."),
            ops.ActiveStatus("Failed to get Jenkins patch version."),
            expected_status,
            id="Both failed (active status)",
        ),
    ],
)
# pylint: enable=unused-variable,undefined-variable,too-many-locals
def test__on_update_status(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    remove_plugin_status: ops.StatusBase,
    update_jenkins_status: ops.StatusBase,
    expected_status: ops.StatusBase,
):
    """
    arrange: given patched statuses from _remove_unlisted_plugins and _update_jenkins_version.
    act: when _on_update_status is called.
    assert: expected status is applied to the unit status.
    """
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_remove_unlisted_plugins",
        lambda *_args, **_kwargs: remove_plugin_status,
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_update_jenkins_version",
        lambda *_args, **_kwargs: update_jenkins_status,
    )
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

    assert jenkins_charm.unit.status == expected_status
