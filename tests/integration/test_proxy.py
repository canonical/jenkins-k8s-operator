# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm proxy settings."""

import re
import shlex
from typing import AsyncGenerator, Awaitable, Callable

import jenkinsapi
import kubernetes.client
import pytest
import pytest_asyncio
from juju.action import Action
from juju.application import Application
from juju.model import Model
from juju.unit import Unit
from kubernetes.stream import stream
from pytest_operator.plugin import OpsTest

from .constants import TINYPROXY_PORT
from .helpers import get_model_unit_addresses, get_pod_ip

SSH_KEY_PATH = "/tmp/ssh-proxy-integration-key"  # nosec B108
SSH_PROXY_CONFIG_PATH = "/etc/ssh/ssh_config.d/00-jenkins-proxy.conf"
SSH_KNOWN_HOSTS_PATH = "/etc/ssh/jenkins_known_hosts"
JENKINS_CONTAINER_NAME = "jenkins"
TINYPROXY_CONTAINER_NAME = "tinyproxy"
TINYPROXY_LOG_PATH = "/var/log/tinyproxy/tinyproxy.log"
SSHD_CONTAINER_NAME = "sshd"
SSHD_TEST_POD_NAME = "ssh-proxy-test-server"
SSHD_CONTAINER_PORT = 2222
EXEC_TIMEOUT_SECONDS = 10 * 60
_EXIT_CODE_MARKER = "__exit_code__"


def jenkins_pod_name(
    kube_core_client: kubernetes.client.CoreV1Api, model: Model, application: Application
) -> str:
    """Return the workload pod name of the single-unit Jenkins application."""
    # Sidecar charms run one pod per unit, named after the unit.
    pod_name = application.units[0].name.replace("/", "-")
    pods = kube_core_client.list_namespaced_pod(namespace=model.name)
    assert any(pod.metadata.name == pod_name for pod in pods.items), (
        f"Pod {pod_name} not found in namespace {model.name}."
    )
    return pod_name


def exec_in_container(
    kube_core_client: kubernetes.client.CoreV1Api,
    model: Model,
    pod_name: str,
    container: str,
    script: str,
) -> tuple[int, str]:
    """Run a shell script in a pod container and return its exit code and output.

    The Kubernetes exec API is used directly: on Kubernetes models `juju ssh --container` does not
    run OpenSSH, it joins its arguments into a `sh -c` command executed in the pod, which also drops
    empty arguments. The script is passed as a single argument, so nothing is lost to re-quoting.
    """
    # A subshell keeps the exit status of the script even if it calls `exit`.
    wrapped = f"( {script}\n); printf '\\n{_EXIT_CODE_MARKER}%s\\n' \"$?\""
    exec_session = stream(
        kube_core_client.connect_get_namespaced_pod_exec,
        name=pod_name,
        namespace=model.name,
        container=container,
        command=["sh", "-c", wrapped],
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
        _preload_content=False,
    )
    try:
        exec_session.run_forever(timeout=EXEC_TIMEOUT_SECONDS)
        output = exec_session.read_all()
    finally:
        exec_session.close()

    assert _EXIT_CODE_MARKER in output, f"Command returned no exit code: {output}"
    command_output, _, exit_code = output.rpartition(_EXIT_CODE_MARKER)
    return int(exit_code.strip()), command_output


def exec_in_jenkins(
    kube_core_client: kubernetes.client.CoreV1Api,
    model: Model,
    application: Application,
    script: str,
) -> tuple[int, str]:
    """Run a shell script in the Jenkins workload container."""
    return exec_in_container(
        kube_core_client,
        model,
        jenkins_pod_name(kube_core_client, model, application),
        JENKINS_CONTAINER_NAME,
        script,
    )


def ssh_command(target_ip: str) -> str:
    """OpenSSH command relying on the charm-managed proxy drop-in and known hosts file.

    Host key verification is left at the OpenSSH default. The test server host key is pinned
    through the `ssh-known-hosts` charm configuration, so the connection is verified and fails
    closed if the server presents a different key.
    """
    return shlex.join(
        [
            "ssh",
            "-v",
            "-i",
            SSH_KEY_PATH,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=30",
            "-p",
            str(SSHD_CONTAINER_PORT),
            f"testuser@{target_ip}",
            "printf",
            "ssh-proxy-ok",
        ]
    )


def ssh_server_known_hosts(
    kube_core_client: kubernetes.client.CoreV1Api, model: Model, server_ip: str
) -> str:
    """Return known_hosts entries that pin the host keys of the SSH test server."""
    exit_code, output = exec_in_container(
        kube_core_client,
        model,
        SSHD_TEST_POD_NAME,
        SSHD_CONTAINER_NAME,
        "cat /etc/ssh/ssh_host_*_key.pub",
    )
    assert exit_code == 0, f"Failed to read the SSH test server host keys: {output}"
    host_keys = [line.strip() for line in output.splitlines() if line.strip()]
    assert host_keys, f"No SSH test server host keys found: {output}"
    return "\n".join(f"[{server_ip}]:{SSHD_CONTAINER_PORT} {key}" for key in host_keys)


def tinyproxy_log(
    kube_core_client: kubernetes.client.CoreV1Api, model: Model, proxy_ip: str
) -> str:
    """Return the access log of the tinyproxy pod serving the given IP.

    The log file is read inside the pod. The image tees it with `tail -f`, and that output is not
    delivered to the container log stream while the test runs.
    """
    pods = kube_core_client.list_namespaced_pod(
        namespace=model.name, label_selector="app=tinyproxy"
    )
    pod = next((pod for pod in pods.items if pod.status.pod_ip == proxy_ip), None)
    assert pod is not None, f"No tinyproxy pod found with IP {proxy_ip}."
    exit_code, output = exec_in_container(
        kube_core_client,
        model,
        pod.metadata.name,
        TINYPROXY_CONTAINER_NAME,
        f"cat {TINYPROXY_LOG_PATH}",
    )
    assert exit_code == 0, f"Could not read the proxy access log: {output}"
    return output


async def _apply_ssh_config(
    model: Model, application: Application, config: dict[str, str]
) -> None:
    """Apply SSH-related charm configuration and wait for the charm to settle."""
    await application.set_config(config)
    await model.wait_for_idle(
        apps=[application.name],
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=10 * 60,
        idle_period=10,
    )


@pytest_asyncio.fixture(name="set_ssh_config")
async def set_ssh_config_fixture(
    model: Model, jenkins_with_proxy: Application
) -> AsyncGenerator[Callable[[dict[str, str]], Awaitable[None]], None]:
    """Apply SSH-related charm configuration, resetting it after the test."""

    async def apply(config: dict[str, str]) -> None:
        await _apply_ssh_config(model, jenkins_with_proxy, config)

    yield apply
    await _apply_ssh_config(
        model, jenkins_with_proxy, {"ssh-proxy-address": "", "ssh-known-hosts": ""}
    )


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


@pytest_asyncio.fixture(scope="module", name="ssh_server_ip")
async def ssh_server_ip_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    jenkins_with_proxy: Application,
) -> AsyncGenerator[str, None]:
    """Create an SSH endpoint that can be reached through the HTTP proxy."""
    key_path = SSH_KEY_PATH
    exit_code, output = exec_in_jenkins(
        kube_core_client,
        model,
        jenkins_with_proxy,
        f"ssh-keygen -q -t ed25519 -N '' -f {key_path}",
    )
    assert exit_code == 0, f"Failed to generate SSH test key: {output}"
    exit_code, public_key = exec_in_jenkins(
        kube_core_client, model, jenkins_with_proxy, f"cat {key_path}.pub"
    )
    assert exit_code == 0, f"Failed to read SSH test public key: {public_key}"

    pod = kubernetes.client.V1Pod(
        metadata=kubernetes.client.V1ObjectMeta(
            name=SSHD_TEST_POD_NAME, labels={"app": SSHD_TEST_POD_NAME}
        ),
        spec=kubernetes.client.V1PodSpec(
            restart_policy="Always",
            containers=[
                kubernetes.client.V1Container(
                    name=SSHD_CONTAINER_NAME,
                    image="lscr.io/linuxserver/openssh-server:latest",
                    image_pull_policy="IfNotPresent",
                    env=[
                        kubernetes.client.V1EnvVar(name="USER_NAME", value="testuser"),
                        kubernetes.client.V1EnvVar(name="PUBLIC_KEY", value=public_key.strip()),
                        kubernetes.client.V1EnvVar(name="PASSWORD_ACCESS", value="false"),
                        kubernetes.client.V1EnvVar(name="SUDO_ACCESS", value="false"),
                    ],
                    ports=[kubernetes.client.V1ContainerPort(container_port=SSHD_CONTAINER_PORT)],
                )
            ],
        ),
    )
    kube_core_client.create_namespaced_pod(namespace=model.name, body=pod)

    try:
        yield await get_pod_ip(model, kube_core_client, SSHD_TEST_POD_NAME)
    finally:
        kube_core_client.delete_namespaced_pod(
            name=SSHD_TEST_POD_NAME, namespace=model.name, grace_period_seconds=0
        )
        exec_in_jenkins(
            kube_core_client,
            model,
            jenkins_with_proxy,
            f"rm -f {key_path} {key_path}.pub",
        )


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


async def test_ssh_connection_uses_explicit_proxy(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    jenkins_with_proxy: Application,
    tinyproxy_ip: str,
    ssh_server_ip: str,
    set_ssh_config: Callable[[dict[str, str]], Awaitable[None]],
):
    """An OpenSSH connection from the Jenkins container is tunnelled through the configured proxy."""
    proxy_address = f"{tinyproxy_ip}:{TINYPROXY_PORT}"
    known_hosts = ssh_server_known_hosts(kube_core_client, model, ssh_server_ip)
    await set_ssh_config({"ssh-proxy-address": proxy_address, "ssh-known-hosts": known_hosts})

    exit_code, output = exec_in_jenkins(
        kube_core_client, model, jenkins_with_proxy, f"cat {SSH_PROXY_CONFIG_PATH}"
    )
    assert exit_code == 0, f"SSH proxy configuration was not written: {output}"
    assert f"-x {proxy_address}" in output

    exit_code, output = exec_in_jenkins(
        kube_core_client, model, jenkins_with_proxy, f"cat {SSH_KNOWN_HOSTS_PATH}"
    )
    assert exit_code == 0, f"Known hosts were not written: {output}"
    assert known_hosts.splitlines()[0] in output

    exit_code, output = exec_in_jenkins(
        kube_core_client,
        model,
        jenkins_with_proxy,
        f"ssh -G -p {SSHD_CONTAINER_PORT} testuser@{ssh_server_ip}",
    )
    assert exit_code == 0, f"ssh -G failed: {output}"
    assert re.search(rf"^proxycommand .*-x {re.escape(proxy_address)}\b", output, re.MULTILINE), (
        f"OpenSSH does not apply the charm-managed proxy configuration: {output}"
    )
    assert f"globalknownhostsfile {SSH_KNOWN_HOSTS_PATH} " in output, (
        f"OpenSSH does not use the charm-managed known hosts file: {output}"
    )
    assert "stricthostkeychecking no" not in output, (
        f"OpenSSH host key verification is disabled: {output}"
    )

    log_before = tinyproxy_log(kube_core_client, model, tinyproxy_ip)
    exit_code, output = exec_in_jenkins(
        kube_core_client, model, jenkins_with_proxy, f"{ssh_command(ssh_server_ip)} 2>&1"
    )
    assert exit_code == 0, f"SSH through proxy failed: {output}"
    assert "ssh-proxy-ok" in output
    assert (
        "Executing proxy command: exec /usr/bin/nc -X connect "
        f"-x {proxy_address} {ssh_server_ip} {SSHD_CONTAINER_PORT}"
    ) in output, f"OpenSSH did not run the configured proxy command: {output}"

    new_log = tinyproxy_log(kube_core_client, model, tinyproxy_ip)[len(log_before) :]
    assert f"CONNECT {ssh_server_ip}:{SSHD_CONTAINER_PORT}" in new_log, (
        f"The proxy did not serve the SSH connection: {new_log}"
    )


async def test_ssh_connection_fails_when_proxy_is_unreachable(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    jenkins_with_proxy: Application,
    tinyproxy_ip: str,
    ssh_server_ip: str,
    set_ssh_config: Callable[[dict[str, str]], Awaitable[None]],
):
    """OpenSSH fails instead of connecting directly when the configured proxy is unreachable."""
    # Nothing listens on the port next to the proxy port, so the proxy command must fail.
    # The server host key is pinned, so the failure cannot be a host key verification failure.
    await set_ssh_config(
        {
            "ssh-proxy-address": f"{tinyproxy_ip}:{TINYPROXY_PORT + 1}",
            "ssh-known-hosts": ssh_server_known_hosts(kube_core_client, model, ssh_server_ip),
        }
    )

    exit_code, output = exec_in_jenkins(
        kube_core_client, model, jenkins_with_proxy, f"{ssh_command(ssh_server_ip)} 2>&1"
    )
    assert exit_code != 0, f"SSH did not use the configured proxy: {output}"
    assert "ssh-proxy-ok" not in output
    assert "Host key verification failed" not in output, f"Unexpected host key failure: {output}"


async def test_jenkins_ui_proxy_config(
    jenkins_with_proxy_client: jenkinsapi.jenkins.Jenkins,
    proxy_jenkins_web_address: str,
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
    assert str(TINYPROXY_PORT) in page_content, "Proxy port not configured."
