# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm event-routing unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import typing
from unittest.mock import MagicMock, patch

import ops
import pytest

from charm import JenkinsK8sOperatorCharm

from .helpers import WAITING_STATUS_NAME
from .types_ import Harness, HarnessWithContainer


@pytest.mark.parametrize(
    "event_spec",
    [
        pytest.param(ops.StorageAttachedEvent, id="storage-attached"),
        pytest.param(ops.PebbleReadyEvent, id="pebble-ready"),
        pytest.param(ops.UpdateStatusEvent, id="update-status"),
    ],
)
def test_workload_not_ready(harness: Harness, event_spec: type):
    """
    arrange: given a charm with storage attached but no container connectivity.
    act: when _reconcile is triggered by an event.
    assert: the charm falls into waiting status.
    """
    harness.add_storage("jenkins-home", count=1, attach=True)
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    jenkins_charm._reconcile(MagicMock(spec=event_spec))

    assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME


@pytest.mark.parametrize(
    "event_spec",
    [
        pytest.param(ops.StorageAttachedEvent, id="storage-attached"),
        pytest.param(ops.PebbleReadyEvent, id="pebble-ready"),
        pytest.param(ops.UpdateStatusEvent, id="update-status"),
    ],
)
def test_storage_not_ready(harness: Harness, event_spec: type):
    """
    arrange: given a charm with container connectivity but no storage attached.
    act: when _reconcile is triggered by an event.
    assert: the charm falls into waiting status.
    """
    harness.begin()
    container = harness.model.unit.get_container("jenkins")
    harness.set_can_connect(container, True)
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    jenkins_charm._reconcile(MagicMock(spec=event_spec))

    assert jenkins_charm.unit.status.name == WAITING_STATUS_NAME


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
    arrange: given a started charm and downstream reconcile steps stubbed.
    act: when an agent relation event triggers _reconcile.
    assert: _reconcile_agents is called.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    with (
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            return_value="hash123",
        ),
        patch.object(jenkins_charm, "_reconcile_admin", return_value="secret"),
        patch("jenkins.Jenkins.wait_ready"),
        patch.object(jenkins_charm, "_reconcile_api_token"),
        patch.object(jenkins_charm, "_reconcile_agents") as reconcile_agents_mock,
        patch.object(jenkins_charm, "_reconcile_agent_discovery"),
        patch.object(jenkins_charm, "_reconcile_auth_proxy"),
        patch.object(jenkins_charm, "_reconcile_plugins"),
    ):
        jenkins_charm._reconcile(MagicMock(spec=event_type))

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
    arrange: given a started charm and downstream reconcile steps stubbed.
    act: when an ingress event triggers _reconcile.
    assert: _reconcile_agent_discovery is called.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    with (
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            return_value="hash123",
        ),
        patch.object(jenkins_charm, "_reconcile_admin", return_value="secret"),
        patch("jenkins.Jenkins.wait_ready"),
        patch.object(jenkins_charm, "_reconcile_api_token"),
        patch.object(jenkins_charm, "_reconcile_agents"),
        patch.object(jenkins_charm, "_reconcile_agent_discovery") as reconcile_discovery_mock,
        patch.object(jenkins_charm, "_reconcile_auth_proxy"),
        patch.object(jenkins_charm, "_reconcile_plugins"),
    ):
        jenkins_charm._reconcile(MagicMock(spec=event_spec))

    reconcile_discovery_mock.assert_called_once()


def test__upgrade_charm_reconciles_storage_and_agents(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given a started charm and downstream reconcile steps stubbed.
    act: when the upgrade-charm event triggers _reconcile.
    assert: _reconcile_storage is called.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    with (
        patch.object(jenkins_charm, "_reconcile_storage") as reconcile_storage_mock,
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            return_value="hash123",
        ),
        patch.object(jenkins_charm, "_reconcile_admin", return_value="secret"),
        patch("jenkins.Jenkins.wait_ready"),
        patch.object(jenkins_charm, "_reconcile_api_token"),
        patch.object(jenkins_charm, "_reconcile_agents"),
        patch.object(jenkins_charm, "_reconcile_agent_discovery"),
        patch.object(jenkins_charm, "_reconcile_auth_proxy"),
        patch.object(jenkins_charm, "_reconcile_plugins"),
    ):
        jenkins_charm._reconcile(MagicMock(spec=ops.UpgradeCharmEvent))

    reconcile_storage_mock.assert_called_once()


@pytest.mark.parametrize(
    "event_type",
    [
        pytest.param(ops.RelationJoinedEvent, id="joined"),
        pytest.param(ops.RelationDepartedEvent, id="departed"),
    ],
)
def test__auth_proxy_relation_handlers_delegate(
    harness_container: HarnessWithContainer,
    event_type: type[ops.EventBase],
):
    """
    arrange: given a started charm and downstream reconcile steps stubbed.
    act: when an auth-proxy relation event triggers _reconcile.
    assert: _reconcile_auth_proxy is called.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    with (
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            return_value="hash123",
        ),
        patch.object(jenkins_charm, "_reconcile_admin", return_value="secret"),
        patch("jenkins.Jenkins.wait_ready"),
        patch.object(jenkins_charm, "_reconcile_api_token"),
        patch.object(jenkins_charm, "_reconcile_agents"),
        patch.object(jenkins_charm, "_reconcile_agent_discovery"),
        patch.object(jenkins_charm, "_reconcile_auth_proxy") as reconcile_auth_proxy_mock,
        patch.object(jenkins_charm, "_reconcile_plugins"),
    ):
        jenkins_charm._reconcile(MagicMock(spec=event_type))

    reconcile_auth_proxy_mock.assert_called_once()


def test_secret_changed_observer_registered(harness: Harness):
    """
    arrange: given a charm being initialized.
    act: when the charm is set up.
    assert: the secret_changed event observer targets _reconcile directly.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    observers = typing.cast(list[tuple[str, str, str, str]], jenkins_charm.framework._observers)

    assert any(
        method_name == "_reconcile" and event_kind == "secret_changed"
        for _, method_name, _, event_kind in observers
    )
    assert not hasattr(jenkins_charm, "_on_secret_changed")


def test_jcasc_environment_secrets_injected_during_reconcile(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given a charm with jcasc-environment-secrets configured.
    act: when _reconcile is triggered.
    assert: the environment secrets are injected into jenkins_environment.
    """
    secret_id = "secret:jcasc1234"  # nosec (test fixture, not real secret)
    harness_container.harness.update_config({"jcasc-environment-secrets": secret_id})
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    # Mock the secret retrieval to return test environment variables
    def mock_get_secret(**kwargs):
        mock_secret = MagicMock()
        mock_secret.get_content.return_value = {"VAR1": "value1", "VAR2": "value2"}
        return mock_secret

    # Capture the jenkins_environment dict passed to _reconcile_pebble
    captured_env = {}

    def capture_reconcile_pebble(container, state, jenkins_environment):
        captured_env.update(jenkins_environment)

    with (
        patch.object(jenkins_charm, "_reconcile_storage"),
        patch.object(
            jenkins_charm,
            "_reconcile_pre_startup_configurations",
            return_value="hash123",
        ),
        patch.object(jenkins_charm, "_reconcile_admin", return_value="secret"),
        patch("jenkins.Jenkins.wait_ready"),
        patch.object(jenkins_charm, "_reconcile_api_token"),
        patch.object(jenkins_charm, "_reconcile_agents"),
        patch.object(jenkins_charm, "_reconcile_agent_discovery"),
        patch.object(jenkins_charm, "_reconcile_auth_proxy"),
        patch.object(jenkins_charm, "_reconcile_plugins"),
        patch.object(
            jenkins_charm.model,
            "get_secret",
            side_effect=mock_get_secret,
        ),
        patch.object(
            jenkins_charm,
            "_reconcile_pebble",
            side_effect=capture_reconcile_pebble,
        ),
    ):
        jenkins_charm._reconcile(MagicMock(spec=ops.UpdateStatusEvent))

    # Verify the injected secrets are present in jenkins_environment
    assert captured_env.get("VAR1") == "value1"
    assert captured_env.get("VAR2") == "value2"
