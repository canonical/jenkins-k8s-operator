# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

# pylint: disable=unused-argument

import typing

import pytest
import requests
from juju.application import Application
from juju.model import Model

import state
from charm import AGENT_DISCOVERY_INGRESS_RELATION_NAME


@pytest.mark.abort_on_fail
async def test_ingress_integration(
    model: Model,
    application: Application,
    traefik_application_and_unit_ip: typing.Tuple[Application, str],
    external_hostname: str,
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    traefik_application, traefik_address = traefik_application_and_unit_ip
    await application.relate("ingress", traefik_application.name)
    await model.wait_for_idle(
        apps=[application.name, traefik_application.name], wait_for_active=True, timeout=20 * 60
    )
    response = requests.get(
        f"http://{traefik_address}/{model.name}-{application.name}",
        headers={"Host": f"{external_hostname}"},
        timeout=5,
    )

    assert "Authentication required" in str(response.content)


# This will only work on microk8s !!
@pytest.mark.abort_on_fail
async def test_agent_discovery_ingress_integration(
    application: Application,
    traefik_application_and_unit_ip: typing.Tuple[Application, str],
    external_hostname: str,
    jenkins_machine_agents: Application,
):
    """
    arrange: deploy the Jenkins charm, ingress, and a machine agent.
    act: integrate the charms with each other and update the machine agent's dns record.
    assert: All units should be in active status.
    """
    model = application.model
    machine_model = jenkins_machine_agents.model
    traefik_application, traefik_address = traefik_application_and_unit_ip
    await application.relate(
        AGENT_DISCOVERY_INGRESS_RELATION_NAME, f"{traefik_application.name}:ingress"
    )
    # Add dns record
    ingress_hostname_mapping = (
        f"{traefik_address} {model.name}-{application.name}.{external_hostname}"
    )
    command = f"sudo echo '{ingress_hostname_mapping}' >> /etc/hosts"
    for unit in jenkins_machine_agents.units:
        action = await unit.run(command)
        await action.wait()

    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, raise_on_error=False
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
