# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import textwrap

import jenkinsapi.jenkins
import pytest
import pytest_asyncio
from juju.action import Action
from juju.application import Application
from juju.client._definitions import FullStatus, UnitStatus
from juju.model import Model
from juju.unit import Unit
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
    assert (
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
    await model.wait_for_idle(apps=[application.name], status="active", raise_on_blocked=True)

    return application


@pytest_asyncio.fixture(scope="module", name="unit_ip")
async def unit_ip_fixture(model: Model, application: Application):
    """Get Jenkins charm unit IP."""
    status: FullStatus = await model.get_status([application.name])
    try:
        unit_status: UnitStatus = next(iter(status.applications[application.name].units.values()))
        assert unit_status.address, "Invalid unit address"
        return unit_status.address
    except StopIteration as exc:
        raise StopIteration("Invalid unit status") from exc


@pytest_asyncio.fixture(scope="module", name="web_address")
async def web_address_fixture(unit_ip: str):
    """Get Jenkins charm web address."""
    return f"http://{unit_ip}:8080"


@pytest_asyncio.fixture(scope="module", name="jenkins_k8s_agent")
async def jenkins_k8s_agent(model: Model) -> Application:
    """The Jenkins k8s agent."""
    agent_app: Application = await model.deploy("jenkins-agent-k8s")
    await model.wait_for_idle(apps=[agent_app.name], status="blocked")
    return agent_app


@pytest_asyncio.fixture(scope="module", name="jenkins_client")
async def jenkins_client_fixture(
    application: Application,
    web_address: str,
) -> jenkinsapi.jenkins.Jenkins:
    """The Jenkins API client."""
    jenkins_unit: Unit = application.units[0]
    action: Action = await jenkins_unit.run_action("get-admin-password")
    await action.wait()
    password = action.results["password"]

    return jenkinsapi.jenkins.Jenkins(
        baseurl=web_address, username="admin", password=password, timeout=60
    )


@pytest.fixture(scope="module", name="jenkins_test_job_xml")
def jenkins_test_job_xml() -> str:
    """The Jenkins test job xml with node label x86_64, the default label on an agent node."""
    return textwrap.dedent(
        """
        <project>
            <actions/>
            <description/>
            <keepDependencies>false</keepDependencies>
            <properties/>
            <scm class="hudson.scm.NullSCM"/>
            <assignedNode>x86_64</assignedNode>
            <canRoam>false</canRoam>
            <disabled>false</disabled>
            <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>
            <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>
            <triggers/>
            <concurrentBuild>false</concurrentBuild>
            <builders>
                <hudson.tasks.Shell>
                    <command>echo "hello world"</command>
                    <configuredLocalRules/>
                </hudson.tasks.Shell>
            </builders>
            <publishers/>
            <buildWrappers/>
        </project>
        """
    )
