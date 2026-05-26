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
def test__on_config_changed_invalid_config_sets_blocked(
    harness_container: HarnessWithContainer, charm_config: dict[str, str]
):
    """
    arrange: given an invalid charm configuration.
    act: when the config-changed handler is triggered.
    assert: the charm falls into blocked status.
    """
    harness_container.harness.update_config(charm_config)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    jenkins_charm._on_config_changed(MagicMock(spec=ops.ConfigChangedEvent))

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


def test__get_state_returns_none_on_invalid_config(harness: Harness):
    """
    arrange: given an invalid charm config.
    act: when _get_state() is called.
    assert: unit is BlockedStatus and None is returned.
    """
    harness.update_config({"restart-time-range": "-2"})
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with patch("state.State.from_charm") as from_charm_mock:
        from_charm_mock.side_effect = state.CharmConfigInvalidError("bad config")
        result = jenkins_charm._get_state()

    assert result is None
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    assert jenkins_charm.unit.status.message == "bad config"


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
    "exception",
    [
        pytest.param(jenkins.JenkinsPluginError, id="plugin error"),
        pytest.param(jenkins.JenkinsError, id="jenkins error"),
        pytest.param(TimeoutError, id="timeout error"),
    ],
)
def test__remove_unlisted_plugins_error(
    harness_container: HarnessWithContainer,
    exception: Exception,
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that raises exceptions.
    act: when _reconcile_plugins is called.
    assert: no unhandled exception is raised (errors are logged internally).
    """
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_unlisted_plugins_mock:
        remove_unlisted_plugins_mock.side_effect = exception
        harness_container.harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
        dummy_state = state.State.from_charm(jenkins_charm)
        # _reconcile_plugins catches exceptions internally and logs them
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)


def test__remove_unlisted_plugins(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that succeeds.
    act: when _reconcile_plugins is called.
    assert: remove_unlisted_plugins is called without error.
    """
    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 12)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    harness_container.harness.update_config({"restart-time-range": "02-22"})
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_mock:
        harness_container.harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
        dummy_state = state.State.from_charm(jenkins_charm)
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)

        remove_mock.assert_called_once()


def test__on_update_status_not_in_time_range(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm with restart-time-range 0-23 and monkeypatched datetime with hour 23.
    act: when _reconcile_plugins is called directly.
    assert: remove_unlisted_plugins is not called since we're outside the time range.
    """
    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 23)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    harness_container.harness.update_config({"restart-time-range": "00-23"})
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    dummy_state = state.State.from_charm(jenkins_charm)
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_unlisted_plugins_mock:
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)

        remove_unlisted_plugins_mock.assert_not_called()


# pylint doesn't quite understand walrus operators
# pylint: disable=unused-variable,undefined-variable,too-many-locals
@pytest.mark.parametrize(
    "exception, log_message",
    [
        pytest.param(
            jenkins.JenkinsPluginError("plugin err"),
            "Failed to remove unlisted plugin",
            id="Failed plugin remove status.",
        ),
        pytest.param(
            jenkins.JenkinsError("jenkins err"),
            "Failed to remove unlisted plugin",
            id="Failed plugin remove status (blocked status).",
        ),
        pytest.param(
            TimeoutError("timeout"),
            "Failed to remove plugins",
            id="Failed plugin remove status (maintenance status).",
        ),
        pytest.param(
            jenkins.JenkinsPluginError("plugin err 2"),
            "Failed to remove unlisted plugin",
            id="Failed update jenkins status (waiting status).",
        ),
        pytest.param(
            jenkins.JenkinsError("jenkins err 2"),
            "Failed to remove unlisted plugin",
            id="Both failed (active status)",
        ),
    ],
)
# pylint: enable=unused-variable,undefined-variable,too-many-locals
def test__on_update_status(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    log_message: str,
):
    """
    arrange: given patched remove_unlisted_plugins that raises an exception.
    act: when _reconcile_plugins is called.
    assert: no unhandled exception is raised (error is logged internally).
    """
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    dummy_state = state.State.from_charm(jenkins_charm)

    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as mock_remove:
        mock_remove.side_effect = exception
        # Should not raise - errors are caught and logged
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)


def test_calculate_env(harness: Harness):
    """
    arrange: given a charm.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    with patch.object(jenkins_charm, "_get_ingress_path", return_value=""):
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
    assert: container.add_layer and container.replan are called.
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
        patch.object(harness_container.container, "get_plan") as get_plan_mock,
    ):
        check_mock.return_value = precondition._CheckResult(success=True, reason=None)
        # Minimal viable layer for add_layer
        layer_mock.return_value = ops.pebble.Layer({"services": {"jenkins": {}}})
        # Return empty plan so services differ and replan is triggered
        get_plan_mock.return_value = ops.pebble.Plan("")

        jenkins_charm._on_config_changed(MagicMock(spec=ops.ConfigChangedEvent))

        add_layer_mock.assert_called_once()
        replan_mock.assert_called_once()


def test__remove_unlisted_plugins_requires_state(harness_container: HarnessWithContainer):
    """
    arrange: given a started charm instance.
    act: when _reconcile_plugins is called without state.
    assert: python rejects the call because state is required.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    reconcile_plugins = typing.cast(typing.Any, jenkins_charm._reconcile_plugins)

    with pytest.raises(TypeError):
        reconcile_plugins(harness_container.container)


@pytest.mark.parametrize(
    "handler_name, event_type",
    [
        pytest.param("_on_agent_relation_joined", ops.RelationJoinedEvent, id="joined"),
        pytest.param("_on_agent_relation_departed", ops.RelationDepartedEvent, id="departed"),
        pytest.param("_on_agent_relation_changed", ops.RelationChangedEvent, id="changed"),
    ],
)
def test__agent_relation_handlers_reconcile_agents(
    harness_container: HarnessWithContainer, handler_name: str, event_type: type[ops.EventBase]
):
    """
    arrange: given a started charm and a valid derived state.
    act: when an agent relation handler is called.
    assert: the handler delegates to _reconcile.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=event_type)

    with patch.object(jenkins_charm, "_reconcile") as reconcile_mock:
        getattr(jenkins_charm, handler_name)(event)

    reconcile_mock.assert_called_once_with(event)


@pytest.mark.parametrize(
    "handler_name",
    [
        pytest.param("_on_agent_discovery_ingress_ready", id="ready"),
        pytest.param("_on_agent_discovery_ingress_revoked", id="revoked"),
    ],
)
def test__agent_discovery_ingress_handlers_reconfigure_agents(
    harness_container: HarnessWithContainer, handler_name: str
):
    """
    arrange: given a started charm and a valid derived state.
    act: when an agent discovery ingress handler is called.
    assert: the handler delegates to _reconcile.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.EventBase)

    with patch.object(jenkins_charm, "_reconcile") as reconcile_mock:
        getattr(jenkins_charm, handler_name)(event)

    reconcile_mock.assert_called_once_with(event)


def test__upgrade_charm_reconciles_storage_and_agents(harness_container: HarnessWithContainer):
    """
    arrange: given a started charm and a valid derived state.
    act: when the upgrade-charm handler is called.
    assert: _reconcile is called with the event.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.UpgradeCharmEvent)

    with patch.object(jenkins_charm, "_reconcile") as reconcile_mock:
        jenkins_charm._on_upgrade_charm(event)

    reconcile_mock.assert_called_once_with(event)


@pytest.mark.parametrize(
    "handler_name, observer_name, event_type",
    [
        pytest.param(
            "_on_auth_proxy_relation_joined",
            "on_auth_proxy_relation_joined",
            ops.RelationCreatedEvent,
            id="joined",
        ),
        pytest.param(
            "_on_auth_proxy_relation_departed",
            "on_auth_proxy_relation_departed",
            ops.RelationDepartedEvent,
            id="departed",
        ),
    ],
)
def test__auth_proxy_relation_handlers_delegate(
    harness_container: HarnessWithContainer,
    handler_name: str,
    observer_name: str,
    event_type: type[ops.EventBase],
):
    """
    arrange: given a started charm and a valid derived state.
    act: when an auth-proxy relation handler is called.
    assert: the handler delegates to _reconcile.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=event_type)

    with patch.object(jenkins_charm, "_reconcile") as reconcile_mock:
        getattr(jenkins_charm, handler_name)(event)

    reconcile_mock.assert_called_once_with(event)
