# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the MetricsEndpointProvider configuration on the Jenkins charm."""

from unittest.mock import PropertyMock

import pytest
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


def test_metrics_path_without_ingress(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: a charm with no ingress URL set (url returns None).
    act: read the metrics_path on the prometheus scrape job.
    assert: the metrics_path is "/prometheus" (no prefix).
    """
    monkeypatch.setattr(IngressPerAppRequirer, "url", PropertyMock(return_value=None))
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.add_network("10.0.0.10")
    harness.begin()
    try:
        assert _scrape_metrics_path(harness) == "/prometheus"
    finally:
        harness.cleanup()


def test_metrics_path_with_root_ingress(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: a charm with an ingress URL whose path is "/".
    act: read the metrics_path on the prometheus scrape job.
    assert: the metrics_path is "/prometheus" (no prefix, because "/" collapses to "").
    """
    monkeypatch.setattr(
        IngressPerAppRequirer,
        "url",
        PropertyMock(return_value="https://host:8080/"),
    )
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.add_network("10.0.0.10")
    harness.begin()
    try:
        assert _scrape_metrics_path(harness) == "/prometheus"
    finally:
        harness.cleanup()


def test_metrics_path_with_ingress_prefix(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: a charm with an ingress URL that has a non-root path.
    act: read the metrics_path on the prometheus scrape job.
    assert: the metrics_path is "<ingress-path>/prometheus".
    """
    monkeypatch.setattr(
        IngressPerAppRequirer,
        "url",
        PropertyMock(return_value="https://host:8080/model-jenkins-0"),
    )
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.add_network("10.0.0.10")
    harness.begin()
    try:
        assert _scrape_metrics_path(harness) == "/model-jenkins-0/prometheus"
    finally:
        harness.cleanup()


def _scrape_metrics_path(harness: Harness) -> str:
    """Return the metrics_path on the first scrape job published by the charm."""
    jobs = harness.charm._prometheus._jobs  # pylint: disable=protected-access
    assert jobs, "Expected at least one scrape job to be configured."
    return jobs[0]["metrics_path"]
