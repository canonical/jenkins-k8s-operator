# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

from dataclasses import dataclass

import jubilant
import pytest

import state

from .constants import LXD_CONTROLLER_NAME
from .helpers import short_model_name
from .types_ import JujuApplication


@dataclass(frozen=True)
class _IngressTraefiks:
    """The ingress applications for the Jenkins server."""

    agent_discovery: JujuApplication
    server: JujuApplication


@pytest.fixture(scope="module", name="ingress_traefik")
def ingress_traefik_fixture(model: jubilant.Juju) -> _IngressTraefiks:
    """Deploy the two Traefik applications used by the ingress test."""
    agent_discovery_name = "agent-discovery-traefik"
    server_name = "server-traefik"
    for name in (agent_discovery_name, server_name):
        model.deploy(
            "traefik-k8s",
            app=name,
            channel="edge",
            trust=True,
            config={"routing_mode": "path"},
        )
    model.wait(
        lambda status: jubilant.all_active(status, agent_discovery_name, server_name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return _IngressTraefiks(
        agent_discovery=JujuApplication(
            name=agent_discovery_name,
            model=model,
            units=tuple(model.status().apps[agent_discovery_name].units),
        ),
        server=JujuApplication(
            name=server_name,
            model=model,
            units=tuple(model.status().apps[server_name].units),
        ),
    )


def test_agent_discovery_ingress_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    ingress_traefik: _IngressTraefiks,
    jenkins_machine_agents: JujuApplication,
    machine_model: jubilant.Juju,
) -> None:
    """Verify agent discovery and server ingress relations become active."""
    model.integrate(
        f"{application.name}:{state.AGENT_DISCOVERY_INGRESS_RELATION_NAME}",
        f"{ingress_traefik.agent_discovery.name}:ingress",
    )
    model.integrate(
        f"{application.name}:{state.INGRESS_RELATION_NAME}",
        f"{ingress_traefik.server.name}:ingress",
    )
    model.integrate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{state.AGENT_RELATION}",
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, jenkins_machine_agents.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
