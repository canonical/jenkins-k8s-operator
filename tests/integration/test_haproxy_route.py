# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the jenkins-k8s haproxy-route relation."""

import pytest
import pytest_asyncio
import requests
from juju.application import Application
from juju.model import Model

from .helpers import ensure_relation, get_model_unit_addresses
from .types_ import KeycloakOIDCMetadata

EXTERNAL_HOSTNAME = "jenkins.internal"
SPOE_EXTERNAL_HOSTNAME = "jenkins-spoe.internal"


@pytest_asyncio.fixture(scope="function", name="haproxy")
async def haproxy_fixture(model: Model) -> Application:
    """Deploy and return a ready HAProxy application."""
    haproxy = await model.deploy("haproxy", channel="latest/edge", trust=True)
    await model.wait_for_idle(apps=[haproxy.name], status="active", timeout=20 * 60)
    return haproxy


@pytest_asyncio.fixture(scope="function", name="oauth_integrator")
async def oauth_integrator_fixture(
    model: Model,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
) -> Application:
    """Deploy oauth-external-idp-integrator configured for Keycloak.

    This charm bridges an external OIDC provider (Keycloak) to the oauth
    interface that haproxy-spoe-auth requires.
    """
    # Parse well_known_endpoint to extract base URL
    # e.g. http://10.1.2.3:8080/realms/oidc_test/.well-known/openid-configuration
    base_url = keycloak_oidc_meta.well_known_endpoint.rsplit("/.well-known", 1)[0]

    integrator = await model.deploy(
        "oauth-external-idp-integrator",
        channel="latest/edge",
        trust=True,
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
    await model.wait_for_idle(apps=[integrator.name], status="blocked", timeout=20 * 60)
    return integrator


@pytest_asyncio.fixture(scope="function", name="haproxy_spoe_auth")
async def haproxy_spoe_auth_fixture(
    model: Model,
    oauth_integrator: Application,
) -> Application:
    """Deploy haproxy-spoe-auth configured for the SPOE hostname.

    The hostname config MUST match Jenkins' external-hostname for the
    SPOE protection to apply to the correct backend.
    """
    spoe_auth = await model.deploy(
        "haproxy-spoe-auth",
        channel="latest/edge",
        trust=True,
        config={"hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    # haproxy-spoe-auth requires oauth relation (optional: false)
    await model.integrate(f"{spoe_auth.name}:oauth", f"{oauth_integrator.name}:oauth")
    await model.wait_for_idle(
        apps=[spoe_auth.name, oauth_integrator.name],
        status="active",
        timeout=20 * 60,
    )
    return spoe_auth


@pytest_asyncio.fixture(scope="function", name="haproxy_with_spoe")
async def haproxy_with_spoe_fixture(
    model: Model,
    haproxy_spoe_auth: Application,
) -> Application:
    """Deploy HAProxy and wire up the SPOE auth chain.

    Creates the full chain:
    haproxy -> spoe-auth -> haproxy-spoe-auth -> oauth -> oauth-integrator -> Keycloak
    """
    haproxy = await model.deploy("haproxy", channel="latest/edge", trust=True)
    await model.wait_for_idle(apps=[haproxy.name], status="active", timeout=20 * 60)

    # Wire haproxy to haproxy-spoe-auth via spoe-auth relation
    await model.integrate(f"{haproxy.name}:spoe-auth", f"{haproxy_spoe_auth.name}:spoe-auth")
    await model.wait_for_idle(
        apps=[haproxy.name, haproxy_spoe_auth.name],
        status="active",
        timeout=20 * 60,
    )
    return haproxy


@pytest.mark.abort_on_fail
async def test_haproxy_route_serves_jenkins(
    model: Model,
    application: Application,
    haproxy: Application,
):
    """
    arrange: deploy haproxy and set jenkins external-hostname.

    act: relate jenkins-k8s and haproxy on haproxy-route, wait for idle.
    assert: HAProxy serves Jenkins for the configured Host header.
    """
    await application.set_config({"external-hostname": EXTERNAL_HOSTNAME})

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


@pytest.mark.abort_on_fail
async def test_haproxy_spoe_redirects_to_oidc(
    model: Model,
    application: Application,
    haproxy_with_spoe: Application,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
):
    """
    arrange: deploy full SPOE auth stack (haproxy + haproxy-spoe-auth +
             oauth-integrator + keycloak) and jenkins with external-hostname.

    act: relate jenkins-k8s to haproxy via haproxy-route, send unauthenticated request.

    assert: HAProxy redirects to Keycloak OIDC login (302 to /realms/.../auth).
    """
    # Configure Jenkins with the SPOE-protected hostname
    await application.set_config({"external-hostname": SPOE_EXTERNAL_HOSTNAME})

    # Relate Jenkins to HAProxy via haproxy-route
    await ensure_relation(
        model=model,
        application=application,
        other_application=haproxy_with_spoe,
        relation_name="haproxy-route",
    )

    haproxy_ip = (await get_model_unit_addresses(model, haproxy_with_spoe.name))[0]

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
