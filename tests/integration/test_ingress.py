# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import pytest
import requests
from juju.application import Application
from pytest_operator.plugin import OpsTest


@pytest.mark.abort_on_fail
async def test_ingress_integration(
    ops_test: OpsTest, ingress_related: Application, external_hostname: str
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    assert ops_test.model
    status = await ops_test.model.get_status(filters=[ingress_related.name])
    for unit in status.applications[ingress_related.name].units.values():
        response = requests.get(
            f"http://{unit.address}",
            headers={"Host": f"{ops_test.model_name}-{ingress_related.name}.{external_hostname}"},
            timeout=5,
        ).json()
        assert response.status_code == 200
