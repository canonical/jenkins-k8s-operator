# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""
import textwrap
import typing

import jenkinsapi.jenkins
import requests
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
        f"{jenkins.EXECUTABLES_PATH / 'jenkins-plugin-manager-2.12.11.jar'}",
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
    # When there are connectivity issues, it prints in stderr and if not it prints in stdout.
    assert any(
        ("Done" in stdout, "Done" in stderr)
    ), f"Failed to install plugins via juju ssh, {stdout}, {stderr}"

    # the library will return 503 or other status codes that are not 200, hence restart and
    # wait rather than check for status code.
    jenkins_client.safe_restart()
    model = ops_test.model
    assert model, "Model not initialized."
    await model.block_until(
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


def _gen_git_test_job_xml(node_label: str):
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


def assert_git_job_success(
    client: jenkinsapi.jenkins.Jenkins, job_name: str, test_target_label: str
):
    """Assert that a test git job can be created and ran successfully.

    Args:
        client: The Jenkins API client.
        job_name: The test job name.
        test_target_label: The Jenkins agent node label.
    """
    job: jenkinsapi.job.Job = client.create_job(job_name, _gen_git_test_job_xml(test_target_label))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
