# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

from dataclasses import dataclass

import jubilant
import pytest

import state

from .constants import LXD_CONTROLLER_NAME
from .helpers import short_model_name
from .resources import application_ref, ensure_application, ensure_integration
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
    agent_discovery = ensure_application(
        model,
        "traefik-k8s",
        name=agent_discovery_name,
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
    )
    server = ensure_application(
        model,
        "traefik-k8s",
        name=server_name,
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
    )
    return _IngressTraefiks(
        agent_discovery=application_ref(model, agent_discovery.name),
        server=application_ref(model, server.name),
    )


def test_agent_discovery_ingress_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    ingress_traefik: _IngressTraefiks,
    jenkins_machine_agents: JujuApplication,
    machine_model: jubilant.Juju,
) -> None:
    """Verify agent discovery and server ingress relations become active."""
    # Arrange
    ensure_integration(
        model,
        f"{application.name}:{state.AGENT_DISCOVERY_INGRESS_RELATION_NAME}",
        f"{ingress_traefik.agent_discovery.name}:ingress",
        applications=(application.name, ingress_traefik.agent_discovery.name),
    )
    ensure_integration(
        model,
        f"{application.name}:{state.INGRESS_RELATION_NAME}",
        f"{ingress_traefik.server.name}:ingress",
        applications=(application.name, ingress_traefik.server.name),
    )
    ensure_integration(
        model,
        f"{application.name}:{state.AGENT_RELATION}",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{state.AGENT_RELATION}",
        applications=(application.name,),
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, jenkins_machine_agents.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    # Act
    status = model.status()

    # Assert
    assert status.apps[application.name].is_active
    assert status.apps[ingress_traefik.agent_discovery.name].is_active
    assert status.apps[ingress_traefik.server.name].is_active
