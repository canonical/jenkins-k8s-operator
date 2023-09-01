# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import pytest
from pytest_operator.plugin import OpsTest

from .constants import INSTALLED_PLUGINS
from .helpers import assert_git_job_success, install_plugins
from .types_ import UnitWebClient


@pytest.mark.usefixtures("app_machine_agent_related")
async def test_git_plugin_machine_agent(ops_test: OpsTest, unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins charm with git plugin installed.
    act: when a job is dispatched with a git workflow.
    assert: job completes successfully.
    """
    await install_plugins(
        ops_test, unit_web_client.unit, unit_web_client.client, INSTALLED_PLUGINS
    )

    # check that the job runs on the Jenkins agent
    job_name = "git-plugin-test-machine"
    assert_git_job_success(unit_web_client.client, job_name, "machine")
