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

import charm
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
        event.defer.assert_not_called()
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
        patch.object(jenkins_charm, "_reconcile_storage") as reconcile_storage_mock,
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            return_value="hash123",
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
        reconcile_storage_mock.assert_called_once_with(harness_container.container)


def test_reconcile_sets_blocked_status_on_reconcile_blocked_error(
    harness_container: HarnessWithContainer,
):
    """_reconcile maps ReconcileBlockedError to unit BlockedStatus message."""
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    with (
        patch.object(jenkins_charm, "_get_state", return_value=MagicMock(spec=state.State)),
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            side_effect=charm.ReconcileBlockedError("blocked by test"),
        ),
    ):
        jenkins_charm._reconcile(MagicMock(spec=ops.ConfigChangedEvent))

    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    assert jenkins_charm.unit.status.message == "blocked by test"


def test_reconcile_admin_generates_password_when_container_credentials_missing(
    harness_container: HarnessWithContainer,
):
    """_reconcile_admin generates a new password when container has no bootstrap credentials."""
    harness = harness_container.harness
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    charm_state = MagicMock(spec=state.State)
    charm_state.admin_password = None

    with (
        patch.object(
            jenkins,
            "get_admin_credentials",
            side_effect=jenkins.JenkinsBootstrapError("missing"),
        ),
        patch.object(charm.secrets, "token_hex", return_value="generated-password"),
        patch.object(jenkins_charm.app, "add_secret") as add_secret_mock,
    ):
        result = jenkins_charm._reconcile_admin(harness_container.container, charm_state)

    assert result == "generated-password"
    add_secret_mock.assert_called_once_with(
        content={"password": "generated-password"}, label=jenkins_charm.app.name
    )


def test_reconcile_api_token_returns_when_api_client_exists(
    harness_container: HarnessWithContainer,
):
    """_reconcile_api_token is a no-op when admin API client is already available."""
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    admin_client.get_admin_api_client.return_value = MagicMock()

    jenkins_charm._reconcile_api_token(admin_client)

    admin_client.generate_admin_user_token.assert_not_called()


def test_reconcile_plugins_skips_when_not_in_restart_window(
    harness_container: HarnessWithContainer,
):
    """_reconcile_plugins skips plugin cleanup when outside configured restart window."""
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    charm_state = MagicMock(spec=state.State)
    charm_state.plugins = ["kubernetes"]
    charm_state.restart_time_range = MagicMock()

    with patch.object(charm.timerange, "check_now_within_bound_hours", return_value=False):
        jenkins_charm._reconcile_plugins(charm_state, admin_client, harness_container.container)

    admin_client.remove_unlisted_plugins.assert_not_called()


def test_reconcile_admin_uses_state_admin_password_when_present(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given charm state already contains admin password.
    act: when _reconcile_admin is called.
    assert: password from state is returned and no new secret is written.
    """
    harness = harness_container.harness
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    existing_password = token_hex(8)
    charm_state = MagicMock(spec=state.State)
    charm_state.admin_password = existing_password

    with patch.object(jenkins_charm.app, "add_secret") as add_secret_mock:
        result = jenkins_charm._reconcile_admin(harness_container.container, charm_state)

    assert result == existing_password
    add_secret_mock.assert_not_called()


def test_reconcile_admin_migrates_password_from_container_to_secret(
    harness_container: HarnessWithContainer, admin_credentials: jenkins.Credentials
):
    """
    arrange: given no secret in state and credentials available in container.
    act: when _reconcile_admin is called.
    assert: container credential is returned and persisted as secret.
    """
    harness = harness_container.harness
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    charm_state = MagicMock(spec=state.State)
    charm_state.admin_password = None

    with patch.object(jenkins_charm.app, "add_secret") as add_secret_mock:
        result = jenkins_charm._reconcile_admin(harness_container.container, charm_state)

    assert result == admin_credentials.password_or_token
    add_secret_mock.assert_called_once_with(
        content={"password": admin_credentials.password_or_token},
        label=jenkins_charm.app.name,
    )


def test_reconcile_api_token_generates_token_when_api_client_missing(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given admin API client is not yet bootstrapped.
    act: when _reconcile_api_token is called.
    assert: token generation is attempted.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    admin_client.get_admin_api_client.side_effect = jenkins.JenkinsBootstrapError("missing")

    jenkins_charm._reconcile_api_token(admin_client)

    admin_client.generate_admin_user_token.assert_called_once_with()


def test_reconcile_api_token_raises_when_token_generation_fails(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given admin API client is missing and token generation fails.
    act: when _reconcile_api_token is called.
    assert: JenkinsBootstrapError is raised.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    admin_client.get_admin_api_client.side_effect = jenkins.JenkinsBootstrapError("missing")
    admin_client.generate_admin_user_token.side_effect = jenkins.JenkinsBootstrapError("failed")

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins_charm._reconcile_api_token(admin_client)


def test_reconcile_plugins_logs_timeout_error(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given remove_unlisted_plugins times out.
    act: when _reconcile_plugins is called.
    assert: timeout is swallowed and timeout-specific log path is used.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    admin_client.remove_unlisted_plugins.side_effect = TimeoutError("timed out")
    charm_state = MagicMock(spec=state.State)
    charm_state.plugins = ["kubernetes"]
    charm_state.restart_time_range = None

    with patch.object(charm.logger, "error") as error_mock:
        jenkins_charm._reconcile_plugins(charm_state, admin_client, harness_container.container)

    error_mock.assert_called_once()
    assert error_mock.call_args.args[0] == "Failed to remove plugins, %s"


def test_reconcile_pre_startup_configurations_runs_required_steps(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given successful pre-startup operations.
    act: when _reconcile_pre_startup_configurations is called.
    assert: required pre-startup hooks are invoked and JCasC hash is returned.
    """
    harness = harness_container.harness
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    charm_state = MagicMock(spec=state.State)
    charm_state.proxy_config = MagicMock()

    with (
        patch.object(
            charm.pebble, "get_jenkins_version", return_value="2.401.1"
        ) as get_version_mock,
        patch.object(jenkins, "unlock_wizard") as unlock_mock,
        patch.object(jenkins, "install_plugins") as install_plugins_mock,
        patch.object(jenkins, "install_logging_config") as install_logging_mock,
        patch.object(
            jenkins_charm, "_reconcile_jcasc_config", return_value="hash123"
        ) as reconcile_jcasc_mock,
    ):
        result = jenkins_charm._reconcile_pre_startup_configurations(
            harness_container.container, charm_state
        )

    assert result == "hash123"
    get_version_mock.assert_called_once_with(harness_container.container)
    unlock_mock.assert_called_once_with(harness_container.container, "2.401.1")
    install_plugins_mock.assert_called_once_with(
        harness_container.container,
        charm.REQUIRED_PLUGINS,
        charm_state.proxy_config,
    )
    install_logging_mock.assert_called_once_with(harness_container.container)
    reconcile_jcasc_mock.assert_called_once_with(harness_container.container, charm_state)
