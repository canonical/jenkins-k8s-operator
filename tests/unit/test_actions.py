# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm actions unit tests."""

import secrets

# Need access to protected functions for testing
import typing
from unittest.mock import MagicMock, patch

import ops
import pytest
from ops.testing import Harness

import jenkins
import precondition
from charm import JenkinsK8sOperatorCharm

from .types_ import HarnessWithContainer


@pytest.mark.parametrize(
    "handler_name",
    [
        pytest.param("_on_get_admin_password"),
        pytest.param("_on_rotate_credentials"),
    ],
)
def test_workload_not_ready(harness: Harness, handler_name: str):
    """
    arrange: given a charm with no container ready.
    act: when an event hook is fired.
    assert: the charm falls into waiting status.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    handler_func = getattr(jenkins_charm, handler_name)
    mock_event = MagicMock(spec=ops.ActionEvent)
    mock_event.workload = MagicMock(spec=ops.model.Container)
    mock_event.workload.can_connect.return_value = False

    handler_func(mock_event)

    mock_event.fail.assert_called_once()


def test_on_reconcile_storage_action_uses_requested_timeout(
    harness_container: HarnessWithContainer,
):
    """The storage action passes its configurable timeout to the reconciler."""
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.ActionEvent)
    event.params = {"timeout": 900}

    charm._storage_repair_state.pending = True
    with patch.object(charm.storage, "reconcile_storage") as reconcile_storage_mock:
        charm._on_reconcile_storage(event)

    assert charm._storage_repair_state.pending is False
    reconcile_storage_mock.assert_called_once_with(
        container=harness_container.container,
        timeout=900,
    )
    event.set_results.assert_called_once_with({"timeout": 900})
    event.fail.assert_not_called()


def test_on_reconcile_storage_action_rejects_non_positive_timeout(
    harness_container: HarnessWithContainer,
):
    """The storage action rejects a timeout that cannot run the command."""
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.ActionEvent)
    event.params = {"timeout": 0}

    with patch.object(charm.storage, "reconcile_storage") as reconcile_storage_mock:
        charm._on_reconcile_storage(event)

    reconcile_storage_mock.assert_not_called()
    event.fail.assert_called_once_with("Storage timeout must be a positive integer.")
    event.set_results.assert_not_called()


def test_on_reconcile_storage_action_fails_when_storage_not_ready(
    harness_container: HarnessWithContainer,
):
    """The storage action fails when its prerequisites are unavailable."""
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.ActionEvent)

    with (
        patch(
            "precondition.check",
            return_value=precondition._CheckResult(success=False, reason="not ready"),
        ),
        patch.object(charm.storage, "reconcile_storage") as reconcile_storage_mock,
    ):
        charm._on_reconcile_storage(event)

    reconcile_storage_mock.assert_not_called()
    event.fail.assert_called_once_with("not ready")
    event.set_results.assert_not_called()


def test_on_reconcile_storage_action_fails_when_chown_times_out(
    harness_container: HarnessWithContainer,
):
    """The storage action reports a failed ownership command."""
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    event = MagicMock(spec=ops.ActionEvent)
    event.params = {"timeout": 900}
    error = ops.pebble.ChangeError(err="timed out", change=MagicMock())

    with patch.object(charm.storage, "reconcile_storage", side_effect=error):
        charm._on_reconcile_storage(event)

    assert charm._storage_repair_state.pending is True
    assert "reconcile-storage" in charm.unit.status.message
    event.fail.assert_called_once_with("Failed to reconcile Jenkins home ownership. See logs.")
    event.set_results.assert_not_called()


def test_on_get_admin_password_fails_when_storage_not_mounted(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given Jenkins storage is not yet mounted.
    act: when get-admin-password action is run.
    assert: action fails with storage-not-mounted message and state is not fetched.
    """
    harness_container.harness.begin()
    mock_event = MagicMock(spec=ops.ActionEvent)
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    monkeypatch.setattr(jenkins, "is_storage_ready", MagicMock(return_value=False))
    get_state_mock = MagicMock()
    monkeypatch.setattr(jenkins_charm, "_get_state", get_state_mock)

    jenkins_charm._on_get_admin_password(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins storage not yet mounted.")
    mock_event.set_results.assert_not_called()
    get_state_mock.assert_not_called()


def test_on_rotate_credentials_fails_when_storage_not_mounted(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given Jenkins storage is not yet mounted.
    act: when rotate-credentials action is run.
    assert: action fails with storage-not-mounted message and readiness checks are skipped.
    """
    harness_container.harness.begin()
    mock_event = MagicMock(spec=ops.ActionEvent)
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    monkeypatch.setattr(jenkins, "is_storage_ready", MagicMock(return_value=False))
    is_jenkins_ready_mock = MagicMock()
    monkeypatch.setattr(jenkins, "is_jenkins_ready", is_jenkins_ready_mock)

    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins storage not yet mounted.")
    mock_event.set_results.assert_not_called()
    is_jenkins_ready_mock.assert_not_called()


def test_on_get_admin_password_action(
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


def test_on_get_admin_password_action_fails_when_charm_state_not_ready(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given storage is ready but charm state is unavailable.
    act: when get-admin-password action is run.
    assert: action fails with not-ready message.
    """
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    monkeypatch.setattr(jenkins_charm, "_get_state", MagicMock(return_value=None))

    jenkins_charm._on_get_admin_password(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins charm is not yet ready.")
    mock_event.set_results.assert_not_called()


def test_on_get_admin_password_action_prefers_secret_from_charm_state(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given charm state already contains admin password secret.
    act: when get-admin-password action is run.
    assert: secret from state is returned without reading credentials from container.
    """
    secret_password = secrets.token_hex(16)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    monkeypatch.setattr(
        jenkins_charm,
        "_get_state",
        MagicMock(return_value=MagicMock(admin_password=secret_password)),
    )
    get_admin_credentials_mock = MagicMock()
    monkeypatch.setattr(jenkins, "get_admin_credentials", get_admin_credentials_mock)

    jenkins_charm._on_get_admin_password(mock_event)

    mock_event.set_results.assert_called_once_with({"password": secret_password})
    get_admin_credentials_mock.assert_not_called()


def test_on_rotate_credentials_action_api_error(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a mocked rotate_credentials that raises a JenkinsError.
    act: when rotate_credentials action is run.
    assert: the event is failed.
    """
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    monkeypatch.setattr(
        jenkins.Jenkins,
        "rotate_credentials",
        MagicMock(side_effect=jenkins.JenkinsError),
    )

    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once()


def test_on_rotate_credentials_action(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a mocked rotate_credentials that returns a password.
    act: when rotate_credentials action is run.
    assert: the event returns a newly generated password.
    """
    password = secrets.token_hex(16)
    harness = harness_container.harness
    harness.set_can_connect(harness_container.harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()
    monkeypatch.setattr(jenkins.Jenkins, "rotate_credentials", MagicMock(return_value=password))
    monkeypatch.setattr(jenkins.Jenkins, "wait_ready", MagicMock(return_value=None))

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.set_results.assert_called_once_with({"password": password})


def test_on_rotate_credentials_action_jenkins_not_ready(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given Jenkins service does not become ready before timeout.
    act: when rotate_credentials action is run.
    assert: the event fails with readiness timeout message.
    """
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()
    monkeypatch.setattr(jenkins.Jenkins, "wait_ready", MagicMock(side_effect=TimeoutError))

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins service is not yet ready.")


def test_on_rotate_credentials_action_fails_when_charm_state_not_ready(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given storage is ready but charm state cannot be loaded.
    act: when rotate_credentials action is run.
    assert: action fails with charm-not-ready message.
    """
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    harness.begin()
    mock_event = MagicMock(spec=ops.ActionEvent)
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    monkeypatch.setattr(jenkins_charm, "_get_state", MagicMock(return_value=None))

    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins charm is not yet ready.")


def test_on_rotate_credentials_action_fails_when_jenkins_not_bootstrapped(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given Jenkins service is up but admin credentials are unavailable.
    act: when rotate_credentials action is run.
    assert: action fails with bootstrap message.
    """
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()
    monkeypatch.setattr(
        jenkins,
        "get_admin_credentials",
        MagicMock(side_effect=jenkins.JenkinsBootstrapError("not bootstrapped")),
    )

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins has not yet bootstrapped.")


def test_on_rotate_credentials_action_prefers_secret_from_charm_state_and_updates_secret(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given charm state contains admin password and app secret exists.
    act: when rotate_credentials action is run.
    assert: state password is used for auth and rotated password is persisted to existing secret.
    """
    old_password = secrets.token_hex(16)
    new_password = secrets.token_hex(16)
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    monkeypatch.setattr(
        jenkins_charm,
        "_get_state",
        MagicMock(return_value=MagicMock(admin_password=old_password)),
    )
    get_admin_credentials_mock = MagicMock()
    monkeypatch.setattr(jenkins, "get_admin_credentials", get_admin_credentials_mock)
    monkeypatch.setattr(
        jenkins.Jenkins, "rotate_credentials", MagicMock(return_value=new_password)
    )

    mock_secret = MagicMock()
    monkeypatch.setattr(jenkins_charm.model, "get_secret", MagicMock(return_value=mock_secret))

    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.set_results.assert_called_once_with({"password": new_password})
    get_admin_credentials_mock.assert_not_called()
    mock_secret.set_content.assert_called_once_with({"password": new_password})


def test_on_rotate_credentials_action_creates_secret_when_missing(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given charm state contains admin password but app secret does not yet exist.
    act: when rotate_credentials action is run.
    assert: rotated password is written by creating app secret.
    """
    old_password = secrets.token_hex(16)
    new_password = secrets.token_hex(16)
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    monkeypatch.setattr(
        jenkins_charm,
        "_get_state",
        MagicMock(return_value=MagicMock(admin_password=old_password)),
    )
    monkeypatch.setattr(
        jenkins.Jenkins, "rotate_credentials", MagicMock(return_value=new_password)
    )
    monkeypatch.setattr(
        jenkins_charm.model,
        "get_secret",
        MagicMock(side_effect=ops.SecretNotFoundError()),
    )

    with patch.object(jenkins_charm.app, "add_secret") as add_secret_mock:
        jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.set_results.assert_called_once_with({"password": new_password})
    add_secret_mock.assert_called_once_with(
        content={"password": new_password},
        label=jenkins_charm.app.name,
    )
