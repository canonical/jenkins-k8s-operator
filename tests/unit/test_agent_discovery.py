# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent discovery tests."""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest
from ops import testing

import charm
from charm import JenkinsK8sOperatorCharm, ReconcileWaitingError
from state import (
    AGENT_DISCOVERY_INGRESS_RELATION_NAME,
    HAPROXY_ROUTE_RELATION_NAME,
    JENKINS_SERVICE_NAME,
)

_MONKEYPATCHED_FQDN = "192.0.2.0"


def _base_state() -> testing.State:
    """Create base Scenario state with a connected Jenkins container."""
    return testing.State(
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)]  # type: ignore[arg-type]
    )


def _state_with_ingress(public_url: str | None, discovery_url: str | None) -> testing.State:
    """Create Scenario state with optional ingress and agent-discovery-ingress relations."""
    relations = []
    if public_url:
        relations.append(
            testing.Relation(
                endpoint="ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{public_url}"}}'},
            )
        )
    if discovery_url:
        relations.append(
            testing.Relation(
                endpoint=AGENT_DISCOVERY_INGRESS_RELATION_NAME,
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{discovery_url}"}}'},
            )
        )

    return testing.State(
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        relations=relations,
    )


def _state_with_juju_info_bind(address: str) -> testing.State:
    """Create Scenario state with juju-info network binding address."""
    return testing.State(
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        networks={
            testing.Network(
                binding_name="juju-info",
                bind_addresses=[testing.BindAddress(addresses=[testing.Address(address)])],
            )
        },
    )


def _state_with_haproxy_endpoint(
    endpoint: str | None, hostname: str = "jenkins.example.com"
) -> testing.State:
    """Create Scenario state with a configured direct HAProxy route."""
    remote_app_data = {"endpoints": json.dumps([endpoint])} if endpoint else {}
    return testing.State(
        config={"external-hostname": hostname},
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        relations=[
            testing.Relation(
                endpoint=HAPROXY_ROUTE_RELATION_NAME,
                interface=HAPROXY_ROUTE_RELATION_NAME,
                remote_app_data=remote_app_data,
            )
        ],
    )


@patch.object(socket, "getfqdn", return_value=_MONKEYPATCHED_FQDN)
def test_agent_discovery_url_priority(_mock_fqdn):
    """Agent discovery URL prioritizes dedicated ingress, then public ingress, then network/fqdn."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    public_url = "https://public-ingress.com"
    discovery_url = "https://agent-discovery-ingress.com"

    cases = [
        (
            _state_with_ingress(public_url=public_url, discovery_url=discovery_url),
            discovery_url,
        ),
        (_state_with_ingress(public_url=public_url, discovery_url=None), public_url),
        (_state_with_juju_info_bind("192.168.0.1"), "http://192.168.0.1:8080"),
        (
            _state_with_juju_info_bind("invalidaddress"),
            f"http://{_MONKEYPATCHED_FQDN}:8080",
        ),
        (_base_state(), f"http://{_MONKEYPATCHED_FQDN}:8080"),
    ]

    for state, expected_url in cases:
        with ctx(ctx.on.config_changed(), state) as mgr:
            assert mgr.charm._agent_discovery_url == expected_url


@patch.object(socket, "getfqdn", return_value=_MONKEYPATCHED_FQDN)
def test_agent_status_message(_mock_fqdn):
    """Agent status message warns only when only public ingress is configured."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)

    both = _state_with_ingress(
        public_url="https://public-ingress.com",
        discovery_url="https://agent-discovery-ingress.com",
    )
    public_only = _state_with_ingress(public_url="https://public-ingress.com", discovery_url=None)

    with ctx(ctx.on.config_changed(), both) as mgr:
        assert mgr.charm._agent_status_message == ""

    with ctx(ctx.on.config_changed(), public_only) as mgr:
        assert (
            mgr.charm._agent_status_message
            == "Consider separating ingress for agents (agent-discovery-ingress)"
        )


@patch.object(socket, "getfqdn", return_value=_MONKEYPATCHED_FQDN)
def test_reconcile_agent_discovery_updates_relation(_mock_fqdn):
    """_reconcile_agent_discovery writes discovery URL into agent relation unit data."""
    state = testing.State(
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        relations=[
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
            )
        ],
    )

    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        mgr.charm._reconcile_agent_discovery()
        agent_rel = mgr.charm.model.relations["agent"][0]
        assert "url" in agent_rel.data[mgr.charm.unit]


@patch.object(socket, "getfqdn", return_value=_MONKEYPATCHED_FQDN)
def test_agent_discovery_url_public_ingress_logs_warning(_mock_fqdn):
    """_agent_discovery_url warns when falling back to public ingress URL."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_ingress(public_url="https://public-ingress.com", discovery_url=None)

    with (
        patch.object(charm.logger, "warning") as warning_mock,
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        assert mgr.charm._agent_discovery_url == "https://public-ingress.com"

    warning_mock.assert_called_once()


@patch.object(socket, "getfqdn", return_value=_MONKEYPATCHED_FQDN)
def test_reconcile_agent_discovery_skips_when_url_already_matches(_mock_fqdn):
    """_reconcile_agent_discovery leaves existing matching relation URL unchanged."""
    discovery_url = "https://agent-discovery-ingress.com"
    state = testing.State(
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        relations=[
            testing.Relation(
                endpoint=AGENT_DISCOVERY_INGRESS_RELATION_NAME,
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{discovery_url}"}}'},
            ),
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
                local_unit_data={"url": discovery_url},
            ),
        ],
    )

    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        agent_rel = mgr.charm.model.relations["agent"][0]
        before = dict(agent_rel.data[mgr.charm.unit])
        mgr.charm._reconcile_agent_discovery()
        after = dict(agent_rel.data[mgr.charm.unit])

    assert before == after


def test_agent_discovery_url_uses_haproxy_provider_endpoint():
    """Direct HAProxy endpoint takes precedence over the pod-address fallback."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_haproxy_endpoint("https://jenkins.example.com/")

    with ctx(ctx.on.config_changed(), state) as mgr:
        assert mgr.charm._agent_discovery_url == "https://jenkins.example.com"


def test_agent_discovery_url_prefers_haproxy_over_ingress():
    """A configured HAProxy endpoint takes precedence over server ingress."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    base = _state_with_haproxy_endpoint("https://jenkins.example.com/")
    state = testing.State(
        config=base.config,
        containers=base.containers,
        relations=[
            testing.Relation(
                endpoint="ingress",
                interface="ingress",
                remote_app_data={"ingress": '{"url":"https://traefik.example.com"}'},
            ),
            *base.relations,
        ],
    )

    with ctx(ctx.on.config_changed(), state) as mgr:
        assert mgr.charm._agent_discovery_url == "https://jenkins.example.com"


def test_agent_discovery_url_uses_agent_haproxy_hostname():
    """Agent discovery selects the additional unprotected HAProxy hostname."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = testing.State(
        config={
            "external-hostname": "jenkins.example.com",
            "agent-external-hostname": "jenkins-agent.example.com",
        },
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
        relations=[
            testing.Relation(
                endpoint=HAPROXY_ROUTE_RELATION_NAME,
                interface=HAPROXY_ROUTE_RELATION_NAME,
                remote_app_data={
                    "endpoints": json.dumps(
                        [
                            "https://jenkins.example.com/",
                            "https://jenkins-agent.example.com/",
                        ]
                    )
                },
            )
        ],
    )

    with ctx(ctx.on.config_changed(), state) as mgr:
        assert mgr.charm._agent_discovery_url == "https://jenkins-agent.example.com"


def test_agent_discovery_url_waits_for_haproxy_provider_endpoint():
    """Direct mode must not publish a pod address before HAProxy is ready."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_haproxy_endpoint(None)

    with (
        ctx(ctx.on.config_changed(), state) as mgr,
        pytest.raises(ReconcileWaitingError, match="HAProxy"),
    ):
        _ = mgr.charm._agent_discovery_url


def test_agent_discovery_url_waits_for_haproxy_relation():
    """A configured external hostname must not fall back without its route relation."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = testing.State(
        config={"external-hostname": "jenkins.example.com"},
        containers=[testing.Container(name=JENKINS_SERVICE_NAME, can_connect=True)],  # type: ignore[arg-type]
    )

    with (
        ctx(ctx.on.config_changed(), state) as mgr,
        pytest.raises(ReconcileWaitingError, match="route relation"),
    ):
        _ = mgr.charm._agent_discovery_url


def test_agent_discovery_url_waits_when_haproxy_hostname_is_not_configured():
    """A stale provider endpoint is ignored when direct mode is unconfigured."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_haproxy_endpoint("https://jenkins.example.com/", hostname="")

    with (
        ctx(ctx.on.config_changed(), state) as mgr,
        pytest.raises(ReconcileWaitingError, match="external-hostname"),
    ):
        _ = mgr.charm._agent_discovery_url


def test_reconcile_agent_discovery_publishes_haproxy_endpoint():
    """Agent relation data uses the HAProxy provider endpoint in direct mode."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    direct_state = _state_with_haproxy_endpoint("https://jenkins.example.com/")
    direct_state = testing.State(
        config=direct_state.config,
        containers=direct_state.containers,
        relations=[
            *direct_state.relations,
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
            ),
        ],
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), direct_state) as mgr,
    ):
        mgr.charm._reconcile_agent_discovery()
        agent_relation = mgr.charm.model.relations["agent"][0]
        assert agent_relation.data[mgr.charm.unit]["url"] == "https://jenkins.example.com"


def test_reconcile_waits_for_haproxy_before_agent_url_publication():
    """Agents are held until direct HAProxy has published its endpoint."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    base = _state_with_haproxy_endpoint(None)
    state = testing.State(
        config=base.config,
        containers=base.containers,
        storages=[testing.Storage(name="jenkins-home")],
        relations=[
            *base.relations,
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
            ),
        ],
    )

    with ctx(ctx.on.config_changed(), state) as mgr:
        mgr.charm._reconcile(MagicMock())
        assert mgr.charm.unit.status.name == "waiting"
        assert (
            mgr.charm.unit.status.message
            == "Waiting for HAProxy to publish the Jenkins endpoint for agents."
        )
        agent_relation = mgr.charm.model.relations["agent"][0]
        assert "url" not in agent_relation.data[mgr.charm.unit]
