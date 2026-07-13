# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the jenkins-k8s haproxy-route relation."""

import pytest
import requests
from juju.application import Application
from juju.model import Model

from .helpers import ensure_relation, get_model_unit_addresses

EXTERNAL_HOSTNAME = "jenkins.internal"


@pytest.mark.abort_on_fail
async def test_haproxy_route_serves_jenkins(
    model: Model,
    application: Application,
):
    """
    arrange: deploy haproxy and set jenkins external-hostname.
    act: relate jenkins-k8s and haproxy on haproxy-route, wait for idle.
    assert: HAProxy serves Jenkins for the configured Host header.
    """
    await application.set_config({"external-hostname": EXTERNAL_HOSTNAME})
    haproxy = await model.deploy("haproxy", channel="latest/edge", trust=True)
    await model.wait_for_idle(apps=[haproxy.name], status="active", timeout=20 * 60)

    await ensure_relation(
        model=model,
        application=application,
        other_application=haproxy,
        relation_name="haproxy-route",
    )

    haproxy_ip = (await get_model_unit_addresses(model, haproxy.name))[0]
    response = requests.get(
        f"http://{haproxy_ip}",
        headers={"Host": EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
    )
    # Jenkins' own security realm answers (no SPOE in this tier): unauthenticated
    # access returns 403 with the Jenkins auth page, or 200 if a login page is served.
    assert response.status_code in (200, 403), (
        f"unexpected status {response.status_code}: {response.text[:200]}"
    )
    assert "jenkins" in response.text.lower() or "Authentication required" in response.text
