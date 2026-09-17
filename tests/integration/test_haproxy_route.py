# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the jenkins-k8s haproxy-route relation."""

import asyncio
import re

import jenkinsapi.jenkins
import pytest
import pytest_asyncio
import requests
import tenacity
from juju.application import Application
from juju.model import Model
from juju.unit import Unit
from pytest_operator.plugin import OpsTest
from requests_toolbelt.adapters.host_header_ssl import HostHeaderSSLAdapter

from .constants import MACHINE_CONTROLLER_NAME
from .helpers import assert_job_success, get_model_unit_addresses
from .types_ import KeycloakOIDCMetadata

EXTERNAL_HOSTNAME = "jenkins.internal"
SPOE_EXTERNAL_HOSTNAME = "jenkins-spoe.internal"
AGENT_EXTERNAL_HOSTNAME = "jenkins-agent.internal"
GATEWAY_CLASS = "ck-gateway"
GATEWAY_APPLICATION_NAME = "jenkins-gateway-api"
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


@pytest_asyncio.fixture(scope="module", name="gateway_agent_ingress")
async def gateway_agent_ingress_fixture(model: Model, application: Application) -> Application:
    """Deploy Gateway API and ingress-configurator for agent discovery."""
    gateway = await model.deploy(
        "gateway-api-integrator",
        channel="1/stable",
        trust=True,
        application_name=GATEWAY_APPLICATION_NAME,
    )
    await gateway.set_config({"gateway-class": GATEWAY_CLASS})
    certificates = await model.deploy(
        "self-signed-certificates",
        channel="1/stable",
        trust=True,
        application_name="jenkins-gateway-certificates",
    )
    await model.integrate(f"{gateway.name}:certificates", f"{certificates.name}:certificates")
    await model.wait_for_idle(
        apps=[gateway.name, certificates.name], status="active", timeout=20 * 60
    )

    ingress_configurator = await model.deploy(
        "ingress-configurator",
        channel="latest/stable",
        trust=True,
        application_name="jenkins-agent-ingress-configurator",
        config={"hostname": AGENT_EXTERNAL_HOSTNAME, "paths": "/"},
    )
    await model.integrate(
        f"{gateway.name}:gateway-route",
        f"{ingress_configurator.name}:gateway-route",
    )
    await model.integrate(
        f"{application.name}:agent-discovery-ingress",
        f"{ingress_configurator.name}:ingress",
    )
    await model.wait_for_idle(
        apps=[gateway.name, ingress_configurator.name, application.name],
        wait_for_active=True,
        timeout=20 * 60,
    )
    return ingress_configurator


async def _get_machine_model_gateway(
    ops_test: OpsTest, machine_model: Model, unit: Unit
) -> str:
    """Get the LXD bridge gateway used by a machine-model unit."""
    machine_model_name = machine_model.name.rsplit("/", 1)[-1]
    return_code, stdout, stderr = await ops_test.run(
        "env", "-u", "JUJU_MODEL", "juju", "ssh", "--model",
        f"{MACHINE_CONTROLLER_NAME}:{machine_model_name}", "--proxy", unit.name,
        "ip", "-4", "route", "show", "default",
    )
    assert return_code == 0, f"Failed to inspect {unit.name} route: {stderr}"
    match = re.search(r"^default via (?P<gateway>\S+)", stdout, re.MULTILINE)
    assert match, f"No default gateway found for {unit.name}: {stdout}"
    return match.group("gateway")


@tenacity.retry(
    retry=tenacity.retry_if_exception_type(OSError),
    wait=tenacity.wait_fixed(1),
    stop=tenacity.stop_after_delay(30),
    reraise=True,
)
async def _wait_for_gateway_forward(process: asyncio.subprocess.Process, address: str) -> None:
    """Wait until the local Gateway HTTPS forward accepts connections."""
    if process.returncode is not None:
        assert process.stderr is not None
        stderr = (await process.stderr.read()).decode(errors="replace")
        raise RuntimeError(f"Gateway port-forward exited early: {stderr}")
    _, writer = await asyncio.open_connection(address, 443)
    writer.close()
    await writer.wait_closed()


@pytest_asyncio.fixture(scope="function", name="gateway_agent_network")
async def gateway_agent_network_fixture(
    gateway_agent_ingress: Application,
    jenkins_machine_agents: Application,
    machine_model: Model,
    model: Model,
    kube_config: str,
    ops_test: OpsTest,
):
    """Bridge the CK8s Gateway HTTPS endpoint into the LXD agent network."""
    del gateway_agent_ingress  # dependency: Gateway service must be ready first
    machine_model_name = machine_model.name.rsplit("/", 1)[-1]
    # The integration backend places all LXD units on this runner. Fail rather
    # than silently misrouting if that topology changes.
    gateways = {
        await _get_machine_model_gateway(ops_test, machine_model, unit)
        for unit in jenkins_machine_agents.units
    }
    assert len(gateways) == 1, f"Machine agents use different gateways: {sorted(gateways)}"
    bridge_address = next(iter(gateways))
    host_line = f"{bridge_address} {AGENT_EXTERNAL_HOSTNAME}"
    port_forward = await asyncio.create_subprocess_exec(
        "sudo", "kubectl", "--kubeconfig", kube_config, "-n", model.name,
        "port-forward", "--address", bridge_address,
        f"svc/cilium-gateway-{GATEWAY_APPLICATION_NAME}", "443:443",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        await _wait_for_gateway_forward(port_forward, bridge_address)
        for unit in jenkins_machine_agents.units:
            return_code, _, stderr = await ops_test.run(
                "env", "-u", "JUJU_MODEL", "juju", "ssh", "--model",
                f"{MACHINE_CONTROLLER_NAME}:{machine_model_name}", "--proxy", unit.name,
                "sudo", "sh", "-c",
                f"grep -qF '{host_line}' /etc/hosts || echo '{host_line}' >> /etc/hosts",
            )
            assert return_code == 0, f"Failed to configure {unit.name}: {stderr}"
        yield
    finally:
        port_forward.terminate()
        try:
            await asyncio.wait_for(port_forward.wait(), timeout=5)
        except asyncio.TimeoutError:
            port_forward.kill()
            await port_forward.wait()
        for unit in jenkins_machine_agents.units:
            await ops_test.run(
                "env", "-u", "JUJU_MODEL", "juju", "ssh", "--model",
                f"{MACHINE_CONTROLLER_NAME}:{machine_model_name}", "--proxy", unit.name,
                "sudo", "sed", "-i",
                rf"\|{AGENT_EXTERNAL_HOSTNAME}|d", "/etc/hosts",
            )


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
        f"{MACHINE_CONTROLLER_NAME}:admin/{machine_model.name}.{HAPROXY_ROUTE_RELATION}",
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
            f"{MACHINE_CONTROLLER_NAME}:admin/{machine_model.name}.{HAPROXY_ROUTE_RELATION}",
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
async def test_haproxy_server_and_gateway_agent_discovery(
    model: Model,
    application: Application,
    haproxy_with_spoe: Application,
    gateway_agent_network: None,
    jenkins_machine_agents: Application,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
    machine_model: Model,
    ca_cert_path: str,
):
    """
    arrange: given HAProxy/SPOE for users and Gateway API ingress for agents.
    act: route Jenkins through HAProxy and execute a job on the related machine agent.
    assert: browser traffic reaches SPOE and the agent executes the Jenkins job through Gateway API.
    """
    await application.set_config({"external-hostname": SPOE_EXTERNAL_HOSTNAME})

    related_endpoints = {
        endpoint.name
        for relation in application.relations
        for endpoint in relation.endpoints
        if endpoint.application_name == application.name
    }
    if HAPROXY_ROUTE_RELATION not in related_endpoints:
        await model.integrate(
            f"{application.name}:{HAPROXY_ROUTE_RELATION}",
            f"{MACHINE_CONTROLLER_NAME}:admin/{machine_model.name}.{HAPROXY_ROUTE_RELATION}",
        )
    if "agent" not in related_endpoints:
        await model.integrate(
            f"{application.name}:agent",
            f"{MACHINE_CONTROLLER_NAME}:admin/{machine_model.name}.agent",
        )

    await model.wait_for_idle(apps=[application.name], wait_for_active=True, timeout=20 * 60)
    await machine_model.wait_for_idle(
        apps=[haproxy_with_spoe.name], wait_for_active=True, timeout=20 * 60
    )

    haproxy_ip = (await get_model_unit_addresses(machine_model, haproxy_with_spoe.name))[0]
    session = requests.Session()
    session.mount("https://", HostHeaderSSLAdapter())
    server_response = session.get(
        f"https://{haproxy_ip}",
        headers={"Host": SPOE_EXTERNAL_HOSTNAME},
        timeout=30,
        allow_redirects=False,
        verify=ca_cert_path,
    )
    assert server_response.status_code == 302

    assert_job_success(jenkins_client, jenkins_machine_agents.name, "machine")
