# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm Kubernetes agents."""

import logging

import jenkinsapi.jenkins
import jubilant
import requests

import state

from .helpers import run_job
from .resources import ensure_configuration, ensure_relation
from .types_ import JujuApplication

logger = logging.getLogger(__name__)


def test_jenkins_wizard_bypass(web_address: str) -> None:
    """Verify the Jenkins setup wizard is bypassed."""
    # Arrange

    # Act
    response = requests.get(f"{web_address}/login", params={"from": "/"}, timeout=10)

    # Assert
    assert "Unlock Jenkins" not in str(response.content), "Jenkins setup wizard not bypassed."
    assert "Sign in to Jenkins" in str(response.content)


def test_jenkins_k8s_agent_relation(
    model: jubilant.Juju,
    application: JujuApplication,
    jenkins_k8s_agents: JujuApplication,
    extra_jenkins_k8s_agents: JujuApplication,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> None:
    """Verify Kubernetes agent relation lifecycle and deregistration."""
    # Arrange
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

    # Act
    builds = (
        run_job(jenkins_client, jenkins_k8s_agent_node, "k8s"),
        run_job(jenkins_client, extra_jenkins_k8s_agent_node, "k8s-extra"),
    )
    remote_filesystems = (
        jenkins_client.get_node(jenkins_k8s_agent_node).get_config_element("remoteFS"),
        jenkins_client.get_node(extra_jenkins_k8s_agent_node).get_config_element("remoteFS"),
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

    # Assert
    assert all(build.get_status() == "SUCCESS" for build in builds)
    assert remote_filesystems == ("/var/lib/jenkins", "/var/lib/jenkins")
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

    # Arrange
    jenkins_client.create_node(
        name=node_name,
        num_executors=1,
        node_description="Created outside Juju",
        remote_fs="/var/lib/jenkins",
        labels="external",
    )

    try:
        ensure_configuration(
            model,
            application=application,
            configuration={"external-agent-nodes": node_name},
        )

        ensure_relation(
            model=model,
            application=application,
            other_application=jenkins_k8s_agents,
            renew=True,
        )

        # Act
        model.remove_relation(
            f"{application.name}:{state.AGENT_RELATION}",
            f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}",
        )
        model.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=20 * 60)

        # Assert
        assert jenkins_client.get_node(node_name).get_config_element("description") == (
            "Created outside Juju"
        )
        assert node_name in jenkins_client.nodes.iterkeys()
    finally:
        # Teardown
        model.config(application.name, reset=["external-agent-nodes"])
        if node_name in jenkins_client.nodes.iterkeys():
            jenkins_client.delete_node(node_name)
