# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import secrets
import textwrap
import typing

import jenkinsapi.jenkins
import pytest
import pytest_asyncio
from juju.action import Action
from juju.application import Application
from juju.client._definitions import FullStatus, UnitStatus
from juju.model import Controller, Model
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
    agent_app: Application = await model.deploy(
        "jenkins-agent-k8s", config={"jenkins_agent_labels": "k8s"}
    )
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

    # Initialization of the jenkins client will raise an exception if unable to connect to the
    # server.
    return jenkinsapi.jenkins.Jenkins(
        baseurl=web_address, username="admin", password=password, timeout=60
    )


@pytest.fixture(scope="module", name="gen_jenkins_test_job_xml")
def gen_jenkins_test_job_xml_fixture() -> typing.Callable[[str], str]:
    """The Jenkins test job xml with given node label on an agent node."""
    return lambda label: textwrap.dedent(
        f"""
        <project>
            <actions/>
            <description/>
            <keepDependencies>false</keepDependencies>
            <properties/>
            <scm class="hudson.scm.NullSCM"/>
            <assignedNode>{label}</assignedNode>
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


@pytest_asyncio.fixture(scope="module", name="machine_controller")
async def machine_controller_fixture() -> Controller:
    """The lxd controller."""
    controller = Controller()
    await controller.connect_controller("localhost")

    return controller


@pytest_asyncio.fixture(scope="module", name="machine_model")
async def machine_model_fixture(
    request: pytest.FixtureRequest, machine_controller: Controller
) -> typing.AsyncGenerator[Model, None]:
    """The machine model for jenkins agent machine charm."""
    machine_model_name = f"jenkins-agent-machine-{secrets.token_hex(2)}"
    model = await machine_controller.add_model(machine_model_name)

    yield model

    if not request.config.option.keep_models:
        await machine_controller.destroy_models(model.name, force=True)
        # Disconnection is required for the coroutine tasks to finish.
    await model.disconnect()


@pytest_asyncio.fixture(scope="module", name="jenkins_machine_agent")
async def jenkins_machine_agent_fixture(machine_model: Model) -> Application:
    """The jenkins machine agent."""
    # 2023-06-02 use the edge version of jenkins agent until the changes have been promoted to
    # stable.
    app = await machine_model.deploy(
        "jenkins-agent", channel="latest/edge", config={"labels": "machine"}
    )
    await machine_model.wait_for_idle(apps=[app.name], status="blocked", timeout=1200)

    return app
