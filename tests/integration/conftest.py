# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import random
import re
import secrets
import string
import typing

import jenkinsapi.jenkins
import kubernetes.client
import kubernetes.config
import kubernetes.stream
import pytest
import pytest_asyncio
import requests
import yaml
from juju.action import Action
from juju.application import Application
from juju.client._definitions import FullStatus, UnitStatus
from juju.model import Controller, Model
from juju.unit import Unit
from pytest import FixtureRequest
from pytest_operator.plugin import OpsTest

import jenkins
import state

from .constants import ALLOWED_PLUGINS
from .helpers import get_pod_ip
from .types_ import ModelAppUnit, TestLDAPSettings, UnitWebClient


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


@pytest.fixture(scope="module", name="num_units")
def num_units_fixture(request: FixtureRequest) -> int:
    """The OCI image for Jenkins charm."""
    return int(request.config.getoption("--num-units"))


@pytest_asyncio.fixture(scope="module", name="charm")
async def charm_fixture(request: FixtureRequest, ops_test: OpsTest) -> str:
    """The path to charm."""
    charm = request.config.getoption("--charm-file")
    if not charm:
        charm = await ops_test.build_charm(".")
    else:
        charm = f"./{charm}"

    return charm


@pytest_asyncio.fixture(scope="module", name="application")
async def application_fixture(
    ops_test: OpsTest, charm: str, model: Model, jenkins_image: str
) -> typing.AsyncGenerator[Application, None]:
    """Deploy the charm."""
    resources = {"jenkins-image": jenkins_image}

    # Deploy the charm and wait for active/idle status
    application = await model.deploy(charm, resources=resources, series="jammy")
    await model.wait_for_idle(
        apps=[application.name],
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=20 * 60,
        idle_period=30,
    )
    # slow down update-status so that it doesn't intervene currently running tests
    # don't yield inside the context since juju cleanup is not reliable.
    # model.set_config(...) also doesn't work as well as the following code.
    async with ops_test.fast_forward(fast_interval="5h", slow_interval="5h"):
        pass
    yield application


@pytest.fixture(scope="module", name="unit")
def unit_fixture(application: Application) -> Unit:
    """The Jenkins-k8s charm application unit."""
    return application.units[0]


@pytest.fixture(scope="module", name="model_app_unit")
def model_app_unit_fixture(model: Model, application: Application, unit: Unit):
    """The packaged model, application, unit of Jenkins to reduce number of parameters in tests."""
    return ModelAppUnit(model=model, app=application, unit=unit)


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


@pytest.fixture(scope="module", name="web_address")
def web_address_fixture(unit_ip: str):
    """Get Jenkins charm web address."""
    return f"http://{unit_ip}:8080"


@pytest_asyncio.fixture(scope="function", name="jenkins_client")
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


@pytest.fixture(scope="function", name="unit_web_client")
def unit_web_client_fixture(
    unit: Unit, web_address: str, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """The wrapper around unit, web_address and jenkins_client."""
    return UnitWebClient(unit=unit, web=web_address, client=jenkins_client)


@pytest.fixture(scope="function", name="app_suffix")
def app_suffix_fixture():
    """Get random 4 char length application suffix."""
    # secrets random hex cannot be used because it has chances to generate numeric only suffix
    # which will return "<application-name> is not a valid application tag"
    app_suffix = "".join(random.choices(string.ascii_lowercase, k=4))  # nosec
    return app_suffix


@pytest_asyncio.fixture(scope="function", name="jenkins_k8s_agents")
async def jenkins_k8s_agents_fixture(
    model: Model, app_suffix: str
) -> typing.AsyncGenerator[Application, None]:
    """The Jenkins k8s agent."""
    agent_app: Application = await model.deploy(
        "jenkins-agent-k8s",
        config={"jenkins_agent_labels": "k8s"},
        channel="latest/edge",
        application_name=f"jenkins-agentk8s-{app_suffix}",
    )
    await model.wait_for_idle(apps=[agent_app.name], status="blocked")

    yield agent_app


@pytest_asyncio.fixture(scope="function", name="app_k8s_agent_related")
async def app_k8s_agent_related_fixture(
    jenkins_k8s_agents: Application,
    application: Application,
):
    """The Jenkins-k8s server charm related to Jenkins-k8s agent charm through agent relation."""
    await application.relate(
        state.AGENT_RELATION, f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}"
    )
    await application.model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name], wait_for_active=True, check_freq=5
    )

    yield application


@pytest_asyncio.fixture(scope="function", name="extra_jenkins_k8s_agents")
async def extra_jenkins_k8s_agents_fixture(
    model: Model,
) -> typing.AsyncGenerator[Application, None]:
    """The Jenkins k8s agent."""
    agent_app: Application = await model.deploy(
        "jenkins-agent-k8s",
        config={"jenkins_agent_labels": "k8s-extra"},
        channel="latest/edge",
        application_name="jenkins-agentk8s-extra",
    )
    await model.wait_for_idle(apps=[agent_app.name], status="blocked")

    yield agent_app


@pytest_asyncio.fixture(scope="function", name="app_k8s_deprecated_agent_related")
async def app_k8s_deprecated_agent_related_fixture(
    jenkins_k8s_agents: Application,
    application: Application,
):
    """The Jenkins-k8s charm related to Jenkins-k8s agent through deprecated agent relation."""
    await application.relate(state.DEPRECATED_AGENT_RELATION, jenkins_k8s_agents.name)
    await application.model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name], wait_for_active=True
    )

    yield application


@pytest_asyncio.fixture(scope="module", name="machine_controller")
async def machine_controller_fixture() -> typing.AsyncGenerator[Controller, None]:
    """The lxd controller."""
    controller = Controller()
    await controller.connect_controller("localhost")

    yield controller

    await controller.disconnect()


@pytest_asyncio.fixture(scope="module", name="machine_model")
async def machine_model_fixture(
    machine_controller: Controller,
) -> typing.AsyncGenerator[Model, None]:
    """The machine model for jenkins agent machine charm."""
    machine_model_name = f"jenkins-agent-machine-{secrets.token_hex(2)}"
    model = await machine_controller.add_model(machine_model_name)
    await model.connect(f"localhost:admin/{model.name}")

    yield model

    await model.disconnect()


@pytest_asyncio.fixture(scope="function", name="jenkins_machine_agents")
async def jenkins_machine_agents_fixture(
    machine_model: Model, num_units: int, app_suffix: str
) -> typing.AsyncGenerator[Application, None]:
    """The jenkins machine agent with 3 units to be used for new agent relation."""
    # 2023-06-02 use the edge version of jenkins agent until the changes have been promoted to
    # stable.
    app: Application = await machine_model.deploy(
        "jenkins-agent",
        channel="latest/edge",
        config={"labels": "machine"},
        application_name=f"jenkins-agent-{app_suffix}",
        num_units=num_units,
    )
    await machine_model.create_offer(f"{app.name}:{state.AGENT_RELATION}", state.AGENT_RELATION)
    await machine_model.create_offer(f"{app.name}:slave", state.DEPRECATED_AGENT_RELATION)
    await machine_model.wait_for_idle(
        apps=[app.name], status="blocked", idle_period=30, timeout=1200, check_freq=5
    )

    yield app


@pytest_asyncio.fixture(scope="function", name="app_machine_agent_related")
async def app_machine_agent_related_fixture(
    jenkins_machine_agents: Application,
    application: Application,
):
    """The Jenkins-k8s server charm related to Jenkins agent charm through agent relation."""
    model: Model = application.model
    machine_model: Model = jenkins_machine_agents.model
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, check_freq=5
    )
    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, check_freq=5
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)

    yield application


@pytest_asyncio.fixture(scope="function", name="app_machine_deprecated_agent_related")
async def app_machine_deprecated_agent_related_fixture(
    jenkins_machine_agents: Application,
    application: Application,
):
    """The Jenkins-k8s server charm related to Jenkins agent charm through agent relation."""
    model: Model = application.model
    machine_model: Model = jenkins_machine_agents.model
    await model.relate(
        f"{application.name}:{state.DEPRECATED_AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.DEPRECATED_AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(apps=[jenkins_machine_agents.name], wait_for_active=True)
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)

    yield application


@pytest.fixture(scope="module", name="jenkins_version")
def jenkins_version_fixture() -> str:
    """The currently installed Jenkins version from rock image."""
    with open("jenkins_rock/rockcraft.yaml", encoding="utf-8") as rockcraft_yaml_file:
        rockcraft_yaml = yaml.safe_load(rockcraft_yaml_file)
        return str(rockcraft_yaml["parts"]["jenkins"]["build-environment"][0]["JENKINS_VERSION"])


@pytest_asyncio.fixture(scope="module", name="latest_jenkins_lts_version")
async def latest_jenkins_lts_version_fixture(jenkins_version: str) -> str:
    """The latest LTS version of the current Jenkins version."""
    # get RSS feed
    rss_feed_response = requests.get(jenkins.RSS_FEED_URL, timeout=10)
    assert rss_feed_response.status_code == 200, "Failed to fetch RSS feed."
    rss_xml = str(rss_feed_response.content, encoding="utf-8")
    # extract all version strings from feed
    pattern = r"\d+\.\d+\.\d+"
    matches = re.findall(pattern, rss_xml)
    # find first matching version starting with same <major>.<minor> version, the rss feed is
    # sorted by latest first.
    current_major_minor = ".".join(jenkins_version.split(".")[:2])
    matched_latest_version = next((v for v in matches if v.startswith(current_major_minor)), None)
    assert matched_latest_version is not None, "Failed to find a matching LTS version."
    return matched_latest_version


@pytest.fixture(scope="module", name="freeze_time")
def freeze_time_fixture() -> str:
    """The time string to freeze the charm time."""
    return "2022-01-01 15:00:00"


@pytest_asyncio.fixture(scope="function", name="app_with_restart_time_range")
async def app_with_restart_time_range_fixture(application: Application):
    """Application with restart-time-range configured."""
    await application.set_config({"restart-time-range": "03-05"})

    yield application

    await application.reset_config(["restart-time-range"])


@pytest_asyncio.fixture(scope="function", name="libfaketime_unit")
async def libfaketime_unit_fixture(ops_test: OpsTest, unit: Unit) -> Unit:
    """Unit with libfaketime installed."""
    await ops_test.juju("run", "--unit", f"{unit.name}", "--", "apt", "update")
    await ops_test.juju(
        "run", "--unit", f"{unit.name}", "--", "apt", "install", "-y", "libfaketime"
    )
    return unit


@pytest.fixture(scope="function", name="libfaketime_env")
def libfaketime_env_fixture(freeze_time: str) -> typing.Iterable[str]:
    """The environment variables for using libfaketime."""
    return (
        'LD_PRELOAD="/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"',
        f'FAKETIME="@{freeze_time}"',
    )


@pytest.fixture(scope="function", name="update_status_env")
def update_status_env_fixture(model: Model, unit: Unit) -> typing.Iterable[str]:
    """The environment variables for executing Juju hooks."""
    return (
        "JUJU_DISPATCH_PATH=hooks/update-status",
        f"JUJU_MODEL_NAME={model.name}",
        f"JUJU_UNIT_NAME={unit.name}",
    )


@pytest.fixture(scope="module", name="kube_config")
def kube_config_fixture(request: FixtureRequest) -> str:
    """The kubernetes config file path."""
    kube_config = request.config.getoption("--kube-config")
    assert (
        kube_config
    ), "--kube-confg argument is required which should contain the path to kube config."
    return kube_config


@pytest.fixture(scope="module", name="kube_core_client")
def kube_core_client_fixture(kube_config: str) -> kubernetes.client.CoreV1Api:
    """Create a kubernetes client for core v1 API."""
    kubernetes.config.load_kube_config(config_file=kube_config)
    return kubernetes.client.CoreV1Api()


@pytest.fixture(scope="module", name="kube_apps_client")
def kube_apps_client_fixture(kube_config: str) -> kubernetes.client.AppsV1Api:
    """Create a kubernetes client for apps v1 API."""
    kubernetes.config.load_kube_config(config_file=kube_config)
    return kubernetes.client.AppsV1Api()


@pytest.fixture(scope="module", name="tinyproxy_port")
def tinyproxy_port_fixture() -> int:
    """Tinyproxy port."""
    return 8888


@pytest.fixture(scope="module", name="tiny_proxy_daemonset")
def tiny_proxy_daemonset_fixture(
    model: Model, kube_apps_client: kubernetes.client.AppsV1Api, tinyproxy_port: int
) -> kubernetes.client.V1DaemonSet:
    """Create a tiny proxy daemonset."""
    container = kubernetes.client.V1Container(
        name="tinyproxy",
        image="monokal/tinyproxy",
        image_pull_policy="IfNotPresent",
        ports=[
            kubernetes.client.V1ContainerPort(
                container_port=tinyproxy_port, host_port=tinyproxy_port
            )
        ],
        args=["ANY"],
    )
    template = kubernetes.client.V1PodTemplateSpec(
        metadata=kubernetes.client.V1ObjectMeta(labels={"app": "tinyproxy"}),
        spec=kubernetes.client.V1PodSpec(containers=[container]),
    )
    spec = kubernetes.client.V1DaemonSetSpec(
        selector=kubernetes.client.V1LabelSelector(match_labels={"app": "tinyproxy"}),
        template=template,
    )
    daemonset = kubernetes.client.V1DaemonSet(
        api_version="apps/v1",
        kind="DaemonSet",
        metadata=kubernetes.client.V1ObjectMeta(name="daemonset-tiny-proxy"),
        spec=spec,
    )
    return kube_apps_client.create_namespaced_daemon_set(namespace=model.name, body=daemonset)


@pytest_asyncio.fixture(scope="module", name="tinyproxy_ip")
async def tinyproxy_ip_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    tiny_proxy_daemonset: kubernetes.client.V1DaemonSet,
) -> str:
    """The tinyproxy daemonset pod ip.

    Localhost is, by default, added to NO_PROXY by juju, hence the pod ip has to be used.
    """
    spec: kubernetes.client.V1DaemonSetSpec = tiny_proxy_daemonset.spec
    template: kubernetes.client.V1PodTemplateSpec = spec.template
    metadata: kubernetes.client.V1ObjectMeta = template.metadata

    return await get_pod_ip(model, kube_core_client, metadata.labels["app"])


@pytest_asyncio.fixture(scope="module", name="model_with_proxy")
async def model_with_proxy_fixture(
    model: Model, tinyproxy_ip: str, tinyproxy_port: int
) -> typing.AsyncGenerator[Model, None]:
    """Model with proxy configuration values."""
    tinyproxy_url = f"http://{tinyproxy_ip}:{tinyproxy_port}"
    await model.set_config({"juju-http-proxy": tinyproxy_url, "juju-https-proxy": tinyproxy_url})

    yield model

    await model.set_config({"juju-http-proxy": "", "juju-https-proxy": ""})


@pytest_asyncio.fixture(scope="module", name="jenkins_with_proxy")
async def jenkins_with_proxy_fixture(
    model_with_proxy: Model, charm: str, ops_test: OpsTest, jenkins_image: str
) -> typing.AsyncGenerator[Application, None]:
    """Jenkins server charm deployed under model with proxy configuration."""
    resources = {"jenkins-image": jenkins_image}

    # Deploy the charm and wait for active/idle status
    application = await model_with_proxy.deploy(
        charm,
        resources=resources,
        series="jammy",
        application_name="jenkins-proxy-k8s",
    )
    await model_with_proxy.wait_for_idle(
        apps=[application.name],
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=20 * 60,
        idle_period=30,
    )

    # slow down update-status so that it doesn't intervene currently running tests
    async with ops_test.fast_forward(fast_interval="5h"):
        yield application

    await model_with_proxy.remove_application(application.name, force=True, block_until_done=True)


@pytest_asyncio.fixture(scope="module", name="proxy_jenkins_unit_ip")
async def proxy_jenkins_unit_ip_fixture(model: Model, jenkins_with_proxy: Application):
    """Get Jenkins charm w/ proxy enabled unit IP."""
    status: FullStatus = await model.get_status([jenkins_with_proxy.name])
    try:
        unit_status: UnitStatus = next(
            iter(status.applications[jenkins_with_proxy.name].units.values())
        )
        assert unit_status.address, "Invalid unit address"
        return unit_status.address
    except StopIteration as exc:
        raise StopIteration("Invalid unit status") from exc


@pytest_asyncio.fixture(scope="module", name="proxy_jenkins_web_address")
async def proxy_jenkins_web_address_fixture(proxy_jenkins_unit_ip: str):
    """Get Jenkins charm w/ proxy enabled web address."""
    return f"http://{proxy_jenkins_unit_ip}:8080"


@pytest_asyncio.fixture(scope="module", name="jenkins_with_proxy_client")
async def jenkins_with_proxy_client_fixture(
    jenkins_with_proxy: Application,
    proxy_jenkins_web_address: str,
) -> jenkinsapi.jenkins.Jenkins:
    """The Jenkins API client."""
    jenkins_unit: Unit = jenkins_with_proxy.units[0]
    action: Action = await jenkins_unit.run_action("get-admin-password")
    await action.wait()
    password = action.results["password"]

    # Initialization of the jenkins client will raise an exception if unable to connect to the
    # server.
    return jenkinsapi.jenkins.Jenkins(
        baseurl=proxy_jenkins_web_address, username="admin", password=password, timeout=60
    )


@pytest_asyncio.fixture(scope="function", name="app_with_allowed_plugins")
async def app_with_allowed_plugins_fixture(
    application: Application,
) -> typing.AsyncGenerator[Application, None]:
    """Jenkins charm with plugins configured."""
    await application.set_config({"allowed-plugins": ",".join(ALLOWED_PLUGINS)})

    yield application

    await application.reset_config(to_default=["allowed-plugins"])


@pytest.fixture(scope="module", name="ldap_settings")
def ldap_settings_fixture() -> TestLDAPSettings:
    """LDAP user for testing."""
    return TestLDAPSettings(
        CONTAINER_PORT=1389,
        USER_NAME="customuser",
        USER_PASSWORD=secrets.token_hex(16),
    )


@pytest_asyncio.fixture(scope="module", name="ldap_server")
async def ldap_server_fixture(
    model: Model, kube_apps_client: kubernetes.client.AppsV1Api, ldap_settings: TestLDAPSettings
):
    """Testing LDAP server pod."""
    container = kubernetes.client.V1Container(
        name="ldap",
        image="bitnami/openldap:latest",
        image_pull_policy="IfNotPresent",
        ports=[
            kubernetes.client.V1ContainerPort(
                container_port=ldap_settings.CONTAINER_PORT
            )
        ],
        env=[
            kubernetes.client.V1EnvVar(name="LDAP_ADMIN_USERNAME", value="admin"),
            kubernetes.client.V1EnvVar(name="LDAP_ADMIN_PASSWORD", value=secrets.token_hex(16)),
            kubernetes.client.V1EnvVar(name="LDAP_USERS", value=ldap_settings.USER_NAME),
            kubernetes.client.V1EnvVar(name="LDAP_PASSWORDS", value=ldap_settings.USER_PASSWORD),
        ],
    )
    template = kubernetes.client.V1PodTemplateSpec(
        metadata=kubernetes.client.V1ObjectMeta(labels={"app": "ldap"}),
        spec=kubernetes.client.V1PodSpec(containers=[container]),
    )
    spec = kubernetes.client.V1DeploymentSpec(
        selector=kubernetes.client.V1LabelSelector(match_labels={"app": "ldap"}),
        template=template,
    )
    daemonset = kubernetes.client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=kubernetes.client.V1ObjectMeta(name="ldap"),
        spec=spec,
    )
    return kube_apps_client.create_namespaced_deployment(namespace=model.name, body=daemonset)


@pytest_asyncio.fixture(scope="module", name="ldap_server_ip")
async def ldap_server_ip_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    ldap_server: kubernetes.client.V1Deployment,
) -> str:
    """The LDAP deployment pod ip.

    Localhost is, by default, added to NO_PROXY by juju, hence the pod ip has to be used.
    """
    spec: kubernetes.client.V1DeploymentSpec = ldap_server.spec
    template: kubernetes.client.V1PodTemplateSpec = spec.template
    metadata: kubernetes.client.V1ObjectMeta = template.metadata

    return await get_pod_ip(model, kube_core_client, metadata.labels["app"])
