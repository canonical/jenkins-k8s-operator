# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

import asyncio
import json
import logging
import re
import secrets
import socket
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Coroutine

import jubilant
import kubernetes
import pyotp
import pytest
import pytest_asyncio
import requests
import yaml
from jinja2 import Environment, FileSystemLoader
from juju.application import Application
from juju.client._definitions import UnitStatus
from juju.model import Model
from playwright.async_api import async_playwright, expect
from playwright.async_api._generated import Browser, BrowserContext, BrowserType, Page
from playwright.async_api._generated import Playwright as AsyncPlaywright

from .helpers import wait_for

logger = logging.getLogger(__name__)

IDENTITY_PLATFORM_HOSTNAME = "idp.test"
JENKINS_HOSTNAME = "jenkins.test"


@dataclass
class _Offer:
    """The representation of a Juju offer.

    Attributes:
        url: The offer URL.
        saas: The offer SaaS name.
    """

    url: str
    saas: str


@dataclass
class _IdentityPlatformOffers:
    """The offers provided by Identity Platform charms.

    Attributes:
        oauth: The OAuth endpoint from hydra.
        send_ca_cert: The send-ca-cert endpoint for self-signed-ceritificates.
    """

    oauth: _Offer
    send_ca_cert: _Offer


@pytest.fixture(scope="module", name="identity_platform_juju")
def identity_platform_juju_fixture(request: pytest.FixtureRequest):
    """The identity platform juju model."""
    with jubilant.temp_model(keep=request.config.option.keep_models) as juju:
        yield juju


@pytest.fixture(scope="module", name="identity_platform_public_traefik")
def identity_platform_public_traefik_fixture(identity_platform_juju: jubilant.Juju):
    """The identity platform public traefik."""
    juju = identity_platform_juju

    traefik_public = "traefik-public"
    juju.deploy(
        "traefik-k8s",
        traefik_public,
        channel="latest/edge",
        revision=270, 
        config={
            "enable_experimental_forward_auth": "true",
            "external_hostname": IDENTITY_PLATFORM_HOSTNAME,
        },
        trust=True,
    )

    juju.wait(lambda status: jubilant.all_active(status, traefik_public), timeout=60 * 30)

    return traefik_public


@pytest.fixture(scope="module", name="identity_platform_offers")
def identity_platform_offers_fixture(
    identity_platform_juju: jubilant.Juju, identity_platform_public_traefik: str
):
    """Deploy, integrate identity platform charms and return offers."""
    juju = identity_platform_juju

    hydra = "hydra"
    login_ui = "identity-platform-login-ui-operator"
    kratos = "kratos"
    postgresql = "postgresql-k8s"
    ca = "self-signed-certificates"
    traefik_public = identity_platform_public_traefik

    juju.deploy(hydra, channel="latest/edge", revision=399, trust=True)
    juju.deploy(kratos, channel="latest/edge", revision=567, trust=True)
    juju.deploy(login_ui, channel="latest/edge", revision=200, trust=True)
    juju.deploy(postgresql, channel="14/stable", trust=True)
    juju.deploy(ca, channel="1/stable", revision=317, trust=True)

    juju.integrate(f"{postgresql}:database", f"{hydra}:pg-database")
    juju.integrate(f"{postgresql}:database", f"{kratos}:pg-database")
    juju.integrate(f"{traefik_public}:certificates", f"{ca}:certificates")
    juju.integrate(f"{kratos}:hydra-endpoint-info", f"{hydra}:hydra-endpoint-info")
    juju.integrate(f"{kratos}:ui-endpoint-info", f"{login_ui}:ui-endpoint-info")
    juju.integrate(f"{kratos}:kratos-info", f"{login_ui}:kratos-info")
    juju.integrate(f"{hydra}:ui-endpoint-info", f"{login_ui}:ui-endpoint-info")
    juju.integrate(f"{hydra}:hydra-endpoint-info", f"{login_ui}:hydra-endpoint-info")
    juju.integrate(f"{traefik_public}:traefik-route", f"{hydra}:public-route")
    juju.integrate(f"{traefik_public}:traefik-route", f"{kratos}:public-route")
    juju.integrate(
        f"{traefik_public}:traefik-route", f"{login_ui}:public-route"
    )

    hydra_endpoint = "oauth"
    send_ca_cert_endpoint = "send-ca-cert"
    juju.offer(f"{juju.model}.{hydra}", endpoint=hydra_endpoint, name=hydra_endpoint)
    juju.offer(f"{juju.model}.{ca}", endpoint=send_ca_cert_endpoint, name=send_ca_cert_endpoint)

    juju.wait(jubilant.all_active, timeout=60 * 30)

    return _IdentityPlatformOffers(
        oauth=_Offer(url=f"admin/{juju.model}.{hydra_endpoint}", saas=hydra_endpoint),
        send_ca_cert=_Offer(
            url=f"admin/{juju.model}.{send_ca_cert_endpoint}",
            saas=send_ca_cert_endpoint,
        ),
    )


@dataclass
class _JenkinsCharms:
    """Jenkins charms.

    Attributes:
        jenkins: Jenkins server charm.
        traefik: Jenkins public traefik charm.
        oauth2: Oauth2-proxy-k8s charm.
    """

    jenkins: str
    traefik: str
    oauth2: str


@pytest.fixture(scope="module", name="jenkins_k8s_charms")
def jenkins_k8s_charms_fixture(
    application: Application,
    identity_platform_offers: _IdentityPlatformOffers,
    # This fixture was deliberately chosen to be added as an argument here to explicitly show the
    # dependency.
    inject_dns: None,  # pylint: disable=unused-argument
):
    """The Jenkins K8s charms model."""
    juju = jubilant.Juju(model=application.model.name)

    traefik_public = "traefik-k8s"
    ca = "self-signed-certificates"
    oauth2_proxy = "oauth2-proxy-k8s"
    juju.deploy(
        traefik_public,
        channel="latest/edge",
        config={
            "enable_experimental_forward_auth": "true",
            "external_hostname": JENKINS_HOSTNAME,
        },
        trust=True,
    )
    juju.deploy(ca, channel="1/stable", trust=True)
    juju.deploy(oauth2_proxy, channel="latest/edge", trust=True)

    juju.consume(identity_platform_offers.oauth.url, alias=identity_platform_offers.oauth.saas)
    juju.consume(
        identity_platform_offers.send_ca_cert.url,
        alias=identity_platform_offers.send_ca_cert.saas,
    )

    juju.integrate(f"{traefik_public}:ingress", f"{application.name}:ingress")
    juju.integrate(f"{traefik_public}:certificates", f"{ca}:certificates")
    juju.integrate(f"{oauth2_proxy}:ingress", f"{traefik_public}:ingress")
    juju.integrate(f"{oauth2_proxy}:oauth", identity_platform_offers.oauth.saas)
    juju.integrate(f"{application.name}:auth-proxy", f"{oauth2_proxy}:auth-proxy")
    juju.integrate(f"{oauth2_proxy}:forward-auth", f"{traefik_public}:experimental-forward-auth")
    juju.integrate(f"{oauth2_proxy}:receive-ca-cert", identity_platform_offers.send_ca_cert.saas)

    juju.wait(jubilant.all_agents_idle, timeout=15 * 60, successes=5, delay=5)
    juju.wait(jubilant.all_active, timeout=15 * 60, successes=5, delay=5)

    return _JenkinsCharms(jenkins=application.name, traefik=traefik_public, oauth2=oauth2_proxy)


@pytest.fixture(scope="module", name="identity_platform_traefik_ip")
def identity_platform_traefik_ip_fixture(
    kube_core_client: kubernetes.client.CoreV1Api,
    identity_platform_public_traefik: str,
    identity_platform_juju: jubilant.Juju,
):
    """Identity platform traefik ip."""
    idp_traefik_loadbalancer_service = kube_core_client.read_namespaced_service(
        name=f"{identity_platform_public_traefik}-lb",
        namespace=identity_platform_juju.model,
    )
    return idp_traefik_loadbalancer_service.status.load_balancer.ingress[0].ip


@pytest.fixture(scope="module", name="jenkins_traefik_ip")
def jenkins_traefik_ip_fixture(
    kube_core_client: kubernetes.client.CoreV1Api,
    jenkins_k8s_charms: _JenkinsCharms,
    model: Model,
):
    """Jenkins traefik ip."""
    jenkins_traefik_loadbalancer_service = kube_core_client.read_namespaced_service(
        name=f"{jenkins_k8s_charms.traefik}-lb", namespace=model.name
    )
    return jenkins_traefik_loadbalancer_service.status.load_balancer.ingress[0].ip


@pytest.fixture(scope="module", name="patch_dns_resolver")
def patch_dns_resolver_fixture(identity_platform_traefik_ip: str, jenkins_traefik_ip: str):
    """Patch DNS resolution."""
    dns_cache = {
        IDENTITY_PLATFORM_HOSTNAME: identity_platform_traefik_ip,
        JENKINS_HOSTNAME: jenkins_traefik_ip,
    }
    original_getaddrinfo = socket.getaddrinfo

    def new_getaddrinfo(*args):
        """Patches getaddrinfo with custom DNS mapping.

        Args:
            args: The getaddrinfo arguments.

        Returns:
            The patched getaddrinfo function.
        """
        if args[0] in dns_cache:
            logger.info("Forcing FQDN: %s to IP: %s", args[0], dns_cache[args[0]])
            return original_getaddrinfo(dns_cache[args[0]], *args[1:])
        return original_getaddrinfo(*args)

    socket.getaddrinfo = new_getaddrinfo

    yield

    socket.getaddrinfo = original_getaddrinfo


@pytest.fixture(scope="module", name="inject_dns")
def inject_dns_fixture(
    kube_core_client: kubernetes.client.CoreV1Api,
    identity_platform_traefik_ip: str,
):
    """Inject IDP hostname to CoreDNS."""
    logger.info("Patching CoreDNS configmap, idp public IP: %s", identity_platform_traefik_ip)
    environment = Environment(loader=FileSystemLoader("tests/integration/files/"), autoescape=True)
    template = environment.get_template("coredns.yaml.j2")
    coredns_yaml = template.render(
        hostname=IDENTITY_PLATFORM_HOSTNAME, ip=identity_platform_traefik_ip
    )
    coredns_configmap_manifest = yaml.safe_load(coredns_yaml)

    original_manifest = kube_core_client.read_namespaced_config_map(
        name="coredns", namespace="kube-system"
    )
    kube_core_client.replace_namespaced_config_map(
        name="coredns", namespace="kube-system", body=coredns_configmap_manifest
    )

    pods = kube_core_client.list_namespaced_pod(
        namespace="kube-system", label_selector="k8s-app=kube-dns"
    )
    for pod in pods.items:
        logger.info("Deleting pod for DNS restart: %s", pod.metadata.name)
        kube_core_client.delete_namespaced_pod(name=pod.metadata.name, namespace="kube-system")

    yield

    coredns_configmap_manifest["data"]["Corefile"] = original_manifest.data.get("Corefile", "")
    kube_core_client.replace_namespaced_config_map(
        name="coredns", namespace="kube-system", body=coredns_configmap_manifest
    )
    pods = kube_core_client.list_namespaced_pod(
        namespace="kube-system", label_selector="k8s-app=kube-dns"
    )
    for pod in pods.items:
        logger.info("Deleting pod for DNS restart: %s", pod.metadata.name)
        kube_core_client.delete_namespaced_pod(name=pod.metadata.name, namespace="kube-system")


# The playwright fixtures are taken from:
# https://github.com/microsoft/playwright-python/blob/main/tests/async/conftest.py
@pytest_asyncio.fixture(scope="module", name="playwright")
async def playwright_fixture() -> AsyncGenerator[AsyncPlaywright, None]:
    """Playwright object."""
    async with async_playwright() as playwright_object:
        yield playwright_object


@pytest_asyncio.fixture(scope="module", name="browser_type")
async def browser_type_fixture(
    playwright: AsyncPlaywright,
) -> AsyncGenerator[BrowserType, None]:
    """Browser type for playwright."""
    yield playwright.chromium


@pytest_asyncio.fixture(scope="module", name="browser_factory")
async def browser_factory_fixture(
    browser_type: BrowserType,
) -> AsyncGenerator[Callable[..., Coroutine[Any, Any, Browser]], None]:
    """Browser factory."""
    browsers = []

    async def launch(**kwargs: Any) -> Browser:
        """Launch browser.

        Args:
            kwargs: kwargs.

        Returns:
            a browser instance.
        """
        browser = await browser_type.launch(**kwargs)
        browsers.append(browser)
        return browser

    yield launch
    for browser in browsers:
        await browser.close()


@pytest_asyncio.fixture(scope="module", name="browser")
async def browser_fixture(
    browser_factory: Callable[..., Coroutine[Any, Any, Browser]],
    identity_platform_traefik_ip: str,
    jenkins_traefik_ip: str,
) -> AsyncGenerator[Browser, None]:
    """Browser."""
    browser = await browser_factory(
        # DO NOT modify /etc/hosts file to map the custom hosts for testing, since it will
        # interfere with the following browser host resolver settings.
        args=[
            f"--host-resolver-rules=MAP "
            f"{IDENTITY_PLATFORM_HOSTNAME} {identity_platform_traefik_ip},"
            f"MAP {JENKINS_HOSTNAME} {jenkins_traefik_ip}"
        ]
    )
    yield browser
    await browser.close()


@pytest_asyncio.fixture(scope="module", name="context_factory")
async def context_factory_fixture(
    browser: Browser,
) -> AsyncGenerator[Callable[..., Coroutine[Any, Any, BrowserContext]], None]:
    """Playwright context factory."""
    contexts = []

    async def launch(**kwargs: Any) -> BrowserContext:
        """Launch browser.

        Args:
            kwargs: kwargs.

        Returns:
            the browser context.
        """
        context = await browser.new_context(**kwargs)
        contexts.append(context)
        return context

    yield launch
    for context in contexts:
        await context.close()


@pytest_asyncio.fixture(scope="module", name="context")
async def context_fixture(
    context_factory: Callable[..., Coroutine[Any, Any, BrowserContext]],
) -> AsyncGenerator[BrowserContext, None]:
    """Playwright context."""
    context = await context_factory(
        ignore_https_errors=True,
        record_video_dir="videos/",
        record_video_size={"width": 1280, "height": 720},
    )
    yield context
    await context.close()


@pytest_asyncio.fixture(scope="function", name="page")
async def page_fixture(context: BrowserContext) -> AsyncGenerator[Page, None]:
    """Playwright page."""
    new_page = await context.new_page()
    yield new_page
    await new_page.close()


async def get_application_unit_status(model: Model, application: str) -> UnitStatus:
    """Get the application unit status object.

    Args:
        model: The Juju model connection object.
        application: The application unit to get the unit status.

    Returns:
        The application first unit's status.
    """
    status = await model.get_status()
    unit_status: UnitStatus = status["applications"][application]["units"][f"{application}/0"]
    return unit_status


def _get_traefik_proxied_endpoints(juju: jubilant.Juju, traefik_app_name: str) -> dict:
    """Get traefik's proxied endpoints via running show-proxied-endpoints action.

    Args:
        juju: The Juju model connected Jubilant Juju instance to search traefik application for.
        traefik_app_name: Deployed traefik application name.

    Returns:
        Mapping of proxied endpoints in the format of {<app-name>: {url: <url>}}
    """
    units = juju.status().get_units(traefik_app_name)
    traefik_unit = units.get(f"{traefik_app_name}/0", None)
    assert traefik_unit, f"Required {traefik_app_name} unit not found"
    # Example output of show-proxied-endpoints action:
    # proxied-endpoints: '{"traefik-public": {"url": "https://10.15.119.4"}, "jenkins-k8s":
    #   {"url": "https://10.15.119.4/testing-jenkins-k8s"}, "hydra": {"url":
    #    "https://10.15.119.4/testing-hydra"}, "kratos": {"url":
    #    "https://10.15.119.4/testing-kratos"}, "identity-platform-login-ui-operator":
    #    {"url": "https://10.15.119.4/testing-identity-platform-login-ui-operator"}}'
    action = juju.run(f"{traefik_app_name}/0", "show-proxied-endpoints")
    endpoints_json: str = str(action.results.get("proxied-endpoints"))
    endpoints: dict = json.loads(endpoints_json)
    return endpoints


@pytest.fixture(scope="module", name="jenkins_endpoint")
def jenkins_endpoint_fixture(model: Model, jenkins_k8s_charms: _JenkinsCharms):
    """The Jenkins endpoint URL from public traefik."""
    juju = jubilant.Juju(model=model.name)

    endpoints = _get_traefik_proxied_endpoints(
        juju=juju, traefik_app_name=jenkins_k8s_charms.traefik
    )
    jenkins_endpoint = endpoints.get("jenkins-k8s", {}).get("url")
    assert jenkins_endpoint, "Jenkins endpoint not found in proxied endpoints"

    return jenkins_endpoint


@pytest.mark.abort_on_fail
@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_dns_resolver")
async def test_auth_proxy_integration_returns_not_authorized(
    jenkins_endpoint: str,
) -> None:
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request Jenkins.
    assert: a 401 is returned.
    """

    def is_auth_ui():
        """Get the application request via ingress.

        Returns:
            Whether request is redirected to UI page.
        """
        response = requests.get(  # nosec
            jenkins_endpoint,
            # The certificate is self signed, so verification is disabled.
            verify=False,
            timeout=5,
        )
        logger.info("Auth UI test response header: %s, url: %s", response.headers, response.url)
        return (
            response.status_code == 200
            and IDENTITY_PLATFORM_HOSTNAME in response.url
            and "identity-platform-login-ui-operator" in response.url
        )

    await wait_for(
        is_auth_ui,
        timeout=60 * 3,
    )


@dataclass
class _TestCredentials:
    """Testing credentials.

    Attributes:
        username: Testing username.
        email: Testing email.
        password: Testing password.
    """

    username: str
    email: str
    password: str


@pytest.fixture(scope="module", name="test_credentials")
def test_credentials_fixture() -> _TestCredentials:
    """Testing credentials fixture.

    Password must contain uppercase, lowercase, number and should be greater than 8 chars.
    """
    return _TestCredentials(
        username="testinguser",
        email="testingemail@test.com",
        password=secrets.token_urlsafe(32),
    )


@pytest_asyncio.fixture(scope="function", name="totp")
async def totp_fixture(
    identity_platform_juju: jubilant.Juju,
    page: Page,
    test_credentials: _TestCredentials,
) -> pyotp.TOTP:
    """User OTP fixture."""
    juju = identity_platform_juju

    await asyncio.sleep(5)

    # output looks something like:
    # expires-at: "2025-09-18T17:44:47.541400692Z"
    # identity-id: 165d553f-61f4-40da-97cb-24ac3179b6a7
    # password-reset-code: "042474"
    # password-reset-link: https://idp.test/.../ui/reset_email?flow=...
    logger.info(
        "Creating admin account: %s %s",
        test_credentials.username,
        test_credentials.email,
    )
    result = juju.run(
        "kratos/0",
        "create-admin-account",
        params={"username": test_credentials.username, "email": test_credentials.email},
    )
    reset_page_url: str | None = result.results.get("password-reset-link")
    assert reset_page_url, f"Reset page link not found in results {result.results}"
    reset_code: str | None = result.results.get("password-reset-code")
    assert reset_code is not None, f"Reset code not found in results {result.results}"
    logger.info("Created admin account, reset link: %s, code: %s", reset_page_url, reset_code)

    # sleep for 5 seconds to prevent weird behavior with reset link giving 500 errors.
    await asyncio.sleep(5)

    logger.info("Navigating to reset link: %s", reset_page_url)
    await page.goto(url=reset_page_url, timeout=1000 * 60)

    async with page.expect_navigation(timeout=1000 * 60):
        logger.info("Page content:%s", await page.content())
        await page.get_by_label("Recovery code", exact=True).fill(reset_code)
        await page.get_by_role("button", name="Submit").click()

    async with page.expect_navigation(timeout=1000 * 60):
        logger.info("Changing password: %s", test_credentials.password)
        await page.get_by_label("New password", exact=True).fill(test_credentials.password)
        await page.get_by_label("Confirm New password", exact=True).fill(test_credentials.password)
        await page.get_by_role("button", name="Reset password").click()

    async with page.expect_navigation(timeout=1000 * 60):
        logger.info("Getting OTP Code")
        code = await page.get_by_role("code").text_content()
        assert code, "Code content not found"
        logger.info("Got OTP Code: %s", code)
        totp = pyotp.TOTP(code)
        await page.get_by_label("Verify code", exact=True).fill(totp.now())
        await page.get_by_role("button", name="Save").click()

    return totp


@pytest.mark.abort_on_fail
@pytest.mark.asyncio
@pytest.mark.usefixtures("inject_dns")
async def test_auth_proxy_integration_authorized(
    jenkins_endpoint: str,
    page: Page,
    totp: pyotp.TOTP,
    test_credentials: _TestCredentials,
) -> None:
    """
    arrange: Deploy jenkins, the authentication bundle.
    act: log in via IDP UI
    assert: the browser is redirected to the Jenkins URL with response code 200
    """
    logger.info("Navigating to Jenkins public endpoint: %s", jenkins_endpoint)
    await page.goto(url=jenkins_endpoint, timeout=1000 * 60 * 10)

    async with page.expect_navigation(timeout=1000 * 60):
        logger.info(
            "Filling in login-ui credentials: %s, %s",
            test_credentials.email,
            test_credentials.password,
        )
        await page.get_by_label("Email").fill(test_credentials.email)
        await page.get_by_label("Password").fill(test_credentials.password)
        await page.get_by_role("button", name="Sign in").click()
        logger.info("Signing in...")

    async with page.expect_navigation(timeout=1000 * 60):
        logger.info("Authenticating with TOTP")
        await page.get_by_label("Authentication code").fill(totp.now())
        await page.get_by_role("button", name="Sign in").click()
        logger.info("Signing in...")

    await expect(page).to_have_url(re.compile(r"https://jenkins.test/*"))
