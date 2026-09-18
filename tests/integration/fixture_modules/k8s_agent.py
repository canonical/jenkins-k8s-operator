# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures used only by Kubernetes-agent integration tests."""

from typing import AsyncGenerator

import pytest_asyncio
from juju.application import Application
from juju.model import Model


@pytest_asyncio.fixture(scope="function", name="extra_jenkins_k8s_agents")
async def extra_jenkins_k8s_agents_fixture(
    model: Model,
) -> AsyncGenerator[Application, None]:
    """The Jenkins k8s agent."""
    agent_app: Application = await model.deploy(
        "jenkins-agent-k8s",
        base="ubuntu@24.04",
        config={"jenkins_agent_labels": "k8s-extra"},
        channel="latest/edge",
        application_name="jenkins-agent-k8s-extra",
    )
    await model.wait_for_idle(apps=[agent_app.name], status="blocked")
    yield agent_app
