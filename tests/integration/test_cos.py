# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with COS."""

import functools
import typing

import pytest
import requests
from juju.action import Action
from juju.application import Application
from juju.client._definitions import FullStatus
from juju.model import Model
from kubernetes.client import CoreV1Api

from .helpers import wait_for
from .types_ import UnitWebClient


@pytest.mark.abort_on_fail
async def test_prometheus_integration(
    unit_web_client: UnitWebClient, prometheus_related: Application
):
    """
    arrange: deploy the Jenkins charm and establish relations with prometheus.
    act: send a request to the metrics endpoint (/prometheus).
    assert: prometheus metrics endpoint for prometheus is active and prometheus has active scrape
        targets.
    """
    web_address = unit_web_client.web
    res = requests.get(f"{web_address}/prometheus", timeout=10)
    assert res.status_code == 200

    model: Model = unit_web_client.unit.model
    status: FullStatus = await model.get_status(filters=[prometheus_related.name])
    for unit in status.applications[prometheus_related.name].units.values():
        query_targets = requests.get(
            f"http://{unit.address}:9090/api/v1/targets", timeout=10
        ).json()
        assert len(query_targets["data"]["activeTargets"])


def log_files_exist(
    unit_address: str, application_name: str, filenames: typing.Iterable[str]
) -> bool:
    """Returns whether log filenames exist in Loki logs query.

    Args:
        unit_address: Loki unit ip address.
        application_name: Application name to query logs for.
        filenames: Expected filenames to be present in logs collected by Loki.

    Returns:
        True if log files with logs exists. False otherwise.
    """
    series = requests.get(f"http://{unit_address}:3100/loki/api/v1/series", timeout=10).json()
    log_files = set(series_data["filename"] for series_data in series["data"])
    if not all(filename in log_files for filename in filenames):
        return False
    log_query = requests.get(
        f"http://{unit_address}:3100/loki/api/v1/query",
        timeout=10,
        params={"query": f'{{juju_application="{application_name}"}}'},
    ).json()

    return len(log_query["data"]["result"]) != 0


@pytest.mark.abort_on_fail
async def test_loki_integration(
    application: Application,
    loki_related: Application,
    unit_web_client: UnitWebClient,
    kube_core_client: CoreV1Api,
):
    """
    arrange: after Jenkins charm has been deployed and relations established.
    act: loki charm joins relation
    assert: loki joins relation successfully, logs are being output to container and to files for
        loki to scrape.
    """
    model: Model = unit_web_client.unit.model
    status: FullStatus = await model.get_status(filters=[loki_related.name])
    for unit in status.applications[loki_related.name].units.values():
        await wait_for(
            functools.partial(
                log_files_exist,
                unit.address,
                application.name,
                ("/var/lib/jenkins/jenkins.log",),
            ),
            timeout=10 * 60,
        )

    kube_log = kube_core_client.read_namespaced_pod_log(
        name=f"{application.name}-0", namespace=model.name, container="jenkins"
    )
    assert kube_log


def datasources_exist(
    loggedin_session: requests.Session, unit_address: str, datasources: typing.Iterable[str]
):
    """Checks if the datasources are registered in Grafana.

    Args:
        loggedin_session: Requests session that's authorized to make API calls.
        unit_address: Grafana unit address.
        datasources: Datasources to check for.

    Returns:
        True if all datasources are found. False otherwise.
    """
    response = loggedin_session.get(
        f"http://{unit_address}:3000/api/datasources", timeout=10
    ).json()
    datasource_types = set(datasource["type"] for datasource in response)
    return all(datasource in datasource_types for datasource in datasources)


def dashboard_exist(loggedin_session: requests.Session, unit_address: str):
    """Checks if the Jenkins dashboard is registered in Grafana.

    Args:
        loggedin_session: Requests session that's authorized to make API calls.
        unit_address: Grafana unit address.

    Returns:
        True if all dashboard is found. False otherwise.
    """
    dashboards = loggedin_session.get(
        f"http://{unit_address}:3000/api/search",
        timeout=10,
        params={"query": "Jenkins: Performance and Health Overview"},
    ).json()
    return len(dashboards)


async def test_grafana_integration(
    application: Application,
    grafana_related: Application,
):
    """
    arrange: after Jenkins charm has been deployed and relations established with Grafana.
    act: grafana charm joins relation
    assert: grafana Jenkins dashboard can be found
    """
    model: Model = application.model
    status: FullStatus = await model.get_status(filters=[grafana_related.name])
    action: Action = await grafana_related.units[0].run_action("get-admin-password")
    await action.wait()
    password = action.results["admin-password"]
    for unit in status.applications[grafana_related.name].units.values():
        sess = requests.session()
        sess.post(
            f"http://{unit.address}:3000/login",
            json={
                "user": "admin",
                "password": password,
            },
        ).raise_for_status()
        await wait_for(
            functools.partial(dashboard_exist, loggedin_session=sess, unit_address=unit.address),
            timeout=60 * 20,
        )
