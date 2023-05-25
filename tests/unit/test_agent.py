# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import secrets
from typing import Callable, cast
from unittest.mock import MagicMock

import jenkinsapi
import pytest
from ops.charm import PebbleReadyEvent

import charm
import jenkins
from charm import JenkinsK8SOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME, MAINTENANCE_STATUS_NAME
from .types_ import HarnessWithContainer


def test__on_agent_relation_joined_no_ip(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a charm instance without assigned IP address.
    act: when agent relation joined event is fired.
    assert: the event is not handled.
    """
    harness_container.harness.begin()
    monkeypatch.setattr(
        harness_container.harness.charm.model, "get_binding", lambda *_args, **_kwargs: None
    )
    mock_event = MagicMock(spec=PebbleReadyEvent)

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    jenkins_charm.agent_observer._on_agent_relation_joined(mock_event)

    assert mock_event.defer.to_not_be_called()
    assert jenkins_charm.unit.status.name == MAINTENANCE_STATUS_NAME


def test__on_agent_relation_joined_no_container(harness_container: HarnessWithContainer):
    """
    arrange: given a charm with no connectable container.
    act: when agent relation joined event is fired.
    assert: the event is deferred.
    """
    harness_container.harness.set_can_connect(
        harness_container.harness.model.unit.containers["jenkins"], False
    )
    harness_container.harness.begin()
    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    mock_event = MagicMock(spec=PebbleReadyEvent)

    jenkins_charm.agent_observer._on_agent_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()
    assert jenkins_charm.unit.status.name == MAINTENANCE_STATUS_NAME


def test__on_agent_relation_joined_relation_data_not_set(harness_container: HarnessWithContainer):
    """
    arrange: given a charm instance.
    act: when an agent relation joined event is fired without required data.
    assert: the event is deferred.
    """
    harness_container.harness.begin()
    relation_id = harness_container.harness.add_relation("agent", "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")

    relation = harness_container.harness.charm.model.get_relation("agent", relation_id)
    harness_container.harness.charm.on["agent"].relation_joined.emit(relation)

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == MAINTENANCE_STATUS_NAME


@pytest.mark.parametrize(
    "relation_data",
    [
        pytest.param(
            {
                "executors": "non-numeric",
                "labels": "x84_64",
                "slavehost": "http://sample-address:8080",
            },
            id="non-numeric executor",
        ),
        pytest.param(
            {
                "executors": "3.14",
                "labels": "x84_64",
                "slavehost": "http://sample-address:8080",
            },
            id="Non int convertible",
        ),
    ],
)
def test__on_agent_relation_joined_relation_data_not_valid(
    harness_container: HarnessWithContainer, relation_data: dict[str, str]
):
    """
    arrange: given a charm instance.
    act: when an agent relation joined event is fired with invalid data.
    assert: the unit falls to BlockedStatus.
    """
    harness_container.harness.begin()
    relation_id = harness_container.harness.add_relation("agent", "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        relation_data,
    )

    relation = harness_container.harness.charm.model.get_relation("agent", relation_id)
    harness_container.harness.charm.on["agent"].relation_joined.emit(
        relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    assert jenkins_charm.unit.status.message == "Invalid agent relation data."


def test__on_agent_relation_joined_client_error(
    harness_container: HarnessWithContainer,
    raise_exception: Callable,
    monkeypatch: pytest.MonkeyPatch,
    agent_relation_data: dict[str, str],
):
    """
    arrange: given a mocked patched jenkins client that raises an error.
    act: when an agent relation joined event is fired.
    assert: the unit falls to BlockedStatus.
    """
    monkeypatch.setattr(
        charm.jenkins,
        "get_client",
        lambda *_args, **_kwargs: MagicMock(spec=jenkinsapi.jenkins.Jenkins),
    )
    monkeypatch.setattr(
        charm.jenkins,
        "add_agent_node",
        lambda *_args, **_kwargs: raise_exception(exception=jenkins.JenkinsError()),
    )
    harness_container.harness.begin()
    relation_id = harness_container.harness.add_relation("agent", "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        agent_relation_data,
    )

    relation = harness_container.harness.charm.model.get_relation("agent", relation_id)
    harness_container.harness.charm.on["agent"].relation_joined.emit(
        relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    assert "Jenkins API exception." in jenkins_charm.unit.status.message


def test__on_agent_relation_joined(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    agent_relation_data: dict[str, str],
):
    """
    arrange: given a charm instance.
    act: when an agent relation joined event is fired.
    assert: the unit becomes Active and sets required agent relation data.
    """
    monkeypatch.setattr(
        charm.jenkins,
        "get_client",
        lambda *_args, **_kwargs: MagicMock(spec=jenkinsapi.jenkins.Jenkins),
    )
    monkeypatch.setattr(
        charm.jenkins,
        "get_node_secret",
        lambda *_args, **_kwargs: secrets.token_hex(),
    )
    harness_container.harness.begin()
    # The charm code `binding.network.bind_address` for getting unit ip address will fail without
    # the add_network call.
    harness_container.harness.add_network("10.0.0.10")
    relation_id = harness_container.harness.add_relation("agent", "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        agent_relation_data,
    )

    relation = harness_container.harness.charm.model.get_relation("agent", relation_id)
    harness_container.harness.charm.on["agent"].relation_joined.emit(
        relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8SOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME
