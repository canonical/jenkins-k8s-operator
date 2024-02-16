# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to auth_proxy integration."""

import logging
from typing import List

import ops
from charms.oathkeeper.v0.auth_proxy import AuthProxyConfig, AuthProxyRequirer
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import jenkins
import state

AUTH_PROXY_ALLOWED_ENDPOINTS: List[str] = []
AUTH_PROXY_HEADERS = ["X-User"]


logger = logging.getLogger(__name__)


class Observer(ops.Object):
    """The Jenkins Auth Proxy integration observer."""

    def __init__(self, charm: ops.CharmBase, ingress: IngressPerAppRequirer):
        """Initialize the observer and register event handlers.

        Args:
            charm: the parent charm to attach the observer to.
            ingress: the ingress object from which to extract the necessary settings.
        """
        super().__init__(charm, "auth-proxy-observer")
        self.charm = charm
        self.ingress = ingress

        self.auth_proxy = AuthProxyRequirer(self.charm)

        self.charm.framework.observe(
            self.charm.on["auth-proxy"].relation_joined, self._auth_proxy_relation_joined
        )

    def _auth_proxy_relation_joined(self, event: ops.RelationCreatedEvent) -> None:
        """Configure the auth proxy.

        Args:
            event: the event triggering the handler.
        """
        container = self.charm.unit.get_container(state.JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container) or not self.ingress.url:
            logger.warning("Service not yet ready. Deferring.")
            event.defer()  # The event needs to be handled after Jenkins has started(pebble ready).
            return

        auth_proxy_config = AuthProxyConfig(
            protected_urls=[self.ingress.url],
            allowed_endpoints=AUTH_PROXY_ALLOWED_ENDPOINTS,
            headers=AUTH_PROXY_HEADERS,
        )
        self.auth_proxy.update_auth_proxy_config(auth_proxy_config=auth_proxy_config)
        jenkins.install_auth_proxy_config(container)