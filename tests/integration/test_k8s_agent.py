# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm Kubernetes agents."""

import logging

import jenkinsapi.jenkins
import jubilant
import requests

import state

from .helpers import assert_job_success, ensure_relation
from .types_ import JujuApplication

logger = logging.getLogger(__name__)


def test_jenkins_wizard_bypass(web_address: str) -> None:
    """Verify the Jenkins setup wizard is bypassed.

    Arrange: Use the active Jenkins web address.
    Act: Request the Jenkins login page with `/` as the `from` query parameter.
    Assert: The response does not contain "Unlock Jenkins" and contains "Sign in to Jenkins".
    """
    response = requests.get(f"{web_address}/login", params={"from": "/"}, timeout=10)
    assert "Unlock Jenkins" not in str(response.content), "Jenkins setup wizard not bypassed."
    assert "Sign in to Jenkins" in str(response.content)


def test_jenkins_k8s_agent_relation(
    model: jubilant.Juju,
    application: JujuApplication,
    jenkins_k8s_agents: JujuApplication,
    extra_jenkins_k8s_agents: JujuApplication,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify the Kubernetes agent relation lifecycle and deregistration.

    Arrange: Use the Jenkins server, two Kubernetes agent applications, and a Jenkins API client.
    Act:
        1. Relate the server to both Kubernetes agents, run jobs on their nodes, and inspect their
           remote file-system settings.
        2. Remove both relations and wait for all agents to become idle.
    Assert:
        1. Both agent jobs succeed, and both nodes use `/var/lib/jenkins` as their remote
           file system.
        2. Both agent nodes are absent from Jenkins after relation removal.
    """
    ensure_relation(
        model=model,
        application=application,
        other_application=jenkins_k8s_agents,
    )
    ensure_relation(
        model=model,
        application=application,
        other_application=extra_jenkins_k8s_agents,
    )

    jenkins_k8s_agent_node = jenkins_k8s_agents.units[0].replace("/", "-")
    extra_jenkins_k8s_agent_node = extra_jenkins_k8s_agents.units[0].replace("/", "-")
    node_names = sorted(jenkins_client.nodes.iterkeys())
    logger.info(
        "Jenkins agent nodes after relation: expected=%s actual=%s",
        [jenkins_k8s_agent_node, extra_jenkins_k8s_agent_node],
        node_names,
    )

    assert_job_success(jenkins_client, jenkins_k8s_agent_node, "k8s")
    assert_job_success(jenkins_client, extra_jenkins_k8s_agent_node, "k8s-extra")
    assert jenkins_client.get_node(jenkins_k8s_agent_node).get_config_element("remoteFS") == (
        "/var/lib/jenkins"
    )
    assert (
        jenkins_client.get_node(extra_jenkins_k8s_agent_node).get_config_element("remoteFS")
        == "/var/lib/jenkins"
    )

    model.remove_relation(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}",
    )
    model.remove_relation(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{extra_jenkins_k8s_agents.name}:{state.AGENT_RELATION}",
    )
    model.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=20 * 60)

    node_names = sorted(jenkins_client.nodes.iterkeys())
    logger.info(
        "Jenkins agent nodes after relation removal: removed=%s remaining=%s",
        [jenkins_k8s_agent_node, extra_jenkins_k8s_agent_node],
        node_names,
    )
    assert jenkins_k8s_agent_node not in node_names
    assert extra_jenkins_k8s_agent_node not in node_names


def test_manually_managed_node_survives_agent_relation(
    model: jubilant.Juju,
    application: JujuApplication,
    jenkins_k8s_agents: JujuApplication,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Preserve a manually created node through agent relation reconciliation."""
    node_name = "manual-external-agent"
    jenkins_client.create_node(
        name=node_name,
        num_executors=1,
        node_description="Created outside Juju",
        remote_fs="/var/lib/jenkins",
        labels="external",
    )

    try:
        model.config(application.name, {"external-agent-nodes": node_name})
        model.wait(
            lambda status: jubilant.all_active(status, application.name),
            error=jubilant.any_error,
            timeout=20 * 60,
        )

        ensure_relation(
            model=model,
            application=application,
            other_application=jenkins_k8s_agents,
            renew=True,
        )

        assert jenkins_client.get_node(node_name).get_config_element("description") == (
            "Created outside Juju"
        )

        model.remove_relation(
            f"{application.name}:{state.AGENT_RELATION}",
            f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}",
        )
        model.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=20 * 60)
        assert node_name in jenkins_client.nodes.iterkeys()
    finally:
        model.config(application.name, reset=["external-agent-nodes"])
        if node_name in jenkins_client.nodes.iterkeys():
            jenkins_client.delete_node(node_name)
