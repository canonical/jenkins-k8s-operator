# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Backwards-compatibility tests for mixed legacy/direct server topologies.

Legacy Traefik ingress (with or without oauth2-proxy via auth-proxy) must keep
working while the direct HAProxy server route is introduced, and the server
ingress and agent-discovery ingress must be independently providable.
"""

from unittest.mock import MagicMock

from ops import testing

import state
from charm import JenkinsK8sOperatorCharm
from state import (
    AGENT_DISCOVERY_INGRESS_RELATION_NAME,
    AGENT_RELATION,
    AUTH_PROXY_RELATION,
    HAPROXY_ROUTE_RELATION_NAME,
    INGRESS_RELATION_NAME,
    JENKINS_SERVICE_NAME,
)


def _relations_mock(mapping):
    """Return a get_relation replacement serving the given relation mapping."""
    return lambda relation_name: mapping.get(relation_name)


def test_legacy_traefik_topology_remains_valid(mock_charm: MagicMock, monkeypatch):
    """agent-discovery-ingress + server ingress without haproxy stays valid."""
    monkeypatch.setattr(
        mock_charm.model,
        "get_relation",
        _relations_mock(
            {
                AGENT_DISCOVERY_INGRESS_RELATION_NAME: MagicMock(),
                INGRESS_RELATION_NAME: MagicMock(),
            }
        ),
    )
    mock_charm.model.relations = {AGENT_RELATION: []}
    mock_charm.config = {}

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.external_hostname is None


def test_auth_proxy_traefik_and_haproxy_coexist(mock_charm: MagicMock, monkeypatch):
    """Rollback topology: auth-proxy + traefik ingress + haproxy-route all related."""
    monkeypatch.setattr(
        mock_charm.model,
        "get_relation",
        _relations_mock(
            {
                AGENT_DISCOVERY_INGRESS_RELATION_NAME: MagicMock(),
                INGRESS_RELATION_NAME: MagicMock(),
                HAPROXY_ROUTE_RELATION_NAME: MagicMock(),
                AUTH_PROXY_RELATION: MagicMock(),
            }
        ),
    )
    mock_charm.model.relations = {AGENT_RELATION: []}
    mock_charm.config = {"external-hostname": "jenkins.example.com"}

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.auth_proxy_integrated is True
    assert charm_state.external_hostname == "jenkins.example.com"


def test_server_ingress_alone_is_valid(mock_charm: MagicMock, monkeypatch):
    """A server ingress without agent-discovery-ingress stays valid (server-only)."""
    monkeypatch.setattr(
        mock_charm.model, "get_relation", _relations_mock({INGRESS_RELATION_NAME: MagicMock()})
    )
    mock_charm.model.relations = {AGENT_RELATION: []}
    mock_charm.config = {}

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state is not None


def test_haproxy_route_alone_is_valid(mock_charm: MagicMock, monkeypatch):
    """A direct HAProxy server route without any traefik ingress is valid."""
    monkeypatch.setattr(
        mock_charm.model,
        "get_relation",
        _relations_mock({HAPROXY_ROUTE_RELATION_NAME: MagicMock()}),
    )
    mock_charm.model.relations = {AGENT_RELATION: []}
    mock_charm.config = {"external-hostname": "jenkins.example.com"}

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.external_hostname == "jenkins.example.com"


def test_traefik_prefix_and_dedicated_agent_url_coexist_with_haproxy():
    """With all routes related, traefik drives the prefix and agents keep their own URL."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    legacy_url = "https://legacy.example.com/jenkins"
    agent_url = "https://agents.example.com"
    scenario_state = testing.State(
        config={"external-hostname": "jenkins.example.com"},
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        relations=[
            testing.Relation(
                endpoint=INGRESS_RELATION_NAME,
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{legacy_url}"}}'},
            ),
            testing.Relation(
                endpoint=AGENT_DISCOVERY_INGRESS_RELATION_NAME,
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{agent_url}"}}'},
            ),
            testing.Relation(endpoint=HAPROXY_ROUTE_RELATION_NAME, interface="haproxy-route"),
            testing.Relation(
                endpoint=AGENT_RELATION,
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
            ),
        ],
    )

    with ctx(ctx.on.config_changed(), scenario_state) as mgr:
        # The workload prefix still comes from the traefik server ingress only.
        assert mgr.charm._get_ingress_path() == "/jenkins"
        # Agents get the dedicated ingress URL, not the haproxy or traefik one.
        assert mgr.charm._agent_discovery_url == agent_url
        # No nag message: the dedicated agent ingress is present.
        assert mgr.charm._agent_status_message == ""
