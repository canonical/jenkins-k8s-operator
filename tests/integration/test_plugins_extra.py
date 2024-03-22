# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import logging

import jenkinsapi.plugin
import pytest

from .helpers import (
    declarative_pipeline_script,
    gen_test_pipeline_with_custom_script_xml,
    install_plugins,
)
from .types_ import UnitWebClient

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_pipeline_model_definition_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with declarative pipeline plugin installed.
    act: Run a job using a declarative pipeline script.
    assert: Job succeeds.
    """
    await install_plugins(unit_web_client, ("pipeline-model-definition",))

    job = unit_web_client.client.create_job(
        "pipeline_model_definition_plugin_test",
        gen_test_pipeline_with_custom_script_xml(declarative_pipeline_script()),
    )

    queue_item = job.invoke()
    queue_item.block_until_complete()

    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
