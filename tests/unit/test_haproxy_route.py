# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s haproxy-route unit tests."""

from unittest.mock import MagicMock

import pytest
from ops.testing import Harness

import jenkins
from charm import JenkinsK8sOperatorCharm
from state import CharmConfigInvalidError, State


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
        check_path="/login",
    )


def test_reconcile_haproxy_route_retracts_when_hostname_cleared():
    """
    arrange: given a charm with a haproxy-route relation and external-hostname set.
    act: when _reconcile_haproxy_route runs after the hostname is cleared.
    assert: the published haproxy-route application relation data is cleared.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.update_config({"external-hostname": "jenkins.example.com"})
    relation_id = harness.add_relation("haproxy-route", "haproxy")
    harness.add_relation_unit(relation_id, "haproxy/0")
    harness.set_leader(True)
    harness.begin()

    harness.charm._reconcile_haproxy_route(State.from_charm(harness.charm))

    published_data = harness.get_relation_data(relation_id, harness.charm.app)
    assert published_data

    harness.update_config({"external-hostname": ""})
    harness.charm._reconcile_haproxy_route(MagicMock(external_hostname=None))

    assert harness.get_relation_data(relation_id, harness.charm.app) == {}


def test_reconcile_haproxy_route_retracts_only_on_leader():
    """A non-leader does not clear published application relation data."""
    harness = Harness(JenkinsK8sOperatorCharm)
    relation_id = harness.add_relation("haproxy-route", "haproxy")
    harness.set_leader(True)
    harness.begin()

    harness.charm._reconcile_haproxy_route(MagicMock(external_hostname="jenkins.example.com"))
    published_data = harness.get_relation_data(relation_id, harness.charm.app)
    assert published_data

    harness.set_leader(False)
    harness.charm._reconcile_haproxy_route(MagicMock(external_hostname=None))

    assert harness.get_relation_data(relation_id, harness.charm.app) == published_data


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

    with pytest.raises(CharmConfigInvalidError, match="requires external-hostname"):
        State.from_charm(harness.charm)

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
