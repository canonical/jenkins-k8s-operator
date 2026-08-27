# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the jenkins-k8s haproxy-route relation."""

import functools
import json
import socket
import ssl

import jubilant
import pytest
import requests
from requests_toolbelt.adapters.host_header_ssl import HostHeaderSSLAdapter

from .constants import LXD_CONTROLLER_NAME
from .helpers import get_model_unit_addresses, short_model_name, wait_for
from .resources import (
    application_ref,
    ensure_application,
    ensure_configuration,
    ensure_integration,
    ensure_offer,
)
from .types_ import JujuApplication, KeycloakOIDCMetadata

EXTERNAL_HOSTNAME = "jenkins.internal"
SPOE_EXTERNAL_HOSTNAME = "jenkins-spoe.internal"
AGENT_EXTERNAL_HOSTNAME = "jenkins-agent.internal"
GATEWAY_CLASS = "ck-gateway"
HAPROXY_ROUTE_RELATION = "haproxy-route"
SELF_SIGNED_CERTIFICATES_APP_NAME = "self-signed-certificates"


@pytest.fixture(scope="module", name="self_signed_certificates")
def self_signed_certificates_fixture(machine_model: jubilant.Juju) -> JujuApplication:
    """Deploy self-signed-certificates to the machine model."""
    return ensure_application(
        machine_model,
        "self-signed-certificates",
        name=SELF_SIGNED_CERTIFICATES_APP_NAME,
        channel="1/stable",
    )


@pytest.fixture(scope="module", name="haproxy")
def haproxy_fixture(
    machine_model: jubilant.Juju,
    self_signed_certificates: JujuApplication,
) -> JujuApplication:
    """Deploy HAProxy and create an offer for cross-model relations."""
    name = "haproxy"
    application = ensure_application(
        machine_model,
        "haproxy",
        name=name,
        channel="2.8/edge",
        config={"external-hostname": EXTERNAL_HOSTNAME},
    )
    ensure_integration(
        machine_model,
        f"{name}:certificates",
        f"{self_signed_certificates.name}:certificates",
        applications=(name, self_signed_certificates.name),
    )
    ensure_offer(
        machine_model,
        application,
        controller=LXD_CONTROLLER_NAME,
        endpoint=HAPROXY_ROUTE_RELATION,
        name=HAPROXY_ROUTE_RELATION,
    )
    return application


@pytest.fixture(scope="module", name="ca_cert_path")
def ca_cert_path_fixture(
    self_signed_certificates: JujuApplication,
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Fetch the self-signed CA certificate into a temporary file."""
    action = self_signed_certificates.model.run(
        self_signed_certificates.units[0],
        "get-ca-certificate",
    )
    ca_certificate = action.results["ca-certificate"]
    ca_cert_file = tmp_path_factory.mktemp("certs") / "ca.pem"
    ca_cert_file.write_text(ca_certificate, encoding="utf-8")
    return str(ca_cert_file)


@pytest.fixture(scope="module", name="oauth_integrator")
def oauth_integrator_fixture(
    machine_model: jubilant.Juju,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
) -> JujuApplication:
    """Deploy oauth-external-idp-integrator configured for Keycloak."""
    base_url = keycloak_oidc_meta.well_known_endpoint.rsplit("/.well-known", 1)[0]
    name = "oauth-external-idp-integrator"
    return ensure_application(
        machine_model,
        "oauth-external-idp-integrator",
        name=name,
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
        expected_status="blocked",
    )


@pytest.fixture(scope="module", name="haproxy_spoe_auth")
def haproxy_spoe_auth_fixture(
    machine_model: jubilant.Juju,
    oauth_integrator: JujuApplication,
) -> JujuApplication:
    """Deploy haproxy-spoe-auth configured for the SPOE hostname."""
    name = "haproxy-spoe-auth"
    application = ensure_application(
        machine_model,
        "haproxy-spoe-auth",
        name=name,
        channel="latest/edge",
        config={"hostname": SPOE_EXTERNAL_HOSTNAME},
        expected_status="blocked",
    )
    ensure_integration(
        machine_model,
        f"{name}:oauth",
        f"{oauth_integrator.name}:oauth",
        applications=(oauth_integrator.name,),
    )
    machine_model.wait(
        lambda status: jubilant.all_blocked(status, name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return application


def _certificate_has_hostname(
    haproxy_ip: str,
    hostname: str,
    ca_cert_path: str,
) -> bool:
    """Return whether HAProxy currently serves a trusted certificate for *hostname*."""
    context = ssl.create_default_context(cafile=ca_cert_path)
    context.check_hostname = False
    try:
        with (
            socket.create_connection((haproxy_ip, 443), timeout=30) as socket_connection,
            context.wrap_socket(socket_connection, server_hostname=hostname) as tls_connection,
        ):
            certificate = tls_connection.getpeercert()
    except (OSError, ssl.SSLError):
        return False

    if not certificate:
        return False
    subject_alt_names = certificate.get("subjectAltName")
    return isinstance(subject_alt_names, tuple) and ("DNS", hostname) in subject_alt_names


@pytest.fixture(scope="module", name="haproxy_with_spoe")
def haproxy_with_spoe_fixture(
    model: jubilant.Juju,
    application: JujuApplication,
    machine_model: jubilant.Juju,
    haproxy: JujuApplication,
    haproxy_spoe_auth: JujuApplication,
    self_signed_certificates: JujuApplication,
    ca_cert_path: str,
) -> JujuApplication:
    """Wire the HAProxy, SPOE, OAuth, and Keycloak authentication chain."""
    # HAProxy proxy mode derives certificate SANs from Jenkins route data.
    ensure_configuration(
        model,
        application=application,
        configuration={"external-hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    ensure_configuration(
        machine_model,
        application=haproxy,
        configuration={"external-hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    ensure_integration(
        machine_model,
        f"{haproxy.name}:spoe-auth",
        f"{haproxy_spoe_auth.name}:spoe-auth",
        applications=(haproxy_spoe_auth.name,),
    )
    # Re-request the certificate after changing the HAProxy hostname. The
    # certificate relation is otherwise allowed to retain the old SAN.
    ensure_integration(
        machine_model,
        f"{haproxy.name}:certificates",
        f"{self_signed_certificates.name}:certificates",
        applications=(haproxy.name, self_signed_certificates.name),
        renew=True,
    )
    machine_model.wait(
        lambda status: jubilant.all_active(
            status, haproxy.name, haproxy_spoe_auth.name, self_signed_certificates.name
        ),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    haproxy_ip = get_model_unit_addresses(machine_model, haproxy.name)[0]
    wait_for(
        functools.partial(
            _certificate_has_hostname,
            haproxy_ip,
            SPOE_EXTERNAL_HOSTNAME,
            ca_cert_path,
        ),
        timeout=10 * 60,
        check_interval=10,
    )
    return haproxy


@pytest.fixture(scope="module", name="gateway_agent_ingress")
def gateway_agent_ingress_fixture(
    model: jubilant.Juju,
    application: JujuApplication,
) -> JujuApplication:
    """Deploy Gateway API and ingress-configurator for agent discovery."""
    gateway_name = "jenkins-gateway-api"
    ingress_name = "jenkins-agent-ingress-configurator"
    ensure_application(
        model,
        "gateway-api-integrator",
        name=gateway_name,
        channel="1/stable",
        trust=True,
    )
    ensure_configuration(
        model,
        application=gateway_name,
        configuration={"gateway-class": GATEWAY_CLASS, "enforce-https": False},
    )
    server_ingress_name = "jenkins-server-ingress"
    ensure_application(
        model,
        "traefik-k8s",
        name=server_ingress_name,
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
    )
    ensure_integration(
        model,
        f"{application.name}:ingress",
        f"{server_ingress_name}:ingress",
        applications=(application.name, server_ingress_name),
    )
    ensure_application(
        model,
        "ingress-configurator",
        name=ingress_name,
        channel="latest/stable",
        trust=True,
        config={"hostname": AGENT_EXTERNAL_HOSTNAME},
    )
    ensure_integration(
        model,
        f"{gateway_name}:gateway-route",
        f"{ingress_name}:gateway-route",
        applications=(gateway_name, ingress_name),
    )
    ensure_integration(
        model,
        f"{application.name}:agent-discovery-ingress",
        f"{ingress_name}:ingress",
        applications=(application.name, ingress_name),
    )
    return application_ref(model, ingress_name)


def test_haproxy_route_serves_jenkins(
    model: jubilant.Juju,
    application: JujuApplication,
    haproxy: JujuApplication,
    machine_model: jubilant.Juju,
    ca_cert_path: str,
) -> None:
    """Verify HAProxy serves Jenkins for the configured host header."""
    # Arrange
    ensure_configuration(
        model,
        application=application,
        configuration={"external-hostname": EXTERNAL_HOSTNAME},
    )
    ensure_integration(
        model,
        f"{application.name}:{HAPROXY_ROUTE_RELATION}",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{HAPROXY_ROUTE_RELATION}",
        applications=(application.name,),
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, haproxy.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    # Act
    haproxy_ip = get_model_unit_addresses(machine_model, haproxy.name)[0]
    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())
    response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
    )

    # Assert
    assert response.status_code in (200, 403), (
        f"unexpected status {response.status_code}: {response.text[:200]}"
    )
    assert "jenkins" in response.text.lower() or "Authentication required" in response.text


def test_haproxy_spoe_redirects_to_oidc(
    model: jubilant.Juju,
    application: JujuApplication,
    haproxy_with_spoe: JujuApplication,
    machine_model: jubilant.Juju,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
    ca_cert_path: str,
) -> None:
    """Verify HAProxy redirects an unauthenticated request to Keycloak."""
    # Arrange
    ensure_configuration(
        model,
        application=application,
        configuration={"external-hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    ensure_integration(
        model,
        f"{application.name}:{HAPROXY_ROUTE_RELATION}",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{HAPROXY_ROUTE_RELATION}",
        applications=(application.name,),
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, haproxy_with_spoe.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    # Act
    haproxy_ip = get_model_unit_addresses(machine_model, haproxy_with_spoe.name)[0]
    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())
    response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": SPOE_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
    )

    # Assert
    assert response.status_code == 302, (
        f"Expected 302 redirect to OIDC, got {response.status_code}: {response.text[:200]}"
    )
    location = response.headers.get("Location", "")
    assert keycloak_oidc_meta.realm in location or "openid-connect/auth" in location, (
        f"Expected redirect to Keycloak OIDC, got Location: {location}"
    )


def test_haproxy_server_and_gateway_agent_discovery(
    model: jubilant.Juju,
    application: JujuApplication,
    haproxy_with_spoe: JujuApplication,
    gateway_agent_ingress: JujuApplication,
    jenkins_machine_agents: JujuApplication,
    machine_model: jubilant.Juju,
    ca_cert_path: str,
) -> None:
    """Verify SPOE server routing and independent Gateway API agent discovery."""
    del gateway_agent_ingress

    # Arrange
    ensure_configuration(
        model,
        application=application,
        configuration={"external-hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    ensure_integration(
        model,
        f"{application.name}:{HAPROXY_ROUTE_RELATION}",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{HAPROXY_ROUTE_RELATION}",
        applications=(application.name,),
    )
    ensure_integration(
        model,
        f"{application.name}:agent",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.agent",
        applications=(application.name,),
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, haproxy_with_spoe.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    # Act
    haproxy_ip = get_model_unit_addresses(machine_model, haproxy_with_spoe.name)[0]
    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())
    response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": SPOE_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
    )

    # Assert
    assert response.status_code == 302

    for unit_name in jenkins_machine_agents.units:
        unit_info = json.loads(machine_model.cli("show-unit", unit_name, "--format=json"))[
            unit_name
        ]
        relation = next(
            relation for relation in unit_info["relation-info"] if relation["endpoint"] == "agent"
        )
        agent_url = next(iter(relation["related-units"].values()))["data"]["url"]
        assert AGENT_EXTERNAL_HOSTNAME in agent_url
        assert SPOE_EXTERNAL_HOSTNAME not in agent_url
        assert not agent_url.startswith("http://10.")
