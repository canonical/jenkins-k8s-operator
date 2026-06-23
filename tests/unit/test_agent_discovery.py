# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent discovery tests."""

import socket
from unittest.mock import patch

from ops import testing

from charm import JenkinsK8sOperatorCharm
from state import AGENT_DISCOVERY_INGRESS_RELATION_NAME, JENKINS_SERVICE_NAME

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
        (_state_with_juju_info_bind("invalidaddress"), f"http://{_MONKEYPATCHED_FQDN}:8080"),
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
