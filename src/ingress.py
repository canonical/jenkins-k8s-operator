# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to ingress integration."""

from urllib.parse import urlparse

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import jenkins


class Observer(ops.Object):
    """The Jenkins Ingress integration observer."""

    def __init__(self, charm: ops.CharmBase):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
        """
        super().__init__(charm, "ingress-observer")
        self.charm = charm
        self.ingress = IngressPerAppRequirer(self.charm, port=jenkins.WEB_PORT, strip_prefix=True)

    def get_path(self) -> str:
        """Return the path in whick Jenkins is expected to be listening.

        Returns:
            the path for the ingress URL.
        """
        if not self.ingress.url:
            return "/"
        return urlparse(self.ingress.url).path
