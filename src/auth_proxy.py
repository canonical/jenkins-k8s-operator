# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to auth_proxy integration."""

import logging
from typing import List

import ops
from charms.oauth2_proxy_k8s.v0.auth_proxy import AuthProxyConfig, AuthProxyRequirer
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppReadyEvent,
    IngressPerAppRequirer,
    IngressPerAppRevokedEvent,
)

import jenkins
import pebble
from state import JENKINS_SERVICE_NAME, State

AUTH_PROXY_ALLOWED_ENDPOINTS: List[str] = []
AUTH_PROXY_HEADERS = ["X-Auth-Request-User"]


logger = logging.getLogger(__name__)


class Observer(ops.Object):
    """The Jenkins Auth Proxy integration observer."""

    def __init__(
        self,
        charm: ops.CharmBase,
        ingress: IngressPerAppRequirer,
        jenkins_instance: jenkins.Jenkins,
    ):
        """Initialize the observer.

        Args:
            charm: the parent charm to attach the observer to.
            ingress: the ingress object from which to extract the necessary settings.
            jenkins_instance: the Jenkins instance.
        """
        super().__init__(charm, "auth-proxy-observer")
        self.charm = charm
        self.ingress = ingress
        self.jenkins = jenkins_instance

        self.auth_proxy = AuthProxyRequirer(self.charm)

    def on_auth_proxy_relation_joined(self, event: ops.RelationCreatedEvent, state: State) -> None:
        """Configure the auth proxy.

        Args:
            event: the event triggering the handler.
            state: the current charm state.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not self.ingress.url:
            logger.warning("Service not yet ready. Deferring.")
            event.defer()
            return

        self._update_auth_proxy_config()
        self._replan_jenkins(event, state)

    # pylint: disable=duplicate-code
    def _replan_jenkins(
        self, event: ops.EventBase, state: State, disable_security: bool = False
    ) -> None:
        """Replan the jenkins service to account for prefix changes.

        Args:
            event: the event fired.
            state: the current charm state.
            disable_security: Whether or not to replan with security disabled.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            logger.warning("Service not yet ready. Deferring.")
            event.defer()
            return
        pebble.replan_jenkins(container, self.jenkins, state, disable_security)

    def _update_auth_proxy_config(self) -> None:
        """Update auth_proxy configuration with the correct jenkins url."""
        auth_proxy_config = AuthProxyConfig(
            protected_urls=[self.ingress.url] if self.ingress.url else [],
            allowed_endpoints=AUTH_PROXY_ALLOWED_ENDPOINTS,
            headers=AUTH_PROXY_HEADERS,
        )
        self.auth_proxy.update_auth_proxy_config(auth_proxy_config=auth_proxy_config)

    def on_auth_proxy_relation_departed(
        self, event: ops.RelationDepartedEvent, state: State
    ) -> None:
        """Unconfigure the auth proxy.

        Args:
            event: the event fired.
            state: the current charm state.
        """
        # The charm still sees the relation when this hook is fired
        # We then force pebble to replan with security
        self._replan_jenkins(event, state, False)

    def on_ingress_ready(self, event: IngressPerAppReadyEvent, state: State) -> None:
        """Handle ready event.

        Args:
            event: The event fired.
            state: the current charm state.
        """
        if state.auth_proxy_integrated:
            self._update_auth_proxy_config()
        self._replan_jenkins(event, state, state.auth_proxy_integrated)

    def on_ingress_revoked(self, event: IngressPerAppRevokedEvent, state: State) -> None:
        """Handle revoked event.

        Args:
            event: The event fired.
            state: the current charm state.
        """
        # call to update_prefix is needed here since the charm is not aware
        # That the prefix has changed during charm-init
        self.jenkins.update_prefix("")
        if state.auth_proxy_integrated:
            self._update_auth_proxy_config()
        self._replan_jenkins(event, state, state.auth_proxy_integrated)
