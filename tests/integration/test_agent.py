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


async def test_jenkins_agent_relation(
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
    await application.relate("agent", f"{jenkins_k8s_agent.name}")
    await model.wait_for_idle(status="active")

    nodes = jenkins_client.get_nodes()
    assert any(
        ("jenkins-agent-k8s-0" in key for key in nodes.keys())
    ), "Jenkins k8s agent node not registered."

    job = jenkins_client.create_job("test", gen_jenkins_test_job_xml("k8s"))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


async def test_jenkins_machine_agent_relation(
    model: Model,
    jenkins_machine_agent: Application,
    application: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    gen_jenkins_test_job_xml: typing.Callable[[str], str],
):
    """
    arrange: given a cross controller cross model jenkins machine agent with an offer.
    act: when the relation is setup through an offer.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    controller_name = model_name = jenkins_machine_agent.model.name
    await model.relate(
        f"{application.name}:agent",
        f"{controller_name}:admin/{model_name}.{jenkins_machine_agent.name}",
    )
    await model.wait_for_idle(status="active", timeout=1200)

    nodes = jenkins_client.get_nodes()
    assert any(
        ("jenkins-agent-0" in key for key in nodes.keys())
    ), "Jenkins agent node not registered."

    job = jenkins_client.create_job("test", gen_jenkins_test_job_xml("machine"))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
