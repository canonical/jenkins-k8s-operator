# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm agent relation tests."""

import inspect
import secrets
import socket
from unittest.mock import MagicMock, patch

import ops
import pytest
from ops import testing
from scenario.errors import UncaughtCharmError

import jenkins
from charm import JenkinsK8sOperatorCharm
from state import JENKINS_SERVICE_NAME, AgentMeta, State

from .helpers import patch_reconcile_pipeline

_MONKEYPATCHED_FQDN = "192.0.2.0"


def test_reconcile_agents_accepts_state_parameter():
    """reconcile_agents must accept state as an explicit keyword argument."""
    sig = inspect.signature(JenkinsK8sOperatorCharm._reconcile_agents)
    assert "state" in sig.parameters, "_reconcile_agents must accept a 'state' parameter"


class FakeJenkinsService:
    """Fake Jenkins class for testing.

    Attributes:
        environment: Fake Jenkins environment.
    """

    def __init__(self, initial_agents: list[str]) -> None:
        """Initialize the fake with agent nodes.

        Args:
            initial_agents: Initial Jenkins agents.
        """
        self.agents_secret_map: dict[str, str] = {
            agent: secrets.token_hex(16) for agent in initial_agents
        }

    # The kwargs are used for testing placeholder
    def add_agent_node(self, agent_meta: AgentMeta, **kwargs):  # pylint: disable=unused-argument
        """Add agent node to fake service.

        Args:
            agent_meta: The agent to add.
            kwargs: other arguments placeholder.
        """
        self.agents_secret_map[agent_meta.name] = secrets.token_hex(16)

    # The kwargs are used for testing placeholder
    def get_node_secret(self, node_name: str, **kwargs):  # pylint: disable=unused-argument
        """Return a fake node secret.

        Args:
            node_name: The node to return fake secret for.
            kwargs: other arguments placeholder.

        Returns:
            Fake Jenkins secret.
        """
        return self.agents_secret_map.get(node_name)

    # The kwargs are used for testing placeholder
    def remove_agent_node(self, agent_name: str, **kwargs):  # pylint: disable=unused-argument
        """Remove agent node from fake service.

        Args:
            agent_name: The agent to remove.
            kwargs: other arguments placeholder.
        """
        self.agents_secret_map.pop(agent_name)

    def wait_ready(self):
        """Fake wait for Jenkins."""
        return

    # The kwargs are used for testing placeholder
    def list_agent_nodes(self, **kwargs):  # pylint: disable=unused-argument
        """List agent nodes managed by fake Jenkins service..

        Args:
            kwargs: other arguments placeholder.

        Returns:
            Fake Jenkins nodes.
        """
        mock_nodes = []
        for node_name in list(self.agents_secret_map.keys()):
            mock_node = MagicMock()
            mock_node.name = node_name
            mock_nodes.append(mock_node)
        return mock_nodes

    @property
    def environment(self):
        """Fake Jenkins environment."""
        return {"JENKINS_PREFIX": "", "JENKINS_HOME": "/var/lib/jenkins/"}


def _generate_reconcile_agents_test_params():
    """Generate testing parameters for reconcile_agents test."""
    testing_containers = [
        # mypy thinks can_connect argument doesn't exist.
        testing.Container("jenkins", can_connect=True),  # type: ignore
    ]
    fail_precondition_state = testing.State(
        # there's incorrect container type inference in scenario.state.Container vs
        # ops.model.Container
        containers=testing_containers,  # type: ignore
    )

    testing_storages = {
        testing.Storage("jenkins-home"),
    }
    no_relation_state = testing.State(
        containers=testing_containers,  # type: ignore[arg-type]
        storages=testing_storages,  # type: ignore
    )

    first_agent_name = "0"
    second_agent_name = "1"
    one_relation_state = testing.State(
        containers=testing_containers,  # type: ignore
        storages=testing_storages,
        relations=[
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={
                    0: {"executors": "1", "labels": "testing", "name": first_agent_name}
                },
            )
        ],
    )
    multiple_relation_state = testing.State(
        containers=testing_containers,  # type: ignore
        storages=testing_storages,
        relations=[
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={
                    0: {
                        "executors": "1",
                        "labels": "testing",
                        "name": first_agent_name,
                    },
                    1: {
                        "executors": "1",
                        "labels": "testing",
                        "name": second_agent_name,
                    },
                },
            )
        ],
    )
    return [
        pytest.param([], fail_precondition_state, [], id="fail precondition"),
        pytest.param([], no_relation_state, [], id="no agent from relation"),
        pytest.param([], one_relation_state, [first_agent_name], id="one agent relation"),
        pytest.param(
            [],
            multiple_relation_state,
            [first_agent_name, second_agent_name],
            id="multiple agents relation",
        ),
        pytest.param(
            [first_agent_name],
            one_relation_state,
            [first_agent_name],
            id="one agent relation, already exists",
        ),
        pytest.param(
            [first_agent_name, second_agent_name],
            multiple_relation_state,
            [first_agent_name, second_agent_name],
            id="multiple agent relation, already exists",
        ),
        pytest.param(
            ["3", "4"],
            multiple_relation_state,
            [first_agent_name, second_agent_name],
            id="multiple agent relation, none from initial exists",
        ),
    ]


@pytest.fixture(name="patch_is_jenkins_ready")
def patch_is_jenkins_ready_fixture(monkeypatch: pytest.MonkeyPatch):
    """Patch jenkins module is_jenkins_ready function."""
    monkeypatch.setattr(jenkins, "is_jenkins_ready", MagicMock())


@pytest.mark.parametrize(
    ("initial_agents", "state", "expected_agents"),
    _generate_reconcile_agents_test_params(),
)
@pytest.mark.usefixtures("patch_is_jenkins_ready")
def test_reconcile_agents(
    initial_agents: list[str],
    state: testing.State,
    expected_agents: list[str],
):
    """
    arrange: given test agent relations.
    act: when reconcile_agents is called.
    assert: expected agents are registered.
    """
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        fake_jenkins_service = FakeJenkinsService(initial_agents=initial_agents)
        mgr.charm.jenkins = fake_jenkins_service  # type: ignore
        charm_state = State.from_charm(mgr.charm)
        mgr.charm._reconcile_agents(state=charm_state)

    all_agent_names = [node.name for node in fake_jenkins_service.list_agent_nodes()]
    assert len(all_agent_names) == len(expected_agents)
    assert all(agent in all_agent_names for agent in expected_agents)


def _generate_reconcile_agent_error_params():
    """Generate testing parameters for reconcile_agent_error test."""
    add_agent_node_fail = MagicMock()
    add_agent_node_fail.get_node_secret.return_value = ""
    add_agent_node_fail.add_agent_node.side_effect = [jenkins.JenkinsError()]

    get_node_secret_fail = MagicMock()
    get_node_secret_fail.get_node_secret.return_value = ""
    get_node_secret_fail.get_node_secret.side_effect = [jenkins.JenkinsError()]

    remove_node_fail = MagicMock()
    remove_node_fail.get_node_secret.return_value = ""
    mock_agent_node = MagicMock()
    mock_agent_node.name = "3"
    remove_node_fail.list_agent_nodes.return_value = [mock_agent_node]
    remove_node_fail.remove_agent_node.side_effect = [jenkins.JenkinsError()]

    return [
        pytest.param(add_agent_node_fail, id="add_agent_node error"),
        pytest.param(get_node_secret_fail, id="get_node_secret error"),
        pytest.param(remove_node_fail, id="remove_node error"),
    ]


@pytest.mark.usefixtures("patch_is_jenkins_ready")
@pytest.mark.parametrize(("mock_jenkins_service",), _generate_reconcile_agent_error_params())
def test_reconcile_agents_error(mock_jenkins_service: MagicMock):
    """
    arrange: given fake Jenkins service mock that errors.
    act: when reconcile is called.
    assert: Jenkins exception is raised.
    """
    testing_containers = [
        # mypy thinks can_connect argument doesn't exist.
        testing.Container(
            "jenkins",
            can_connect=True,  # type: ignore
        ),
    ]
    testing_storages = {
        testing.Storage("jenkins-home"),
    }
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    # Patch the charm's _reconcile_agents to use our mock jenkins service.
    # The reconciliation pattern means the event dispatch itself calls reconcile_agents,
    # so we need the mock in place before ctx.run().
    original_reconcile_agents = JenkinsK8sOperatorCharm._reconcile_agents

    def patched_reconcile_agents(self, state):
        self.jenkins = mock_jenkins_service
        return original_reconcile_agents(self, state)

    with (
        patch_reconcile_pipeline(
            JenkinsK8sOperatorCharm,
            patch_agents=False,
        ),
        patch.object(JenkinsK8sOperatorCharm, "_reconcile_agents", patched_reconcile_agents),
        pytest.raises(UncaughtCharmError, match="JenkinsError"),
    ):
        ctx.run(
            ctx.on.config_changed(),
            testing.State(
                # there's incorrect container type inference in scenario.state.Container vs
                # ops.model.Container
                containers=testing_containers,  # type: ignore
                storages=testing_storages,
                relations=[
                    testing.Relation(
                        endpoint="agent",
                        interface="jenkins_agent_v0",
                        remote_units_data={
                            0: {"executors": "1", "labels": "testing", "name": "0"},
                            1: {"executors": "1", "labels": "testing", "name": "1"},
                        },
                    )
                ],
            ),
        )


def _generate_agent_discovery_url_test_params():
    """Generate testing params for agent discovery URL."""
    public_ingress_address = "https://public-ingress.com"
    agent_discovery_ingress_address = "https://agent-discovery-ingress.com"
    agent_discovery_and_public_ingress = testing.State(
        containers=[
            testing.Container(
                # Mypy thinks that can_connect argument doesn't exist.
                name=JENKINS_SERVICE_NAME,
                can_connect=True,  # type: ignore
            )
        ],
        relations=[
            testing.Relation(
                endpoint="ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{public_ingress_address}"}}'},
            ),
            testing.Relation(
                endpoint="agent-discovery-ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{agent_discovery_ingress_address}"}}'},
            ),
        ],
    )
    public_ingress_only = testing.State(
        containers=[
            testing.Container(
                # Mypy thinks that can_connect argument doesn't exist.
                name=JENKINS_SERVICE_NAME,
                can_connect=True,  # type: ignore
            )
        ],
        relations=[
            testing.Relation(
                endpoint="ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{public_ingress_address}"}}'},
            ),
        ],
    )
    juju_network_address = "192.168.0.1"
    juju_network = testing.State(
        containers=[
            testing.Container(
                # Mypy thinks that can_connect argument doesn't exist.
                name=JENKINS_SERVICE_NAME,
                can_connect=True,  # type: ignore
            )
        ],
        networks={
            testing.Network(
                binding_name="juju-info",
                bind_addresses=[
                    testing.BindAddress(addresses=[testing.Address(juju_network_address)])
                ],
            )
        },
    )
    juju_network_invalid_address = testing.State(
        containers=[
            testing.Container(
                # Mypy thinks that can_connect argument doesn't exist.
                name=JENKINS_SERVICE_NAME,
                can_connect=True,  # type: ignore
            )
        ],
        networks={
            testing.Network(
                binding_name="juju-info",
                bind_addresses=[
                    testing.BindAddress(addresses=[testing.Address("invalidaddress")])
                ],
            )
        },
    )
    return [
        pytest.param(
            agent_discovery_and_public_ingress,
            agent_discovery_ingress_address,
            id="agent_discovery ingress url prioritized",
        ),
        pytest.param(
            public_ingress_only,
            public_ingress_address,
            id="public ingress only",
        ),
        pytest.param(
            juju_network,
            f"http://{juju_network_address}:8080",
            id="juju (kubernetes) pod IP",
        ),
        pytest.param(
            juju_network_invalid_address,
            f"http://{_MONKEYPATCHED_FQDN}:8080",
            id="invalid juju (kubernetes) pod IP",
        ),
        pytest.param(
            testing.State(
                containers=[
                    testing.Container(
                        # Mypy thinks that can_connect argument doesn't exist.
                        name=JENKINS_SERVICE_NAME,
                        can_connect=True,  # type: ignore
                    )
                ],
                networks={},
            ),
            f"http://{_MONKEYPATCHED_FQDN}:8080",
            id="socket fqdn",
        ),
    ]


@pytest.fixture(name="patch_fqdn")
def patch_fqdn_fixture(monkeypatch: pytest.MonkeyPatch):
    """Patch socket.fqdn."""
    monkeypatch.setattr(socket, "getfqdn", lambda: _MONKEYPATCHED_FQDN)


@pytest.mark.parametrize(
    ("state", "expected_discovery_url"), _generate_agent_discovery_url_test_params()
)
@pytest.mark.usefixtures("patch_fqdn")
def test_reconfigure_agent_discovery(
    state: testing.State,
    expected_discovery_url: str,
):
    """
    arrange: given an ingress relation state.
    act: when agent_discovery_url property is accessed.
    assert: expected agent discovery URL is returned.
    """
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with ctx(ctx.on.config_changed(), state) as mgr:
        mgr.charm._reconcile_agent_discovery()
        assert mgr.charm._agent_discovery_url == expected_discovery_url


def _generate_status_message_test_params():
    """Generate testing parameters for status message for ingress statuses."""
    public_ingress_address = "https://public-ingress.com"
    agent_discovery_ingress_address = "https://agent-discovery-ingress.com"
    agent_discovery_and_public_ingress = testing.State(
        containers=[
            testing.Container(
                # Mypy thinks that can_connect argument doesn't exist.
                name=JENKINS_SERVICE_NAME,
                can_connect=True,  # type: ignore
            )
        ],
        relations=[
            testing.Relation(
                endpoint="ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{public_ingress_address}"}}'},
            ),
            testing.Relation(
                endpoint="agent-discovery-ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{agent_discovery_ingress_address}"}}'},
            ),
        ],
    )
    public_ingress_only = testing.State(
        containers=[
            testing.Container(
                # Mypy thinks that can_connect argument doesn't exist.
                name=JENKINS_SERVICE_NAME,
                can_connect=True,  # type: ignore
            )
        ],
        relations=[
            testing.Relation(
                endpoint="ingress",
                interface="ingress",
                remote_app_data={"ingress": f'{{"url":"{public_ingress_address}"}}'},
            ),
        ],
    )
    return [
        pytest.param(agent_discovery_and_public_ingress, "", id="both ingresses"),
        pytest.param(
            public_ingress_only,
            "Consider separating ingress for agents (agent-discovery-ingress)",
            id="public ingress only",
        ),
    ]


@pytest.mark.parametrize(
    ("state", "expected_status_message"), _generate_status_message_test_params()
)
def test_status_message(state: testing.State, expected_status_message: str):
    """
    arrange: given ingress relations.
    act: when _status_message property is accessed.
    assert: expected status message is returned.
    """
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with ctx(ctx.on.config_changed(), state) as mgr:
        # Need access to protected functions for testing
        # pylint:disable=protected-access
        assert mgr.charm._agent_status_message == expected_status_message


@patch("jenkins.is_jenkins_ready", return_value=False)
def test_reconcile_agents_jenkins_not_ready(_mock_ready):
    """
    arrange: given jenkins not ready.
    act: when _reconcile_agents is called.
    assert: waiting status is set and the method returns False.
    """
    state = testing.State(
        containers=[testing.Container("jenkins", can_connect=True)],  # type: ignore
        storages={testing.Storage("jenkins-home")},
        relations=[
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
            ),
        ],
    )
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        charm_state = State.from_charm(mgr.charm)
        reconciled = mgr.charm._reconcile_agents(state=charm_state)
        assert reconciled is False
        assert isinstance(mgr.charm.unit.status, ops.WaitingStatus)


def test_reconcile_agent_discovery_updates_relation():
    """
    arrange: given an agent relation with no url set.
    act: when _reconcile_agent_discovery is called.
    assert: the url is set in the relation data.
    """
    state = testing.State(
        containers=[testing.Container("jenkins", can_connect=True)],  # type: ignore
        storages={testing.Storage("jenkins-home")},
        relations=[
            testing.Relation(
                endpoint="agent",
                interface="jenkins_agent_v0",
                remote_units_data={0: {"executors": "1", "labels": "x", "name": "a1"}},
            ),
        ],
    )
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with (
        patch.object(JenkinsK8sOperatorCharm, "_reconcile", new=lambda self, event: None),
        ctx(ctx.on.config_changed(), state) as mgr,
    ):
        mgr.charm._reconcile_agent_discovery()
        # Check that url was set in relation data
        agent_rel = mgr.charm.model.relations["agent"][0]
        assert "url" in agent_rel.data[mgr.charm.unit]
