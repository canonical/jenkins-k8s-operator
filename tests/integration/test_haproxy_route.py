# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the jenkins-k8s haproxy-route relation."""

import secrets
from typing import AsyncGenerator

import pytest
import pytest_asyncio
import requests
from juju.application import Application
from juju.controller import Controller
from juju.model import Model

from .helpers import get_model_unit_addresses
from .types_ import KeycloakOIDCMetadata

EXTERNAL_HOSTNAME = "jenkins.internal"
SPOE_EXTERNAL_HOSTNAME = "jenkins-spoe.internal"
HAPROXY_ROUTE_RELATION = "haproxy-route"


@pytest_asyncio.fixture(scope="function", name="haproxy_model")
async def haproxy_model_fixture(
    request: pytest.FixtureRequest,
    machine_controller: Controller,
) -> AsyncGenerator[Model, None]:
    """Create a model on the LXD controller for HAProxy (machine charm)."""
    haproxy_model_name = f"haproxy-{secrets.token_hex(2)}"
    model = await machine_controller.add_model(haproxy_model_name)
    await model.connect(f"localhost:admin/{model.name}")
    yield model
    if not request.config.option.keep_models:
        await machine_controller.destroy_models(
            model.name, destroy_storage=True, force=True, max_wait=10 * 60
        )
    await model.disconnect()


@pytest_asyncio.fixture(scope="function", name="haproxy")
async def haproxy_fixture(haproxy_model: Model) -> Application:
    """Deploy HAProxy to the machine model and create an offer for CMR."""
    haproxy = await haproxy_model.deploy(
        "haproxy",
        channel="latest/edge",
        config={"external-hostname": EXTERNAL_HOSTNAME},
    )
    await haproxy_model.wait_for_idle(apps=[haproxy.name], status="active", timeout=20 * 60)
    # Create offer for cross-model relation with jenkins-k8s
    await haproxy_model.create_offer(
        f"{haproxy.name}:{HAPROXY_ROUTE_RELATION}", HAPROXY_ROUTE_RELATION
    )
    return haproxy


@pytest_asyncio.fixture(scope="function", name="oauth_integrator")
async def oauth_integrator_fixture(
    haproxy_model: Model,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
) -> Application:
    """Deploy oauth-external-idp-integrator configured for Keycloak.

    This charm bridges an external OIDC provider (Keycloak) to the oauth
    interface that haproxy-spoe-auth requires. This is a machine charm.
    """
    # Parse well_known_endpoint to extract base URL
    # e.g. http://10.1.2.3:8080/realms/oidc_test/.well-known/openid-configuration
    base_url = keycloak_oidc_meta.well_known_endpoint.rsplit("/.well-known", 1)[0]

    integrator = await haproxy_model.deploy(
        "oauth-external-idp-integrator",
        channel="latest/edge",
        config={
            "client_id": keycloak_oidc_meta.client_id,
            "client_secret": keycloak_oidc_meta.client_secret,
            "issuer_url": base_url,
            "authorization_endpoint": f"{base_url}/protocol/openid-connect/auth",
            "token_endpoint": f"{base_url}/protocol/openid-connect/token",
            "introspection_endpoint": f"{base_url}/protocol/openid-connect/token/introspect",
            "jwks_endpoint": f"{base_url}/protocol/openid-connect/certs",
            "userinfo_endpoint": f"{base_url}/protocol/openid-connect/userinfo",
            "scope": "openid email profile",
        },
    )
    await haproxy_model.wait_for_idle(apps=[integrator.name], status="blocked", timeout=20 * 60)
    return integrator


@pytest_asyncio.fixture(scope="function", name="haproxy_spoe_auth")
async def haproxy_spoe_auth_fixture(
    haproxy_model: Model,
    oauth_integrator: Application,
) -> Application:
    """Deploy haproxy-spoe-auth configured for the SPOE hostname.

    The hostname config MUST match Jenkins' external-hostname for the
    SPOE protection to apply to the correct backend. This is a machine charm.
    """
    spoe_auth = await haproxy_model.deploy(
        "haproxy-spoe-auth",
        channel="latest/edge",
        config={"hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    # haproxy-spoe-auth requires oauth relation (optional: false)
    await haproxy_model.integrate(f"{spoe_auth.name}:oauth", f"{oauth_integrator.name}:oauth")
    await haproxy_model.wait_for_idle(
        apps=[spoe_auth.name, oauth_integrator.name],
        status="active",
        timeout=20 * 60,
    )
    return spoe_auth


@pytest_asyncio.fixture(scope="function", name="haproxy_with_spoe")
async def haproxy_with_spoe_fixture(
    haproxy_model: Model,
    haproxy_spoe_auth: Application,
) -> Application:
    """Deploy HAProxy and wire up the SPOE auth chain on the machine model.

    Creates the full chain (all on machine model):
    haproxy -> spoe-auth -> haproxy-spoe-auth -> oauth -> oauth-integrator -> Keycloak
    """
    haproxy = await haproxy_model.deploy(
        "haproxy",
        channel="latest/edge",
        config={"external-hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    await haproxy_model.wait_for_idle(apps=[haproxy.name], status="active", timeout=20 * 60)

    # Wire haproxy to haproxy-spoe-auth via spoe-auth relation
    await haproxy_model.integrate(
        f"{haproxy.name}:spoe-auth", f"{haproxy_spoe_auth.name}:spoe-auth"
    )
    await haproxy_model.wait_for_idle(
        apps=[haproxy.name, haproxy_spoe_auth.name],
        status="active",
        timeout=20 * 60,
    )

    # Create offer for cross-model relation with jenkins-k8s
    await haproxy_model.create_offer(
        f"{haproxy.name}:{HAPROXY_ROUTE_RELATION}", HAPROXY_ROUTE_RELATION
    )
    return haproxy


@pytest.mark.abort_on_fail
async def test_haproxy_route_serves_jenkins(
    model: Model,
    application: Application,
    haproxy: Application,
    haproxy_model: Model,
):
    """
    arrange: deploy haproxy on machine model and set jenkins external-hostname.

    act: relate jenkins-k8s and haproxy via CMR on haproxy-route, wait for idle.
    assert: HAProxy serves Jenkins for the configured Host header.
    """
    await application.set_config({"external-hostname": EXTERNAL_HOSTNAME})

    # Cross-model relation: k8s model (jenkins) -> machine model (haproxy)
    await model.integrate(
        f"{application.name}:{HAPROXY_ROUTE_RELATION}",
        f"localhost:admin/{haproxy_model.name}.{HAPROXY_ROUTE_RELATION}",
    )
    await haproxy_model.wait_for_idle(apps=[haproxy.name], wait_for_active=True, timeout=20 * 60)
    await model.wait_for_idle(apps=[application.name], wait_for_active=True, timeout=20 * 60)

    haproxy_ip = (await get_model_unit_addresses(haproxy_model, haproxy.name))[0]
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


@pytest.mark.abort_on_fail
async def test_haproxy_spoe_redirects_to_oidc(
    model: Model,
    application: Application,
    haproxy_with_spoe: Application,
    haproxy_model: Model,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
):
    """
    arrange: deploy full SPOE auth stack (haproxy + haproxy-spoe-auth +
             oauth-integrator + keycloak) and jenkins with external-hostname.

    act: relate jenkins-k8s to haproxy via CMR on haproxy-route, send unauthenticated request.

    assert: HAProxy redirects to Keycloak OIDC login (302 to /realms/.../auth).
    """
    # Configure Jenkins with the SPOE-protected hostname
    await application.set_config({"external-hostname": SPOE_EXTERNAL_HOSTNAME})

    # Cross-model relation: k8s model (jenkins) -> machine model (haproxy)
    await model.integrate(
        f"{application.name}:{HAPROXY_ROUTE_RELATION}",
        f"localhost:admin/{haproxy_model.name}.{HAPROXY_ROUTE_RELATION}",
    )
    await haproxy_model.wait_for_idle(
        apps=[haproxy_with_spoe.name], wait_for_active=True, timeout=20 * 60
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True, timeout=20 * 60)

    haproxy_ip = (await get_model_unit_addresses(haproxy_model, haproxy_with_spoe.name))[0]

    # Send unauthenticated request - SPOE should redirect to OIDC
    response = requests.get(
        f"http://{haproxy_ip}",
        headers={"Host": SPOE_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,  # Don't follow redirects - we want to see the 302
    )

    # SPOE auth redirects unauthenticated requests to OIDC provider
    # Expected: 302 redirect to Keycloak's authorization endpoint
    assert response.status_code == 302, (
        f"Expected 302 redirect to OIDC, got {response.status_code}: {response.text[:200]}"
    )

    location = response.headers.get("Location", "")
    # Verify redirect is to Keycloak (the OIDC provider)
    # Location should contain the Keycloak realm's auth endpoint
    assert keycloak_oidc_meta.realm in location or "openid-connect/auth" in location, (
        f"Expected redirect to Keycloak OIDC, got Location: {location}"
    )
