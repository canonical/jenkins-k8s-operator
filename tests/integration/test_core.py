# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging
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
    jenkins_test_job_xml: str,
):
    """
    arrange: given jenkins-k8s-agent and jenkins server charms.
    act: when the server charm is related to the k8s agent charm.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    await application.relate("agent", f"{jenkins_k8s_agent.name}")
    await model.wait_for_idle(status="active")

    nodes = jenkins_client.get_nodes()
    assert len(nodes) == 2, "Nodes should contain 2 nodes, 1 Built-in and 1 agent."
    assert "Built-In Node" == nodes.keys()[0]
    assert "jenkins-agent-k8s-0" in nodes.keys()[1]

    job = jenkins_client.create_job("test", jenkins_test_job_xml)
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
