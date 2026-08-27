# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm machine agents."""

import jenkinsapi.jenkins
import jubilant

import state

from .constants import LXD_CONTROLLER_NAME
from .helpers import assert_job_success, short_model_name
from .types_ import JujuApplication


def test_jenkins_machine_agent_relation(
    model: jubilant.Juju,
    application: JujuApplication,
    jenkins_machine_agents: JujuApplication,
    machine_model: jubilant.Juju,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify the machine-agent relation lifecycle and deregistration."""
    machine_relation = f"{short_model_name(machine_model)}-{state.AGENT_RELATION}"
    model.consume(
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{state.AGENT_RELATION}",
        alias=machine_relation,
    )
    model.integrate(
        f"{application.name}:{state.AGENT_RELATION}",
        machine_relation,
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, jenkins_machine_agents.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    assert_job_success(jenkins_client, jenkins_machine_agents.name, "machine")

    model.remove_relation(
        f"{application.name}:{state.AGENT_RELATION}",
        machine_relation,
    )
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    machine_model.wait(
        lambda status: jubilant.all_agents_idle(status, jenkins_machine_agents.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    assert not any(application.name in key for key in jenkins_client.nodes.iterkeys())
