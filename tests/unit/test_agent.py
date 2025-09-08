# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import ipaddress
import json
import secrets
import socket
from typing import Callable, cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops import Model, Network
from ops.charm import PebbleReadyEvent

import jenkins
import state
from charm import JenkinsK8sOperatorCharm

from .helpers import ACTIVE_STATUS_NAME, BLOCKED_STATUS_NAME, MAINTENANCE_STATUS_NAME
from .types_ import Harness, HarnessWithContainer


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
    mock_event = MagicMock(spec=PebbleReadyEvent)

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
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a mocked patched jenkins client that raises an error.
    act: when an agent relation joined event is fired.
    assert: the unit falls to BlockedStatus.
    """
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        get_relation_data(relation),
    )
    harness_container.harness.begin()

    model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
    with (
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "add_agent_node") as add_agent_node_mock,
    ):
        add_agent_node_mock.side_effect = jenkins.JenkinsError()

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
def test__on_agent_relation_joined(
    harness_container: HarnessWithContainer,
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a charm instance.
    act: when an agent relation joined event is fired.
    assert: the unit becomes Active and sets required agent relation data.
    """
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id,
        "jenkins-agent/0",
        get_relation_data(relation),
    )
    with (
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "add_agent_node"),
        patch.object(jenkins.Jenkins, "get_node_secret") as get_node_secret_mock,
    ):
        get_node_secret_mock.return_value = secrets.token_hex()
        harness_container.harness.begin()
        jenkins_charm = cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

        model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
        harness_container.harness.charm.on[relation].relation_joined.emit(
            model_relation,
            app=harness_container.harness.model.get_app("jenkins-agent"),
            unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
        )

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
    relation: str,
):
    """
    arrange: given a charm with established relation but no container.
    act: when an agent relation departed event is fired.
    assert: nothing happens since the workload doesn't exist.
    """
    harness_container.harness.begin()
    harness_container.harness.set_can_connect("jenkins", False)
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")

    with patch.object(jenkins.Jenkins, "remove_agent_node") as remove_agent_node_mock:

        model_relation = harness_container.harness.charm.model.get_relation(relation, relation_id)
        harness_container.harness.charm.on[relation].relation_departed.emit(
            model_relation,
            app=harness_container.harness.model.get_app("jenkins-agent"),
            unit=harness_container.harness.model.get_unit("jenkins-agent/0"),
        )

        remove_agent_node_mock.assert_not_called()


@pytest.mark.parametrize(
    "relation",
    [
        pytest.param(state.AGENT_RELATION, id="agent relation"),
        pytest.param(state.DEPRECATED_AGENT_RELATION, id="deprecated agent relation"),
    ],
)
def test__on_agent_relation_departed_remove_agent_node_error(
    harness_container: HarnessWithContainer,
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a charm with established relation but no container.
    act: when an agent relation departed event is fired.
    assert: nothing happens since the workload doesn't exist.
    """
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id, "jenkins-agent/0", get_relation_data(relation)
    )
    with patch.object(jenkins.Jenkins, "remove_agent_node") as remove_agent_node_mock:
        remove_agent_node_mock.side_effect = jenkins.JenkinsError()
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
    get_relation_data: Callable[[str], dict[str, str]],
    relation: str,
):
    """
    arrange: given a charm with established relation.
    act: when an agent relation departed event is fired.
    assert: the remove_agent_node is called and unit falls into ActiveStatus.
    """
    relation_id = harness_container.harness.add_relation(relation, "jenkins-agent")
    harness_container.harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness_container.harness.update_relation_data(
        relation_id, "jenkins-agent/0", get_relation_data(relation)
    )
    with patch.object(jenkins.Jenkins, "remove_agent_node") as remove_agent_node_mock:
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
        remove_agent_node_mock.assert_called_once()


def test_agent_discovery_url_with_ingress(harness: Harness):
    """
    arrange: given a base jenkins charm with ingress integration.
    act: start the charm and add an ingress integration with traefik.
    assert: charm.agent_observer.agent_discovery_url is the value
    from the ingress integration databag.
    """
    harness.begin()

    mock_ingress_url = "http://ingress.test"
    harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": mock_ingress_url})},
    )

    assert harness.charm.agent_observer.agent_discovery_url == mock_ingress_url


def test_agent_discovery_url_with_server_ingress(harness: Harness):
    """
    arrange: given a base jenkins charm with server ingress integration.
    act: start the charm and add an server ingress integration with traefik.
    assert: charm.agent_observer.agent_discovery_url is the value
    from the ingress integration databag.
    """
    harness.begin()

    mock_ingress_url = "http://ingress.test"
    harness.add_relation(
        "ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": mock_ingress_url})},
    )

    assert harness.charm.agent_observer.agent_discovery_url == mock_ingress_url
    assert "Consider separating ingress for agents" in harness.charm.agent_observer._status_message


def test_agent_discovery_url_fqdn_fallback(harness: Harness, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a base jenkins charm with no ingress and an invalid ip.
    act: access the charm's agent_discovery_url property.
    assert: the charm returns the value from socket.get_fqdn().
    """
    harness.begin()
    mock_fqdn = "test"
    monkeypatch.setattr(socket, "getfqdn", MagicMock(return_value=mock_fqdn))
    monkeypatch.setattr(ipaddress, "ip_address", MagicMock(side_effect=ValueError))

    assert (
        harness.charm.agent_observer.agent_discovery_url
        == f"http://{mock_fqdn}:{jenkins.WEB_PORT}"
    )


def test_agent_discovery_url_model_error_null_binding(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a base jenkins charm and mocked ingress requirer to return None.
    act: start the charm and add an ingress integration with traefik.
    assert: charm.agent_observer.agent_discovery_url is the value from socket.get_fqdn().
    """
    mock_fqdn = "test"
    monkeypatch.setattr(IngressPerAppRequirer, "url", PropertyMock(return_value=None))
    monkeypatch.setattr(Model, "get_binding", MagicMock(return_value=None))
    monkeypatch.setattr(socket, "getfqdn", MagicMock(return_value=mock_fqdn))

    harness.begin()
    harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": "http://ingress.test"})},
    )

    assert (
        harness.charm.agent_observer.agent_discovery_url
        == f"http://{mock_fqdn}:{jenkins.WEB_PORT}"
    )


def test_agent_discovery_url_with_ingress_ip_validation_error(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a base jenkins charm and mocked ingress requirer to return None.
    act: start the charm and add an ingress integration with traefik.
    assert: charm.agent_observer.agent_discovery_url is the value from socket.get_fqdn().
    """
    monkeypatch.setattr(IngressPerAppRequirer, "url", PropertyMock(return_value=None))
    monkeypatch.setattr(ipaddress, "ip_address", MagicMock(side_effect=ValueError))
    mock_fqdn = "test"
    monkeypatch.setattr(socket, "getfqdn", MagicMock(return_value=mock_fqdn))

    harness.begin()
    harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": "http://ingress.test"})},
    )

    assert (
        harness.charm.agent_observer.agent_discovery_url
        == f"http://{mock_fqdn}:{jenkins.WEB_PORT}"
    )


def test_agent_discovery_url_pod_ip(harness: Harness, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a base jenkins charm and mocked ingress requirer to return None.
    act: start the charm and add an ingress integration with traefik.
    assert: charm.agent_observer.agent_discovery_url is the value from socket.get_fqdn().
    """
    mock_pod_ip = "10.10.10.10"
    monkeypatch.setattr(IngressPerAppRequirer, "url", PropertyMock(return_value=None))
    monkeypatch.setattr(Network, "bind_address", PropertyMock(return_value=mock_pod_ip))

    harness.begin()
    harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": "http://ingress.test"})},
    )

    assert (
        harness.charm.agent_observer.agent_discovery_url
        == f"http://{mock_pod_ip}:{jenkins.WEB_PORT}"
    )


def test_reconfigure_agent_discovery_url(
    harness: Harness,
    get_relation_data: Callable[[str], dict[str, str]],
):
    """
    arrange: given a base jenkins charm integrated with the jenkins-agent charm.
    act: add an integration with traefik.
    assert: the discovery url in the integration databag is changed to the ingress url.
    """
    relation_id = harness.add_relation(state.AGENT_RELATION, "jenkins-agent")
    harness.add_relation_unit(relation_id, "jenkins-agent/0")
    harness.update_relation_data(
        relation_id, "jenkins-agent/0", get_relation_data(state.AGENT_RELATION)
    )
    harness.begin()

    mock_ingress_url = "http://ingress.test"
    harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": mock_ingress_url})},
    )

    assert (
        harness.get_relation_data(relation_id, harness.model.unit.name)["url"] == mock_ingress_url
    )


def test_reconfigure_agent_discovery_url_ingress_revoked(
    harness: Harness,
    get_relation_data: Callable[[str], dict[str, str]],
):
    """
    arrange: given a base jenkins charm integrated with the jenkins-agent charm with ingress.
    act: remove the traefik integration.
    assert: the discovery url in the integration databag is different from the ingress url.
    """
    mock_ingress_url = "http://ingress.test"
    ingress_relation_id = harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": mock_ingress_url})},
    )
    relation_id = harness.add_relation(
        state.AGENT_RELATION, "jenkins-agent", unit_data=get_relation_data(state.AGENT_RELATION)
    )
    harness.begin()

    harness.remove_relation(ingress_relation_id)
    assert (
        harness.get_relation_data(relation_id, harness.model.unit.name)["url"] != mock_ingress_url
    )


def test_reconfigure_agent_discovery_url_unchanged(
    harness: Harness,
    get_relation_data: Callable[[str], dict[str, str]],
):
    """
    arrange: given a base jenkins charm integrated with the jenkins-agent charm.
    The integration databag contains an agent discovery url.
    act: add an integration with traefik providing the same url.
    assert: the discovery url in the integration databag is not changed.
    """
    mock_ingress_url = "http://ingress.test"
    relation_id = harness.add_relation(
        state.AGENT_RELATION, "jenkins-agent", unit_data=get_relation_data(state.AGENT_RELATION)
    )
    harness.update_relation_data(relation_id, harness.model.unit.name, {"url": mock_ingress_url})
    harness.begin()
    harness.add_relation(
        "agent-discovery-ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": mock_ingress_url})},
    )

    assert (
        harness.get_relation_data(relation_id, harness.model.unit.name)["url"] == mock_ingress_url
    )
