# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s auth_proxy unit tests."""

# pylint:disable=protected-access

from unittest.mock import ANY, MagicMock

import ops
from charms.oathkeeper.v0.auth_proxy import AuthProxyRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


def test_auth_proxy_relation_joined_when_jenkins_storage_not_ready():
    """
    arrange: given a charm with no connectable container.
    act: when auth_proxy relation joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()


def test_auth_proxy_relation_joined_when_ingress_not_ready():
    """
    arrange: given a charm with no ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()


def test_auth_proxy_relation_joined():
    """
    arrange: given a charm with ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the relation data is updated.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    mock_ingress = MagicMock(spec=IngressPerAppRequirer)
    mock_ingress.url.return_value = "https://example.com"
    harness.charm.auth_proxy_observer.auth_proxy = MagicMock(spec=AuthProxyRequirer)
    harness.charm.auth_proxy_observer.ingress = mock_ingress
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    harness.charm.auth_proxy_observer.auth_proxy.update_auth_proxy_config.assert_called_once_with(
        auth_proxy_config=ANY
    )
