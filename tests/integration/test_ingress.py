# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import pytest
import requests
from juju.application import Application
from juju.model import Model


@pytest.mark.abort_on_fail
async def test_ingress_integration(
    model: Model, application: Application, ingress_related: Application, external_hostname: str
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    status = await model.get_status(filters=[ingress_related.name])
    unit = next(iter(status.applications[ingress_related.name].units))
    address = status["applications"][ingress_related.name]["units"][unit]["address"]
    print(address)
    response = requests.get(
        f"http://{address}",
        headers={"Host": f"{model.name}-{application.name}.{external_hostname}"},
        timeout=5,
    ).json()
    assert response.status_code == 200
