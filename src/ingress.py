# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to ingress integration."""

from urllib.parse import urlparse

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import jenkins


class Observer(ops.Object):
    """The Jenkins Ingress integration observer."""

    def __init__(self, charm: ops.CharmBase, key: str, relation_name: str):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
            key: The ops's Object identifier, to have a unique path for event handling.
            relation_name: The ingress relation that this observer is managing.
        """
        super().__init__(charm, key)
        self.charm = charm
        self.ingress = IngressPerAppRequirer(
            self.charm,
            relation_name=relation_name,
            port=jenkins.WEB_PORT,
        )

    def get_path(self) -> str:
        """Return the path in whick Jenkins is expected to be listening.

        Returns:
            the path for the ingress URL.
        """
        if not self.ingress.url:
            return ""
        path = urlparse(self.ingress.url).path
        if path == "/":
            return ""
        return path

    def is_ingress_ready(self) -> str:
        """Indicate if the ingress relation is ready.

        Returns:
            True if ingress is ready
        """
        return self.ingress.is_ready()
