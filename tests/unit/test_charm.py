# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import datetime
import functools
import typing
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import pytest
import requests

import ingress
import jenkins
import precondition
import state
import timerange
from charm import JenkinsK8sOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME, WAITING_STATUS_NAME
from .types_ import Harness, HarnessWithContainer


@pytest.mark.parametrize(
    "charm_config",
    [pytest.param({"restart-time-range": "-2"}, id="invalid restart-time-range")],
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
    mock_event = MagicMock(spec=ops.WorkloadEvent)
    mock_event.workload = MagicMock(spec=ops.model.Container)
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
    mock_event = MagicMock(spec=ops.WorkloadEvent)
    mock_event.workload = MagicMock(spec=ops.model.Container)
    mock_event.workload.can_connect.return_value = True

    handler_func(mock_event)

    assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME


def test__on_jenkins_pebble_ready_get_version_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[..., requests.Response],
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a patched jenkins.version property that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the charm raises an error.
    """
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))
    harness = harness_container.harness
    harness.begin()

    with (
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
        patch.object(jenkins.Jenkins, "bootstrap"),
    ):
        version_mock.side_effect = jenkins.JenkinsError

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

        with pytest.raises(jenkins.JenkinsError):
            jenkins_charm._on_jenkins_pebble_ready(MagicMock(spec=ops.PebbleReadyEvent))


@pytest.mark.usefixtures("patch_os_environ")
def test__on_jenkins_pebble_ready(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked jenkins client and a patched requests instance.
    act: when the Jenkins pebble ready event is fired.
    assert: the unit status should show expected status and the jenkins port should be open.
    """
    harness = harness_container.harness
    with (
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "bootstrap"),
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
    ):
        version_mock.return_value = "1"
        harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        jenkins_charm._on_jenkins_pebble_ready(MagicMock(spec=ops.PebbleReadyEvent))

        assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME, (
            f"unit should be in {ACTIVE_STATUS_NAME}"
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
            ops.BlockedStatus("Failed to remove plugins."),
            id="jenkins error",
        ),
    ],
)
def test__remove_unlisted_plugins_error(
    harness_container: HarnessWithContainer,
    exception: Exception,
    expected_status: ops.StatusBase,
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that raises exceptions.
    act: when _remove_unlisted_plugins is called.
    assert: ActiveStatus with error message is returned.
    """
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_unlisted_plugins_mock:
        remove_unlisted_plugins_mock.side_effect = exception
        harness_container.harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
        returned_status = jenkins_charm._remove_unlisted_plugins(harness_container.container)

        assert returned_status == expected_status


def test__remove_unlisted_plugins(harness_container: HarnessWithContainer):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that succeeds.
    act: when _remove_unlisted_plugins is called.
    assert: ActiveStatus without error message is returned.
    """
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins"):
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
    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 23)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    harness_container.harness.update_config({"restart-time-range": "00-23"})
    harness_container.harness.begin()
    harness = harness_container.harness
    original_status = harness.charm.unit.status.name

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_unlisted_plugins_mock:
        jenkins_charm._on_update_status(MagicMock(spec=ops.UpdateStatusEvent))

        assert jenkins_charm.unit.status.name == original_status
        remove_unlisted_plugins_mock.assert_not_called()


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
            expected_status := ops.ActiveStatus("Failed to remove unlisted plugin."),  # type: ignore
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


def test_calculate_env(harness: Harness):
    """
    arrange: given a charm.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    harness.begin()
    ingress_observer = MagicMock(spec=ingress.Observer)
    ingress_observer.get_path.return_value = ""
    harness.charm.ingress_observer = ingress_observer
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    env = jenkins_charm.calculate_env()

    assert env == {"JENKINS_HOME": str(jenkins.JENKINS_HOME_PATH), "JENKINS_PREFIX": ""}


def test__on_config_changed_invalid_config_blocked(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given State.from_charm raises CharmConfigInvalidError during config-changed.
    act: when _on_config_changed is invoked.
    assert: unit falls into BlockedStatus and no container actions are performed.
    """
    # Start charm normally so __init__ completes and observers are registered.
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with (
        patch("state.State.from_charm") as from_charm_mock,
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
        patch.object(harness_container.container, "restart") as restart_mock,
    ):
        from_charm_mock.side_effect = state.CharmConfigInvalidError("bad sysprops")

        jenkins_charm._on_config_changed(MagicMock(spec=ops.ConfigChangedEvent))

        assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
        assert jenkins_charm.unit.status.message == "bad sysprops"
        add_layer_mock.assert_not_called()
        replan_mock.assert_not_called()
        restart_mock.assert_not_called()


def test__on_config_changed_relation_data_invalid_raises(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given State.from_charm raises CharmRelationDataInvalidError.
    act: when _on_config_changed is invoked.
    assert: a RuntimeError is raised by the handler.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with patch("state.State.from_charm") as from_charm_mock:
        from_charm_mock.side_effect = state.CharmRelationDataInvalidError("bad relation")

        with pytest.raises(RuntimeError):
            jenkins_charm._on_config_changed(MagicMock(spec=ops.ConfigChangedEvent))


def test__on_config_changed_precondition_waits_and_defers(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given precondition.check indicates not ready.
    act: when _on_config_changed is invoked.
    assert: unit is in WaitingStatus and the event is deferred.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    event = MagicMock(spec=ops.ConfigChangedEvent)

    with (
        patch("state.State.from_charm", wraps=state.State.from_charm),
        patch("precondition.check") as check_mock,
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
        patch.object(harness_container.container, "restart") as restart_mock,
    ):
        check_mock.return_value = precondition._CheckResult(success=False, reason="not ready")

        jenkins_charm._on_config_changed(event)

        assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME
        assert jenkins_charm.unit.status.message == "not ready"
        event.defer.assert_called_once_with()
        add_layer_mock.assert_not_called()
        replan_mock.assert_not_called()
        restart_mock.assert_not_called()


def test__on_config_changed_success_replans_and_restarts(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given precondition.check success and a valid pebble layer builder.
    act: when _on_config_changed is invoked.
    assert: container.add_layer, container.replan and container.restart are called.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with (
        patch("state.State.from_charm", wraps=state.State.from_charm),
        patch("precondition.check") as check_mock,
        patch("pebble.get_pebble_layer") as layer_mock,
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
        patch.object(harness_container.container, "restart") as restart_mock,
    ):
        check_mock.return_value = precondition._CheckResult(success=True, reason=None)
        # Minimal viable layer for add_layer
        layer_mock.return_value = ops.pebble.Layer({"services": {"jenkins": {}}})

        jenkins_charm._on_config_changed(MagicMock(spec=ops.ConfigChangedEvent))

        add_layer_mock.assert_called_once()
        replan_mock.assert_called_once()
        restart_mock.assert_called_once_with(state.JENKINS_SERVICE_NAME)
