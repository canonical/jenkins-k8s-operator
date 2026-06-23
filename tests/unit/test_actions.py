# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm actions unit tests."""

import secrets

# Need access to protected functions for testing
import typing
from unittest.mock import MagicMock

import ops
import pytest
from ops.testing import Harness

import jenkins
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
    monkeypatch.setattr(jenkins, "is_jenkins_ready", MagicMock(return_value=True))
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
    monkeypatch.setattr(jenkins, "is_jenkins_ready", MagicMock(return_value=True))
    monkeypatch.setattr(jenkins.Jenkins, "rotate_credentials", MagicMock(return_value=password))

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.set_results.assert_called_once_with({"password": password})


def test_on_rotate_credentials_action_jenkins_not_ready(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given Jenkins service is not ready.
    act: when rotate_credentials action is run.
    assert: the event is failed with appropriate message.
    """
    harness = harness_container.harness
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.ActionEvent)
    harness.begin()
    monkeypatch.setattr(jenkins, "is_jenkins_ready", MagicMock(return_value=False))

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins service is not yet ready.")


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
    monkeypatch.setattr(jenkins, "is_jenkins_ready", MagicMock(return_value=True))
    monkeypatch.setattr(
        jenkins,
        "get_admin_credentials",
        MagicMock(side_effect=jenkins.JenkinsBootstrapError("not bootstrapped")),
    )

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm._on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once_with("Jenkins has not yet bootstrapped.")
