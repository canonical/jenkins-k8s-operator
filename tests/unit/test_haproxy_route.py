# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s haproxy-route unit tests."""

from unittest.mock import MagicMock

import pytest
from ops.testing import Harness

import jenkins
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
def test_external_hostname_parsing(harness: Harness, config_value: str, expected):
    """
    arrange: given a charm with external-hostname config set to a value.
    act: when State.from_charm parses the config.
    assert: external_hostname holds the stripped hostname or None when empty.
    """
    harness.update_config({"external-hostname": config_value})
    harness.begin()

    state = State.from_charm(harness.charm)

    assert state.external_hostname == expected


def test_external_hostname_defaults_to_none(harness: Harness):
    """
    arrange: given a charm with no external-hostname config set.
    act: when State.from_charm parses the config.
    assert: external_hostname defaults to None.
    """
    harness.begin()

    state = State.from_charm(harness.charm)

    assert state.external_hostname is None


def test_reconcile_haproxy_route_publishes_when_hostname_and_relation_present(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm with a haproxy-route relation and external-hostname set.
    act: when _reconcile_haproxy_route runs.
    assert: haproxy-route requirements are published with the configured hostname.
    """
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


def test_reconcile_haproxy_route_retracts_when_hostname_cleared(harness: Harness):
    """
    arrange: given a charm with a haproxy-route relation and external-hostname set.
    act: when _reconcile_haproxy_route runs after the hostname is cleared.
    assert: the published haproxy-route application relation data is cleared.
    """
    harness.update_config({"external-hostname": "jenkins.example.com"})
    relation_id = harness.add_relation("haproxy-route", "haproxy")
    harness.add_relation_unit(relation_id, "haproxy/0")
    harness.set_leader(True)
    harness.begin()

    harness.charm._reconcile_haproxy_route(State.from_charm(harness.charm))

    published_data = harness.get_relation_data(relation_id, harness.charm.app)
    assert published_data

    harness.update_config({"external-hostname": ""})
    harness.charm._retract_invalid_haproxy_route()

    assert harness.charm._get_state() is None
    assert harness.charm.unit.status.name == "blocked"
    assert harness.get_relation_data(relation_id, harness.charm.app) == {}


def test_haproxy_route_without_hostname_blocks(harness: Harness):
    """
    arrange: given a related haproxy-route without external-hostname.
    act: when State.from_charm validates the topology.
    assert: CharmConfigInvalidError is raised.
    """
    harness.add_relation("haproxy-route", "haproxy")
    harness.begin()

    with pytest.raises(CharmConfigInvalidError, match="requires external-hostname"):
        State.from_charm(harness.charm)


def test_haproxy_route_without_relation_does_not_publish(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given external-hostname without a haproxy-route relation.
    act: when _reconcile_haproxy_route runs.
    assert: no haproxy-route requirements are published.
    """
    harness.update_config({"external-hostname": "jenkins.example.com"})
    harness.begin()

    provide_mock = MagicMock()
    monkeypatch.setattr(
        harness.charm._haproxy_route, "provide_haproxy_route_requirements", provide_mock
    )

    harness.charm._reconcile_haproxy_route(State.from_charm(harness.charm))

    provide_mock.assert_not_called()
