# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins agent node unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

from contextlib import nullcontext
from typing import Any
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


@pytest.mark.parametrize("raise_api_error", [True, False], ids=["api-error", "success"])
def test_list_agent_nodes(container: ops.Container, mock_client: MagicMock, raise_api_error: bool):
    """list_agent_nodes handles API errors and success paths."""
    mock_node = MagicMock()
    expected_ctx = pytest.raises(jenkins.JenkinsError) if raise_api_error else nullcontext()

    if raise_api_error:
        mock_client.get_nodes.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()
    else:
        mock_client.get_nodes.return_value = {"node": mock_node}

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        expected_ctx,
    ):
        result = list(_jenkins_instance(container).list_agent_nodes())

    if not raise_api_error:
        assert result == [mock_node]


@pytest.mark.parametrize("raise_api_error", [True, False], ids=["api-error", "success"])
def test_get_node_secret(container: ops.Container, mock_client: MagicMock, raise_api_error: bool):
    """get_node_secret handles API errors and success path."""
    expected_ctx = pytest.raises(jenkins.JenkinsError) if raise_api_error else nullcontext()

    if raise_api_error:
        mock_client.run_groovy_script.side_effect = (
            jenkinsapi.custom_exceptions.JenkinsAPIException()
        )
    else:
        mock_client.run_groovy_script.return_value = "abc123\n"

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        expected_ctx,
    ):
        node_secret = _jenkins_instance(container).get_node_secret("jenkins-agent")

    if not raise_api_error:
        assert node_secret == "abc123"


@pytest.mark.parametrize(
    "side_effect,expect_error",
    [
        pytest.param(jenkinsapi.custom_exceptions.JenkinsAPIException, True, id="api-error"),
        pytest.param(jenkinsapi.custom_exceptions.AlreadyExists, False, id="already-exists"),
    ],
)
def test_add_agent_node_exception_paths(
    container: ops.Container,
    mock_client: MagicMock,
    agent_meta: state.AgentMeta,
    side_effect: Any,
    expect_error: bool,
):
    """add_agent_node raises on API error and swallows AlreadyExists."""
    expected_ctx = pytest.raises(jenkins.JenkinsError) if expect_error else nullcontext()
    mock_client.create_node_with_config.side_effect = side_effect

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        patch.object(jenkins.Jenkins, "_get_node_config", return_value={"json": "{}"}),
        expected_ctx,
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


@pytest.mark.parametrize("raise_api_error", [True, False], ids=["api-error", "success"])
def test_remove_agent_node(
    container: ops.Container, mock_client: MagicMock, raise_api_error: bool
):
    """remove_agent_node handles API errors and success path."""
    expected_ctx = pytest.raises(jenkins.JenkinsError) if raise_api_error else nullcontext()

    if raise_api_error:
        mock_client.delete_node.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with (
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        expected_ctx,
    ):
        _jenkins_instance(container).remove_agent_node("jenkins-agent-0")

    if not raise_api_error:
        mock_client.delete_node.assert_called_once_with(nodename="jenkins-agent-0")
