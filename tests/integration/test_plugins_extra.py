# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging

import jenkinsapi
import pytest
from juju.application import Application

import state

from .helpers import (
    declarative_pipeline_script,
    gen_test_pipeline_with_custom_script_xml,
    install_plugins,
)
from .types_ import UnitWebClient

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_pipeline_model_definition_plugin(
    application: Application,
    jenkins_k8s_agents: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a Jenkins charm with declarative pipeline plugin installed.
    act: Run a job using a declarative pipeline script.
    assert: Job succeeds.
    """
    await install_plugins(
        UnitWebClient(application.units[0], web_address, jenkins_client),
        ("pipeline-model-definition",),
    )

    application.relate(state.AGENT_RELATION, f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}")
    await application.model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name], wait_for_active=True, check_freq=5
    )

    job = jenkins_client.create_job(
        "pipeline_model_definition_plugin_test",
        gen_test_pipeline_with_custom_script_xml(declarative_pipeline_script()),
    )

    queue_item = job.invoke()
    queue_item.block_until_complete()

    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
