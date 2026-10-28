# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s ingress unit tests."""

import json
from unittest.mock import MagicMock

import pytest
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


def _patch_reconcile_dependencies(monkeypatch: pytest.MonkeyPatch):
    """Patch non-ingress reconcile paths for focused ingress event tests."""
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_storage", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_reconcile_pre_startup_configurations",
        MagicMock(return_value="config-hash"),
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_reconcile_admin",
        MagicMock(return_value="admin-password"),
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_api_token", MagicMock(return_value=None)
    )
    monkeypatch.setattr(JenkinsK8sOperatorCharm, "_reconcile_agents", MagicMock(return_value=None))
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_reconcile_agent_discovery",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_plugins", MagicMock(return_value=None)
    )


@pytest.mark.parametrize(
    "ingress_url, expected_path",
    [
        pytest.param("https://host:8080/path", "/path", id="path"),
        pytest.param("https://host:8080/", "", id="root"),
        pytest.param(None, "", id="unset"),
    ],
)
def test_get_ingress_path(harness: Harness, ingress_url: str | None, expected_path: str):
    """
    arrange: given a server ingress URL variant.
    act: when _get_ingress_path is called.
    assert: the expected Jenkins path is returned.
    """
    harness.begin()
    ingress_per_app = MagicMock(spec=IngressPerAppRequirer)
    ingress_per_app.url = ingress_url
    harness.charm.server_ingress = ingress_per_app

    assert harness.charm._get_ingress_path() == expected_path


def test_traefik_integration_added_replans_jenkins(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a base jenkins charm.
    act: add an integration with traefik on :ingress endpoint and remove it.
    assert: pebble replan should run twice, one for ingress ready, one for ingress revoked.
    """
    _patch_reconcile_dependencies(monkeypatch)
    mock_ingress_url = "http://ingress.test/model-unit-0"

    harness.add_storage("jenkins-home", attach=True)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)

    container = harness.model.unit.containers["jenkins"]
    replan_mock = MagicMock()
    monkeypatch.setattr(container, "replan", replan_mock)

    ingress_relation_id = harness.add_relation(
        "ingress",
        "traefik-k8s",
        app_data={"ingress": json.dumps({"url": mock_ingress_url})},
    )
    harness.remove_relation(ingress_relation_id)

    assert replan_mock.call_count == 2


@pytest.mark.parametrize(
    "server_url, agent_url, expected_prefix",
    [
        pytest.param(
            "https://jenkins.example.com/jenkins",
            "https://agents.example.com/jenkins",
            "/jenkins",
            id="server-path-wins",
        ),
        pytest.param(
            None,
            "https://agents.example.com/jenkins",
            "/jenkins",
            id="agent-path-when-no-server-ingress",
        ),
        pytest.param(
            "https://jenkins.example.com/",
            "https://agents.example.com/",
            "",
            id="root-when-both-are-root",
        ),
        pytest.param(None, None, "", id="root-when-no-ingress"),
    ],
)
def test_jenkins_prefix_follows_the_ingress_paths(
    harness: Harness,
    server_url: str | None,
    agent_url: str | None,
    expected_prefix: str,
):
    """
    arrange: given server and agent ingress URLs.
    act: when the Jenkins prefix is resolved.
    assert: the server path wins, the agent path is the fallback, otherwise root.
    """
    harness.begin()
    for attribute, url in (
        ("server_ingress", server_url),
        ("agent_discovery_ingress", agent_url),
    ):
        ingress_per_app = MagicMock(spec=IngressPerAppRequirer)
        ingress_per_app.url = url
        setattr(harness.charm, attribute, ingress_per_app)

    assert harness.charm._jenkins_prefix == expected_prefix
