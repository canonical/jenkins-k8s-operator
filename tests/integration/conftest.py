# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

# subprocess module is required to bootstrap controllers for testing.
import subprocess  # nosec
import textwrap
import typing
from pathlib import Path
from random import choices
from string import ascii_lowercase, digits

import jenkinsapi.jenkins
import pytest
import pytest_asyncio
from juju.action import Action
from juju.application import Application
from juju.client._definitions import FullStatus, UnitStatus
from juju.client.jujudata import FileJujuData
from juju.model import Controller, Model
from juju.unit import Unit
from pytest import FixtureRequest
from pytest_operator.plugin import OpsTest


@pytest_asyncio.fixture(scope="module", name="model")
async def model_fixture(ops_test: OpsTest) -> Model:
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


@pytest.fixture(scope="module", name="controller_model_name")
def controller_model_name_fixture(request: pytest.FixtureRequest) -> str:
    """The name for machine controller and model."""
    # This is taken from the same logic in pytest_operator plugin.py _generate_model_name
    # to match the ops test naming.
    module_name = request.module.__name__.rpartition(".")[-1]
    suffix = "".join(choices(ascii_lowercase + digits, k=4))  # nosec
    return f"{module_name.replace('_', '-')}-{suffix}"


@pytest_asyncio.fixture(scope="module", name="machine_controller")
async def machine_controller_fixture(
    request: pytest.FixtureRequest, controller_model_name: str
) -> typing.AsyncGenerator[Controller, None]:
    """The lxd controller."""
    prev_controller_name = FileJujuData().current_controller()
    # bandit will warn about partial process path in executable, but juju executable can be trusted
    # in a test environment.
    res = subprocess.run(
        ["juju", "bootstrap", "localhost", controller_model_name],
        capture_output=True,
        check=False,  # nosec
    )
    assert res.returncode == 0, f"failed to bootstrap localhost, {res=!r}"
    # bandit will warn about partial process path in executable, but juju executable can be trusted
    # in a test environment.
    res = subprocess.run(["juju", "switch", prev_controller_name], check=False)  # nosec
    assert res.returncode == 0, f"failed to switch back to original controller, {res=!r}"
    controller = Controller()
    await controller.connect_controller(controller_model_name)

    yield controller

    if not request.config.option.keep_models:
        # bandit will warn about partial process path in executable, but juju executable can be
        # trusted in a test environment.
        res = subprocess.run(  # nosec
            [
                "juju",
                "destroy-controller",
                "-y",
                controller_model_name,
                "--force",
                "--destroy-all-models",
            ],
            check=False,
            capture_output=True,
        )
        assert res.returncode == 0, f"failed to clean up controller, {res=!r}"
    # Disconnection is required for the coroutine tasks to finish.
    await controller.disconnect()


@pytest_asyncio.fixture(scope="module", name="machine_model")
async def machine_model_fixture(
    request: pytest.FixtureRequest, machine_controller: Controller, controller_model_name: str
) -> typing.AsyncGenerator[Model, None]:
    """The machine model."""
    model = await machine_controller.add_model(controller_model_name)

    yield model

    if not request.config.option.keep_models:
        await machine_controller.destroy_models(model.name, destroy_storage=True, force=True)
        # Disconnection is required for the coroutine tasks to finish.
    await model.disconnect()


@pytest_asyncio.fixture(scope="module", name="jenkins_machine_agent")
async def jenkins_machine_agent_fixture(machine_model: Model) -> Application:
    """The machine model controller."""
    app = await machine_model.deploy(
        "jenkins-agent", channel="latest/edge", config={"labels": "machine"}
    )
    await machine_model.wait_for_idle(apps=[app.name], status="blocked", timeout=1200)
    await machine_model.create_offer(f"{app.name}:slave")

    return app
