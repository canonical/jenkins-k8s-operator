# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging
import typing
from pathlib import Path

import jenkinsapi.jenkins
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


async def test_jenkins_k8s_deprecated_agent_relation(
    model: Model,
    application: Application,
    jenkins_k8s_agent: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given jenkins-k8s-agent and jenkins server charms.
    act: when the server charm is related to the k8s agent charm.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    await application.relate(state.DEPRECATED_AGENT_RELATION, f"{jenkins_k8s_agent.name}")
    await model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agent.name], wait_for_active=True
    )

    nodes = jenkins_client.get_nodes()
    assert any(
        (jenkins_k8s_agent.name in key for key in nodes.keys())
    ), "Jenkins k8s agent node not registered."

    job = jenkins_client.create_job(jenkins_k8s_agent.name, gen_jenkins_test_job_xml("k8s"))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


async def test_jenkins_machine_deprecated_agent_relation(
    jenkins_machine_agent: Application,
    application: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a cross controller cross model jenkins machine agent with an offer.
    act: when the relation is setup through the offer.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    model: Model = application.model
    machine_model: Model = jenkins_machine_agent.model
    await application.relate(
        state.DEPRECATED_AGENT_RELATION,
        f"localhost:admin/{machine_model.name}.{jenkins_machine_agent.name}",
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
    await machine_model.wait_for_idle(apps=[jenkins_machine_agent.name], wait_for_active=True)

    nodes = jenkins_client.get_nodes()
    assert any(
        (jenkins_machine_agent.name in key for key in nodes.keys())
    ), "Jenkins agent node not registered."

    job = jenkins_client.create_job(
        jenkins_machine_agent.name, gen_jenkins_test_job_xml("machine")
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


async def test_jenkins_k8s_agent_relation(
    model: Model,
    application: Application,
    new_relation_k8s_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given jenkins-k8s-agent and jenkins server charms.
    act: when the server charm is related to the k8s agent charm.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    await application.relate(state.AGENT_RELATION, new_relation_k8s_agents.name)
    await model.wait_for_idle(
        apps=[application.name, new_relation_k8s_agents.name], wait_for_active=True
    )

    nodes = jenkins_client.get_nodes()
    assert any(
        (new_relation_k8s_agents.name in key for key in nodes.keys())
    ), "Jenkins k8s agent node not registered."

    job = jenkins_client.create_job(new_relation_k8s_agents.name, gen_jenkins_test_job_xml("k8s"))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


async def test_jenkins_k8s_agent_relation_removed(
    model: Model,
    new_relation_k8s_agents_related: Application,
    new_relation_k8s_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a jenkins server charm related to jenkins-k8s-agent charm via agent relation.
    act: when the relation is removed.
    assert: no agent nodes remain registered.
    """
    await new_relation_k8s_agents_related.remove_relation(
        state.AGENT_RELATION, f"{new_relation_k8s_agents.name}:{state.AGENT_RELATION}"
    )
    await model.wait_for_idle(
        apps=[new_relation_k8s_agents_related.name, new_relation_k8s_agents.name]
    )

    nodes = jenkins_client.get_nodes()
    assert not any((new_relation_k8s_agents.name in key for key in nodes.keys()))


async def test_jenkins_machine_agent_relation(
    model: Model,
    application: Application,
    new_relation_machine_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a cross controller cross model jenkins machine agent with an offer.
    act: when the relation is setup through the offer.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    machine_model: Model = new_relation_machine_agents.model
    await application.relate(
        state.AGENT_RELATION,
        f"localhost:admin/{machine_model.name}.{new_relation_machine_agents.name}",
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
    await machine_model.wait_for_idle(
        apps=[new_relation_machine_agents.name], wait_for_active=True
    )

    nodes = jenkins_client.get_nodes()
    assert any(
        (new_relation_machine_agents.name in key for key in nodes.keys())
    ), "Jenkins agent nodes not registered."

    job = jenkins_client.create_job(
        new_relation_machine_agents.name, gen_jenkins_test_job_xml("machine")
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


async def test_jenkins_machine_agent_relation_removed(
    model: Model,
    new_relation_agent_related: Application,
    new_relation_machine_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given jenkins server charm related to jenkins-agent machine charm via agent relation.
    act: when the relation is removed.
    assert: no agent nodes remain registered.
    """
    await new_relation_agent_related.remove_relation(
        state.AGENT_RELATION, f"{new_relation_machine_agents.name}:{state.AGENT_RELATION}"
    )
    await model.wait_for_idle(apps=[new_relation_agent_related.name])

    nodes = jenkins_client.get_nodes()
    assert not any((new_relation_machine_agents.name in key for key in nodes.keys()))
