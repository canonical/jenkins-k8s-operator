# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins agent node unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

from unittest.mock import MagicMock, patch

import jenkinsapi
import ops
import pytest

import jenkins
import state


def _jenkins_instance(container: ops.Container) -> jenkins.Jenkins:
    """Create Jenkins client wrapper for tests."""
    return jenkins.Jenkins("/", "admin-password", container)


@pytest.fixture(name="agent_meta")
def agent_meta_fixture() -> state.AgentMeta:
    """Return sample agent metadata."""
    return state.AgentMeta(executors="3", labels="x86_64", name="agent_node_0")


def test_list_agent_nodes_error(container: ops.Container, mock_client: MagicMock):
    """list_agent_nodes raises JenkinsError on API exception."""
    mock_client.get_nodes.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        pytest.raises(jenkins.JenkinsError),
    ):
        _jenkins_instance(container).list_agent_nodes()


def test_list_agent_nodes(container: ops.Container, mock_client: MagicMock):
    """list_agent_nodes returns node values from Jenkins API."""
    mock_client.get_nodes.return_value = {"node": (mock_node := MagicMock())}

    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        assert list(_jenkins_instance(container).list_agent_nodes()) == [mock_node]


def test_get_node_secret_api_error(container: ops.Container, mock_client: MagicMock):
    """get_node_secret raises JenkinsError on groovy API failure."""
    mock_client.run_groovy_script.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        pytest.raises(jenkins.JenkinsError),
    ):
        _jenkins_instance(container).get_node_secret("jenkins-agent")


def test_get_node_secret(container: ops.Container, mock_client: MagicMock):
    """get_node_secret returns trimmed secret value."""
    secret = "abc123"
    mock_client.run_groovy_script.return_value = f"{secret}\n"

    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        node_secret = _jenkins_instance(container).get_node_secret("jenkins-agent")

    assert secret == node_secret


def test_add_agent_node_fail(
    container: ops.Container, mock_client: MagicMock, agent_meta: state.AgentMeta
):
    """add_agent_node raises JenkinsError on API exception."""
    mock_client.create_node_with_config.side_effect = (
        jenkinsapi.custom_exceptions.JenkinsAPIException
    )

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        patch.object(jenkins.Jenkins, "_get_node_config", return_value={"json": "{}"}),
        pytest.raises(jenkins.JenkinsError),
    ):
        _jenkins_instance(container).add_agent_node(agent_meta)


def test_add_agent_node_already_exists(
    container: ops.Container, mock_client: MagicMock, agent_meta: state.AgentMeta
):
    """add_agent_node swallows AlreadyExists exception."""
    mock_client.create_node_with_config.side_effect = jenkinsapi.custom_exceptions.AlreadyExists

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        patch.object(jenkins.Jenkins, "_get_node_config", return_value={"json": "{}"}),
    ):
        _jenkins_instance(container).add_agent_node(agent_meta)


def test_add_agent_node(
    container: ops.Container, mock_client: MagicMock, agent_meta: state.AgentMeta
):
    """add_agent_node creates node with generated config."""
    config = {"json": '{"dummy": true}'}

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        patch.object(jenkins.Jenkins, "_get_node_config", return_value=config),
    ):
        _jenkins_instance(container).add_agent_node(agent_meta)

    mock_client.create_node_with_config.assert_called_once_with(
        name=agent_meta.name, config=config
    )


def test_add_agent_node_websocket(
    container: ops.Container, mock_client: MagicMock, agent_meta: state.AgentMeta
):
    """add_agent_node uses websocket-enabled node config path."""
    config = {"json": '{"launcher": {"webSocket": true}}'}

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        patch.object(
            jenkins.Jenkins, "_get_node_config", return_value=config
        ) as get_node_config_mock,
    ):
        _jenkins_instance(container).add_agent_node(agent_meta)

    get_node_config_mock.assert_called_once_with(agent_meta=agent_meta)


def test_remove_agent_node_fail(container: ops.Container, mock_client: MagicMock):
    """remove_agent_node raises JenkinsError on API exception."""
    mock_client.delete_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        pytest.raises(jenkins.JenkinsError),
    ):
        _jenkins_instance(container).remove_agent_node("jenkins-agent-0")


def test_remove_agent_node(container: ops.Container, mock_client: MagicMock):
    """remove_agent_node delegates to Jenkins API with nodename."""
    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        _jenkins_instance(container).remove_agent_node("jenkins-agent-0")

    mock_client.delete_node.assert_called_once_with(nodename="jenkins-agent-0")
