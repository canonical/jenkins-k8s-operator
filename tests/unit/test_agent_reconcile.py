# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent reconcile tests."""

import inspect
import logging
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
    "initial_agents, relation_agent_names, expected_agents, config",
    [
        pytest.param([], [], [], {}, id="no relation agents"),
        pytest.param([], ["0"], ["0"], {}, id="one relation agent"),
        pytest.param([], ["0", "1"], ["0", "1"], {}, id="two relation agents"),
        pytest.param(["0"], ["0"], ["0"], {}, id="already registered"),
        pytest.param(["3", "4"], ["0", "1"], ["0", "1"], {}, id="prune unprotected agents"),
        pytest.param(
            ["external-0"],
            [],
            ["external-0"],
            {"external-agent-nodes": "external-0"},
            id="preserve configured external agent",
        ),
        pytest.param(
            ["external-0"],
            [],
            ["external-0"],
            {"external-agent-nodes": "external-*"},
            id="preserve external agent matching pattern",
        ),
        pytest.param(
            ["worker[1]"],
            [],
            ["worker[1]"],
            {"external-agent-nodes": "worker[1]"},
            id="preserve exact external agent with pattern characters",
        ),
    ],
)
def test_reconcile_agents(
    initial_agents: list[str],
    relation_agent_names: list[str],
    expected_agents: list[str],
    config: dict[str, str],
):
    """_reconcile_agents registers relation nodes and prunes unprotected nodes."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(relation_agent_names, config=config)

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
    """_reconcile_agents propagates JenkinsError from add and secret stages."""
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
        result = mgr.charm._reconcile_agents(state=charm_state, client=mock_client)

        assert result is False


def test_reconcile_agents_accepts_state_and_client_parameters():
    """_reconcile_agents accepts the current state and Jenkins client."""
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


def test_reconcile_agents_prunes_when_no_relation_meta():
    """_reconcile_agents prunes unprotected nodes without active relations."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), testing.State()) as mgr,
    ):
        charm_state = MagicMock(spec=State)
        charm_state.agent_relation_meta = None
        charm_state.external_agent_nodes = frozenset()
        mock_client = MagicMock(spec=jenkins.Jenkins)
        mock_client.list_agent_nodes.return_value = []

        mgr.charm._reconcile_agents(state=charm_state, client=mock_client)

        mock_client.list_agent_nodes.assert_called_once()
        assert isinstance(mgr.charm.unit.status, ops.MaintenanceStatus)


def test_reconcile_agents_skips_external_agent_updates():
    """Do not update a relation node declared as externally managed."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state_with_relation = _state_with_agents(
        ["external-0"],
        remote_fs={"external-0": "/relation/workspace"},
        config={"external-agent-nodes": "external-0"},
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state_with_relation) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        fake_client = FakeJenkinsService(initial_agents=["external-0"])
        mgr.charm._reconcile_agents(state=charm_state, client=fake_client)

    assert fake_client.agents_remote_fs["external-0"] == "/var/lib/jenkins"


def test_reconcile_agents_does_not_create_external_agent():
    """Do not create a relation node declared as externally managed."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state_with_relation = _state_with_agents(
        ["external-0"], config={"external-agent-nodes": "external-0"}
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state_with_relation) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        client = MagicMock(spec=jenkins.Jenkins)
        client.list_agent_nodes.return_value = [SimpleNamespace(name="external-0")]
        client.get_node_secret.return_value = "secret"
        mgr.charm._reconcile_agents(state=charm_state, client=client)
        agent_rel = mgr.charm.model.relations["agent"][0]

    assert agent_rel.data[mgr.charm.unit]["external-0_secret"] == "secret"
    client.add_agent_node.assert_not_called()


def test_reconcile_agents_warns_for_missing_external_agent():
    """Missing external relation agents are visible in the status message."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state_with_relation = _state_with_agents(
        ["external-0"], config={"external-agent-nodes": "external-0"}
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state_with_relation) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        client = MagicMock(spec=jenkins.Jenkins)
        client.list_agent_nodes.return_value = []
        mgr.charm._reconcile_agents(state=charm_state, client=client)

    assert (
        "External agent nodes not registered in Jenkins: external-0"
        in mgr.charm._agent_status_message
    )


def test_reconcile_agents_propagates_unmanaged_delete_error():
    """Propagate failures while pruning unmanaged nodes."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), testing.State()) as mgr,
    ):
        charm_state = MagicMock(spec=State)
        charm_state.agent_relation_meta = None
        charm_state.external_agent_nodes = frozenset()
        client = MagicMock(spec=jenkins.Jenkins)
        client.list_agent_nodes.return_value = [SimpleNamespace(name="stale-0")]
        client.remove_agent_node.side_effect = jenkins.JenkinsError("unavailable")

        result = mgr.charm._reconcile_agents(charm_state, client)

        assert result is False
        client.remove_agent_node.assert_called_once_with(agent_name="stale-0")


def test_update_agent_nodes_skips_external_agent_pattern():
    """External nodes are not changed during relation reconciliation."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["external-0"], config={"external-agent-nodes": "external-*"})

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        client = MagicMock(spec=jenkins.Jenkins)
        relation = {object(): [AgentMeta(executors="2", labels="new-label", name="external-0")]}

        mgr.charm._update_agent_nodes_from_relation(
            agent_relation=relation,
            agent_nodes=[SimpleNamespace(name="external-0")],
            external_agent_nodes=charm_state.external_agent_nodes,
            api_client=client,
        )

    client.reconcile_agent_node.assert_not_called()


def test_reconcile_agents_skips_external_agent_pattern(caplog: pytest.LogCaptureFixture):
    """External patterns skip relation-node updates without blocking reconciliation."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(
        ["external-0"],
        remote_fs={"external-0": "/relation/workspace"},
        config={"external-agent-nodes": "external-*"},
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        fake_client = FakeJenkinsService(initial_agents=["external-0"])
        with caplog.at_level(logging.WARNING, logger="charm"):
            mgr.charm._reconcile_agents(state=charm_state, client=fake_client)

    assert fake_client.agents_remote_fs["external-0"] == "/var/lib/jenkins"
    assert "external-0" in caplog.text


def test_reconcile_agents_preserves_secret_for_missing_external_agent(
    caplog: pytest.LogCaptureFixture,
):
    """Missing external agents do not replace the last known secret."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["external-0"], config={"external-agent-nodes": "external-0"})

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        relation = mgr.charm.model.relations["agent"][0]
        relation.data[mgr.charm.unit].update({"external-0_secret": "stale-secret"})
        client = MagicMock(spec=jenkins.Jenkins)
        client.list_agent_nodes.return_value = []
        client.get_node_secret.return_value = "bogus-secret"

        with caplog.at_level(logging.WARNING, logger="charm"):
            mgr.charm._reconcile_agents(state=charm_state, client=client)

    assert relation.data[mgr.charm.unit]["external-0_secret"] == "stale-secret"
    client.get_node_secret.assert_not_called()
    assert "not registered; skipping secret publication" in caplog.text


def test_reconcile_agents_preserves_last_external_secret_when_node_missing():
    """A transient missing external node does not delete the last known secret."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state_with_relation = _state_with_agents(
        ["external-0"], config={"external-agent-nodes": "external-0"}
    )

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state_with_relation) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        relation = mgr.charm.model.relations["agent"][0]
        relation.data[mgr.charm.unit].update({"external-0_secret": "last-known-good"})
        client = MagicMock(spec=jenkins.Jenkins)
        client.list_agent_nodes.return_value = []

        mgr.charm._reconcile_agents(state=charm_state, client=client)

    assert relation.data[mgr.charm.unit]["external-0_secret"] == "last-known-good"
    client.get_node_secret.assert_not_called()


def test_update_agent_nodes_records_update_failure():
    """Agent update failures are recorded without stopping reconciliation."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["agent-0"])

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        client = MagicMock(spec=jenkins.Jenkins)
        client.reconcile_agent_node.side_effect = jenkins.JenkinsError("unavailable")
        result = mgr.charm._update_agent_nodes_from_relation(
            agent_relation=charm_state.agent_relation_meta or {},
            agent_nodes=[SimpleNamespace(name="agent-0")],
            external_agent_nodes=frozenset(),
            api_client=client,
        )

    assert result is False


def test_add_agent_nodes_records_relation_data_failure():
    """Relation-data update failures are recorded after Jenkins actions."""
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = _state_with_agents(["agent-0"])

    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        assert charm_state is not None
        relation = mgr.charm.model.relations["agent"][0]
        relation.data[mgr.charm.unit].update = MagicMock(side_effect=ops.ModelError())
        client = MagicMock(spec=jenkins.Jenkins)
        client.get_node_secret.return_value = "secret"
        result = mgr.charm._add_agent_nodes_from_relation(
            agent_relation={
                relation: [AgentMeta(executors="1", labels="testing", name="agent-0")]
            },
            agent_node_names=["agent-0"],
            external_agent_nodes=frozenset(),
            api_client=client,
            agent_discovery_url="http://agents.example",
        )

    assert result is False
