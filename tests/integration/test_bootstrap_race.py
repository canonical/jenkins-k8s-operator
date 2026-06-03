# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Jenkins bootstrap race conditions."""

import logging

import pytest
from juju.application import Application
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_bootstrap_with_ingress_prefix(
    model: Model, charm: str, jenkins_image: str, ops_test: OpsTest
):
    """
    arrange: deploy Jenkins with traefik ingress to set a non-trivial prefix.
    act: wait for the charm to bootstrap.
    assert: the charm reaches active status (bootstrap succeeded despite prefix).

    This catches crumb/session race conditions where the JENKINS_PREFIX causes
    crumb URLs and token generation URLs to diverge, invalidating session-bound crumbs.
    """
    resources = {"jenkins-image": jenkins_image}
    app_name = "jenkins-prefix-test"

    # Deploy traefik for ingress (sets prefix on the jenkins app)
    traefik_app = await model.deploy(
        "traefik-k8s",
        application_name="traefik-prefix",
        channel="latest/stable",
        trust=True,
    )

    application = await model.deploy(
        charm,
        resources=resources,
        application_name=app_name,
    )

    # Relate to traefik — this sets JENKINS_PREFIX to /<model>-<app>-<unit>
    await model.integrate(f"{app_name}:ingress", "traefik-prefix:ingress")

    await model.wait_for_idle(
        apps=[application.name],
        raise_on_error=False,
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=30 * 60,
        idle_period=30,
    )
    assert application.status == "active", (
        f"Jenkins with ingress prefix failed to bootstrap: {application.status}"
    )
    # Cleanup
    await application.remove()
    await traefik_app.remove()
    await model.block_until(lambda: app_name not in model.applications, timeout=300)


@pytest.mark.abort_on_fail
async def test_bootstrap_after_restart(application: Application, unit: Unit):
    """
    arrange: a running Jenkins deployment.
    act: delete the API token file and restart the workload to re-trigger bootstrap.
    assert: the charm re-bootstraps successfully and returns to active status.

    This exercises the bootstrap code path (crumb fetch + token generation) on an
    already-initialized Jenkins instance, which is more likely to hit the crumb/session
    race because Jenkins's security subsystem restarts with existing state.
    """
    # Delete the API token to force re-bootstrap on next pebble-ready
    action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble exec -- rm -f /var/lib/jenkins/juju_api_token"
    )
    await action.wait()

    # Restart the jenkins service — triggers pebble-ready → bootstrap
    action = await unit.run(
        "PEBBLE_SOCKET=/charm/containers/jenkins/pebble.socket "
        "/charm/bin/pebble restart jenkins"
    )
    await action.wait()
    assert action.status == "completed", f"Failed to restart jenkins: {action.data}"

    # Wait for the charm to re-settle — if crumb race hits, this will error/block
    model = unit.model
    await model.wait_for_idle(
        apps=[application.name],
        raise_on_error=False,
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=10 * 60,
        idle_period=30,
    )
    assert application.status == "active", (
        f"Jenkins failed to re-bootstrap after restart: {application.status}"
    )
