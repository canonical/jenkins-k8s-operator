# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import jenkinsapi.jenkins
import pytest
from pytest_operator.plugin import OpsTest

from .constants import ALLOWED_PLUGINS, INSTALLED_PLUGINS, REMOVED_PLUGINS
from .helpers import install_plugins
from .types_ import UnitWebClient


@pytest.mark.usefixtures("prepare_allowed_plugins_config")
async def test_jenkins_plugins_config(
    ops_test: OpsTest,
    unit_web_client: UnitWebClient,
    update_status_env: typing.Iterable[str],
):
    """
    arrange: given a jenkins charm with plugin config and plugins installed not in the config.
    act: when update_status_hook is fired.
    assert: the plugin is uninstalled and the system message is set on Jenkins.
    """
    await install_plugins(ops_test, unit_web_client.unit, INSTALLED_PLUGINS)

    ret_code, _, stderr = await ops_test.juju(
        "exec",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    res = unit_web_client.client.requester.get_url(unit_web_client.web)
    page_content = str(res.content, encoding="utf-8")

    assert all(plugin in page_content for plugin in REMOVED_PLUGINS), page_content
    assert "The following plugins have been removed by the system administrator:" in page_content
    assert (
        "To allow the plugins, please include them in the plugins configuration of the charm."
        in page_content
    )
    assert all(unit_web_client.client.has_plugin(plugin) for plugin in ALLOWED_PLUGINS)


@pytest.mark.usefixtures("prepare_k8s_agents_relation", "cleanup_k8s_agents_relation")
async def test_git_plugin_k8s_agent(
    ops_test: OpsTest,
    unit_web_client: UnitWebClient,
    gen_git_plugin_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a jenkins charm with git plugin installed.
    act: when a job is dispatched with a git workflow.
    assert: job completes successfully.
    """
    await install_plugins(ops_test, unit_web_client.unit, INSTALLED_PLUGINS)

    # check that the job runs on the Jenkins agent
    job_name = "git-plugin-test-k8s"
    job: jenkinsapi.job.Job = unit_web_client.client.create_job(
        job_name, gen_git_plugin_job_xml("k8s")
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"

    # check that git plugin git repository validation works on Jenkins server
    check_url_res = unit_web_client.client.requester.post_url(
        f"{jenkins_cunit_web_client.clientlient.baseurl}/job/{job_name}/descriptorByName/"
        "hudson.plugins.git.UserRemoteConfig/checkUrl",
        data={
            "value": "https://github.com/canonical/jenkins-k8s-operator",
            "credentialsId": "",
        },
    )
    assert (
        check_url_content := str(check_url_res.content, encoding="utf-8")
    ) == "<div/>", f"Non-empty error message returned, {check_url_content}"


@pytest.mark.usefixtures("prepare_machine_agents_relation", "cleanup_machine_agents_relation")
async def test_git_plugin_machine_agent(
    ops_test: OpsTest,
    unit_web_client: UnitWebClient,
    gen_git_plugin_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a jenkins charm with git plugin installed.
    act: when a job is dispatched with a git workflow.
    assert: job completes successfully.
    """
    await install_plugins(ops_test, unit_web_client.unit, INSTALLED_PLUGINS)

    # check that the job runs on the Jenkins agent
    job_name = "git-plugin-test-machine"
    job: jenkinsapi.job.Job = unit_web_client.client.create_job(
        job_name,
        gen_git_plugin_job_xml("machine"),
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
