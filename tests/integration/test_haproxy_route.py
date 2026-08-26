# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the jenkins-k8s haproxy-route relation."""

import base64
import json
from pathlib import Path

import pytest
import pytest_asyncio
import requests
from juju.application import Application
from juju.model import Model
from pytest_operator.plugin import OpsTest
from requests_toolbelt.adapters.host_header_ssl import HostHeaderSSLAdapter

from .helpers import assert_job_success, get_model_unit_addresses
from .types_ import KeycloakOIDCMetadata

EXTERNAL_HOSTNAME = "jenkins.internal"
SPOE_EXTERNAL_HOSTNAME = "jenkins-spoe.internal"
AGENT_EXTERNAL_HOSTNAME = "jenkins-agent.internal"
HAPROXY_ROUTE_RELATION = "haproxy-route"
SELF_SIGNED_CERTIFICATES_APP_NAME = "self-signed-certificates"


@pytest_asyncio.fixture(scope="module", name="self_signed_certificates")
async def self_signed_certificates_fixture(machine_model: Model) -> Application:
    """Deploy self-signed-certificates to the machine model."""
    self_signed_certificates = await machine_model.deploy(
        SELF_SIGNED_CERTIFICATES_APP_NAME,
        channel="1/stable",
    )
    assert isinstance(self_signed_certificates, Application)
    return self_signed_certificates


@pytest_asyncio.fixture(scope="module", name="haproxy")
async def haproxy_fixture(
    machine_model: Model, self_signed_certificates: Application
) -> Application:
    """Deploy HAProxy to the machine model and create an offer for CMR."""
    haproxy = await machine_model.deploy(
        "haproxy",
        channel="2.8/edge",
        config={"external-hostname": EXTERNAL_HOSTNAME},
    )
    await machine_model.integrate(
        f"{haproxy.name}:certificates", f"{self_signed_certificates.name}:certificates"
    )
    await machine_model.wait_for_idle(
        apps=[haproxy.name, self_signed_certificates.name], status="active", timeout=20 * 60
    )
    # Create offer for cross-model relation with jenkins-k8s
    await machine_model.create_offer(
        f"{haproxy.name}:{HAPROXY_ROUTE_RELATION}", HAPROXY_ROUTE_RELATION
    )
    return haproxy


@pytest_asyncio.fixture(scope="module", name="ca_cert_path")
async def ca_cert_path_fixture(
    self_signed_certificates: Application,
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Fetch the self-signed CA certificate and write it to a temp file.

    Used to verify TLS connections against HAProxy's self-signed cert instead
    of disabling certificate verification outright.
    """
    unit = self_signed_certificates.units[0]
    action = await unit.run_action("get-ca-certificate")
    await action.wait()
    ca_certificate = action.results["ca-certificate"]

    ca_cert_file = tmp_path_factory.mktemp("certs") / "ca.pem"
    ca_cert_file.write_text(ca_certificate, encoding="utf-8")
    return str(ca_cert_file)


@pytest_asyncio.fixture(scope="module", name="oauth_integrator")
async def oauth_integrator_fixture(
    machine_model: Model,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
) -> Application:
    """Deploy oauth-external-idp-integrator configured for Keycloak.

    This charm bridges an external OIDC provider (Keycloak) to the oauth
    interface that haproxy-spoe-auth requires. This is a machine charm.
    """
    # Parse well_known_endpoint to extract base URL
    # e.g. http://10.1.2.3:8080/realms/oidc_test/.well-known/openid-configuration
    base_url = keycloak_oidc_meta.well_known_endpoint.rsplit("/.well-known", 1)[0]

    integrator = await machine_model.deploy(
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
    await machine_model.wait_for_idle(apps=[integrator.name], status="blocked", timeout=20 * 60)
    return integrator


@pytest_asyncio.fixture(scope="module", name="haproxy_spoe_auth")
async def haproxy_spoe_auth_fixture(
    machine_model: Model,
    oauth_integrator: Application,
) -> Application:
    """Deploy haproxy-spoe-auth configured for the SPOE hostname.

    The hostname config MUST match Jenkins' external-hostname for the
    SPOE protection to apply to the correct backend. This is a machine charm.
    """
    spoe_auth = await machine_model.deploy(
        "haproxy-spoe-auth",
        channel="latest/edge",
        config={"hostname": SPOE_EXTERNAL_HOSTNAME},
    )
    # haproxy-spoe-auth requires oauth relation (optional: false)
    await machine_model.integrate(f"{spoe_auth.name}:oauth", f"{oauth_integrator.name}:oauth")
    await machine_model.wait_for_idle(
        apps=[oauth_integrator.name], status="active", timeout=20 * 60
    )
    # haproxy-spoe-auth also requires the spoe-auth relation (wired in the
    # haproxy_with_spoe fixture); until then it stays blocked, so only wait
    # for the oauth side to settle here.
    await machine_model.wait_for_idle(
        apps=[spoe_auth.name],
        status="blocked",
        timeout=20 * 60,
    )
    return spoe_auth


@pytest_asyncio.fixture(scope="module", name="haproxy_with_spoe")
async def haproxy_with_spoe_fixture(
    machine_model: Model,
    haproxy: Application,
    haproxy_spoe_auth: Application,
) -> Application:
    """Deploy HAProxy and wire up the SPOE auth chain on the machine model.

    Creates the full chain (all on machine model):
    haproxy -> spoe-auth -> haproxy-spoe-auth -> oauth -> oauth-integrator -> Keycloak

    Reuses the same haproxy deployment as the `haproxy` fixture (module-scoped)
    instead of deploying a second haproxy + self-signed-certificates pair.
    """
    # Point haproxy at the SPOE-protected hostname (must match haproxy-spoe-auth's
    # hostname config for SPOE to apply to the correct backend).
    await haproxy.set_config({"external-hostname": SPOE_EXTERNAL_HOSTNAME})
    # Wire haproxy to haproxy-spoe-auth via spoe-auth relation
    await machine_model.integrate(
        f"{haproxy.name}:spoe-auth", f"{haproxy_spoe_auth.name}:spoe-auth"
    )
    await machine_model.wait_for_idle(
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
    machine_model: Model,
    ca_cert_path: str,
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
        f"localhost:admin/{machine_model.name}.{HAPROXY_ROUTE_RELATION}",
    )
    await machine_model.wait_for_idle(apps=[haproxy.name], wait_for_active=True, timeout=20 * 60)
    await model.wait_for_idle(apps=[application.name], wait_for_active=True, timeout=20 * 60)

    haproxy_ip = (await get_model_unit_addresses(machine_model, haproxy.name))[0]
    # HAProxy is fronted by TLS (self-signed-certificates relation), so plain HTTP
    # requests are redirected (302) to HTTPS. Query HTTPS directly, verifying
    # against the deployment's own self-signed CA certificate. The cert is issued
    # for EXTERNAL_HOSTNAME, not the raw IP, so HostHeaderSSLAdapter is used to
    # verify the Host header against the cert instead of the connection IP.
    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())
    response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
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
    machine_model: Model,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
    ca_cert_path: str,
):
    """
    arrange: deploy full SPOE auth stack (haproxy + haproxy-spoe-auth +
             oauth-integrator + keycloak) and jenkins with external-hostname.

    act: relate jenkins-k8s to haproxy via CMR on haproxy-route, send unauthenticated request.

    assert: HAProxy redirects to Keycloak OIDC login (302 to /realms/.../auth).
    """
    # Configure Jenkins with the SPOE-protected hostname
    await application.set_config({"external-hostname": SPOE_EXTERNAL_HOSTNAME})

    # Cross-model relation: k8s model (jenkins) -> machine model (haproxy).
    # Already established by test_haproxy_route_serves_jenkins (shared haproxy/
    # application fixtures), so only integrate if it's not there yet.
    existing_endpoints = {
        endpoint.name
        for relation in application.relations
        for endpoint in relation.endpoints
        if endpoint.application_name == application.name
    }
    if HAPROXY_ROUTE_RELATION not in existing_endpoints:
        await model.integrate(
            f"{application.name}:{HAPROXY_ROUTE_RELATION}",
            f"localhost:admin/{machine_model.name}.{HAPROXY_ROUTE_RELATION}",
        )
    await machine_model.wait_for_idle(
        apps=[haproxy_with_spoe.name], wait_for_active=True, timeout=20 * 60
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True, timeout=20 * 60)

    haproxy_ip = (await get_model_unit_addresses(machine_model, haproxy_with_spoe.name))[0]

    # HAProxy is fronted by TLS (self-signed-certificates relation); query HTTPS
    # directly, verifying against the deployment's own self-signed CA
    # certificate. The cert is issued for SPOE_EXTERNAL_HOSTNAME, not the raw
    # IP, so HostHeaderSSLAdapter is used to verify the Host header against the
    # cert instead of the connection IP. The 302 we assert on is the
    # SPOE->OIDC redirect, not a plain HTTP->HTTPS upgrade redirect.
    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())
    response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": SPOE_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,  # Don't follow redirects - we want to see the 302
        verify=ca_cert_path,
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


@pytest.mark.abort_on_fail
async def test_haproxy_spoe_server_and_unprotected_agent_route(
    ops_test: OpsTest,
    model: Model,
    application: Application,
    jenkins_client,
    haproxy_with_spoe: Application,
    jenkins_machine_agents: Application,
    machine_model: Model,
    ca_cert_path: str,
):
    """SPOE protects the server hostname while the agent hostname stays public."""
    await application.set_config(
        {
            "external-hostname": SPOE_EXTERNAL_HOSTNAME,
            "agent-external-hostname": AGENT_EXTERNAL_HOSTNAME,
        }
    )
    related_endpoints = {
        endpoint.name
        for relation in application.relations
        for endpoint in relation.endpoints
        if endpoint.application_name == application.name
    }
    if HAPROXY_ROUTE_RELATION not in related_endpoints:
        await model.integrate(
            f"{application.name}:{HAPROXY_ROUTE_RELATION}",
            f"localhost:admin/{machine_model.name}.{HAPROXY_ROUTE_RELATION}",
        )
    await machine_model.wait_for_idle(
        apps=[haproxy_with_spoe.name], wait_for_active=True, timeout=20 * 60
    )
    # The test hostnames are intentionally synthetic. Wait for the Jenkins side
    # to publish route data, then use --resolve from each agent unit so the
    # request exercises the agent network path without requiring deployment DNS.
    await model.wait_for_idle(apps=[application.name], wait_for_active=True, timeout=20 * 60)

    haproxy_ip = (await get_model_unit_addresses(machine_model, haproxy_with_spoe.name))[0]

    # The test names are synthetic. Install the test CA and map the agent name
    # on each machine unit so the real agent service can use its published URL.
    ca_certificate = base64.b64encode(Path(ca_cert_path).read_bytes()).decode()
    for unit in jenkins_machine_agents.units:
        action = await unit.run(
            command=(
                "echo "
                f"{ca_certificate}"
                " | base64 -d | sudo tee /usr/local/share/ca-certificates/jenkins-test.crt "
                ">/dev/null && sudo update-ca-certificates && "
                f"printf '%s\n' '{haproxy_ip} {AGENT_EXTERNAL_HOSTNAME}' "
                "| sudo tee -a /etc/hosts >/dev/null"
            ),
            timeout=60,
        )
        await action.wait()
        assert action.status == "completed", f"Agent setup failed on {unit.name}: {action.data}"
        assert action.results.get("return-code") == 0, (
            f"Agent setup failed on {unit.name}: {action.data}"
        )

    if "agent" not in related_endpoints:
        await model.integrate(
            f"{application.name}:agent",
            f"localhost:admin/{machine_model.name}.agent",
        )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, timeout=20 * 60
    )

    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())

    server_response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": SPOE_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
    )
    assert server_response.status_code == 302, (
        f"Expected SPOE redirect for server hostname, got "
        f"{server_response.status_code}: {server_response.text[:200]}"
    )

    agent_response = session.get(
        f"https://{haproxy_ip}/jnlpJars/agent.jar",
        headers={"Host": AGENT_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
    )
    assert agent_response.status_code == 200, (
        f"Expected unauthenticated agent JAR access, got "
        f"{agent_response.status_code}: {agent_response.text[:200]}"
    )
    assert agent_response.content

    # Verify the URL published to every machine agent is the unprotected HAProxy
    # hostname, rather than the protected server hostname or a pod IP.
    for unit in jenkins_machine_agents.units:
        action = await unit.run(
            command=(
                "curl --fail --silent --show-error --noproxy '*' --insecure "
                f"--resolve {AGENT_EXTERNAL_HOSTNAME}:443:{haproxy_ip} "
                f"https://{AGENT_EXTERNAL_HOSTNAME}/jnlpJars/agent.jar --output /dev/null"
            ),
            timeout=60,
        )
        await action.wait()
        assert action.status == "completed", (
            f"Agent JAR request failed on {unit.name}: {action.data}"
        )
        assert action.results.get("return-code") == 0, (
            f"Agent JAR request failed on {unit.name}: {action.data}"
        )

        log_action = await unit.run(
            command="sudo journalctl -u jenkins-agent -n 200 --no-pager",
            timeout=60,
        )
        await log_action.wait()
        assert log_action.status == "completed", (
            f"Failed to inspect agent logs on {unit.name}: {log_action.data}"
        )
        assert log_action.results.get("return-code") == 0, (
            f"Failed to inspect agent logs on {unit.name}: {log_action.data}"
        )
        agent_logs = str(log_action.results.get("stdout", ""))
        assert "WebSocket connection open" in agent_logs
        assert "port:50000 is not reachable" not in agent_logs

        return_code, stdout, stderr = await ops_test.juju(
            "show-unit", "-m", machine_model.name, unit.name, "--format=json"
        )
        assert return_code == 0, f"Failed to inspect {unit.name}: {stderr}"
        unit_info = json.loads(stdout)[unit.name]
        relation_info = next(
            relation for relation in unit_info["relation-info"] if relation["endpoint"] == "agent"
        )
        server_unit_data = next(iter(relation_info["related-units"].values()))["data"]
        assert server_unit_data["url"] == f"https://{AGENT_EXTERNAL_HOSTNAME}"

    assert_job_success(jenkins_client, jenkins_machine_agents.name, "machine")
