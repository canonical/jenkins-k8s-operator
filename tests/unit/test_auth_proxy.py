# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s auth_proxy unit tests."""

# pylint:disable=protected-access

from unittest.mock import MagicMock, patch

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


@patch("jenkins.is_storage_ready", return_value=False)
def test_auth_proxy_relation_joined_when_jenkins_storage_not_ready(_):
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


@patch("jenkins.is_storage_ready", return_value=False)
def test_auth_proxy_relation_joined_when_ingress_not_ready(_):
    """
    arrange: given a charm with ready storage but no ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()


@patch("jenkins.is_storage_ready", return_value=True)
@patch("jenkins.install_auth_proxy_config")
def test_auth_proxy_relation_joined(install_auth_proxy_config_mock, _):
    """
    arrange: given a charm with ready storage and ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the new jenkins configuration is installed.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    mock_ingress = MagicMock(spec=IngressPerAppRequirer)
    mock_ingress.url.return_value = "https://example.com"
    harness.charm.auth_proxy_observer.ingress = mock_ingress
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    install_auth_proxy_config_mock.assert_called_once()


@patch("jenkins.is_storage_ready", return_value=False)
def test_auth_proxy_relation_departed_when_jenkins_storage_not_ready(_):
    """
    arrange: given a charm with no connectable container.
    act: when auth_proxy departed joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_departed(mock_event)

    assert mock_event.defer.to_be_called_once()


@patch("jenkins.is_storage_ready", return_value=True)
@patch("jenkins.install_default_config")
def test_auth_proxy_relation_departed(install_default_config_mock, _):
    """
    arrange: given a charm with ready storage and ingress related.
    act: when auth_proxy relation departed event is fired.
    assert: the default jenkins configuration is installed.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    mock_event = MagicMock(spec=ops.RelationDepartedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_departed(mock_event)

    install_default_config_mock.assert_called_once()
