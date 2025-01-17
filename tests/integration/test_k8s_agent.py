# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging
from pathlib import Path

import jenkinsapi.jenkins
import requests
import yaml
from juju.application import Application
from juju.model import Model

import state

from .helpers import assert_job_success

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text(encoding="utf-8"))


async def test_jenkins_wizard_bypass(web_address: str):
    """
    arrange: given an active Jenkins charm's unit ip.
    act: when web application is accessed
    assert: wizard is bypassed and a login screen is shown.
    """
    response = requests.get(f"{web_address}/login", params={"from": "/"}, timeout=10)

    # This should not appear since when Jenkins setup is complete, the wizard should have been
    # bypassed.
    assert "Unlock Jenkins" not in str(response.content), "Jenkins setup wizard not bypassed."
    assert "Sign in to Jenkins" in str(response.content)


async def test_jenkins_k8s_agent_relation(
    model: Model,
    application: Application,
    jenkins_k8s_agents: Application,
    extra_jenkins_k8s_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
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
    await application.relate(state.AGENT_RELATION, extra_jenkins_k8s_agents.name)
    await model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name, extra_jenkins_k8s_agents.name],
        wait_for_active=True,
    )

    # 1. Assert that the node is registered and is able to run jobs successfully.
    assert_job_success(jenkins_client, jenkins_k8s_agents.name, "k8s")
    assert_job_success(jenkins_client, extra_jenkins_k8s_agents.name, "k8s-extra")

    # 2. Remove the relation
    await application.remove_relation(
        state.AGENT_RELATION, f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}"
    )
    await application.remove_relation(
        state.AGENT_RELATION, f"{extra_jenkins_k8s_agents.name}:{state.AGENT_RELATION}"
    )
    await model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name, extra_jenkins_k8s_agents.name]
    )

    # 2. Assert that the agent nodes are deregistered from Jenkins.
    assert not any((jenkins_k8s_agents.name in key for key in jenkins_client.get_nodes().keys()))
    assert not any(
        (extra_jenkins_k8s_agents.name in key for key in jenkins_client.get_nodes().keys())
    )
