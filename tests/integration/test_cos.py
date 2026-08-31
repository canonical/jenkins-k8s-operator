# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with COS."""

import logging
from collections.abc import Iterable

import jubilant
import requests
import tenacity
from kubernetes.client import CoreV1Api

from .helpers import _raise_timeout, get_model_unit_addresses, short_model_name
from .types_ import JujuApplication, UnitWebClient

logger = logging.getLogger(__name__)


def _prometheus_targets_exist(model: jubilant.Juju, application_name: str) -> bool:
    """Return whether every Prometheus unit exposes active scrape targets."""
    unit_ips = get_model_unit_addresses(model, application_name)
    if not unit_ips:
        return False

    try:
        return all(
            requests.get(f"http://{ip}:9090/api/v1/targets", timeout=10).json()["data"][
                "activeTargets"
            ]
            for ip in unit_ips
        )
    except (KeyError, TypeError, ValueError, requests.RequestException):
        return False


def test_prometheus_integration(
    model: jubilant.Juju,
    unit_web_client: UnitWebClient,
    prometheus_related: JujuApplication,
) -> None:
    """
    Arrange: Given the Jenkins application is related to Prometheus.
    Act: Request Jenkins metrics and wait for every Prometheus unit to expose active scrape targets.
    Assert: The metrics endpoint returns HTTP 200 and every Prometheus unit has active scrape targets.
    """
    response = requests.get(f"{unit_web_client.web}/prometheus", timeout=10)
    assert response.status_code == 200

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda result: not result),
        stop=tenacity.stop_after_delay(10 * 60),
        wait=tenacity.wait_fixed(10),
        reraise=True,
        retry_error_callback=_raise_timeout,
    )
    def prometheus_targets_are_ready() -> bool:
        return _prometheus_targets_exist(model, prometheus_related.name)

    prometheus_targets_are_ready()


def log_files_exist(
    unit_address: str,
    application_name: str,
    filenames: Iterable[str],
) -> bool:
    """Return whether Loki has the expected Jenkins log files."""
    try:
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
    except (KeyError, TypeError, ValueError, requests.RequestException):
        return False


def _loki_logs_exist(
    model: jubilant.Juju,
    application_name: str,
    loki_application_name: str,
    filenames: Iterable[str],
) -> bool:
    """Return whether current Loki units expose the expected Jenkins logs."""
    unit_ips = get_model_unit_addresses(model, loki_application_name)
    return bool(unit_ips) and all(
        log_files_exist(ip, application_name, filenames) for ip in unit_ips
    )


def test_loki_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    loki_related: JujuApplication,
    kube_core_client: CoreV1Api,
) -> None:
    """
    Arrange: Given the Jenkins application is related to Loki.
    Act: Wait for Loki to expose Jenkins log data, then read the Jenkins pod log.
    Assert: Loki exposes the expected Jenkins log data and the Jenkins pod log is not empty.
    """

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda result: not result),
        stop=tenacity.stop_after_delay(10 * 60),
        wait=tenacity.wait_fixed(10),
        reraise=True,
        retry_error_callback=_raise_timeout,
    )
    def loki_logs_are_ready() -> bool:
        return _loki_logs_exist(
            model,
            application.name,
            loki_related.name,
            ("/var/lib/jenkins/logs/jenkins.log",),
        )

    loki_logs_are_ready()

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


def _grafana_login_is_ready(
    model: jubilant.Juju,
    grafana_unit: str,
    unit_ip: str,
    session: requests.Session,
) -> bool:
    """Log in with a fresh password after Grafana restarts."""
    action = model.run(grafana_unit, "get-admin-password")
    if not action.success:
        logger.info("Grafana password action not ready: status=%s", action.status)
        return False
    password = action.results.get("admin-password")
    if not password:
        logger.info("Grafana password action returned no password")
        return False

    session.cookies.clear()
    try:
        response = session.post(
            f"http://{unit_ip}:3000/login",
            json={"user": "admin", "password": password},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.info("Grafana login endpoint not ready: %s", exc)
        return False
    logger.info("Grafana login status: %s", response.status_code)
    return response.status_code == 200


def test_grafana_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    grafana_related: JujuApplication,
) -> None:
    """
    Arrange: Given the Jenkins application is related to Grafana.
    Act: Log in to each Grafana unit and wait for the Jenkins dashboard.
    Assert: Each Grafana unit accepts the login and exposes the Jenkins dashboard.
    """
    unit_ips = get_model_unit_addresses(model, grafana_related.name)
    assert unit_ips, f"Unit IP address not found for {grafana_related.name}"
    for ip in unit_ips:
        session = requests.Session()

        @tenacity.retry(
            retry=tenacity.retry_if_result(lambda result: not result),
            stop=tenacity.stop_after_delay(10 * 60),
            wait=tenacity.wait_fixed(10),
            reraise=True,
            retry_error_callback=_raise_timeout,
        )
        def grafana_login_is_ready(
            unit_ip: str = ip,
            login_session: requests.Session = session,
        ) -> bool:
            return _grafana_login_is_ready(
                model,
                grafana_related.units[0],
                unit_ip,
                login_session,
            )

        grafana_login_is_ready()

        @tenacity.retry(
            retry=tenacity.retry_any(
                tenacity.retry_if_result(lambda result: not result),
                tenacity.retry_if_exception_type((requests.RequestException, ValueError)),
            ),
            stop=tenacity.stop_after_delay(60 * 20),
            wait=tenacity.wait_fixed(10),
            reraise=True,
            retry_error_callback=_raise_timeout,
        )
        def dashboard_is_ready(
            login_session: requests.Session = session,
            unit_ip: str = ip,
        ) -> int:
            return dashboard_exist(loggedin_session=login_session, unit_address=unit_ip)

        dashboard_is_ready()
