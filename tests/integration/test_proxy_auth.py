# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

import pytest
import requests
from juju.application import Application
from juju.model import Model


@pytest.mark.abort_on_fail
async def test_auth_proxy_integration(
    model: Model, ingress_related: Application, external_hostname: str
):
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request to the ingress in /.
    assert: the response is not authorised.
    """
    status = await model.get_status(filters=[ingress_related.name])
    unit = next(iter(status.applications[ingress_related.name].units))
    response = requests.get(
        f"http://{unit.address}",
        headers={"Host": f"{model.name}-{ingress_related.name}.{external_hostname}"},
        timeout=5,
    ).json()
    assert response.status_code == 401
