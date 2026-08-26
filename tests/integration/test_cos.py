# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with COS."""

import functools
import logging
from collections.abc import Iterable

import jubilant
import requests
from kubernetes.client import CoreV1Api

from .helpers import get_model_unit_addresses, short_model_name, wait_for
from .types_ import JujuApplication, UnitWebClient

logger = logging.getLogger(__name__)


def test_prometheus_integration(
    model: jubilant.Juju,
    unit_web_client: UnitWebClient,
    prometheus_related: JujuApplication,
) -> None:
    """Verify Prometheus scrapes Jenkins metrics."""
    response = requests.get(f"{unit_web_client.web}/prometheus", timeout=10)
    assert response.status_code == 200

    unit_ips = get_model_unit_addresses(model, prometheus_related.name)
    assert unit_ips, f"Unit IP address not found for {prometheus_related.name}"
    for ip in unit_ips:
        query_targets = requests.get(f"http://{ip}:9090/api/v1/targets", timeout=10).json()
        assert len(query_targets["data"]["activeTargets"])


def log_files_exist(
    unit_address: str,
    application_name: str,
    filenames: Iterable[str],
) -> bool:
    """Return whether Loki has the expected Jenkins log files."""
    series = requests.get(f"http://{unit_address}:3100/loki/api/v1/series", timeout=10).json()
    log_files = {
        series_data["filename"] for series_data in series["data"] if "filename" in series_data
    }
    logger.info("Loki log files: %s", log_files)
    if not all(filename in log_files for filename in filenames):
        return False
    log_query = requests.get(
        f"http://{unit_address}:3100/loki/api/v1/query",
        timeout=10,
        params={"query": f'{{juju_application="{application_name}"}}'},
    ).json()
    return len(log_query["data"]["result"]) != 0


def test_loki_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    loki_related: JujuApplication,
    kube_core_client: CoreV1Api,
) -> None:
    """Verify Loki receives Jenkins logs."""
    unit_ips = get_model_unit_addresses(model, loki_related.name)
    assert unit_ips, f"Unit IP address not found for {loki_related.name}"
    for ip in unit_ips:
        wait_for(
            functools.partial(
                log_files_exist,
                ip,
                application.name,
                ("/var/lib/jenkins/logs/jenkins.log",),
            ),
            timeout=10 * 60,
        )

    kube_log = kube_core_client.read_namespaced_pod_log(
        name=f"{application.name}-0",
        namespace=short_model_name(model),
        container="jenkins",
    )
    assert kube_log


def datasources_exist(
    loggedin_session: requests.Session,
    unit_address: str,
    datasources: Iterable[str],
) -> bool:
    """Return whether Grafana has all expected datasource types."""
    response = loggedin_session.get(
        f"http://{unit_address}:3000/api/datasources", timeout=10
    ).json()
    datasource_types = {datasource["type"] for datasource in response}
    return all(datasource in datasource_types for datasource in datasources)


def dashboard_exist(loggedin_session: requests.Session, unit_address: str) -> int:
    """Return the number of Jenkins dashboards in Grafana."""
    dashboards = loggedin_session.get(
        f"http://{unit_address}:3000/api/search",
        timeout=10,
        params={"query": "Jenkins: Performance and Health Overview"},
    ).json()
    return len(dashboards)


def test_grafana_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    grafana_related: JujuApplication,
) -> None:
    """Verify Grafana has the Jenkins dashboard."""
    action = model.run(grafana_related.units[0], "get-admin-password")
    password = action.results["admin-password"]
    unit_ips = get_model_unit_addresses(model, grafana_related.name)
    for ip in unit_ips:
        session = requests.Session()
        session.post(
            f"http://{ip}:3000/login",
            json={"user": "admin", "password": password},
        ).raise_for_status()
        wait_for(
            functools.partial(dashboard_exist, loggedin_session=session, unit_address=ip),
            timeout=60 * 20,
        )
