# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

from dataclasses import dataclass

import pytest
import pytest_asyncio
from juju.application import Application
from juju.model import Model

import state


@dataclass
class _IngressTraefiks:
    """The ingress applications for Jenkins server.

    Attributes:
        agent_discovery: The ingress application for agent discovery.
        server: The ingress application for Jenkins server.
    """

    agent_discovery: Application
    server: Application


@pytest_asyncio.fixture(scope="module", name="ingress_traefik")
async def ingress_traefik_fixture(model: Model):
    """The application related to Jenkins via ingress v2 relation."""
    agent_discovery_traefik = await model.deploy(
        "traefik-k8s",
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
        application_name="agent-discovery-traefik",
    )
    server_traefik = await model.deploy(
        "traefik-k8s",
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
        application_name="server-traefik",
    )
    await model.wait_for_idle(
        status="active",
        apps=[agent_discovery_traefik.name, server_traefik.name],
        timeout=20 * 60,
        idle_period=30,
        raise_on_error=False,
    )
    return _IngressTraefiks(agent_discovery=agent_discovery_traefik, server=server_traefik)


# This will only work on microk8s !!
@pytest.mark.abort_on_fail
async def test_agent_discovery_ingress_integration(
    application: Application,
    ingress_traefik: _IngressTraefiks,
    jenkins_machine_agents: Application,
):
    """
    arrange: deploy the Jenkins charm, ingress, and a machine agent.
    act: integrate the charms with each other.
    assert: All units should be in active status.
    """
    model = application.model
    machine_model = jenkins_machine_agents.model

    await application.relate(
        state.AGENT_DISCOVERY_INGRESS_RELATION_NAME,
        f"{ingress_traefik.agent_discovery.name}:ingress",
    )
    await application.relate(state.INGRESS_RELATION_NAME, f"{ingress_traefik.server.name}:ingress")

    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, raise_on_error=False
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
