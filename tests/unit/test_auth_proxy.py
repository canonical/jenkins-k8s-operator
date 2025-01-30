# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s auth_proxy unit tests."""

# pylint:disable=protected-access

from unittest.mock import MagicMock, patch

import ops
from charms.oathkeeper.v0.auth_proxy import AuthProxyRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


@patch("jenkins.is_storage_ready", return_value=False)
def test_on_auth_proxy_relation_joined_when_jenkins_storage_not_ready(_):
    """
    arrange: given a charm with no connectable container.
    act: when auth_proxy relation joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._on_auth_proxy_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()


@patch("jenkins.is_storage_ready", return_value=False)
def test_on_auth_proxy_relation_joined_when_ingress_not_ready(_):
    """
    arrange: given a charm with ready storage but no ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._on_auth_proxy_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()


@patch("jenkins.is_storage_ready", return_value=True)
@patch("pebble.replan_jenkins")
def test_on_auth_proxy_relation_joined(replan_mock, _):
    """
    arrange: given a charm with ready storage and ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the pebble service is replaned.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    mock_ingress = MagicMock(spec=IngressPerAppRequirer)
    mock_ingress.url.return_value = "https://example.com"
    harness.charm.auth_proxy_observer.ingress = mock_ingress
    harness.charm.auth_proxy_observer.auth_proxy = MagicMock(spec=AuthProxyRequirer)
    harness.charm.auth_proxy_observer._on_auth_proxy_relation_joined(mock_event)

    replan_mock.assert_called_once()


@patch("jenkins.is_storage_ready", return_value=False)
def test_auth_proxy_relation_departed_when_jenkins_storage_not_ready(_):
    """
    arrange: given a charm with no connectable container.
    act: when auth_proxy departed joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_departed(mock_event)

    assert mock_event.defer.to_be_called_once()


@patch("jenkins.is_storage_ready", return_value=True)
@patch("pebble.replan_jenkins")
def test_auth_proxy_relation_departed(replan_mock, _):
    """
    arrange: given a charm with ready storage and ingress related.
    act: when auth_proxy relation departed event is fired.
    assert: the pebble service is replaned.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationDepartedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_departed(mock_event)

    replan_mock.assert_called_once()
