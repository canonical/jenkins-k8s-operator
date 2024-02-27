# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""


# pylint: disable=unused-argument

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
    traefik_application: Application,
    external_hostname: str,
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    await application.relate("ingress", traefik_application.name)
    # Find traefik IP
    status = await model.get_status(filters=[traefik_application.name])
    unit = next(iter(status.applications[traefik_application.name].units))
    traefik_address = status["applications"][traefik_application.name]["units"][unit]["address"]
    response = requests.get(
        f"http://{traefik_address}",
        headers={"Host": f"{model.name}-{application.name}.{external_hostname}"},
        timeout=5,
    )
    assert response.status_code == 200


# This will only work on microk8s !!
@pytest.mark.abort_on_fail
async def test_agent_discovery_ingress_integration(
    model: Model,
    application: Application,
    traefik_application: Application,
    external_hostname: str,
    jenkins_machine_agents: Application,
):
    """
    arrange: deploy the Jenkins charm, ingress, and a machine agent.
    act: integrate the charms with each other and update the machine agent's dns record.
    assert: All units should be in active status.
    """
    await application.relate(
        AGENT_DISCOVERY_INGRESS_RELATION_NAME, f"{traefik_application.name}:ingress"
    )
    # Find traefik IP
    status = await model.get_status(filters=[traefik_application.name])
    unit = next(iter(status.applications[traefik_application.name].units))
    traefik_address = status["applications"][traefik_application.name]["units"][unit]["address"]
    # Add dns record
    ingress_hostname = f"{traefik_address} {model.name}-{application.name}.{external_hostname}"
    command = f"sudo echo '{ingress_hostname}' >> /etc/hosts"
    for unit in jenkins_machine_agents.units:
        action = await unit.run(command)
        await action.wait()

    model = application.model
    machine_model = jenkins_machine_agents.model
    # this code is similar to the machine_agent_related_app fixture but shouldn't be using the
    # fixture since this test tests for teardown of relation as well.
    # pylint: disable=duplicate-code
    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, raise_on_error=False
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
