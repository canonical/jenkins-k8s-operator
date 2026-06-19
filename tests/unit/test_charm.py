# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import dataclasses
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

from .helpers import (
    ACTIVE_STATUS_NAME,
    BLOCKED_STATUS_NAME,
    WAITING_STATUS_NAME,
    patch_reconcile_pipeline,
)
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
    jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME, "unit should be in BlockedStatus"


@pytest.mark.parametrize(
    "event_spec",
    [
        pytest.param(ops.StorageAttachedEvent, id="_on_jenkins_home_storage_attached"),
        pytest.param(ops.PebbleReadyEvent, id="_on_jenkins_pebble_ready"),
        pytest.param(ops.UpdateStatusEvent, id="_on_update_status"),
    ],
)
def test_workload_not_ready(harness: Harness, event_spec: type):
    """
    arrange: given a charm with no container ready.
    act: when an event hook is fired.
    assert: the charm falls into waiting status.
    """
    harness.add_storage(state.JENKINS_HOME_STORAGE_NAME, count=1, attach=True)
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    mock_event = MagicMock(spec=event_spec)

    jenkins_charm._reconcile(mock_event)

    assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME


@pytest.mark.parametrize(
    "event_spec",
    [
        pytest.param(ops.StorageAttachedEvent, id="_on_jenkins_home_storage_attached"),
        pytest.param(ops.PebbleReadyEvent, id="_on_jenkins_pebble_ready"),
        pytest.param(ops.UpdateStatusEvent, id="_on_update_status"),
    ],
)
def test_storage_not_ready(harness: Harness, event_spec: type):
    """
    arrange: given a charm with no storage ready.
    act: when an event hook is fired.
    assert: the charm falls into waiting status.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    container = harness.model.unit.get_container("jenkins")
    harness.set_can_connect(container, True)
    mock_event = MagicMock(spec=event_spec)

    jenkins_charm._reconcile(mock_event)

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


def test__reconcile_pebble_ready_get_version_error(
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
        patch.object(JenkinsK8sOperatorCharm, "_reconcile_storage"),
    ):
        version_mock.side_effect = jenkins.JenkinsError

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

        with pytest.raises(jenkins.JenkinsError):
            jenkins_charm._reconcile(MagicMock(spec=ops.PebbleReadyEvent))


@pytest.mark.usefixtures("patch_os_environ")
def test__reconcile_pebble_ready(harness_container: HarnessWithContainer):
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
        patch.object(JenkinsK8sOperatorCharm, "_reconcile_storage"),
    ):
        version_mock.return_value = "1"
        harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        jenkins_charm._reconcile(MagicMock(spec=ops.PebbleReadyEvent))

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

        jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))

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
            jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))


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

        jenkins_charm._reconcile(event)

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
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
        patch.object(harness_container.container, "get_plan") as get_plan_mock,
    ):
        check_mock.return_value = precondition._CheckResult(success=True, reason=None)
        # Minimal viable layer for add_layer
        layer_mock.return_value = ops.pebble.Layer({"services": {"jenkins": {}}})
        # Return empty plan so services differ and replan is triggered
        get_plan_mock.return_value = ops.pebble.Plan("")

        jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))

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
    "event_type",
    [
        pytest.param(ops.RelationJoinedEvent, id="joined"),
        pytest.param(ops.RelationDepartedEvent, id="departed"),
        pytest.param(ops.RelationChangedEvent, id="changed"),
    ],
)
def test__agent_relation_handlers_reconcile_agents(
    harness_container: HarnessWithContainer, event_type: type[ops.EventBase]
):
    """
    arrange: given a started charm and a valid derived state.
    act: when an agent relation event triggers _reconcile.
    assert: reconcile executes without error (delegates internally to _reconcile_agents).
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=event_type)

    with patch_reconcile_pipeline(jenkins_charm, agents_return=True) as patched:
        reconcile_agents_mock = patched["reconcile_agents"]
        jenkins_charm._reconcile(event)

    reconcile_agents_mock.assert_called_once()


@pytest.mark.parametrize(
    "event_spec",
    [
        pytest.param(ops.EventBase, id="ready"),
        pytest.param(ops.EventBase, id="revoked"),
    ],
)
def test__agent_discovery_ingress_handlers_reconfigure_agents(
    harness_container: HarnessWithContainer, event_spec: type
):
    """
    arrange: given a started charm and a valid derived state.
    act: when an agent discovery ingress event triggers _reconcile.
    assert: reconcile executes without error (delegates internally to _reconcile_agent_discovery).
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=event_spec)

    with (
        patch_reconcile_pipeline(jenkins_charm, agents_return=True),
        patch.object(jenkins_charm, "_reconcile_agent_discovery") as reconcile_discovery_mock,
    ):
        jenkins_charm._reconcile(event)

    reconcile_discovery_mock.assert_called_once()


def test__upgrade_charm_reconciles_storage_and_agents(harness_container: HarnessWithContainer):
    """
    arrange: given a started charm and a valid derived state.
    act: when the upgrade-charm event triggers _reconcile.
    assert: _reconcile_storage is called (UpgradeCharmEvent triggers storage reconciliation).
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.UpgradeCharmEvent)

    with patch_reconcile_pipeline(jenkins_charm, agents_return=True) as patched:
        reconcile_storage_mock = patched["reconcile_storage"]
        jenkins_charm._reconcile(event)

    reconcile_storage_mock.assert_called_once()


def test_reconcile_orders_bootstrap_prestart_before_pebble_and_poststart_after(
    harness_container: HarnessWithContainer,
):
    """Ensure reconcile executes bootstrap prestart and poststart around pebble reconciliation."""
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    call_order: list[str] = []

    with (
        patch.object(
            jenkins_charm,
            "_reconcile_storage",
            side_effect=lambda container: call_order.append("storage"),
        ),
        patch.object(
            jenkins_charm,
            "_reconcile_bootstrap_prestart",
            create=True,
            side_effect=lambda container, state: call_order.append("bootstrap_prestart") or True,
        ),
        patch.object(
            jenkins_charm,
            "_reconcile_pebble",
            side_effect=lambda container, state: call_order.append("pebble"),
        ),
        patch.object(
            jenkins_charm,
            "_reconcile_bootstrap_poststart",
            create=True,
            side_effect=lambda container, state: call_order.append("bootstrap_poststart") or True,
        ),
        patch.object(
            jenkins_charm,
            "_reconcile_agents",
            side_effect=lambda state: call_order.append("agents") or True,
        ),
        patch.object(jenkins_charm, "_reconcile_agent_discovery"),
        patch.object(jenkins_charm, "_reconcile_auth_proxy"),
    ):
        jenkins_charm._reconcile(MagicMock(spec=ops.UpgradeCharmEvent))

    assert call_order == ["storage", "bootstrap_prestart", "pebble", "bootstrap_poststart", "agents"]


def test_bootstrap_poststart_marks_complete_only_after_restart_and_wait_ready(
    harness_container: HarnessWithContainer,
):
    """Ensure bootstrap marker is written after runtime steps complete."""
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    charm_state = state.State.from_charm(jenkins_charm)
    call_order: list[str] = []

    with (
        patch.object(jenkins, "is_jenkins_ready", return_value=True),
        patch.object(jenkins_charm, "_jenkins_bootstrapped", return_value=False),
        patch.object(
            jenkins_charm.jenkins,
            "wait_ready",
            side_effect=lambda: call_order.append("wait_ready"),
        ),
        patch.object(
            jenkins_charm.jenkins,
            "complete_bootstrap_runtime",
            side_effect=lambda container, proxy_config: call_order.append(
                "complete_bootstrap_runtime"
            ),
        ),
        patch.object(jenkins_charm.jenkins, "bootstrap") as legacy_bootstrap_mock,
        patch.object(
            harness_container.container,
            "restart",
            side_effect=lambda service_name: call_order.append("restart"),
        ),
        patch.object(
            jenkins_charm,
            "_mark_jenkins_bootstrapped",
            side_effect=lambda container: call_order.append("mark_bootstrapped"),
        ),
        patch.object(
            jenkins_charm.unit,
            "set_workload_version",
            side_effect=lambda version: call_order.append("set_workload_version"),
        ),
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
    ):
        version_mock.return_value = "1"

        result = jenkins_charm._reconcile_bootstrap_poststart(harness_container.container, charm_state)

    assert result is True
    assert call_order == [
        "wait_ready",
        "complete_bootstrap_runtime",
        "restart",
        "wait_ready",
        "mark_bootstrapped",
        "set_workload_version",
    ]
    legacy_bootstrap_mock.assert_not_called()


def test_bootstrap_poststart_does_not_mark_complete_on_runtime_error(
    harness_container: HarnessWithContainer,
):
    """Ensure bootstrap marker is not written when runtime bootstrap fails."""
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    charm_state = state.State.from_charm(jenkins_charm)

    with (
        patch.object(jenkins, "is_jenkins_ready", return_value=True),
        patch.object(jenkins_charm, "_jenkins_bootstrapped", return_value=False),
        patch.object(jenkins_charm.jenkins, "wait_ready"),
        patch.object(
            jenkins_charm.jenkins,
            "complete_bootstrap_runtime",
            side_effect=jenkins.JenkinsBootstrapError("runtime bootstrap failed"),
        ),
        patch.object(jenkins_charm.jenkins, "bootstrap") as legacy_bootstrap_mock,
        patch.object(jenkins_charm, "_mark_jenkins_bootstrapped") as mark_bootstrapped_mock,
    ):
        result = jenkins_charm._reconcile_bootstrap_poststart(harness_container.container, charm_state)

    assert result is False
    legacy_bootstrap_mock.assert_not_called()
    mark_bootstrapped_mock.assert_not_called()
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME


@pytest.mark.parametrize(
    "auth_proxy_integrated, expected_config",
    [
        pytest.param(False, jenkins.DEFAULT_JENKINS_CONFIG, id="default-config"),
        pytest.param(True, jenkins.AUTH_PROXY_JENKINS_CONFIG, id="auth-proxy-config"),
    ],
)
def test_bootstrap_prestart_prepares_static_phase(
    harness_container: HarnessWithContainer,
    auth_proxy_integrated: bool,
    expected_config: str,
):
    """Ensure prestart phase prepares static artifacts with selected config."""
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    charm_state = dataclasses.replace(
        state.State.from_charm(jenkins_charm), auth_proxy_integrated=auth_proxy_integrated
    )

    with patch.object(jenkins_charm.jenkins, "prepare_bootstrap_static") as prepare_static_mock:
        result = jenkins_charm._reconcile_bootstrap_prestart(harness_container.container, charm_state)

    assert result is True
    prepare_static_mock.assert_called_once_with(
        harness_container.container,
        expected_config,
        charm_state.proxy_config,
    )


def test_bootstrap_prestart_blocks_on_static_phase_error(
    harness_container: HarnessWithContainer,
):
    """Ensure prestart phase failures set BlockedStatus and stop reconcile."""
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    charm_state = state.State.from_charm(jenkins_charm)

    with patch.object(
        jenkins_charm.jenkins,
        "prepare_bootstrap_static",
        side_effect=jenkins.JenkinsBootstrapError("static bootstrap failed"),
    ):
        result = jenkins_charm._reconcile_bootstrap_prestart(harness_container.container, charm_state)

    assert result is False
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    assert jenkins_charm.unit.status.message == "Failed to bootstrap Jenkins static phase."


@pytest.mark.parametrize(
    (
        "sentinel_exists",
        "legacy_exists",
        "expected_bootstrapped",
        "expect_mark_backfill",
    ),
    [
        pytest.param(True, False, True, False, id="sentinel-exists"),
        pytest.param(False, True, True, True, id="legacy-artifacts-backfill"),
        pytest.param(False, False, False, False, id="no-sentinel-or-legacy"),
    ],
)
def test_jenkins_bootstrapped(
    harness_container: HarnessWithContainer,
    sentinel_exists: bool,
    legacy_exists: bool,
    expected_bootstrapped: bool,
    expect_mark_backfill: bool,
):
    """Validate bootstrap marker + legacy backfill matrix."""
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    sentinel_path = str(jenkins.JENKINS_HOME_PATH / ".charm/bootstrap-complete")
    legacy_paths = {
        str(jenkins.API_TOKEN_PATH),
        str(jenkins.LAST_EXEC_VERSION_PATH),
        str(jenkins.WIZARD_VERSION_PATH),
    }

    def exists_side_effect(path: str) -> bool:
        if path == sentinel_path:
            return sentinel_exists
        if path in legacy_paths:
            return legacy_exists
        return False

    with (
        patch.object(harness_container.container, "exists", side_effect=exists_side_effect),
        patch.object(jenkins_charm, "_mark_jenkins_bootstrapped") as mark_bootstrapped_mock,
    ):
        assert (
            jenkins_charm._jenkins_bootstrapped(harness_container.container)
            is expected_bootstrapped
        )

    if expect_mark_backfill:
        mark_bootstrapped_mock.assert_called_once_with(harness_container.container)
    else:
        mark_bootstrapped_mock.assert_not_called()


@pytest.mark.parametrize(
    "event_type",
    [
        pytest.param(
            ops.RelationJoinedEvent,
            id="joined",
        ),
        pytest.param(
            ops.RelationDepartedEvent,
            id="departed",
        ),
    ],
)
def test__auth_proxy_relation_handlers_delegate(
    harness_container: HarnessWithContainer,
    event_type: type[ops.EventBase],
):
    """
    arrange: given a started charm and a valid derived state.
    act: when an auth-proxy relation event triggers _reconcile.
    assert: reconcile executes without error (delegates internally to _reconcile_auth_proxy).
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=event_type)

    with (
        patch_reconcile_pipeline(jenkins_charm, agents_return=True),
        patch.object(jenkins_charm, "_reconcile_auth_proxy") as reconcile_auth_mock,
    ):
        jenkins_charm._reconcile(event)

    reconcile_auth_mock.assert_called_once()
