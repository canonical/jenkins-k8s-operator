# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import time

import jenkinsapi
from juju.application import Application
from juju.client import client
from juju.model import Model

from .helpers import assert_substrings_not_in_string


async def test_jenkins_update_ui_disabled(
    web_address: str, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """
    arrange: a Jenkins deployment.
    act: -
    assert: The UI with update suggestion does not pop out
    """
    res = jenkins_client.requester.get_url(f"{web_address}/manage")

    page_content = str(res.content, encoding="utf-8")
    assert_substrings_not_in_string(
        ("New version of Jenkins", "is available", "download"), page_content
    )


async def test_jenkins_automatic_update(
    application: Application, model: Model, jenkins_version: str, latest_jenkins_lts_version: str
):
    """
    arrange: a Jenkins deployment.
    act: update status hook is triggered.
    assert: The latest LTS Jenkins version is set as workload version.
    """
    status: client.FullStatus = await model.get_status()
    app_status: client.ApplicationStatus = status.applications.get(application.name)
    original_workload_version = app_status.workload_version

    await model.set_config({"update-status-hook-interval": "10s"})
    time.sleep(15)
    await model.wait_for_idle(status="active")
    status: client.FullStatus = await model.get_status()
    app_status: client.ApplicationStatus = status.applications.get(application.name)

    assert original_workload_version == jenkins_version
    assert app_status.workload_version == latest_jenkins_lts_version

    await model.set_config({"update-status-hook-interval": "5m"})
