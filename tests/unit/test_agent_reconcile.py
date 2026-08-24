# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent reconcile tests."""

import inspect
import secrets
import typing
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ops
import pytest
from ops import testing

import charm
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


def _state_with_agents(
    agent_names: list[str],
    remote_fs: dict[str, str] | None = None,
    config: dict[str, str] | None = None,
) -> testing.State:
    """Create Scenario state with connected Jenkins container and agent relation."""
    remote_fs = remote_fs or {}
    remote_units_data = {
        idx: {
            "executors": "1",
            "labels": "testing",
            "name": name,
            **({"remote_fs": remote_fs[name]} if name in remote_fs else {}),
        }
        for idx, name in enumerate(agent_names)
    }
    return testing.State(
        containers=[testing.Container("jenkins", can_connect=True)],  # type: ignore[arg-type]
        storages={testing.Storage("jenkins-home")},
        relations=[_agent_relation(remote_units_data)],
        config=config or {},
    )


class FakeJenkinsService:
    """In-memory fake Jenkins client for agent reconcile tests."""

    def __init__(self, initial_agents: list[str]) -> None:
        self.agents_secret_map: dict[str, str] = {
            agent: secrets.token_hex(16) for agent in initial_agents
        }
        self.agents_remote_fs: dict[str, str | None] = dict.fromkeys(
            initial_agents, "/var/lib/jenkins"
        )

    def add_agent_node(self, agent_meta: AgentMeta) -> None:
        self.agents_secret_map[agent_meta.name] = secrets.token_hex(16)
        self.agents_remote_fs[agent_meta.name] = agent_meta.remote_fs

    def reconcile_agent_node(self, node: SimpleNamespace, agent_meta: AgentMeta) -> None:
        self.agents_remote_fs[node.name] = agent_meta.remote_fs

    def get_node_secret(self, node_name: str) -> str | None:
        return self.agents_secret_map.get(node_name)

    def remove_agent_node(self, agent_name: str) -> None:
        self.agents_secret_map.pop(agent_name)
        self.agents_remote_fs.pop(agent_name)

    def list_agent_nodes(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in self.agents_secret_map]


@pytest.mark.parametrize(
    "initial_agents, relation_agent_names, expected_agents",
    [
        pytest.param([], [], [], id="no relation agents"),
        pytest.param([], ["0"], ["0"], id="one relation agent"),
        pytest.param([], ["0", "1"], ["0", "1"], id="two relation agents"),
        pytest.param(["0"], ["0"], ["0"], id="already registered"),
        pytest.param(
            ["3", "4"], ["0", "1"], ["0", "1", "3", "4"], id="preserve non-relation agents"
        ),
    ],
)
def test_reconcile_agents(
    initial_agents: list[str],
    relation_agent_names: list[str],
    expected_agents: list[str],
):
    """_reconcile_agents registers relation nodes without pruning external nodes."""
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
        for agent_name in relation_agent_names:
            assert f"{agent_name}_secret" in rel_data


def test_reconcile_agents_adds_node_with_relation_remote_fs():
    """New nodes receive the remote filesystem from relation metadata."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["0"], remote_fs={"0": "/workspace/jenkins"})

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        fake_client = FakeJenkinsService(initial_agents=[])
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None

        mgr.charm._reconcile_agents(state=charm_state, client=fake_client)  # type: ignore[arg-type]

    assert fake_client.agents_remote_fs["0"] == "/workspace/jenkins"


def test_reconcile_agents_updates_existing_node_remote_fs():
    """_reconcile_agents updates an existing node when relation remote_fs changes."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["0"], remote_fs={"0": "/workspace/jenkins"})

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        fake_client = FakeJenkinsService(initial_agents=["0"])
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None

        mgr.charm._reconcile_agents(state=charm_state, client=fake_client)  # type: ignore[arg-type]

    assert fake_client.agents_remote_fs["0"] == "/workspace/jenkins"


@pytest.mark.parametrize(
    "error_stage",
    [
        pytest.param("add", id="add_agent_node error"),
        pytest.param("secret", id="get_node_secret error"),
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


def test_reconcile_agents_accepts_event_parameter():
    """_reconcile_agents accepts an optional event for departure cleanup."""
    sig = inspect.signature(JenkinsK8sOperatorCharm._reconcile_agents)
    assert "state" in sig.parameters
    assert "client" in sig.parameters
    assert "event" in sig.parameters


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


def test_reconcile_agents_returns_early_when_no_relation_meta():
    """_reconcile_agents exits early when there is no agent relation metadata."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), testing.State()) as mgr,
    ):
        charm_state = MagicMock(spec=State)
        charm_state.agent_relation_meta = None
        mock_client = MagicMock(spec=jenkins.Jenkins)

        mgr.charm._reconcile_agents(state=charm_state, client=mock_client)

        mock_client.list_agent_nodes.assert_not_called()
        assert not isinstance(mgr.charm.unit.status, ops.MaintenanceStatus)


def test_reconcile_agents_rejects_external_agent_name_collision():
    """Do not silently adopt a node declared as externally managed."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state_with_relation = _state_with_agents(
        ["external-0"], config={"external-agent-nodes": "external-0"}
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state_with_relation) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)

        with pytest.raises(charm.ReconcileBlockedError, match="externally managed"):
            mgr.charm._reconcile_agents(state=charm_state, client=MagicMock(spec=jenkins.Jenkins))


def test_reconcile_departed_agent_removes_departing_relation_node():
    """Remove only the node described by a departing agent relation."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    relation_state = _state_with_agents(["0"])

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), relation_state) as mgr,
    ):
        unit = next(iter(mgr.charm.model.relations["agent"][0].units))
        relation = mgr.charm.model.relations["agent"][0]
        event = SimpleNamespace(departing_unit=unit, relation=relation)
        client = MagicMock(spec=jenkins.Jenkins)
        client.remove_agent_node.return_value = None
        charm_state = State.from_charm(mgr.charm)

        mgr.charm._reconcile_departed_agents(event, charm_state, client)

        client.remove_agent_node.assert_called_once_with(agent_name="0")


def test_reconcile_departed_agent_skips_incomplete_relation_data():
    """Do not delete a node when the departing relation has no agent name."""
    unit = object()
    event = SimpleNamespace(
        departing_unit=unit, relation=SimpleNamespace(data={unit: {}}, units=[unit])
    )
    client = MagicMock(spec=jenkins.Jenkins)
    charm_state = MagicMock(external_agent_nodes=frozenset())

    JenkinsK8sOperatorCharm._reconcile_departed_agents(
        MagicMock(), typing.cast(ops.RelationDepartedEvent, event), charm_state, client
    )

    client.remove_agent_node.assert_not_called()


def test_reconcile_departed_agent_rejects_protected_node():
    """Do not delete a node declared as externally managed."""
    unit = object()
    event = SimpleNamespace(
        departing_unit=unit,
        relation=SimpleNamespace(
            data={unit: {"executors": "1", "labels": "test", "name": "agent-0"}},
            units=[unit],
        ),
    )
    client = MagicMock(spec=jenkins.Jenkins)
    charm_state = MagicMock(external_agent_nodes=frozenset({"agent-0"}))

    with pytest.raises(charm.ReconcileBlockedError, match="externally managed"):
        JenkinsK8sOperatorCharm._reconcile_departed_agents(
            MagicMock(), typing.cast(ops.RelationDepartedEvent, event), charm_state, client
        )

    client.remove_agent_node.assert_not_called()


def test_reconcile_departed_agent_propagates_delete_error():
    """Propagate Jenkins deletion failures so Juju can retry the hook."""
    unit = object()
    event = SimpleNamespace(
        departing_unit=unit,
        relation=SimpleNamespace(
            data={unit: {"executors": "1", "labels": "test", "name": "agent-0"}},
            units=[unit],
        ),
    )
    client = MagicMock(spec=jenkins.Jenkins)
    client.remove_agent_node.side_effect = jenkins.JenkinsError("unavailable")
    charm_state = MagicMock(external_agent_nodes=frozenset())

    with pytest.raises(jenkins.JenkinsError, match="unavailable"):
        JenkinsK8sOperatorCharm._reconcile_departed_agents(
            MagicMock(), typing.cast(ops.RelationDepartedEvent, event), charm_state, client
        )


def test_reconcile_agents_routes_departure_cleanup_through_event():
    """Agent reconciliation invokes departure cleanup only for departed events."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    relation_state = _state_with_agents(["0"])

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), relation_state) as mgr,
        patch.object(mgr.charm, "_reconcile_departed_agents") as cleanup,
    ):
        charm_state = State.from_charm(mgr.charm)
        event = MagicMock(spec=ops.RelationDepartedEvent)
        client = MagicMock(spec=jenkins.Jenkins)
        client.get_node_secret.return_value = "secret"
        mgr.charm._reconcile_agents(state=charm_state, client=client, event=event)

    cleanup.assert_called_once_with(event, charm_state, client)
