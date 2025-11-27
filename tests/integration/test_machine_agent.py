# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import jenkinsapi.jenkins
from juju.application import Application

import state

from .helpers import assert_job_success


async def test_jenkins_machine_agent_relation(
    application: Application,
    jenkins_machine_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
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
    # 1. Relate jenkins-k8s charm to the jenkins-agent charm.
    model = application.model
    machine_model = jenkins_machine_agents.model
    # this code is similar to the machine_agent_related_app fixture but shouldn't be using the
    # fixture since this test tests for teardown of relation as well.
    # pylint: disable=duplicate-code
    await model.relate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"localhost:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(apps=[jenkins_machine_agents.name], wait_for_active=True)
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
    # pylint: enable=duplicate-code

    # 1. Assert that the node is registered and is able to run jobs successfully.
    assert_job_success(jenkins_client, jenkins_machine_agents.name, "machine")

    # 2. Remove the relation
    await application.remove_relation(state.AGENT_RELATION, state.AGENT_RELATION)
    await model.wait_for_idle(apps=[application.name])
    await machine_model.wait_for_idle(apps=[jenkins_machine_agents.name])

    # 2. Assert that the agent nodes are deregistered from Jenkins.
    assert not any(application.name in key for key in jenkins_client.get_nodes())
