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
