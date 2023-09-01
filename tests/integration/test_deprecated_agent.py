# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import jenkinsapi.jenkins
import pytest
from juju.application import Application

from .helpers import assert_job_success


@pytest.mark.usefixtures("app_k8s_deprecated_agent_related")
async def test_jenkins_k8s_deprecated_agent_relation(
    jenkins_k8s_agents: Application, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """
    arrange: given jenkins-k8s-agent and jenkins server charms.
    act: when the server charm is related to the k8s agent charm.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    assert_job_success(jenkins_client, jenkins_k8s_agents.name, "k8s")


@pytest.mark.usefixtures("app_machine_deprecated_agent_related")
async def test_jenkins_machine_deprecated_agent_relation(
    jenkins_machine_agents: Application, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """
    arrange: given a cross controller cross model jenkins machine agent with an offer.
    act: when the relation is setup through the offer.
    assert: the relation succeeds and the agent is able to run jobs successfully.
    """
    assert_job_success(jenkins_client, jenkins_machine_agents.name, "machine")
