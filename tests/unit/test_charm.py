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
import timerange
from charm import JenkinsK8sOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME
from .types_ import Harness, HarnessWithContainer


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
    monkeypatch.setattr(jenkins, "_setup_user_token", lambda *_args, **_kwargs: None)
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

    mock_event.set_results.assert_called_once_with(
        {"password": admin_credentials.password_or_token}
    )


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
    mock_remove_unlisted_plugins_func = MagicMock(
        spec=JenkinsK8sOperatorCharm._remove_unlisted_plugins
    )
    harness, container = harness_container.harness, harness_container.container
    harness.set_can_connect(container, False)
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    monkeypatch.setattr(
        jenkins_charm, "_remove_unlisted_plugins", mock_remove_unlisted_plugins_func
    )
    jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

    mock_remove_unlisted_plugins_func.assert_not_called()


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
    mock_remove_unlisted_plugins_func = MagicMock(
        spec=JenkinsK8sOperatorCharm._remove_unlisted_plugins
    )
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    harness_container.harness.update_config({"restart-time-range": "00-23"})
    harness_container.harness.begin()
    harness = harness_container.harness
    original_status = harness.charm.unit.status.name

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    monkeypatch.setattr(
        jenkins_charm, "_remove_unlisted_plugins", mock_remove_unlisted_plugins_func
    )
    jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

    assert jenkins_charm.unit.status.name == original_status
    mock_remove_unlisted_plugins_func.assert_not_called()


# pylint doesn't quite understand walrus operators
# pylint: disable=unused-variable,undefined-variable,too-many-locals
@pytest.mark.parametrize(
    "remove_plugin_status, expected_status",
    [
        pytest.param(
            expected_status := ops.ActiveStatus("Failed to remove unlisted plugin."),
            expected_status,
            id="Failed plugin remove status.",
        ),
        pytest.param(
            ops.ActiveStatus("Failed to remove unlisted plugin."),
            expected_status,
            id="Failed plugin remove status (blocked status).",
        ),
        pytest.param(
            ops.ActiveStatus("Failed to remove unlisted plugin."),
            expected_status,
            id="Failed plugin remove status (maintenance status).",
        ),
        # walrus operator is initialized with another status, mypy complains about
        # incompatible types in assignment
        pytest.param(
            expected_status := ops.ActiveStatus(
                "Failed to remove unlisted plugin."
            ),  # type: ignore
            expected_status,
            id="Failed update jenkins status (waiting status).",
        ),
        pytest.param(
            ops.ActiveStatus("Failed to remove unlisted plugin."),
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
    expected_status: ops.StatusBase,
):
    """
    arrange: given patched statuses from _remove_unlisted_plugins.
    act: when _on_update_status is called.
    assert: expected status is applied to the unit status.
    """
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_remove_unlisted_plugins",
        lambda *_args, **_kwargs: remove_plugin_status,
    )
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

    assert jenkins_charm.unit.status == expected_status


def test__on_jenkins_home_storage_attached(harness: Harness, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a base jenkins charm.
    act: when _on_jenkins_home_storage_attached is called.
    assert: The chown command was ran on the jenkins container with correct parameters.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    container = jenkins_charm.unit.containers["jenkins"]
    harness.set_can_connect(container, True)
    # We don't use harness.handle_exec here because we want to assert
    # the parameters passed to exec()
    exec_handler = MagicMock()
    monkeypatch.setattr(container, "exec", exec_handler)

    event = MagicMock()
    mock_jenkins_home_path = "/var/lib/jenkins"
    event.storage.location.resolve = lambda: mock_jenkins_home_path
    jenkins_charm._on_jenkins_home_storage_attached(event)

    exec_handler.assert_called_once_with(
        ["chown", "-R", "jenkins:jenkins", mock_jenkins_home_path], timeout=120
    )


def test__on_jenkins_home_storage_attached_container_not_ready(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a base jenkins charm with container not ready.
    act: when _on_jenkins_home_storage_attached is called.
    assert: The chown command was not ran.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    container = jenkins_charm.unit.containers["jenkins"]
    harness.set_can_connect(container, False)
    # We don't use harness.handle_exec here because we want to assert
    # whether exec() was called
    exec_handler = MagicMock()
    monkeypatch.setattr(container, "exec", exec_handler)

    jenkins_charm._on_jenkins_home_storage_attached(MagicMock())

    exec_handler.assert_not_called()
