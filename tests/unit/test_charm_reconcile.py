# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm reconcile-focused unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import typing
from secrets import token_hex
from unittest.mock import MagicMock, patch

import ops
import pytest

import jenkins
import precondition
import state
from charm import JenkinsK8sOperatorCharm

from .helpers import BLOCKED_STATUS_NAME, WAITING_STATUS_NAME
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

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME


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


def test_calculate_env(harness: Harness):
    """
    arrange: given a charm.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    admin_password = token_hex(8)
    with patch.object(jenkins_charm, "_get_ingress_path", return_value=""):
        env = jenkins_charm.calculate_env(config_hash="hash123", admin_password=admin_password)

    assert env == {
        "JENKINS_HOME": str(jenkins.JENKINS_HOME_PATH),
        "JENKINS_PREFIX": "",
        "CASC_JENKINS_CONFIG": str(jenkins.JCASC_CONFIG_PATH),
        "JENKINS_ADMIN_PASSWORD": admin_password,
        "CONFIGURATION_HASH": "hash123",
    }


def test__on_config_changed_invalid_config_blocked(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given State.from_charm raises CharmConfigInvalidError during config-changed.
    act: when _reconcile is invoked.
    assert: unit falls into BlockedStatus and no container actions are performed.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with (
        patch("state.State.from_charm") as from_charm_mock,
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
    ):
        from_charm_mock.side_effect = state.CharmConfigInvalidError("bad sysprops")

        jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))

        assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
        assert jenkins_charm.unit.status.message == "bad sysprops"
        add_layer_mock.assert_not_called()
        replan_mock.assert_not_called()


def test__on_config_changed_relation_data_invalid_raises(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given State.from_charm raises CharmRelationDataInvalidError.
    act: when _reconcile is invoked.
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
    act: when _reconcile is invoked.
    assert: unit is in WaitingStatus and the event is deferred.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    event = MagicMock(spec=ops.ConfigChangedEvent)

    with (
        patch("precondition.check") as check_mock,
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
    ):
        check_mock.return_value = precondition._CheckResult(success=False, reason="not ready")

        jenkins_charm._reconcile(event)

        assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME
        assert jenkins_charm.unit.status.message == "not ready"
        event.defer.assert_called_once_with()
        add_layer_mock.assert_not_called()
        replan_mock.assert_not_called()


def test__on_config_changed_success_replans_and_restarts(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given precondition check passes and downstream reconcile steps are stubbed.
    act: when _reconcile is invoked.
    assert: container.add_layer and container.replan are called via pebble reconciliation.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with (
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(
            jenkins_charm, "_reconcile_pre_startup_configurations", return_value="hash123"
        ),
        patch.object(jenkins_charm, "_reconcile_admin", return_value="secret"),
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins_charm, "_reconcile_api_token"),
        patch.object(jenkins_charm, "_reconcile_agents"),
        patch.object(jenkins_charm, "_reconcile_agent_discovery"),
        patch.object(jenkins_charm, "_reconcile_auth_proxy"),
        patch.object(jenkins_charm, "_reconcile_plugins"),
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
    ):
        jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))

        add_layer_mock.assert_called_once()
        replan_mock.assert_called_once()
