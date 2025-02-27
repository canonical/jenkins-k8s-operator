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
    "event_handler",
    [
        pytest.param("on_get_admin_password"),
        pytest.param("on_rotate_credentials"),
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
    handler_func = getattr(jenkins_charm.actions_observer, event_handler)
    mock_event = MagicMock(spec=ops.ActionEvent)
    mock_event.workload = MagicMock(spec=ops.model.Container)
    mock_event.workload.can_connect.return_value = False

    handler_func(mock_event)

    mock_event.fail.assert_called_once()


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
    jenkins_charm.actions_observer.on_get_admin_password(mock_event)

    mock_event.set_results.assert_called_once_with(
        {"password": admin_credentials.password_or_token}
    )


def test_on_rotate_credentials_action_api_error(harness_container: HarnessWithContainer):
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
    harness.charm.jenkins.rotate_credentials = MagicMock(side_effect=jenkins.JenkinsError)

    jenkins_charm.actions_observer.on_rotate_credentials(mock_event)

    mock_event.fail.assert_called_once()


def test_on_rotate_credentials_action(harness_container: HarnessWithContainer):
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
    harness.charm.jenkins.rotate_credentials = MagicMock(return_value=password)

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    jenkins_charm.actions_observer.on_rotate_credentials(mock_event)

    mock_event.set_results.assert_called_once_with({"password": password})
