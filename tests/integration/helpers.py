# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""

import inspect
import logging
import secrets
import textwrap
import time
import typing
from enum import Enum
from urllib.parse import urlparse

import jenkinsapi.jenkins
import kubernetes.client
import requests
import tenacity
from jenkinsapi.custom_exceptions import JenkinsAPIException, NotBuiltYet
from juju.application import Application
from juju.client._definitions import ApplicationStatus, FullStatus, UnitStatus
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

import jenkins

from .types_ import UnitWebClient

logger = logging.getLogger(__name__)


def _jenkins_available(web: str) -> bool:
    """Return whether Jenkins is responding after a restart."""
    try:
        return requests.get(web, timeout=10).status_code in (200, 403)
    except requests.RequestException:
        return False


def _plugins_are_active(
    client: jenkinsapi.jenkins.Jenkins, plugins: tuple[str, ...]
) -> bool:
    """Return whether all requested Jenkins plugins are active and enabled."""
    try:
        plugin_map = client.get_plugins(depth=1).get_plugins_dict()
    except (JenkinsAPIException, requests.RequestException):
        return False
    return all(
        (plugin := plugin_map.get(name))
        and getattr(plugin, "active", False)
        and getattr(plugin, "enabled", False)
        for name in plugins
    )


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, max=60),
    reraise=True,
    stop=tenacity.stop_after_attempt(5),
)
async def install_plugins(
    unit_web_client: UnitWebClient,
    plugins: typing.Iterable[str],
) -> None:
    """Install plugins to Jenkins unit.

    Args:
        unit_web_client: The wrapper around unit, web_address and jenkins_client.
        plugins: Desired plugins to install.
    """
    web, client = unit_web_client.web, unit_web_client.client
    plugins = tuple(plugin for plugin in plugins if not client.has_plugin(plugin))
    if not plugins:
        return

    logger.info("phase=plugin_install requested=%s", plugins)
    post_data = {f"plugin.{plugin}.default": "on" for plugin in plugins}
    post_data["dynamic_load"] = ""
    res = client.requester.post_url(f"{web}/manage/pluginManager/install", data=post_data)
    assert res.status_code == 200, "Failed to request plugins install"

    logger.info("phase=plugin_install waiting_for_download plugins=%s", plugins)
    await wait_for(
        lambda: (
            "Pending"
            not in str(
                client.requester.post_url(f"{web}/manage/pluginManager/updates/body").content,
                encoding="utf-8",
            )
        ),
        timeout=60 * 10,
    )
    logger.info("phase=plugin_install download_complete plugins=%s", plugins)

    client.safe_restart()
    logger.info("phase=plugin_install restart_requested plugins=%s", plugins)

    await wait_for(lambda: _jenkins_available(web), timeout=60 * 10)
    logger.info("phase=plugin_install jenkins_available plugins=%s", plugins)

    await wait_for(lambda: _plugins_are_active(client, plugins), timeout=60 * 10)
    logger.info("phase=plugin_install active plugins=%s", plugins)


async def get_model_unit_addresses(model: Model, app_name: str) -> list[str]:
    """Extract the address of a given unit.

    Args:
        model: Juju model
        app_name: Juju application name

    Returns:
        the IP address of the Jenkins unit.
    """
    status: FullStatus = await _get_status_with_retry(model)
    # mypy cannot infer the type ApplicationStatus but thinks its the base class type "Type".
    application_status: ApplicationStatus | None = status.applications[app_name]  # type: ignore
    assert application_status, f"Application status {app_name} not found in {status}"
    # mypy cannot infer the type UnitStatus but thinks its the base class type "Type".
    unit_status_map: dict[typing.Any, UnitStatus | None] = application_status.units  # type: ignore
    units_statuses: list[UnitStatus | None] = list(unit_status_map.values())
    # Machine (IAAS) model units populate ``public_address`` rather than ``address``,
    # which is only set for k8s (CAAS) units. Fall back to ``public_address`` so this
    # helper also works against machine-model applications (e.g. haproxy).
    return [
        str(unit_status.address or unit_status.public_address)
        for unit_status in units_statuses
        if unit_status and (unit_status.address or unit_status.public_address)
    ]


def _is_juju_proxy_error(exc: BaseException) -> bool:
    """Check if exception is a transient juju kubernetes proxy error.

    Args:
        exc: The exception to check

    Returns:
        True if the exception is a known transient proxy error.
    """
    name = type(exc).__name__
    return name in {
        "ConnectionClosedError",
        "ConnectionClosed",
        "ProxyNotConnectedError",
        "BrokenPipeError",
    }


async def _model_reconnect_on_proxy_error(exc: Exception, attempt: int) -> None:
    """On proxy error, force model reconnect before retry.

    Args:
        exc: The exception that triggered this callback
        attempt: Current attempt number (1-indexed by tenacity)
    """
    if not _is_juju_proxy_error(exc):
        return
    name = type(exc).__name__
    logger.warning(
        "model.get_status() transient failure (attempt %d): %s: %s",
        attempt,
        name,
        exc,
    )
    # Note: This is called by tenacity after the exception is caught but
    # before sleeping/retrying. We need the model reference, but tenacity
    # doesn't pass the original coroutine args. We'll disconnect/reconnect
    # in the retry wrapper instead.


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=5, max=60),
    stop=tenacity.stop_after_attempt(3),
    retry=tenacity.retry_if_exception(_is_juju_proxy_error),
    reraise=True,
)
async def _get_status_with_retry(model: Model) -> FullStatus:
    """Call ``model.get_status()`` with retries on transient juju proxy errors.

    The kubernetes port-forward proxy that ``python-libjuju`` uses to reach the
    juju controller (port 17070) occasionally dies mid-test on busy CI runners,
    surfacing as ``ConnectionClosedError`` / ``ProxyNotConnectedError`` /
    ``BrokenPipeError``. On retry we force ``model.disconnect()`` /
    ``model.connect()`` so we don't keep hammering a dead socket.

    Args:
        model: Juju model

    Returns:
        The full juju model status.
    """
    try:
        return await model.get_status()
    except Exception as exc:
        if _is_juju_proxy_error(exc):
            # Force the juju model to drop the dead connection so the next
            # call reopens the k8s port-forward proxy from scratch.
            try:
                await model.disconnect()
            except Exception as disconnect_exc:
                logger.debug("model.disconnect() ignored error: %s", disconnect_exc)
            try:
                await model.connect()
            except Exception as connect_exc:
                logger.warning("model.connect() reconnect failed: %s", connect_exc)
        raise


def gen_test_job_xml(node_label: str):
    """Generate a job xml with target node label.

    Args:
        node_label: The node label to assign to job to.

    Returns:
        The job XML.
    """
    return textwrap.dedent(f"""
        <project>
            <actions/>
            <description/>
            <keepDependencies>false</keepDependencies>
            <properties/>
            <scm class="hudson.scm.NullSCM"/>
            <assignedNode>{node_label}</assignedNode>
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
        """)


def assert_job_success(
    client: jenkinsapi.jenkins.Jenkins, agent_name: str, test_target_label: str
):
    """Assert that a job can be created and ran successfully.

    Args:
        client: The Jenkins API client.
        agent_name: The registered Jenkins agent node to check.
        test_target_label: The Jenkins agent node label.
    """
    node_names = list(client.nodes.iterkeys())
    node_name = next((key for key in node_names if agent_name in key), None)
    assert node_name is not None, f"Jenkins {agent_name} node not registered."

    deadline = time.monotonic() + 10 * 60
    while True:
        node = client.get_node(node_name)
        online = node.is_online()
        offline_reason = "" if online else node.offline_reason()
        logger.info(
            "phase=jenkins_agent_readiness agent=%s online=%s offline_reason=%r",
            agent_name,
            online,
            offline_reason,
        )
        if online:
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Jenkins agent did not come online: agent={agent_name}, "
                f"offline_reason={offline_reason!r}"
            )
        time.sleep(5)

    job = client.create_job(agent_name, gen_test_job_xml(test_target_label))
    queue_item = job.invoke()
    deadline = time.monotonic() + 10 * 60
    while True:
        try:
            queue_item.poll()
            build: jenkinsapi.build.Build = queue_item.get_build()
        except NotBuiltYet:
            build = None  # type: ignore[assignment]
        if build is not None and not build.is_running():
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Jenkins job did not complete: agent={agent_name}, "
                f"why={queue_item.why!r}, queue={queue_item._data!r}"
            )
        time.sleep(5)
    assert build.get_status() == "SUCCESS"


def gen_git_test_job_xml(node_label: str):
    """Generate a git test job xml with target node label.

    Args:
        node_label: The node label to assign to job to.

    Returns:
        The git test job XML.
    """
    return textwrap.dedent(f"""
        <project>
            <actions />
            <description></description>
            <keepDependencies>false</keepDependencies>
            <properties />
            <scm class="hudson.plugins.git.GitSCM" plugin="git@5.0.2">
                <configVersion>2</configVersion>
                <userRemoteConfigs>
                    <hudson.plugins.git.UserRemoteConfig>
                        <url>https://github.com/canonical/jenkins-k8s-operator</url>
                    </hudson.plugins.git.UserRemoteConfig>
                </userRemoteConfigs>
                <branches>
                    <hudson.plugins.git.BranchSpec>
                        <name>*/main</name>
                    </hudson.plugins.git.BranchSpec>
                </branches>
                <doGenerateSubmoduleConfigurations>
                    false</doGenerateSubmoduleConfigurations>
                <submoduleCfg class="empty-list" />
                <extensions />
            </scm>
            <assignedNode>{node_label}</assignedNode>
            <canRoam>true</canRoam>
            <disabled>false</disabled>
            <blockBuildWhenDownstreamBuilding>
                false</blockBuildWhenDownstreamBuilding>
            <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>
            <triggers />
            <concurrentBuild>false</concurrentBuild>
            <builders>
                <hudson.tasks.Shell>
                    <command>git checkout main\ngit pull</command>
                    <configuredLocalRules />
                </hudson.tasks.Shell>
            </builders>
            <publishers />
            <buildWrappers />
        </project>
        """)


async def get_pod_ip(model: Model, kube_core_client: kubernetes.client.CoreV1Api, app_label: str):
    """Get pod IP of a kubernetes application.

    Args:
        model: The juju model under test.
        kube_core_client: The Kubernetes V1 client.
        app_label: Target pod's app label.

    Returns:
        The IP of the pod.
    """

    def get_ready_pod_ip() -> str | None:
        """Get pod IP when ready.

        Returns:
            Pod IP when pod is ready. None otherwise.
        """
        podlist: kubernetes.client.V1PodList = kube_core_client.list_namespaced_pod(
            namespace=model.name, label_selector=f"app={app_label}"
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

    await model.block_until(get_ready_pod_ip, timeout=300, wait_period=5)

    return typing.cast(str, get_ready_pod_ip())


async def wait_for(
    func: typing.Callable[[], typing.Union[typing.Awaitable, typing.Any]],
    timeout: int = 300,
    check_interval: int = 10,
) -> typing.Any:
    """Wait for function execution to become truthy.

    Args:
        func: A callback function to wait to return a truthy value.
        timeout: Time in seconds to wait for function result to become truthy.
        check_interval: Time in seconds to wait between ready checks.

    Raises:
        TimeoutError: if the callback function did not return a truthy value within timeout.

    Returns:
        The result of the function if any.
    """
    deadline = time.time() + timeout
    is_awaitable = inspect.iscoroutinefunction(func)
    while time.time() < deadline:
        if is_awaitable:
            if result := await func():
                return result
        else:
            if result := func():
                return result
        time.sleep(check_interval)

    # final check before raising TimeoutError.
    if is_awaitable:
        if result := await func():
            return result
    else:
        if result := func():
            return result
    raise TimeoutError()


async def ensure_relation(
    *,
    model: Model,
    application: Application,
    other_application: Application,
    relation: str | tuple[str, str] | None = None,
    renew: bool = False,
    apps: typing.Optional[typing.Iterable[str]] = None,
    wait_for_active: bool = True,
    timeout: int = 20 * 60,
    idle_period: typing.Optional[int] = None,
) -> None:
    """Ensure a relation exists and the model becomes idle.

    Args:
        model: The Juju model.
        application: The primary application to relate from.
        other_application: The target application to relate to.
        relation: One endpoint name shared by both applications, or a tuple of
            ``(application_endpoint, other_application_endpoint)``. Defaults to ``agent``.
        renew: Remove an existing relation and recreate it before waiting when true.
        apps: Optional explicit list of app names to wait on; defaults to both apps.
        wait_for_active: Whether to wait until applications are active.
        timeout: Max seconds to wait for idle.
        idle_period: Optional idle period to pass to wait_for_idle.
    """
    if relation is None:
        application_endpoint = other_application_endpoint = "agent"
    elif isinstance(relation, tuple):
        application_endpoint, other_application_endpoint = relation
    else:
        application_endpoint = other_application_endpoint = relation

    app_list = list(apps) if apps is not None else [application.name, other_application.name]
    status: FullStatus = await model.get_status()
    app_status: ApplicationStatus | None = status.applications.get(application.name)  # type: ignore[attr-defined]
    related_apps: typing.Iterable[str] = []
    if app_status and getattr(app_status, "relations", None):
        rels = typing.cast(dict[str, typing.Any], app_status.relations)
        targets = rels.get(application_endpoint) or []
        related_apps = [str(target) for target in targets]
    expected_target = f"{other_application.name}:{other_application_endpoint}"
    if isinstance(relation, tuple):
        already_related = any(target == expected_target for target in related_apps)
    else:
        already_related = any(
            target == other_application.name or target == expected_target
            for target in related_apps
        )

    if renew and already_related:
        await application.remove_relation(
            application_endpoint, f"{other_application.name}:{other_application_endpoint}"
        )
        if idle_period is not None:
            await model.wait_for_idle(
                apps=app_list,
                wait_for_active=False,
                timeout=timeout,
                idle_period=idle_period,
            )
        else:
            await model.wait_for_idle(
                apps=app_list,
                wait_for_active=False,
                timeout=timeout,
            )
        already_related = False

    if not already_related:
        await model.integrate(
            f"{application.name}:{application_endpoint}",
            f"{other_application.name}:{other_application_endpoint}",
        )

    if idle_period is not None:
        await model.wait_for_idle(
            apps=app_list,
            wait_for_active=wait_for_active,
            timeout=timeout,
            idle_period=idle_period,
        )
    else:
        await model.wait_for_idle(
            apps=app_list,
            wait_for_active=wait_for_active,
            timeout=timeout,
        )


class AuthMethod(Enum):
    """Authentication method for Jenkins client generation."""

    # These fields are not hardcoded passwords which bandit thinks it is.
    TOKEN = "token"  # nosec: B105
    PASSWORD = "password"  # nosec: B105


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, max=60),
    reraise=True,
    stop=tenacity.stop_after_attempt(5),
)
async def generate_jenkins_client(
    ops_test: OpsTest,
    jenkins_app: Application,
    address: str,
    method: AuthMethod = AuthMethod.TOKEN,
) -> jenkinsapi.jenkins.Jenkins:
    """Generate a Jenkins client using either API token or admin password.

    Args:
        ops_test: OpsTest framework.
        jenkins_app: Juju Jenkins-k8s application.
        address: Base URL of the Jenkins server (e.g., http://IP:8080).
        method: Authentication method enum (`AuthMethod.TOKEN` or `AuthMethod.PASSWORD`).

    Returns:
        A Jenkins web client.
    """
    jenkins_unit = jenkins_app.units[0]
    start = time.monotonic()
    model = ops_test.model
    assert model is not None
    current_unit_ips = await get_model_unit_addresses(model=model, app_name=jenkins_app.name)
    requested_host = urlparse(address).hostname
    logger.info(
        "phase=generate_client app=%s unit=%s address=%s requested_host=%s resolved_ips=%s method=%s",
        jenkins_app.name,
        jenkins_unit.name,
        address,
        requested_host,
        current_unit_ips,
        method.value,
    )
    if requested_host and requested_host not in current_unit_ips:
        logger.warning(
            "phase=generate_client app=%s unit=%s stale_address_detected address_host=%s resolved_ips=%s",
            jenkins_app.name,
            jenkins_unit.name,
            requested_host,
            current_unit_ips,
        )

    if method == AuthMethod.TOKEN:
        ret, api_token, stderr = await ops_test.juju(
            "ssh",
            "--container",
            "jenkins",
            jenkins_unit.name,
            "cat",
            str(jenkins.API_TOKEN_PATH),
        )
        assert ret == 0, f"Failed to get Jenkins API token, {stderr}"
        secret = api_token
    elif method == AuthMethod.PASSWORD:
        action = await jenkins_unit.run_action("get-admin-password")
        await action.wait()
        logger.info(
            "phase=generate_client app=%s unit=%s auth_action=%s action_status=%s action_result_keys=%s",
            jenkins_app.name,
            jenkins_unit.name,
            "get-admin-password",
            action.status,
            sorted(action.results.keys()),
        )
        secret = action.results["password"]
    else:
        raise ValueError(f"Unsupported auth method: {method}")

    try:
        response = requests.get(f"{address}/login", timeout=10)
        logger.info(
            "phase=generate_client app=%s unit=%s login_probe_status=%s elapsed_s=%.2f",
            jenkins_app.name,
            jenkins_unit.name,
            response.status_code,
            time.monotonic() - start,
        )
    except requests.RequestException as exc:
        logger.warning(
            "phase=generate_client app=%s unit=%s login_probe_error=%s elapsed_s=%.2f",
            jenkins_app.name,
            jenkins_unit.name,
            repr(exc),
            time.monotonic() - start,
        )

    try:
        client = jenkinsapi.jenkins.Jenkins(address, "admin", secret, timeout=60)
        logger.info(
            "phase=generate_client app=%s unit=%s client_created=true elapsed_s=%.2f",
            jenkins_app.name,
            jenkins_unit.name,
            time.monotonic() - start,
        )
        return client
    except Exception as exc:
        logger.warning(
            "phase=generate_client app=%s unit=%s client_created=false exc_type=%s exc=%s elapsed_s=%.2f",
            jenkins_app.name,
            jenkins_unit.name,
            type(exc).__name__,
            exc,
            time.monotonic() - start,
        )
        raise


async def generate_unit_web_client_from_application(
    ops_test: OpsTest, model: Model, jenkins_app: Application
) -> UnitWebClient:
    """Generate a UnitWebClient client directly from the Juju application.

    Args:
        ops_test: OpsTest framework
        model: Juju model
        jenkins_app: Juju Jenkins-k8s application.

    Returns:
        A Jenkins web client.
    """
    assert model
    unit_ips = await get_model_unit_addresses(model, jenkins_app.name)
    assert unit_ips, f"Unit IP address not found for {jenkins_app.name}"
    address = f"http://{unit_ips[0]}:8080"
    jenkins_unit = jenkins_app.units[0]
    jenkins_client = await generate_jenkins_client(ops_test, jenkins_app, address)
    unit_web_client = UnitWebClient(unit=jenkins_unit, web=address, client=jenkins_client)
    return unit_web_client


def get_job_invoked_unit(job: jenkins.jenkinsapi.job.Job, units: typing.List[Unit]) -> Unit | None:
    """Get the jenkins unit that has run the latest job.

    Args:
        job: The jenkins job that has been run.
        units: Jenkins agent units.

    Returns:
        The agent unit that run the job if found.
    """
    invoked_agent = job.get_last_build().get_slave()
    unit: Unit
    for unit in units:
        if unit.name.replace("/", "-") == invoked_agent:
            return unit
    return None


def gen_test_pipeline_with_custom_script_xml(script: str) -> str:
    """Generate a job xml with custom pipeline script.

    Args:
        script: Custom pipeline script.

    Returns:
        The job XML.
    """
    return textwrap.dedent(f"""
        <flow-definition plugin="workflow-job@1385.vb_58b_86ea_fff1">
            <actions/>
            <description></description>
            <keepDependencies>false</keepDependencies>
            <properties/>
            <definition
                class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition"
                plugin="workflow-cps@3837.v305192405b_c0">
                <script>{script}</script>
                <sandbox>true</sandbox>
            </definition>
            <triggers/>
            <disabled>false</disabled>
        </flow-definition>
        """)


def kubernetes_test_pipeline_script() -> str:
    """Generate a test pipeline script using the kubernetes plugin.

    Return:
        The pipeline script
    """
    return textwrap.dedent("""
        podTemplate(yaml: '''
            apiVersion: v1
            kind: Pod
            metadata:
            labels:
                some-label: some-label-value
            spec:
            containers:
            - name: busybox
              image: busybox
              imagePullPolicy: IfNotPresent
              command:
              - sleep
              args:
              - 99d
              tty: true
        ''') {
        node(POD_LABEL) {
            stage('Integration Test') {
            sh '''#!/bin/bash
                hostname
            '''
            }
        }
        }""")


def declarative_pipeline_script() -> str:
    """Generate a declarative pipeline script.

    Return:
        The pipeline script
    """
    return textwrap.dedent("""
        pipeline {
            agent any

            stages {
                stage('Integration Test') {
                    steps {
                        sh'''#!/bin/bash
                            echo "$(hostname) $(date) : Running in $(pwd)"
                        '''
                    }
                }
            }
        }""")


def _raise_timeout(_: tenacity.RetryCallState) -> None:
    """Raise the timeout used when a tenacity polling retry expires."""
    raise TimeoutError()


def get_coredns_config_map(
    kube_core_client: kubernetes.client.CoreV1Api,
) -> kubernetes.client.V1ConfigMap:
    """Find the CoreDNS ConfigMap installed by Canonical Kubernetes."""
    config_maps = kube_core_client.list_namespaced_config_map(
        namespace="kube-system",
        label_selector="app.kubernetes.io/instance=ck-dns",
    ).items
    config_maps = [
        config_map
        for config_map in config_maps
        if config_map.data and "Corefile" in config_map.data
    ]
    names = [
        config_map.metadata.name
        for config_map in config_maps
        if config_map.metadata and config_map.metadata.name
    ]
    assert len(config_maps) == 1, f"Expected one CoreDNS ConfigMap, found {names}"
    config_map = config_maps[0]
    assert config_map.metadata and config_map.metadata.name
    return config_map


@tenacity.retry(
    retry=tenacity.retry_any(
        tenacity.retry_if_result(lambda result: not result),
        tenacity.retry_if_exception_type(kubernetes.client.exceptions.ApiException),
    ),
    stop=tenacity.stop_after_delay(5 * 60),
    wait=tenacity.wait_fixed(5),
    reraise=True,
    retry_error_callback=_raise_timeout,
)
def _wait_for_coredns_pods_ready(
    kube_core_client: kubernetes.client.CoreV1Api, selector: str
) -> bool:
    """Return True when all CoreDNS pods with the given selector are running and ready."""
    current_pods = kube_core_client.list_namespaced_pod(
        namespace="kube-system", label_selector=selector
    ).items
    return bool(current_pods) and all(
        pod.status
        and pod.status.phase == "Running"
        and pod.status.container_statuses
        and all(container.ready for container in pod.status.container_statuses)
        and not (pod.metadata and pod.metadata.deletion_timestamp)
        for pod in current_pods
    )


def restart_coredns(kube_core_client: kubernetes.client.CoreV1Api) -> None:
    """Restart CoreDNS and wait until its replacement pods are ready."""
    selector = "app.kubernetes.io/name=coredns"
    pods = kube_core_client.list_namespaced_pod(namespace="kube-system", label_selector=selector)
    for pod in pods.items:
        if pod.metadata and pod.metadata.name:
            logger.info("Deleting pod for DNS restart: %s", pod.metadata.name)
            kube_core_client.delete_namespaced_pod(name=pod.metadata.name, namespace="kube-system")
    _wait_for_coredns_pods_ready(kube_core_client, selector)


def create_secret_file_credentials(
    unit_web_client: UnitWebClient, kube_config: str
) -> typing.Optional[str]:
    """Use the jenkins client to create a new secretfile credential.

    plain-credentials plugin is required.

    Args:
        unit_web_client: Client for Jenkins's remote access API.
        kube_config: path to the kube_config file.

    Returns:
        The id of the created credential, or None in case of error.
    """
    url = f"{unit_web_client.web}/credentials/store/system/domain/_/createCredentials"
    credentials_id = f"kube-config-{secrets.token_hex(4)}"
    payload = {
        "json": f"""{{
            "": "4",
            "credentials": {{
                "file": "file0",
                "id": "{credentials_id}",
                "description": "Created by API",
                "stapler-class": "org.jenkinsci.plugins.plaincredentials.impl.FileCredentialsImpl",
                "$class": "org.jenkinsci.plugins.plaincredentials.impl.FileCredentialsImpl",
            }},
        }}"""
    }
    headers = {
        "Accept": "*/*",
    }

    with open(kube_config, "rb") as kube_config_file:
        files = [("file0", ("config", kube_config_file, "application/octet-stream"))]
        logger.debug("Creating jenkins credentials, params: %s %s %s", headers, files, payload)
        res = unit_web_client.client.requester.post_url(
            url=url, headers=headers, data=payload, files=files, timeout=30
        )
        logger.debug("Credential created, %s", res.status_code)
        return credentials_id if res.status_code == 200 else None


def create_kubernetes_cloud(
    unit_web_client: UnitWebClient, kube_config_credentials_id: str
) -> typing.Optional[str]:
    """Use the Jenkins client to add a Kubernetes cloud.

    For dynamic agent provisioning through pods.

    Args:
        unit_web_client: Client for Jenkins's remote access API.
        kube_config_credentials_id: credential id stored in jenkins.

    Returns:
        The created kubernetes cloud name or None in case of error.
    """
    kubernetes_test_cloud_name = "kubernetes"

    url = f"{unit_web_client.web}/manage/cloud/doCreate"

    payload = {
        "name": kubernetes_test_cloud_name,
        "cloudDescriptorName": "org.csanchez.jenkins.plugins.kubernetes.KubernetesCloud",
        "json": f"""
        {{
            "name": "{kubernetes_test_cloud_name}",
            "credentialsId": "{kube_config_credentials_id}",
            "jenkinsUrl": "{unit_web_client.web}",
            "type": "org.csanchez.jenkins.plugins.kubernetes.KubernetesCloud",
            "webSocket":true,
            "connectTimeout": "300",
            "Submit": "",
        }}""",
        "webSocket": True,
        "Submit": '""',
    }
    accept_header = (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,"
        "image/webp,"
        "image/apng,"
        "*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    )
    headers = {
        "Accept": accept_header,
    }

    logger.debug("Creating jenkins kubernetes cloud, params: %s %s", headers, payload)
    res = unit_web_client.client.requester.post_url(
        url=url, headers=headers, data=payload, timeout=60 * 5
    )
    logger.debug("Cloud created, status=%s body=%s", res.status_code, res.text)

    return kubernetes_test_cloud_name if res.status_code == 200 else None
