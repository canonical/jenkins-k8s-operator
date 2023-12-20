# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import datetime
import functools
import typing
import unittest.mock

import ops
import pytest
import requests

import jenkins
import timerange
from charm import JenkinsK8sOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME, WAITING_STATUS_NAME
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


@pytest.mark.parametrize(
    "event_handler",
    [
        pytest.param("_on_jenkins_home_storage_attached"),
        pytest.param("_on_jenkins_pebble_ready"),
        pytest.param("_on_update_status"),
    ],
)
def test_workload_not_ready(harness: Harness, event_handler: str):
    """
    arrange: given a charm with no container ready.
    act: when an event hook is fired.
    assert: the charm falls into waiting status.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    handler_func = getattr(jenkins_charm, event_handler)
    mock_event = unittest.mock.MagicMock(spec=ops.WorkloadEvent)
    mock_event.workload = unittest.mock.MagicMock(spec=ops.model.Container)
    mock_event.workload.can_connect.return_value = False

    handler_func(mock_event)

    assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME


@pytest.mark.parametrize(
    "event_handler",
    [
        pytest.param("_on_jenkins_home_storage_attached"),
        pytest.param("_on_jenkins_pebble_ready"),
        pytest.param("_on_update_status"),
    ],
)
def test_storage_not_ready(harness: Harness, event_handler: str):
    """
    arrange: given a charm with no storage ready.
    act: when an event hook is fired.
    assert: the charm falls into waiting status.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    handler_func = getattr(jenkins_charm, event_handler)
    mock_event = unittest.mock.MagicMock(spec=ops.WorkloadEvent)
    mock_event.workload = unittest.mock.MagicMock(spec=ops.model.Container)
    mock_event.workload.can_connect.return_value = True

    handler_func(mock_event)

    assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME


def test__on_jenkins_pebble_ready_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a patched jenkins bootstrap method that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the unit status should be in BlockedStatus.
    """
    harness = harness_container.harness
    # speed up waiting by changing default argument values
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(
        jenkins,
        "bootstrap",
        unittest.mock.MagicMock(side_effect=jenkins.JenkinsBootstrapError()),
    )
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_jenkins_pebble_ready(unittest.mock.MagicMock(spec=ops.PebbleReadyEvent))

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


def test__on_jenkins_pebble_ready_get_version_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a patched jenkins.get_version function that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the unit status should be in BlockedStatus.
    """
    harness = harness_container.harness
    # speed up waiting by changing default argument values
    monkeypatch.setattr(
        jenkins, "get_version", unittest.mock.MagicMock(side_effect=jenkins.JenkinsError)
    )
    monkeypatch.setattr(jenkins.wait_ready, "__defaults__", (1, 1))
    monkeypatch.setattr(jenkins, "bootstrap", lambda *_args: None)
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_jenkins_pebble_ready(unittest.mock.MagicMock(spec=ops.PebbleReadyEvent))

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


@pytest.mark.usefixtures("patch_os_environ")
def test__on_jenkins_pebble_jenkins_not_ready(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a mocked jenkins get_version raises TimeoutError on the second call.
    act: when the Jenkins pebble ready event is fired.
    assert: Jenkins falls into BlockedStatus.
    """
    harness = harness_container.harness
    monkeypatch.setattr(
        jenkins, "wait_ready", unittest.mock.MagicMock(side_effect=[None, TimeoutError])
    )
    monkeypatch.setattr(jenkins, "bootstrap", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(jenkins, "get_version", lambda *_args, **_kwargs: "1")
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_jenkins_pebble_ready(unittest.mock.MagicMock(spec=ops.PebbleReadyEvent))

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    assert (
        jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    ), f"unit should be in {BLOCKED_STATUS_NAME}"


@pytest.mark.usefixtures("patch_os_environ")
def test__on_jenkins_pebble_ready(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a mocked jenkins client and a patched requests instance.
    act: when the Jenkins pebble ready event is fired.
    assert: the unit status should show expected status and the jenkins port should be open.
    """
    harness = harness_container.harness
    monkeypatch.setattr(jenkins, "wait_ready", unittest.mock.MagicMock(return_value=None))
    monkeypatch.setattr(jenkins, "bootstrap", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(jenkins, "get_version", lambda *_args, **_kwargs: "1")
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_jenkins_pebble_ready(unittest.mock.MagicMock(spec=ops.PebbleReadyEvent))

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    assert (
        jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME
    ), f"unit should be in {ACTIVE_STATUS_NAME}"
    assert jenkins.WEB_PORT in {open_port.port for open_port in harness.model.unit.opened_ports()}


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
            ops.BlockedStatus("Failed to remove plugins."),
            id="jenkins error",
        ),
    ],
)
def test__remove_unlisted_plugins_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    expected_status: ops.StatusBase,
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that raises exceptions.
    act: when _remove_unlisted_plugins is called.
    assert: ActiveStatus with error message is returned.
    """
    monkeypatch.setattr(
        jenkins,
        "remove_unlisted_plugins",
        unittest.mock.MagicMock(side_effect=exception),
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


def test__on_update_status_not_in_time_range(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm with restart-time-range 0-23 and monkeypatched datetime with hour 23.
    act: when update_status action is triggered.
    assert: no further functions are called.
    """
    mock_datetime = unittest.mock.MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 23)
    mock_remove_unlisted_plugins_func = unittest.mock.MagicMock(
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
    jenkins_charm._on_update_status(unittest.mock.MagicMock(spec=ops.UpdateStatusEvent))

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
    jenkins_charm._on_update_status(unittest.mock.MagicMock(spec=ops.UpdateStatusEvent))

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
    exec_handler = unittest.mock.MagicMock()
    monkeypatch.setattr(container, "exec", exec_handler)

    event = unittest.mock.MagicMock()
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
    exec_handler = unittest.mock.MagicMock()
    monkeypatch.setattr(container, "exec", exec_handler)

    jenkins_charm._on_jenkins_home_storage_attached(unittest.mock.MagicMock())

    exec_handler.assert_not_called()
