# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures used only by COS integration tests."""

import pytest_asyncio
from juju.application import Application
from juju.model import Model


@pytest_asyncio.fixture(scope="module", name="prometheus_related")
async def prometheus_related_fixture(application: Application, model: Model):
    """The prometheus-k8s application related to Jenkins via metrics-endpoint relation."""
    prometheus = await model.deploy("prometheus-k8s", channel="1/stable", trust=True)
    await model.wait_for_idle(
        status="active", apps=[prometheus.name], raise_on_error=False, timeout=30 * 60
    )
    await model.add_relation(f"{application.name}:metrics-endpoint", prometheus.name)
    await model.wait_for_idle(
        status="active",
        apps=[prometheus.name, application.name],
        timeout=30 * 60,
        idle_period=30,
        raise_on_error=False,
    )
    return prometheus


@pytest_asyncio.fixture(scope="module", name="loki_related")
async def loki_related_fixture(application: Application, model: Model):
    """The loki-k8s application related to Jenkins via logging relation."""
    loki = await model.deploy("loki-k8s", channel="1/stable", trust=True)
    await model.wait_for_idle(
        status="active", apps=[loki.name], raise_on_error=False, timeout=30 * 60
    )
    await model.add_relation(f"{application.name}:logging", loki.name)
    await model.wait_for_idle(
        status="active",
        apps=[loki.name, application.name],
        timeout=30 * 60,
        idle_period=30,
        raise_on_error=False,
    )
    return loki


@pytest_asyncio.fixture(scope="module", name="grafana_related")
async def grafana_related_fixture(application: Application, model: Model):
    """The grafana-k8s application related to Jenkins via grafana-dashboard relation."""
    grafana = await model.deploy("grafana-k8s", channel="1/stable", trust=True)
    await model.wait_for_idle(
        status="active", apps=[grafana.name], raise_on_error=False, timeout=30 * 60
    )
    await model.add_relation(f"{application.name}:grafana-dashboard", grafana.name)
    await model.wait_for_idle(
        status="active",
        apps=[grafana.name, application.name],
        timeout=30 * 60,
        idle_period=30,
        raise_on_error=False,
    )
    return grafana
