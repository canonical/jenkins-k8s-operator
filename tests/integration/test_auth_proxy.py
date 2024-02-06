# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

import pytest
import requests
from juju.application import Application
from juju.model import Model


@pytest.mark.abort_on_fail
async def test_auth_proxy_integration_retuns_not_authorized(
    model: Model, oathkeeper_related: Application, external_hostname: str
):
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request to the ingress in /.
    assert: a 401 is returned.
    """
    status = await model.get_status(filters=[oathkeeper_related.name])
    unit = next(iter(status.applications[oathkeeper_related.name].units))
    response = requests.get(
        f"http://{unit.address}",
        headers={"Host": f"{model.name}-{oathkeeper_related.name}.{external_hostname}"},
        timeout=5,
    ).json()
    assert response.status_code == 401
