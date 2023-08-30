# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging
import typing
from pathlib import Path

import jenkinsapi.jenkins
import pytest
import requests
import yaml
from juju.application import Application
from juju.model import Model

import state

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))


async def test_jenkins_wizard_bypass(web_address: str):
    """
    arrange: given an active Jenkins charm's unit ip.
    act: when web application is accessed
    assert: wizard is bypassed and a login screen is shown.
    """
    response = requests.get(f"{web_address}/login", params={"from": "/"}, timeout=10)

    assert "Unlock Jenkins" not in str(response.content)
    assert "Welcome to Jenkins!" in str(response.content)


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


async def test_jenkins_k8s_agent_relation(
    model: Model,
    application: Application,
    jenkins_k8s_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given jenkins-k8s-agent and jenkins server charms.
    act:
        1. when the server charm is related to the k8s agent charm.
        2. when the relation is removed.
    assert:
        1. the relation succeeds and the k8s agent is able to run jobs successfully.
        2. the k8s agent is deregistered from Jenkins.
    """
    # 1. Relate jenkins-k8s charm to the jenkins-k8s-agent charm.
    await application.relate(state.AGENT_RELATION, jenkins_k8s_agents.name)
    await model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name], wait_for_active=True
    )

    # 1. Assert that the node is registered and is able to run jobs successfully.
    assert any(
        (jenkins_k8s_agents.name in key for key in jenkins_client.get_nodes().keys())
    ), "Jenkins k8s agent node not registered."
    job = jenkins_client.create_job(jenkins_k8s_agents.name, gen_jenkins_test_job_xml("k8s"))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"

    # 2. Remove the relation
    await application.remove_relation(
        state.AGENT_RELATION, f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}"
    )
    await model.wait_for_idle(apps=[application.name, jenkins_k8s_agents.name])

    # 2. Assert that the agent nodes are deregistered from Jenkins.
    assert not any((application.name in key for key in jenkins_client.get_nodes().keys()))


async def test_jenkins_machine_agent_relation(
    app_machine_agent_related: Application,
    jenkins_machine_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a cross controller cross model jenkins machine agent with an offer.
    act:
        1. when the server charm is related to the machine agent charm.
        2. when the relation is removed.
    assert:
        1. the relation succeeds and the machine agent is able to run jobs successfully.
        2. the machine agent is deregistered from Jenkins.
    """
    application = app_machine_agent_related

    # 1. Assert that the node is registered and is able to run jobs successfully.
    assert any(
        (jenkins_machine_agents.name in key for key in jenkins_client.get_nodes().keys())
    ), "Jenkins agent nodes not registered."

    job = jenkins_client.create_job(
        jenkins_machine_agents.name, gen_jenkins_test_job_xml("machine")
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"

    # 2. Remove the relation
    model: Model = application.model
    machine_model: Model = jenkins_machine_agents.model
    await application.remove_relation(state.AGENT_RELATION, state.AGENT_RELATION)
    await model.wait_for_idle(apps=[application.name])
    await machine_model.wait_for_idle(apps=[jenkins_machine_agents.name])

    # 2. Assert that the agent nodes are deregistered from Jenkins.
    assert not any((application.name in key for key in jenkins_client.get_nodes().keys()))
