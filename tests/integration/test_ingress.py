# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""


# pylint: disable=unused-argument

import pytest
import requests
from juju.application import Application
from juju.model import Model

import jenkins


@pytest.mark.abort_on_fail
async def test_ingress_integration(
    model: Model, application: Application, ingress_related: Application, external_hostname: str
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    status = await model.get_status(filters=[application.name])
    unit = next(iter(status.applications[application.name].units))
    address = status["applications"][application.name]["units"][unit]["address"]
    response = requests.get(
        f"http://{address}:{jenkins.WEB_PORT}{jenkins.LOGIN_PATH}",
        headers={"Host": f"{model.name}-{application.name}.{external_hostname}"},
        timeout=5,
    )
    assert response.status_code == 200
