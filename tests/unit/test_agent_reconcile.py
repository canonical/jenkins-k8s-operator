# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent reconcile tests."""

import inspect
import secrets
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ops
import pytest
from ops import testing

import jenkins
from charm import JenkinsK8sOperatorCharm
from state import AgentMeta, State


def _agent_relation(remote_units_data: dict[int, dict[str, str]]) -> testing.Relation:
    """Build an agent relation for Scenario state."""
    return testing.Relation(
        endpoint="agent",
        interface="jenkins_agent_v0",
        remote_units_data=remote_units_data,
    )


def _state_with_agents(agent_names: list[str]) -> testing.State:
    """Create Scenario state with connected Jenkins container and agent relation."""
    remote_units_data = {
        idx: {"executors": "1", "labels": "testing", "name": name}
        for idx, name in enumerate(agent_names)
    }
    return testing.State(
        containers=[testing.Container("jenkins", can_connect=True)],  # type: ignore[arg-type]
        storages={testing.Storage("jenkins-home")},
        relations=[_agent_relation(remote_units_data)],
    )


class FakeJenkinsService:
    """In-memory fake Jenkins client for agent reconcile tests."""

    def __init__(self, initial_agents: list[str]) -> None:
        self.agents_secret_map: dict[str, str] = {
            agent: secrets.token_hex(16) for agent in initial_agents
        }

    def add_agent_node(self, agent_meta: AgentMeta) -> None:
        self.agents_secret_map[agent_meta.name] = secrets.token_hex(16)

    def get_node_secret(self, node_name: str) -> str | None:
        return self.agents_secret_map.get(node_name)

    def remove_agent_node(self, agent_name: str) -> None:
        self.agents_secret_map.pop(agent_name)

    def list_agent_nodes(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in self.agents_secret_map]


@pytest.mark.parametrize(
    "initial_agents, relation_agent_names, expected_agents",
    [
        pytest.param([], [], [], id="no relation agents"),
        pytest.param([], ["0"], ["0"], id="one relation agent"),
        pytest.param([], ["0", "1"], ["0", "1"], id="two relation agents"),
        pytest.param(["0"], ["0"], ["0"], id="already registered"),
        pytest.param(["3", "4"], ["0", "1"], ["0", "1"], id="replace stale agents"),
    ],
)
def test_reconcile_agents(
    initial_agents: list[str],
    relation_agent_names: list[str],
    expected_agents: list[str],
):
    """_reconcile_agents converges Jenkins nodes to relation state and writes relation data."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(relation_agent_names)

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        fake_client = FakeJenkinsService(initial_agents=initial_agents)
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None

        mgr.charm._reconcile_agents(state=charm_state, client=fake_client)  # type: ignore[arg-type]

        agent_rel = mgr.charm.model.relations["agent"][0]
        rel_data = dict(agent_rel.data[mgr.charm.unit])

    all_agent_names = [node.name for node in fake_client.list_agent_nodes()]
    assert sorted(all_agent_names) == sorted(expected_agents)

    if expected_agents:
        assert "url" in rel_data
        for agent_name in expected_agents:
            assert f"{agent_name}_secret" in rel_data


@pytest.mark.parametrize(
    "error_stage",
    [
        pytest.param("add", id="add_agent_node error"),
        pytest.param("secret", id="get_node_secret error"),
        pytest.param("remove", id="remove_node error"),
    ],
)
def test_reconcile_agents_error(error_stage: str):
    """_reconcile_agents propagates JenkinsError from add/secret/remove stages."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["0", "1"])

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        mock_client = MagicMock(spec=jenkins.Jenkins)
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None

        if error_stage == "add":
            mock_client.list_agent_nodes.return_value = []
            mock_client.add_agent_node.side_effect = jenkins.JenkinsError()
        elif error_stage == "secret":
            mock_client.list_agent_nodes.return_value = []
            mock_client.get_node_secret.side_effect = jenkins.JenkinsError()
        else:
            stale_node = MagicMock()
            stale_node.name = "stale-agent"
            mock_client.list_agent_nodes.return_value = [stale_node]
            mock_client.get_node_secret.return_value = "dummy-secret"
            mock_client.remove_agent_node.side_effect = jenkins.JenkinsError()

        with pytest.raises(jenkins.JenkinsError):
            mgr.charm._reconcile_agents(state=charm_state, client=mock_client)


def test_reconcile_agents_accepts_state_parameter():
    """_reconcile_agents must accept state and client parameters (no event arg)."""
    sig = inspect.signature(JenkinsK8sOperatorCharm._reconcile_agents)
    assert "state" in sig.parameters
    assert "client" in sig.parameters
    assert "event" not in sig.parameters


def test_reconcile_agents_sets_maintenance_status():
    """_reconcile_agents sets maintenance status when processing relation agents."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), _state_with_agents(["0"])) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        mgr.charm._reconcile_agents(
            state=charm_state, client=FakeJenkinsService(initial_agents=[])
        )  # type: ignore[arg-type]
        assert isinstance(mgr.charm.unit.status, ops.MaintenanceStatus)
