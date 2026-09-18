# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures used only by ingress integration tests."""

import pytest_asyncio
from juju.model import Model

from ..helpers import get_model_unit_addresses


@pytest_asyncio.fixture(scope="module", name="traefik_application_and_unit_ip")
async def traefik_application_fixture(model: Model):
    """The application related to Jenkins via ingress v2 relation."""
    traefik = await model.deploy(
        "traefik-k8s", channel="edge", trust=True, config={"routing_mode": "path"}
    )
    await model.wait_for_idle(
        status="active",
        apps=[traefik.name],
        timeout=30 * 60,
        idle_period=30,
        raise_on_error=False,
    )
    unit_ips = await get_model_unit_addresses(model=model, app_name=traefik.name)
    assert unit_ips, f"Unit IP address not found for {traefik.name}"
    return (traefik, unit_ips[0])
