# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import pytest
import pytest_asyncio
from juju.application import Application
from juju.client._definitions import FullStatus
from juju.model import Model
from pytest import FixtureRequest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module", name="model")
def model_fixture(ops_test: OpsTest) -> Model:
    """The testing model."""
    assert ops_test.model
    return ops_test.model


@pytest.fixture(scope="module", name="jenkins_image")
def jenkins_image_fixture(request: FixtureRequest) -> str:
    """The OCI image for Jenkins charm."""
    jenkins_image = request.config.getoption("--jenkins-image")
        jenkins_image
    ), "--jenkins-image argument is required which should contain the name of the OCI image."
    return jenkins_image


@pytest_asyncio.fixture(scope="module", name="application")
async def application_fixture(ops_test: OpsTest, model: Model, jenkins_image: str) -> Application:
    """Build and deploy the charm."""
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    resources = {"jenkins-image": jenkins_image}

    # Deploy the charm and wait for active/idle status
    application = await model.deploy(charm, resources=resources, series="jammy")
    await model.wait_for_idle(
        apps=[application.name], status="active", raise_on_blocked=True, timeout=1000
    )

    return application


@pytest_asyncio.fixture(scope="module", name="unit_ip")
async def unit_ip_fixture(model: Model, application: Application):
    """Get Jenkins charm unit IP."""
    status: FullStatus = await model.get_status([application.name])
    for unit in status.applications[application.name].units.values():
        assert unit, "Invalid unit status."
        assert unit.address, "Unit does not have an assigned IP."
        return str(unit.address)


@pytest_asyncio.fixture(scope="module", name="web_address")
async def web_address_fixture(unit_ip: str):
    """Get Jenkins charm web address."""
    return f"http://{unit_ip}:8080"
