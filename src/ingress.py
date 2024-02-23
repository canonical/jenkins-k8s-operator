# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to ingress integration."""

import typing

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

import jenkins


class Observer(ops.Object):
    """The Jenkins Ingress integration observer."""

    def __init__(self, charm: ops.CharmBase, key: str, relation_name: typing.Optional[str] = None):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
            key: The ops's Object identifier, to have a unique path for event handling.
            relation_name: The ingress relation that this observer is managing.
        """
        super().__init__(charm, key)
        self.charm = charm
        requirer_args = {}
        if relation_name:
            requirer_args["relation_name"] = relation_name
        self.ingress = IngressPerAppRequirer(
            self.charm,
            **requirer_args,
            port=jenkins.WEB_PORT,
            strip_prefix=True,
        )
