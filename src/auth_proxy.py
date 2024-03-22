# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to auth_proxy integration."""

import logging
from typing import List

import ops
from charms.oathkeeper.v0.auth_proxy import AuthProxyConfig, AuthProxyRequirer
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppReadyEvent,
    IngressPerAppRequirer,
    IngressPerAppRevokedEvent,
)

import jenkins
import pebble
from state import AUTH_PROXY_RELATION, JENKINS_SERVICE_NAME, State

AUTH_PROXY_ALLOWED_ENDPOINTS: List[str] = []
AUTH_PROXY_HEADERS = ["X-User"]


logger = logging.getLogger(__name__)


class Observer(ops.Object):
    """The Jenkins Auth Proxy integration observer."""

    def __init__(
        self,
        charm: ops.CharmBase,
        ingress: IngressPerAppRequirer,
        jenkins_instance: jenkins.Jenkins,
        state: State,
    ):
        """Initialize the observer and register event handlers.

        Args:
            charm: the parent charm to attach the observer to.
            ingress: the ingress object from which to extract the necessary settings.
            jenkins_instance: the Jenkins instance.
            state: the charm state.
        """
        super().__init__(charm, "auth-proxy-observer")
        self.charm = charm
        self.ingress = ingress
        self.jenkins = jenkins_instance
        self.state = state

        self.auth_proxy = AuthProxyRequirer(self.charm)

        self.charm.framework.observe(
            self.charm.on[AUTH_PROXY_RELATION].relation_joined,
            self._on_auth_proxy_relation_joined,
        )
        self.charm.framework.observe(
            self.charm.on[AUTH_PROXY_RELATION].relation_departed,
            self._auth_proxy_relation_departed,
        )

        # Event hooks for agent-discovery-ingress
        charm.framework.observe(
            self.ingress.on.ready,
            self._ingress_on_ready,
        )
        charm.framework.observe(
            self.ingress.on.revoked,
            self._ingress_on_revoked,
        )

    def _on_auth_proxy_relation_joined(self, event: ops.RelationCreatedEvent) -> None:
        """Configure the auth proxy.

        Args:
            event: the event triggering the handler.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not self.ingress.url:
            logger.warning("Service not yet ready. Deferring.")
            event.defer()
            return

        auth_proxy_config = AuthProxyConfig(
            protected_urls=[self.ingress.url],
            allowed_endpoints=AUTH_PROXY_ALLOWED_ENDPOINTS,
            headers=AUTH_PROXY_HEADERS,
        )
        self.auth_proxy.update_auth_proxy_config(auth_proxy_config=auth_proxy_config)
        pebble.replan_jenkins(container, self.jenkins, self.state)

    # pylint: disable=duplicate-code
    def _replan_jenkins(self, event: ops.EventBase) -> None:
        """Replan the jenkins service to account for prefix changes.

        Args:
            event: the event fired.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            logger.warning("Service not yet ready. Deferring.")
            event.defer()
            return
        pebble.replan_jenkins(container, self.jenkins, self.state)

    def _auth_proxy_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Unconfigure the auth proxy.

        Args:
            event: the event fired.
        """
        self._replan_jenkins(event)

    def _ingress_on_ready(self, event: IngressPerAppReadyEvent) -> None:
        """Handle ready event.

        Args:
            event: The event fired.
        """
        self._replan_jenkins(event)

    def _ingress_on_revoked(self, event: IngressPerAppRevokedEvent) -> None:
        """Handle revoked event.

        Args:
            event: The event fired.
        """
        self._replan_jenkins(event)
