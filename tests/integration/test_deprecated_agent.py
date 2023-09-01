# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import jenkinsapi.jenkins
import pytest
from juju.application import Application


@pytest.mark.usefixtures("app_k8s_deprecated_agent_related")
async def test_jenkins_k8s_deprecated_agent_relation(
    jenkins_k8s_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given jenkins-k8s-agent and jenkins server charms.
    act: when the server charm is related to the k8s agent charm.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    nodes = jenkins_client.get_nodes()
    assert any(
        (jenkins_k8s_agents.name in key for key in nodes.keys())
    ), "Jenkins k8s agent node not registered."

    job = jenkins_client.create_job(jenkins_k8s_agents.name, gen_jenkins_test_job_xml("k8s"))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


@pytest.mark.usefixtures("app_machine_deprecated_agent_related")
async def test_jenkins_machine_deprecated_agent_relation(
    jenkins_machine_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a cross controller cross model jenkins machine agent with an offer.
    act: when the relation is setup through the offer.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    nodes = jenkins_client.get_nodes()
    assert any(
        (jenkins_machine_agents.name in key for key in nodes.keys())
    ), "Jenkins agent node not registered."

    job = jenkins_client.create_job(
        jenkins_machine_agents.name, gen_jenkins_test_job_xml("machine")
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
