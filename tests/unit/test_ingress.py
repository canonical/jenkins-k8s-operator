# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s ingress unit tests."""

from unittest.mock import MagicMock

from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


def test_get_path():
    """
    arrange: given a charm with an ingress URL set.
    act: when get_path is called.
    assert: it returns the URL path.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    ingress_per_app = MagicMock(spec=IngressPerAppRequirer)
    harness.charm.ingress_observer.ingress = ingress_per_app

    ingress_per_app.url = "https://host:8080/path"
    assert harness.charm.ingress_observer.get_path() == "/path"
    ingress_per_app.url = "https://host:8080/"
    assert harness.charm.ingress_observer.get_path() == ""
    ingress_per_app.url = None
    assert harness.charm.ingress_observer.get_path() == ""
