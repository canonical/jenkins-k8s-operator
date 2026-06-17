# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s ingress unit tests."""

import json
from unittest.mock import MagicMock

import pytest
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

import jenkins
from charm import JenkinsK8sOperatorCharm


def test_get_ingress_path():
    """
    arrange: given a charm with an ingress URL set.
    act: when _get_ingress_path is called.
    assert: it returns the URL path.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    ingress_per_app = MagicMock(spec=IngressPerAppRequirer)
    harness.charm.server_ingress = ingress_per_app

    ingress_per_app.url = "https://host:8080/path"
    assert harness.charm._get_ingress_path() == "/path"
    ingress_per_app.url = "https://host:8080/"
    assert harness.charm._get_ingress_path() == ""
    ingress_per_app.url = None
    assert harness.charm._get_ingress_path() == ""


def test_traefik_integration_added_replans_jenkins(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a base jenkins charm.
    act: add an integration with traefik on :ingress endpoint and remove it.
    assert: pebble replan should run twice, one for ingress ready, one for ingress revoked.
    """
    monkeypatch.setattr(jenkins, "is_storage_ready", MagicMock(return_value=True))
    monkeypatch.setattr(jenkins.Jenkins, "remove_unlisted_plugins", MagicMock(return_value=None))
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


def test_traefik_integration_added_with_auth_proxy_replans_jenkins(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a base jenkins charm with auth-proxy relation.
    act: add an integration with traefik on :ingress endpoint and remove it.
    assert: pebble replan should run twice, one for ingress ready, one for ingress revoked.
    """
    monkeypatch.setattr(jenkins, "is_storage_ready", MagicMock(return_value=True))
    mock_ingress_url = "http://ingress.test/model-unit-0"
    harness.add_storage("jenkins-home", attach=True)
    harness.add_relation(
        "auth-proxy",
        "oathkeeper",
        app_data={},
    )
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
