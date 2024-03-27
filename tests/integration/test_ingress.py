# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import typing

import pytest
import requests
from juju.application import Application
from juju.model import Model


@pytest.mark.abort_on_fail
async def test_ingress_integration(
    model: Model,
    application: Application,
    traefik_application_and_unit_ip: typing.Tuple[Application, str],
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
        timeout=5,
    )

    assert "Authentication required" in str(response.content)
