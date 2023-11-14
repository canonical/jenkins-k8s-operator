# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to ingress integration."""

import ops
from charms.traefik_k8s.v1.ingress import IngressPerAppRequirer

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

        self.ingress = IngressPerAppRequirer(self.charm, port=jenkins.WEB_PORT)
