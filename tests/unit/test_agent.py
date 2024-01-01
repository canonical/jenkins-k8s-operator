# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import secrets
import unittest.mock
from typing import Callable, cast

import jenkinsapi
import pytest
from ops.charm import PebbleReadyEvent

import charm
import jenkins
import state
from charm import JenkinsK8sOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME, MAINTENANCE_STATUS_NAME
from .types_ import HarnessWithContainer


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
def test__on_agent_relation_joined_no_container(
    harness_container: HarnessWithContainer, relation: str
):
    """
    arrange: given a charm with no connectable container.
    act: when agent relation joined event is fired.
    assert: the event is deferred.
    """
    harness_container.harness.set_can_connect(
        harness_container.harness.model.unit.containers["jenkins"], False
    )
    harness_container.harness.begin()
    jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_event = unittest.mock.MagicMock(spec=PebbleReadyEvent)

    if relation == state.AGENT_RELATION:
        jenkins_charm.agent_observer._on_agent_relation_joined(mock_event)
    else:
        jenkins_charm.agent_observer._on_deprecated_agent_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()
    assert jenkins_charm.unit.status.name == MAINTENANCE_STATUS_NAME


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="slave relation"),
    ],
)
def test__on_agent_relation_joined_relation_data_not_set(
    harness_container: HarnessWithContainer, relation: str
):
    """
    arrange: given a charm instance.
    act: when an agent relation joined event is fired without required data.
    assert: the event is deferred.
    """
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    harness_container.harness.charm.on[relation].relation_joined.emit(
        model_relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == MAINTENANCE_STATUS_NAME


@pytest.mark.parametrize(
    "relation_data, relation",
    [
        pytest.param(
            {
                "executors": "non-numeric",
                "labels": "x84_64",
                "slavehost": "http://sample-address:8080",
            },
            state.DEPRECATED_AGENT_RELATION,
            id="non-numeric executor(deprecated agent)",
        ),
        pytest.param(
            {
                "executors": "3.14",
                "labels": "x84_64",
                "slavehost": "http://sample-address:8080",
            },
            state.DEPRECATED_AGENT_RELATION,
            id="Non int convertible(deprecated agent)",
        ),
        pytest.param(
            {
                "executors": "non-numeric",
                "labels": "x84_64",
                "name": "http://sample-address:8080",
            },
            state.AGENT_RELATION,
            id="non-numeric executor(agent)",
        ),
        pytest.param(
            {
                "executors": "3.14",
                "labels": "x84_64",
                "name": "http://sample-address:8080",
            },
            state.AGENT_RELATION,
            id="Non int convertible(agent)",
        ),
    ],
)
def test__on_agent_relation_joined_relation_data_not_valid(
    harness_container: HarnessWithContainer, relation_data: dict[str, str], relation: str
):
    """
    arrange: given a charm instance.
    act: when a relation joined event is fired with invalid data.
    assert: the unit raises RuntimeError since corrupt data was received.
    """
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        relation_data,
    )
    with pytest.raises(RuntimeError):
        harness_container.harness.begin()


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
def test__on_agent_relation_joined_client_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a mocked patched jenkins client that raises an error.
    act: when an agent relation joined event is fired.
    assert: the unit falls to BlockedStatus.
    """
    monkeypatch.setattr(
        charm.jenkins,
        "_get_client",
        lambda *_args, **_kwargs: unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins),
    )
    monkeypatch.setattr(
        charm.jenkins,
        "add_agent_node",
        unittest.mock.MagicMock(side_effect=jenkins.JenkinsError()),
    )
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        get_relation_data(relation),
    )
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    harness_container.harness.charm.on[relation].relation_joined.emit(
        model_relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == BLOCKED_STATUS_NAME
    assert "Jenkins API exception." in jenkins_charm.unit.status.message


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
@pytest.mark.usefixtures("patch_jenkins_node")
def test__on_agent_relation_joined(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a charm instance.
    act: when an agent relation joined event is fired.
    assert: the unit becomes Active and sets required agent relation data.
    """
    monkeypatch.setattr(
        charm.jenkins,
        "_get_client",
        lambda *_args, **_kwargs: unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins),
    )
    monkeypatch.setattr(
        charm.jenkins,
        "get_node_secret",
        lambda *_args, **_kwargs: secrets.token_hex(),
    )
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        get_relation_data(relation),
    )
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    harness_container.harness.charm.on[relation].relation_joined.emit(
        model_relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
def test__on_agent_relation_departed_no_container(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    relation: str,
):
    """
    arrange: given a charm with established relation but no container.
    act: when an agent relation departed event is fired.
    assert: nothing happens since the workload doesn't exist.
    """
    mocked_remove_agent = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    monkeypatch.setattr(charm.jenkins, "remove_agent_node", mocked_remove_agent)
    harness_container.harness.set_can_connect("jenkins", False)
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    harness_container.harness.charm.on[relation].relation_departed.emit(
        model_relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    mocked_remove_agent.assert_not_called()


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
def test__on_agent_relation_departed_remove_agent_node_error(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a charm with established relation but no container.
    act: when an agent relation departed event is fired.
    assert: nothing happens since the workload doesn't exist.
    """
    monkeypatch.setattr(
        charm.jenkins,
        "remove_agent_node",
        unittest.mock.MagicMock(side_effect=jenkins.JenkinsError),
    )
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id, "jenkins-agent/0", get_relation_data(relation)
    )
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    harness_container.harness.charm.on[relation].relation_departed.emit(
        model_relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME
    assert jenkins_charm.unit.status.message == "Failed to remove jenkins-agent-0"


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
def test__on_agent_relation_departed(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a charm with established relation.
    act: when an agent relation departed event is fired.
    assert: the remove_agent_node is called and unit falls into ActiveStatus.
    """
    mocked_remove_agent = unittest.mock.MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    monkeypatch.setattr(charm.jenkins, "remove_agent_node", mocked_remove_agent)
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id, "jenkins-agent/0", get_relation_data(relation)
    )
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    harness_container.harness.charm.on[relation].relation_departed.emit(
        model_relation,
        app=harness_container.harness.model.get_app("jenkins-agent"),
        unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
    )

    jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME
    assert not jenkins_charm.unit.status.message
    mocked_remove_agent.assert_called_once()
