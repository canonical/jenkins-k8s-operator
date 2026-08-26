# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Gateway API agent-discovery integration tests on Canonical Kubernetes."""

import json
from collections.abc import Generator
from typing import Any

import jubilant
import pytest

GATEWAY_APP = "jenkins-gateway-api"
INGRESS_APP = "jenkins-agent-ingress-configurator"
JENKINS_APP = "jenkins"
AGENT_APP = "jenkins-machine-agent"
AGENT_RELATION = "agent"
AGENT_HOSTNAME = "jenkins-agent.internal"


@pytest.fixture(scope="module")
def k8s_juju() -> Generator[jubilant.Juju, None, None]:
    """Connect to the Canonical Kubernetes model provisioned by Concierge."""
    juju = jubilant.Juju(model="concierge-k8s:k8s", wait_timeout=30 * 60)
    yield juju


@pytest.fixture(scope="module")
def machine_juju(k8s_juju: jubilant.Juju) -> Generator[jubilant.Juju, None, None]:
    """Create the machine model used by the external Jenkins agent."""
    try:
        k8s_juju.cli("show-model", "concierge-lxd:testing", include_model=False)
    except jubilant.CLIError:
        k8s_juju.cli("add-model", "--controller", "concierge-lxd", "testing", include_model=False)
    yield jubilant.Juju(model="concierge-lxd:testing", wait_timeout=30 * 60)


@pytest.fixture(scope="module")
def jenkins(
    k8s_juju: jubilant.Juju,
    charm_paths: Any,
    charm_resource_images: Any,
) -> str:
    """Deploy Jenkins from the charm-ci build artifacts."""
    k8s_juju.deploy(
        charm_paths[JENKINS_APP].path,
        app=JENKINS_APP,
        base="ubuntu@24.04",
        resources=charm_resource_images[JENKINS_APP],
        trust=True,
    )
    k8s_juju.wait(lambda status: jubilant.all_active(status, JENKINS_APP), timeout=30 * 60)
    return JENKINS_APP


@pytest.fixture(scope="module")
def gateway(k8s_juju: jubilant.Juju) -> str:
    """Deploy Canonical's Gateway API implementation."""
    k8s_juju.deploy(
        "gateway-api-integrator",
        app=GATEWAY_APP,
        channel="1/stable",
        base="ubuntu@24.04",
        config={"gateway-class": "ck-gateway"},
        trust=True,
    )
    k8s_juju.deploy(
        "ingress-configurator",
        app=INGRESS_APP,
        channel="latest/stable",
        base="ubuntu@24.04",
        config={"hostname": AGENT_HOSTNAME},
        trust=True,
    )
    k8s_juju.integrate(f"{GATEWAY_APP}:gateway-route", f"{INGRESS_APP}:gateway-route")
    k8s_juju.integrate(f"{JENKINS_APP}:agent-discovery-ingress", f"{INGRESS_APP}:ingress")
    k8s_juju.wait(
        lambda status: jubilant.all_active(status, GATEWAY_APP, INGRESS_APP),
        timeout=30 * 60,
    )
    return INGRESS_APP


@pytest.fixture(scope="module")
def machine_agent(machine_juju: jubilant.Juju) -> str:
    """Deploy the machine agent and publish its relation offer."""
    machine_juju.deploy(
        "jenkins-agent",
        app=AGENT_APP,
        channel="latest/stable",
        config={"jenkins_agent_labels": "machine"},
        num_units=2,
    )
    machine_juju.offer(AGENT_APP, endpoint=AGENT_RELATION, name=AGENT_RELATION)
    machine_juju.wait(
        lambda status: status.apps[AGENT_APP].app_status.current == "blocked", timeout=20 * 60
    )
    return AGENT_APP


def _relation_url(juju: jubilant.Juju, unit: str) -> str:
    """Read the URL published on a unit's agent relation."""
    data = json.loads(juju.cli("show-unit", unit, "--format=json"))
    relation_info = next(
        relation
        for relation in data[unit]["relation-info"]
        if relation["endpoint"] == AGENT_RELATION
    )
    return next(iter(relation_info["related-units"].values()))["data"]["url"]


def test_gateway_agent_discovery(
    k8s_juju: jubilant.Juju,
    machine_juju: jubilant.Juju,
    jenkins: str,
    gateway: str,
    machine_agent: str,
) -> None:
    """Machine agents receive the dedicated Gateway URL, not the server route."""
    k8s_juju.integrate(
        f"{jenkins}:{AGENT_RELATION}",
        f"concierge-lxd:admin/testing.{AGENT_RELATION}",
    )
    k8s_juju.wait(lambda status: jubilant.all_active(status, jenkins, gateway), timeout=30 * 60)
    machine_juju.wait(lambda status: jubilant.all_active(status, machine_agent), timeout=30 * 60)

    for unit in machine_juju.status().apps[machine_agent].units:
        url = _relation_url(machine_juju, unit)
        assert AGENT_HOSTNAME in url
        assert not url.startswith("http://10.")
