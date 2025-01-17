# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""
import inspect
import logging
import secrets
import textwrap
import time
import typing

import jenkinsapi.jenkins
import kubernetes.client
import requests
import tenacity
from juju.application import Application
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

import jenkins

from .types_ import UnitWebClient

logger = logging.getLogger(__name__)


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
    unit, web, client = unit_web_client.unit, unit_web_client.web, unit_web_client.client
    plugins = tuple(plugin for plugin in plugins if not client.has_plugin(plugin))
    if not plugins:
        return

    post_data = {f"plugin.{plugin}.default": "on" for plugin in plugins}
    post_data["dynamic_load"] = ""
    res = client.requester.post_url(f"{web}/manage/pluginManager/install", data=post_data)
    assert res.status_code == 200, "Failed to request plugins install"

    # block until the UI does not have "Pending" in download progress column.
    await wait_for(
        lambda: "Pending"
        not in str(
            client.requester.post_url(f"{web}/manage/pluginManager/updates/body").content,
            encoding="utf-8",
        ),
        timeout=60 * 10,
    )

    # the library will return 503 or other status codes that are not 200, hence restart and
    # wait rather than check for status code.
    client.safe_restart()
    await unit.model.block_until(
        lambda: requests.get(web, timeout=10).status_code == 403,
        timeout=60 * 10,
        wait_period=10,
    )


async def get_model_jenkins_unit_address(model: Model, app_name: str):
    """Extract the address of a given unit.

    Args:
        model: Juju model
        app_name: Juju application name

    Returns:
        the IP address of the Jenkins unit.
    """
    status = await model.get_status()
    application = typing.cast(Application, status.applications[app_name])
    unit = list(application.units)[0]
    address = status["applications"][app_name]["units"][unit]["address"]
    return address


def gen_test_job_xml(node_label: str):
    """Generate a job xml with target node label.

    Args:
        node_label: The node label to assign to job to.

    Returns:
        The job XML.
    """
    return textwrap.dedent(
        f"""
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
        """
    )


def assert_job_success(
    client: jenkinsapi.jenkins.Jenkins, agent_name: str, test_target_label: str
):
    """Assert that a job can be created and ran successfully.

    Args:
        client: The Jenkins API client.
        agent_name: The registered Jenkins agent node to check.
        test_target_label: The Jenkins agent node label.
    """
    nodes = client.get_nodes()
    assert any(
        (agent_name in key for key in nodes.keys())
    ), f"Jenkins {agent_name} node not registered."

    job = client.create_job(agent_name, gen_test_job_xml(test_target_label))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


def gen_git_test_job_xml(node_label: str):
    """Generate a git test job xml with target node label.

    Args:
        node_label: The node label to assign to job to.

    Returns:
        The git test job XML.
    """
    return textwrap.dedent(
        f"""
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
        """
    )


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


async def generate_jenkins_client_from_application(
    ops_test: OpsTest, jenkins_app: Application, address: str
):
    """Generate a Jenkins client directly from the Juju application.

    Args:
        ops_test: OpsTest framework
        jenkins_app: Juju Jenkins-k8s application.
        address: IP address of the jenkins unit.

    Returns:
        A Jenkins web client.
    """
    jenkins_unit = jenkins_app.units[0]
    ret, api_token, stderr = await ops_test.juju(
        "ssh",
        "--container",
        "jenkins",
        jenkins_unit.name,
        "cat",
        str(jenkins.API_TOKEN_PATH),
    )
    assert ret == 0, f"Failed to get Jenkins API token, {stderr}"
    return jenkinsapi.jenkins.Jenkins(address, "admin", api_token, timeout=60)


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
    unit_ip = await get_model_jenkins_unit_address(model, jenkins_app.name)
    address = f"http://{unit_ip}:8080"
    jenkins_unit = jenkins_app.units[0]
    jenkins_client = await generate_jenkins_client_from_application(ops_test, jenkins_app, address)
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
    return textwrap.dedent(
        f"""
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
        """
    )


def kubernetes_test_pipeline_script() -> str:
    """Generate a test pipeline script using the kubernetes plugin.

    Return:
        The pipeline script
    """
    return textwrap.dedent(
        """
        podTemplate(yaml: '''
            apiVersion: v1
            kind: Pod
            metadata:
            labels:
                some-label: some-label-value
            spec:
            containers:
            - name: httpd
              image: httpd
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
        }"""
    )


def declarative_pipeline_script() -> str:
    """Generate a declarative pipeline script.

    Return:
        The pipeline script
    """
    return textwrap.dedent(
        """
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
        }"""
    )


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

    logger.debug("Creating jenkins kubernets cloud, params: %s %s", headers, payload)
    res = unit_web_client.client.requester.post_url(
        url=url, headers=headers, data=payload, timeout=60 * 5
    )
    logger.debug("Cloud created, %s", res.status_code)

    return kubernetes_test_cloud_name if res.status_code == 200 else None
