# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s auth_proxy unit tests."""

# pylint:disable=protected-access

from unittest.mock import ANY, MagicMock, patch

import ops
from charms.oathkeeper.v0.auth_proxy import AuthProxyRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

import auth_proxy
import ingress
from charm import JenkinsK8sOperatorCharm

CHARM_METADATA = """
name: test-charm
requires:
  auth-proxy:
    interface: auth_proxy
  ingress:
    interface: ingress
containers:
  jenkins:
    resource: jenkins-image
"""


class TestCharm(ops.CharmBase):
    """Class for charm testing."""

    def __init__(self, *args):
        """Init method for the class.

        Args:
            args: Variable list of positional arguments passed to the parent constructor.
        """
        super().__init__(*args)
        self.events = []
        self.ingress_observer = ingress.Observer(self)
        self.auth_proxy_observer = auth_proxy.Observer(self, self.ingress_observer.ingress)
        self.framework.observe(self.on.jenkins_pebble_ready, self._record_event)

    def _record_event(self, event: ops.EventBase) -> None:
        """Record emitted event in the event list.

        Args:
            event: event.
        """
        self.events.append(event)


@patch("jenkins.is_storage_ready", return_value=False)
def test_auth_proxy_relation_joined_when_jenkins_storage_not_ready(_):
    """
    arrange: given a charm with no connectable container.
    act: when auth_proxy relation joined event is fired.
    assert: the event is deferred.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
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
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    assert mock_event.defer.to_be_called_once()


@patch("jenkins.is_storage_ready", return_value=True)
def test_auth_proxy_relation_joined(_):
    """
    arrange: given a charm with ready storage and ingress related.
    act: when auth_proxy relation joined event is fired.
    assert: the new jenkins configuration is installed.
    """
    harness = Harness(TestCharm, meta=CHARM_METADATA)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationCreatedEvent)
    mock_ingress = MagicMock(spec=IngressPerAppRequirer)
    mock_ingress.url.return_value = "https://example.com"
    harness.charm.auth_proxy_observer.ingress = mock_ingress
    harness.charm.auth_proxy_observer.auth_proxy = MagicMock(spec=AuthProxyRequirer)
    harness.charm.auth_proxy_observer._auth_proxy_relation_joined(mock_event)

    harness.charm.auth_proxy_observer.auth_proxy.update_auth_proxy_config.assert_called_once_with(
        auth_proxy_config=ANY
    )
    assert len(harness.charm.events) == 1


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
def test_auth_proxy_relation_departed(_):
    """
    arrange: given a charm with ready storage and ingress related.
    act: when auth_proxy relation departed event is fired.
    assert: the default jenkins configuration is installed.
    """
    harness = Harness(TestCharm, meta=CHARM_METADATA)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)
    mock_event = MagicMock(spec=ops.RelationDepartedEvent)
    harness.charm.auth_proxy_observer._auth_proxy_relation_departed(mock_event)

    assert len(harness.charm.events) == 1


def test_has_relation_when_no_relation():
    """
    arrange: given a charm no auth-proxy relation.
    act: when has_relation is executed.
    assert: it returns False.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()

    assert not harness.charm.auth_proxy_observer.has_relation()


def test_has_relation_when_relation_data():
    """
    arrange: given a charm with an auth-proxy relation.
    act: when has_relation is executed.
    assert: it returns True.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.add_relation("auth-proxy", harness.charm.app.name)

    assert harness.charm.auth_proxy_observer.has_relation()
