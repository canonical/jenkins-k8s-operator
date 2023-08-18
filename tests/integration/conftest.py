# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import random
import re
import secrets
import string
import textwrap
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

from .types_ import ModelAppUnit, PluginsMeta, UnitWebClient


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
    async with ops_test.fast_forward(fast_interval="5h"):
        yield application

    await model.remove_application(application.name, force=True, block_until_done=True)


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


@pytest_asyncio.fixture(scope="function", name="jenkins_k8s_agent")
async def jenkins_k8s_agent_fixture(
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

    await model.remove_application(agent_app.name, force=True)


@pytest_asyncio.fixture(scope="function", name="new_relation_k8s_agents")
async def new_relation_k8s_agents_fixture(
    model: Model, num_units: int, app_suffix: str
) -> typing.AsyncGenerator[Application, None]:
    """The Jenkins k8s agent to be used for new agent relation with multiple units."""
    agent_app: Application = await model.deploy(
        "jenkins-agent-k8s",
        config={"jenkins_agent_labels": "k8s"},
        channel="edge",
        num_units=num_units,
        application_name=f"jenkins-agentk8s-{app_suffix}",
    )
    await model.wait_for_idle(apps=[agent_app.name], status="blocked")

    yield agent_app

    await model.remove_application(agent_app.name, force=True)


@pytest_asyncio.fixture(scope="function", name="new_relation_k8s_agents_related")
async def new_relation_k8s_agents_related_fixture(
    model: Model,
    new_relation_k8s_agents: Application,
    application: Application,
):
    """The Jenkins-k8s server charm related to Jenkins-k8s agent charm through agent relation."""
    await application.relate(
        state.AGENT_RELATION, f"{new_relation_k8s_agents.name}:{state.AGENT_RELATION}"
    )
    await model.wait_for_idle(
        apps=[application.name, new_relation_k8s_agents.name], wait_for_active=True
    )

    return application


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

    yield model

    await model.disconnect()


@pytest_asyncio.fixture(scope="function", name="jenkins_machine_agent")
async def jenkins_machine_agent_fixture(
    machine_model: Model, app_suffix: str
) -> typing.AsyncGenerator[Application, None]:
    """The jenkins machine agent."""
    # 2023-06-02 use the edge version of jenkins agent until the changes have been promoted to
    # stable.
    app = await machine_model.deploy(
        "jenkins-agent",
        channel="latest/edge",
        config={"labels": "machine"},
        application_name=f"jenkins-agent-{app_suffix}",
    )
    await machine_model.create_offer(f"{app.name}:slave")
    await machine_model.wait_for_idle(apps=[app.name], status="blocked", timeout=1200)

    yield app

    await machine_model.remove_offer(f"admin/{machine_model.name}.{app.name}", force=True)
    await machine_model.remove_application(app.name, force=True)


@pytest_asyncio.fixture(scope="function", name="new_relation_machine_agents")
async def new_relation_machine_agents_fixture(
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
    await machine_model.create_offer(f"{app.name}:{state.AGENT_RELATION}")
    await machine_model.wait_for_idle(
        apps=[app.name], status="blocked", idle_period=30, timeout=1200
    )

    yield app

    await machine_model.remove_offer(f"admin/{machine_model.name}.{app.name}", force=True)
    await machine_model.remove_application(app.name, force=True, block_until_done=True)


@pytest_asyncio.fixture(scope="function", name="new_relation_agent_related")
async def new_relation_agents_related_fixture(
    model: Model,
    new_relation_machine_agents: Application,
    application: Application,
):
    """The Jenkins-k8s server charm related to Jenkins agent charm through agent relation."""
    machine_model: Model = new_relation_machine_agents.model
    await machine_model.create_offer(f"{new_relation_machine_agents.name}:{state.AGENT_RELATION}")
    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{new_relation_machine_agents.name}",
    )
    await machine_model.wait_for_idle(
        apps=[new_relation_machine_agents.name], wait_for_active=True
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)

    return application


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


@pytest_asyncio.fixture(scope="function", name="restart_time_range_app")
async def restart_time_range_app_fixture(application: Application):
    """Application with restart-time-range configured."""
    await application.set_config({"restart-time-range": "03-05"})

    yield application

    await application.reset_config(["restart-time-range"])


@pytest_asyncio.fixture(scope="function", name="libfaketime_unit")
async def libfaketime_unit_fixture(ops_test: OpsTest, unit: Unit):
    """Unit with libfaketime installed."""
    await ops_test.juju("run", "--unit", f"{unit.name}", "--", "apt", "update")
    await ops_test.juju(
        "run", "--unit", f"{unit.name}", "--", "apt", "install", "-y", "libfaketime"
    )

    return unit


@pytest.fixture(scope="function", name="timerange_model_app_unit")
def timerange_model_app_unit_fixture(
    model: Model, restart_time_range_app: Application, libfaketime_unit: Unit
):
    """The packaged model, application, unit of Jenkins to reduce number of parameters in tests."""
    return ModelAppUnit(model=model, app=restart_time_range_app, unit=libfaketime_unit)


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

    def get_tinyproxy_ip() -> str | None:
        """Get tinyproxy pod IP when ready.

        Returns:
            Pod IP when pod is ready. None otherwise.
        """
        podlist: kubernetes.client.V1PodList = kube_core_client.list_namespaced_pod(
            namespace=model.name, label_selector=f"app={metadata.labels['app']}"
        )
        pods: list[kubernetes.client.V1Pod] = podlist.items
        for pod in pods:
            status: kubernetes.client.V1PodStatus = pod.status
            if status.conditions is None:
                return None
            for condition in status.conditions:
                if condition.type == "Ready" and condition.status == "True":
                    return status.pod_ip
        return None

    await model.block_until(get_tinyproxy_ip, timeout=300, wait_period=5)

    return typing.cast(str, get_tinyproxy_ip())


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


@pytest.fixture(scope="function", name="plugins_config")
def plugins_config_fixture() -> typing.Iterable[str]:
    """The test Jenkins plugins configuration values."""
    return ("structs", "script-security")


@pytest.fixture(scope="function", name="plugins_to_install")
def plugins_to_install_fixture() -> typing.Iterable[str]:
    """The plugins to install on Jenkins."""
    return ("structs", "script-security", "git")


@pytest.fixture(scope="function", name="plugins_to_remove")
def plugins_to_remove_fixture(
    plugins_config: typing.Iterable[str],
    plugins_to_install: typing.Iterable[str],
) -> typing.Iterable[str]:
    """Plugins that are installed but not part of the plugins config."""
    return set(plugins_to_install) - set(plugins_config)


@pytest.fixture(scope="function", name="plugins_meta")
def plugins_meta_fixture(
    plugins_config: typing.Iterable[str],
    plugins_to_install: typing.Iterable[str],
    plugins_to_remove: typing.Iterable[str],
) -> PluginsMeta:
    """The wrapper around plugins configuration, plugins to install and plugins to remove."""
    return PluginsMeta(config=plugins_config, install=plugins_to_install, remove=plugins_to_remove)


@pytest_asyncio.fixture(scope="function", name="jenkins_with_plugin_config")
async def jenkins_with_plugin_config_fixture(
    application: Application,
    plugins_config: typing.Iterable[str],
) -> Application:
    """Jenkins charm with plugins configured."""
    await application.set_config({"allowed-plugins": ",".join(plugins_config)})

    yield application

    await application.reset_config(to_default=["allowed-plugins"])


@pytest_asyncio.fixture(scope="function", name="install_plugins")
async def install_plugins_fixture(
    model: Model,
    jenkins_with_plugin_config: Application,
    kube_core_client: kubernetes.client.CoreV1Api,
    plugins_to_install: typing.Iterable[str],
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """Install plugins using kubernetes container command."""
    unit: Unit = jenkins_with_plugin_config.units[0]
    stdout = kubernetes.stream.stream(
        kube_core_client.connect_get_namespaced_pod_exec,
        unit.name.replace("/", "-"),
        model.name,
        container="jenkins",
        command=[
            "java",
            "-jar",
            f"{jenkins.EXECUTABLES_PATH / 'jenkins-plugin-manager-2.12.11.jar'}",
            "-w",
            f"{jenkins.EXECUTABLES_PATH / 'jenkins.war'}",
            "-d",
            str(jenkins.PLUGINS_PATH),
            "-p",
            " ".join(plugins_to_install),
        ],
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )
    assert "Done" in stdout, f"Failed to install plugins via kube exec, {stdout}"

    # the library will return 503 or other status codes that are not 200, hence restart and wait
    # rather than check for status code.
    jenkins_client.safe_restart()
    await model.block_until(
        lambda: requests.get(jenkins_client.baseurl, timeout=10).status_code == 403,
        timeout=300,
        wait_period=10,
    )
