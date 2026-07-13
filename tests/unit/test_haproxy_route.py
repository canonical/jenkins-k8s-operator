# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s haproxy-route unit tests."""

from unittest.mock import MagicMock

import pytest
from ops.testing import Harness

import jenkins
from charm import JenkinsK8sOperatorCharm
from state import State


def _patch_reconcile_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch non-haproxy-route reconcile paths for focused event tests."""
    monkeypatch.setattr(jenkins, "is_storage_ready", MagicMock(return_value=True))
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_storage", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm,
        "_reconcile_pre_startup_configurations",
        MagicMock(return_value="config-hash"),
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_admin", MagicMock(return_value="admin-password")
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_api_token", MagicMock(return_value=None)
    )
    monkeypatch.setattr(JenkinsK8sOperatorCharm, "_reconcile_agents", MagicMock(return_value=None))
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_agent_discovery", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_auth_proxy", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        JenkinsK8sOperatorCharm, "_reconcile_plugins", MagicMock(return_value=None)
    )


@pytest.mark.parametrize(
    "config_value, expected",
    [
        pytest.param("jenkins.example.com", "jenkins.example.com", id="hostname-set"),
        pytest.param("  jenkins.example.com  ", "jenkins.example.com", id="hostname-stripped"),
        pytest.param("", None, id="empty-string"),
        pytest.param("   ", None, id="whitespace-only"),
    ],
)
def test_external_hostname_parsing(config_value: str, expected):
    """
    arrange: given a charm with external-hostname config set to a value.
    act: when State.from_charm parses the config.
    assert: external_hostname holds the stripped hostname or None when empty.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.update_config({"external-hostname": config_value})
    harness.begin()

    state = State.from_charm(harness.charm)

    assert state.external_hostname == expected


def test_external_hostname_defaults_to_none():
    """
    arrange: given a charm with no external-hostname config set.
    act: when State.from_charm parses the config.
    assert: external_hostname defaults to None.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()

    state = State.from_charm(harness.charm)

    assert state.external_hostname is None


def test_reconcile_haproxy_route_publishes_when_hostname_and_relation_present(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a charm with a haproxy-route relation and external-hostname set.
    act: when _reconcile_haproxy_route runs.
    assert: haproxy-route requirements are published with the configured hostname.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.update_config({"external-hostname": "jenkins.example.com"})
    harness.add_relation("haproxy-route", "haproxy")
    harness.begin()

    provide_mock = MagicMock()
    monkeypatch.setattr(
        harness.charm._haproxy_route, "provide_haproxy_route_requirements", provide_mock
    )

    harness.charm._reconcile_haproxy_route(State.from_charm(harness.charm))

    provide_mock.assert_called_once_with(
        service=harness.charm.app.name,
        ports=[jenkins.WEB_PORT],
        hostname="jenkins.example.com",
    )


def test_reconcile_haproxy_route_noop_without_hostname(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a charm with a haproxy-route relation but no external-hostname.
    act: when _reconcile_haproxy_route runs.
    assert: no haproxy-route requirements are published.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.add_relation("haproxy-route", "haproxy")
    harness.begin()

    provide_mock = MagicMock()
    monkeypatch.setattr(
        harness.charm._haproxy_route, "provide_haproxy_route_requirements", provide_mock
    )

    harness.charm._reconcile_haproxy_route(State.from_charm(harness.charm))

    provide_mock.assert_not_called()


def test_reconcile_haproxy_route_noop_without_relation(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a charm with external-hostname set but no haproxy-route relation.
    act: when _reconcile_haproxy_route runs.
    assert: no haproxy-route requirements are published.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.update_config({"external-hostname": "jenkins.example.com"})
    harness.begin()

    provide_mock = MagicMock()
    monkeypatch.setattr(
        harness.charm._haproxy_route, "provide_haproxy_route_requirements", provide_mock
    )

    harness.charm._reconcile_haproxy_route(State.from_charm(harness.charm))

    provide_mock.assert_not_called()
