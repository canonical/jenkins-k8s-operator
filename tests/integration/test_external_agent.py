# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import typing

import pytest
import pytest_asyncio
from juju.application import Application
from juju.model import Model

import state

from .helpers import get_model_unit_addresses


@pytest_asyncio.fixture(scope="module", name="agent_discovery_traefik")
async def agent_discovery_traefik_fixture(model: Model):
    """The application related to Jenkins via ingress v2 relation."""
    traefik = await model.deploy(
        "traefik-k8s",
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
        application_name="agent_discovery_traefik",
    )
    await model.wait_for_idle(
        status="active", apps=[traefik.name], timeout=20 * 60, idle_period=30, raise_on_error=False
    )
    unit_ips = await get_model_unit_addresses(model=model, app_name=traefik.name)
    assert unit_ips, f"Unit IP address not found for {traefik.name}"
    return (traefik, unit_ips[0])


@pytest_asyncio.fixture(scope="module", name="server_traefik")
async def server_traefik_fixture(model: Model):
    """The application related to Jenkins via ingress v2 relation."""
    traefik = await model.deploy(
        "traefik-k8s",
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
        application_name="server_traefik",
    )
    await model.wait_for_idle(
        status="active", apps=[traefik.name], timeout=20 * 60, idle_period=30, raise_on_error=False
    )
    unit_ips = await get_model_unit_addresses(model=model, app_name=traefik.name)
    assert unit_ips, f"Unit IP address not found for {traefik.name}"
    return (traefik, unit_ips[0])


# This will only work on microk8s !!
@pytest.mark.abort_on_fail
async def test_agent_discovery_ingress_integration(
    application: Application,
    agent_discovery_traefik: typing.Tuple[Application, str],
    server_traefik: typing.Tuple[Application, str],
    jenkins_machine_agents: Application,
):
    """
    arrange: deploy the Jenkins charm, ingress, and a machine agent.
    act: integrate the charms with each other.
    assert: All units should be in active status.
    """
    model = application.model
    machine_model = jenkins_machine_agents.model
    agent_discovery_traefik_application, _ = server_traefik
    server_ingress_traefik_application, _ = agent_discovery_traefik

    await application.relate(
        state.AGENT_DISCOVERY_INGRESS_RELATION_NAME,
        f"{agent_discovery_traefik_application.name}:ingress",
    )
    await application.relate(
        state.INGRESS_RELATION_NAME, f"{server_ingress_traefik_application.name}:ingress"
    )

    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, raise_on_error=False
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
