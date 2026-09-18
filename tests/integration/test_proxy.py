# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm proxy settings."""

from typing import AsyncGenerator

import jenkinsapi
import kubernetes.client
import pytest
import pytest_asyncio
from juju.action import Action
from juju.application import Application
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from .constants import TINYPROXY_PORT
from .helpers import get_model_unit_addresses, get_pod_ip


@pytest.fixture(scope="module", name="tiny_proxy_daemonset")
def tiny_proxy_daemonset_fixture(
    model: Model, kube_apps_client: kubernetes.client.AppsV1Api
) -> kubernetes.client.V1DaemonSet:
    """Create a tiny proxy daemonset."""
    container = kubernetes.client.V1Container(
        name="tinyproxy",
        image="monokal/tinyproxy",
        image_pull_policy="IfNotPresent",
        ports=[
            kubernetes.client.V1ContainerPort(
                container_port=TINYPROXY_PORT, host_port=TINYPROXY_PORT
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
async def model_with_proxy_fixture(model: Model, tinyproxy_ip: str) -> AsyncGenerator[Model, None]:
    """Model with proxy configuration values."""
    tinyproxy_url = f"http://{tinyproxy_ip}:{TINYPROXY_PORT}"
    await model.set_config({"juju-http-proxy": tinyproxy_url, "juju-https-proxy": tinyproxy_url})
    yield model
    await model.set_config({"juju-http-proxy": "", "juju-https-proxy": ""})


@pytest_asyncio.fixture(scope="module", name="jenkins_with_proxy")
async def jenkins_with_proxy_fixture(
    model_with_proxy: Model, charm: str, ops_test: OpsTest, jenkins_image: str
) -> AsyncGenerator[Application, None]:
    """Jenkins server charm deployed under model with proxy configuration."""
    resources = {"jenkins-image": jenkins_image}
    # Deploy the charm and wait for active/idle status
    application = await model_with_proxy.deploy(
        charm, resources=resources, application_name="jenkins-proxy-k8s"
    )
    await model_with_proxy.wait_for_idle(
        apps=[application.name],
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=30 * 60,
        idle_period=30,
    )
    # slow down update-status so that it doesn't intervene currently running tests
    async with ops_test.fast_forward(fast_interval="5h"):
        yield application
    await model_with_proxy.remove_application(application.name, block_until_done=True)


@pytest_asyncio.fixture(scope="module", name="proxy_jenkins_unit_ip")
async def proxy_jenkins_unit_ip_fixture(model: Model, jenkins_with_proxy: Application):
    """Get Jenkins charm w/ proxy enabled unit IP."""
    unit_ips = await get_model_unit_addresses(model=model, app_name=jenkins_with_proxy.name)
    assert unit_ips, f"Unit IP address not found for {jenkins_with_proxy.name}"
    return unit_ips[0]


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
        baseurl=proxy_jenkins_web_address,
        username="admin",
        password=password,
        timeout=60,
    )


async def test_jenkins_ui_proxy_config(
    jenkins_with_proxy_client: jenkinsapi.jenkins.Jenkins,
    proxy_jenkins_web_address: str,
    tinyproxy_port: int,
    tinyproxy_ip: str,
):
    """
    arrange: given a jenkins deployed under juju model with proxy settings.
    act: when plugin manager page w/ proxy settings is fetched.
    assert: proxy server host and port exists in configuration value.
    """
    res = jenkins_with_proxy_client.requester.get_url(
        f"{proxy_jenkins_web_address}/manage/configure"
    )

    page_content = str(res.content, encoding="utf-8")

    assert tinyproxy_ip in page_content, "Proxy host not configured."
    assert str(tinyproxy_port) in page_content, "Proxy port not configured."
