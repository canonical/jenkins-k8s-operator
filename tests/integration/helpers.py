# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""
import inspect
import textwrap
import time
import typing

import jenkinsapi.jenkins
import kubernetes.client
import requests
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

import jenkins


async def install_plugins(
    ops_test: OpsTest,
    unit: Unit,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    plugins: typing.Iterable[str],
) -> None:
    """Install plugins to Jenkins unit.

    Args:
        ops_test: The Ops testing fixture.
        unit: The Jenkins unit to install plugins to.
        jenkins_client: The Jenkins client of given unit.
        plugins: Desired plugins to install.
    """
    plugins = tuple(plugin for plugin in plugins if not jenkins_client.has_plugin(plugin))
    if not plugins:
        return

    returncode, stdout, stderr = await ops_test.juju(
        "ssh",
        "--container",
        "jenkins",
        unit.name,
        "java",
        "-jar",
        f"{jenkins.EXECUTABLES_PATH / 'jenkins-plugin-manager-2.12.13.jar'}",
        "-w",
        f"{jenkins.EXECUTABLES_PATH / 'jenkins.war'}",
        "-d",
        str(jenkins.PLUGINS_PATH),
        "-p",
        " ".join(plugins),
    )
    assert (
        not returncode
    ), f"Non-zero return code {returncode} received, stdout: {stdout} stderr: {stderr}"
    # When there are connectivity issues it retries with other mirrors/links which the output gets
    # printed in stderr and if not it prints in stdout.
    assert any(
        ("Done" in stdout, "Done" in stderr)
    ), f"Failed to install plugins via juju ssh, {stdout}, {stderr}"

    # the library will return 503 or other status codes that are not 200, hence restart and
    # wait rather than check for status code.
    jenkins_client.safe_restart()
    await unit.model.block_until(
        lambda: requests.get(jenkins_client.baseurl, timeout=10).status_code == 403,
        timeout=300,
        wait_period=10,
    )


def _get_test_job_xml(node_label: str):
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

    job = client.create_job(agent_name, _get_test_job_xml(test_target_label))
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
