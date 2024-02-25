# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""


# pylint: disable=unused-argument

import pytest
import requests
from juju.application import Application
from juju.model import Model

import jenkins
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

    status = await model.get_status(filters=[traefik_application.name])
    unit = next(iter(status.applications[traefik_application.name].units))
    traefik_address = status["applications"][traefik_application.name]["units"][unit]["address"]
    response = requests.get(
        f"http://{traefik_address}:{jenkins.WEB_PORT}{jenkins.LOGIN_PATH}",
        headers={"Host": f"{model.name}-{application.name}.{external_hostname}"},
        timeout=5,
    )
    assert response.status_code == 200


@pytest.mark.abort_on_fail
async def test_agent_discovery_ingress_integration(
    model: Model,
    application: Application,
    traefik_application: Application,
    external_hostname: str,
    jenkins_k8s_agents: Application,
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    await application.relate(state.AGENT_RELATION, jenkins_k8s_agents.name)
    await application.relate(AGENT_DISCOVERY_INGRESS_RELATION_NAME, traefik_application.name)

    await model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name, traefik_application.name],
        wait_for_active=True,
    )

    agent_discovery_url_verified = False
    for relation in application.relations:
        if set([jenkins_k8s_agents.name, application.name]) == set(relation.applications):
            assert (
                relation.data[application.units[0].name]["url"]
                == f"{model.name}-{application.name}.{external_hostname}"
            )
            agent_discovery_url_verified = True
    assert agent_discovery_url_verified
