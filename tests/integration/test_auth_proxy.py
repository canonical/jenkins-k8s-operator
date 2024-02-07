# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

# pylint: disable=unused-argument

import pytest
import requests
from juju.application import Application
from juju.model import Model


@pytest.mark.abort_on_fail
async def test_auth_proxy_integration_retuns_not_authorized(
    model: Model, application: Application, oathkeeper_related: Application, external_hostname: str
):
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request to the ingress in /.
    assert: a 401 is returned.
    """
    status = await model.get_status(filters=[application.name])
    unit = next(iter(status.applications[application.name].units))
    address = status["applications"][application.name]["units"][unit]["address"]
    response = requests.get(
        f"http://{unit.address}:{jenkins.WEB_PORT}",
        headers={"Host": f"{model.name}-{application.name}.{external_hostname}"},
        timeout=5,
    )
    assert response.status_code == 401
