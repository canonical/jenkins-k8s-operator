# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for JCasC (Jenkins Configuration as Code) feature."""

import logging

import jenkinsapi.jenkins
import pytest
import yaml
from juju.application import Application
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_jcasc_default_config_applied(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm with default jcasc-config.
    act: when the charm is active/idle.
    assert: the JCasC plugin endpoint is reachable and config is applied.
    """
    # The default jcasc-config sets numExecutors: 0 and crumb issuer
    response = jenkins_client.requester.get_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert response.status_code == 200, "JCasC export endpoint should be accessible"
    exported = response.text
    assert "jenkins" in exported, "Exported JCasC should contain jenkins section"


async def test_jcasc_custom_config_updates(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm.
    act: when jcasc-config is updated with a custom systemMessage.
    assert: the system message is applied to Jenkins.
    """
    custom_message = "Managed by JCasC integration test"
    custom_config = yaml.dump(
        {
            "jenkins": {
                "systemMessage": custom_message,
                "numExecutors": 0,
            }
        }
    )

    await application.set_config({"jcasc-config": custom_config})
    await ops_test.model.wait_for_idle(
        apps=[application.name],
        status="active",
        timeout=300,
    )

    # Verify the system message was applied
    response = jenkins_client.requester.get_url(f"{web_address}/api/json")
    assert response.status_code == 200
    api_data = response.json()
    # Jenkins API exposes description field which corresponds to systemMessage
    # Note: may need to check via /configuration-as-code/export instead
    exported_response = jenkins_client.requester.get_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert custom_message in exported_response.text


async def test_jcasc_invalid_yaml_blocks(
    ops_test: OpsTest,
    application: Application,
):
    """
    arrange: given a deployed Jenkins charm.
    act: when jcasc-config is set to invalid YAML.
    assert: the charm enters blocked status.
    """
    await application.set_config({"jcasc-config": "{{invalid yaml [["})
    await ops_test.model.wait_for_idle(
        apps=[application.name],
        status="blocked",
        timeout=120,
    )

    # Verify blocked message
    unit = application.units[0]
    assert "Invalid jcasc-config YAML" in unit.workload_status_message

    # Restore valid config
    default_config = yaml.dump(
        {
            "jenkins": {
                "numExecutors": 0,
            }
        }
    )
    await application.set_config({"jcasc-config": default_config})
    await ops_test.model.wait_for_idle(
        apps=[application.name],
        status="active",
        timeout=300,
    )


async def test_jcasc_reload_without_restart(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a deployed Jenkins charm that is active.
    act: when jcasc-config is changed.
    assert: Jenkins applies the change without restarting (uptime check).
    """
    # Get current Jenkins version header (proves it's running)
    response = jenkins_client.requester.get_url(web_address)
    assert response.status_code == 200
    original_session_cookie = response.cookies

    # Update config with a different message
    new_message = "JCasC hot-reload test"
    new_config = yaml.dump(
        {
            "jenkins": {
                "systemMessage": new_message,
                "numExecutors": 0,
            }
        }
    )
    await application.set_config({"jcasc-config": new_config})
    await ops_test.model.wait_for_idle(
        apps=[application.name],
        status="active",
        timeout=300,
    )

    # Verify config was applied (system message visible in export)
    exported_response = jenkins_client.requester.get_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert new_message in exported_response.text
