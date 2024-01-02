# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Observer module for Jenkins to COS integration."""

import typing

import ops
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

import jenkins


class PrometheusStaticConfig(typing.TypedDict, total=False):
    """Configuration parameters for prometheus metrics endpoint scraping.

    For more information, see:
    https://prometheus.io/docs/prometheus/latest/configuration/configuration/#static_config

    Attrs:
        targets: list of hosts to scrape, e.g. "*:8080", every unit's port 8080
        labels: labels assigned to all metrics scraped from the targets.
    """

    targets: typing.List[str]
    labels: typing.Dict[str, str]


class PrometheusMetricsJob(typing.TypedDict, total=False):
    """Configuration parameters for prometheus metrics scraping job.

    For more information, see:
    https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config

    Attrs:
        metrics_path: The HTTP resource path on which to fetch metrics from targets.
        static_configs: List of labeled statically configured targets for this job.
    """

    metrics_path: str
    static_configs: typing.List[PrometheusStaticConfig]


JENKINS_SCRAPE_JOBS = [
    PrometheusMetricsJob(
        metrics_path="/prometheus",
        static_configs=[
            PrometheusStaticConfig(
                targets=[
                    f"*:{jenkins.WEB_PORT}",
                ]
            )
        ],
    )
]


class Observer(ops.Object):
    """The Jenkins COS integration observer."""

    def __init__(self, charm: ops.CharmBase):
        """Initialize the observer and register event handlers.

        Args:
            charm: The parent charm to attach the observer to.
        """
        super().__init__(charm, "cos-observer")
        self.charm = charm

        self._loki = LogProxyConsumer(
            charm,
            relation_name="logging",
            log_files=str(jenkins.LOGGING_PATH),
            container_name="jenkins",
        )
        self._prometheus = MetricsEndpointProvider(
            charm,
            jobs=JENKINS_SCRAPE_JOBS,
        )
        self._grafana = GrafanaDashboardProvider(charm)
