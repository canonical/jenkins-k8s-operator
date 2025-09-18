# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

import json
import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Coroutine, Match

import jubilant
import pytest
import pytest_asyncio
import requests
from juju.action import Action
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
        certificates: The Certificates endpoint fro self-signed-ceritificates.
        send_ca_cert: The send-ca-cert endpoint fro self-signed-ceritificates.
    """

    oauth: _Offer
    certificates: _Offer
    send_ca_cert: _Offer


@pytest.fixture(scope="module", name="identity_platform_offers")
def identity_platform_offers_fixture():
    """Deploy, integrate identity platform charms and return offers."""
    with jubilant.temp_model() as juju:
        hydra = "hydra"
        login_ui = "identity-platform-login-ui-operator"
        kratos = "kratos"
        postgresql = "postgresql-k8s"
        ca = "self-signed-certificates"
        traefik_admin = "traefik-admin"
        traefik_public = "traefik-public"

        juju.deploy(hydra, channel="latest/edge")
        juju.deploy(login_ui, channel="latest/edge")
        juju.deploy(kratos, channel="latest/edge")
        juju.deploy(postgresql, channel="14/stable")
        juju.deploy(ca, channel="1/stable")
        juju.deploy(traefik_admin, channel="latest/edge")
        juju.deploy(
            traefik_public,
            channel="latest/edge",
            config={
                "enable_experimental_forward_auth": "true",
                "external_hostname": IDENTITY_PLATFORM_HOSTNAME,
            },
        )

        juju.integrate(f"{postgresql}:database", f"{hydra}:pg-database")
        juju.integrate(f"{postgresql}:database", f"{kratos}:pg-database")
        juju.integrate(f"{hydra}:public-ingress", f"{traefik_public}:ingress")
        juju.integrate(f"{hydra}:internal-ingress", f"{traefik_admin}:traefik-route")
        juju.integrate(f"{traefik_public}:certificates", f"{ca}:certificates")
        juju.integrate(f"{kratos}:hydra-endpoint-info", f"{hydra}:hydra-endpoint-info")
        juju.integrate(f"{kratos}:ui-endpoint-info", f"{login_ui}:ui-endpoint-info")
        juju.integrate(f"{kratos}:kratos-info", f"{login_ui}:kratos-info")
        juju.integrate(f"{kratos}:public-ingress", f"{traefik_public}:ingress")
        juju.integrate(f"{kratos}:internal-ingress", f"{traefik_admin}:traefik-route")
        juju.integrate(f"{hydra}:ui-endpoint-info", f"{login_ui}:ui-endpoint-info")
        juju.integrate(f"{hydra}:hydra-endpoint-info", f"{login_ui}:hydra-endpoint-info")
        juju.integrate(f"{hydra}:admin-ingress", f"{traefik_admin}:ingress")
        juju.integrate(f"{kratos}:admin-ingress", f"{traefik_admin}:ingress")
        juju.integrate(f"{login_ui}:ingress", f"{traefik_public}:ingress")

        hydra_endpoint = "oauth"
        certificates_endpoint = "oauth"
        send_ca_cert_endpoint = "send-ca-cert"
        juju.offer(f"{juju.model}.{hydra}", endpoint=hydra_endpoint, name=hydra_endpoint)
        juju.offer(
            f"{juju.model}.{ca}", endpoint=certificates_endpoint, name=certificates_endpoint
        )
        juju.offer(
            f"{juju.model}.{ca}", endpoint=send_ca_cert_endpoint, name=send_ca_cert_endpoint
        )

        juju.wait(lambda ready: jubilant.all_active(ready), timeout=60 * 15)

        return _IdentityPlatformOffers(
            oauth=_Offer(url=f"admin/{juju.model}.{hydra_endpoint}", saas=hydra_endpoint),
            certificates=_Offer(
                url=f"admin/{juju.model}.{certificates_endpoint}", saas=certificates_endpoint
            ),
            send_ca_cert=_Offer(
                url=f"admin/{juju.model}.{send_ca_cert_endpoint}", saas=send_ca_cert_endpoint
            ),
        )


@pytest.fixture(scope="module", name="jenkins_k8s_charms")
def jenkins_k8s_charms_fixture(
    application: Application, identity_platform_offers: _IdentityPlatformOffers
):
    """The Jenkins K8s charms model."""
    juju = jubilant.Juju(model=application.model.name)

    traefik_public = "traefik-k8s"
    oauth2_proxy = "oauth2-k8s-proxy"
    juju.deploy(
        traefik_public,
        channel="latest/edge",
        config={
            "enable_experimental_forward_auth": "true",
            "external_hostname": JENKINS_HOSTNAME,
        },
    )
    juju.deploy(oauth2_proxy, channel="latest/edge")

    juju.consume(
        identity_platform_offers.certificates.url, alias=identity_platform_offers.certificates.saas
    )
    juju.consume(identity_platform_offers.oauth.url, alias=identity_platform_offers.oauth.saas)
    juju.consume(
        identity_platform_offers.send_ca_cert.url, alias=identity_platform_offers.send_ca_cert.saas
    )

    juju.integrate(f"{traefik_public}:ingress", f"{application.name}:ingress")
    juju.integrate(f"{traefik_public}:certificates", identity_platform_offers.certificates.saas)
    juju.integrate(f"{oauth2_proxy}:ingress", f"{traefik_public}:ingress")
    juju.integrate(f"{oauth2_proxy}:oauth", identity_platform_offers.oauth.saas)
    juju.integrate(f"{application.name}:auth-proxy", f"{oauth2_proxy}:auth-proxy")
    juju.integrate(f"{oauth2_proxy}:forward-auth", f"{traefik_public}:experimental-forward-auth")
    juju.integrate(f"{oauth2_proxy}:receive-ca-cert", identity_platform_offers.send_ca_cert.saas)

    juju.wait(lambda status: jubilant.all_active(status), timeout=15 * 60)


# The playwright fixtures are taken from:
# https://github.com/microsoft/playwright-python/blob/main/tests/async/conftest.py
@pytest_asyncio.fixture(scope="module", name="playwright")
async def playwright_fixture() -> AsyncGenerator[AsyncPlaywright, None]:
    """Playwright object."""
    async with async_playwright() as playwright_object:
        yield playwright_object


@pytest_asyncio.fixture(scope="module", name="browser_type")
async def browser_type_fixture(playwright: AsyncPlaywright) -> AsyncGenerator[BrowserType, None]:
    """Browser type for playwright."""
    yield playwright.firefox


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
) -> AsyncGenerator[Browser, None]:
    """Browser."""
    browser = await browser_factory()
    yield browser
    await browser.close()


@pytest_asyncio.fixture(name="context_factory")
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


@pytest_asyncio.fixture(name="context")
async def context_fixture(
    context_factory: Callable[..., Coroutine[Any, Any, BrowserContext]],
) -> AsyncGenerator[BrowserContext, None]:
    """Playwright context."""
    context = await context_factory(ignore_https_errors=True)
    yield context
    await context.close()


@pytest_asyncio.fixture(name="page")
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


async def _get_traefik_proxied_endpoints(model: Model, traefik_app_name: str) -> dict:
    """Get traefik's proxied endpoints via running show-proxied-endpoints action.

    Args:
        model: The Juju model to search traefik application for.
        traefik_app_name: Deployed traefik application name.

    Returns:
        Mapping of proxied endpoints in the format of {<app-name>: {url: <url>}}
    """
    traefik_unit = model.units.get(f"{traefik_app_name}/0", None)
    assert traefik_unit, f"Required {traefik_app_name} unit not found"
    # Example output of show-proxied-endpoints action:
    # proxied-endpoints: '{"traefik-public": {"url": "https://10.15.119.4"}, "jenkins-k8s":
    #   {"url": "https://10.15.119.4/testing-jenkins-k8s"}, "hydra": {"url":
    #    "https://10.15.119.4/testing-hydra"}, "kratos": {"url":
    #    "https://10.15.119.4/testing-kratos"}, "identity-platform-login-ui-operator":
    #    {"url": "https://10.15.119.4/testing-identity-platform-login-ui-operator"}}'
    action: Action = await traefik_unit.run_action("show-proxied-endpoints")
    await action.wait()
    endpoints_json: str = str(action.results.get("proxied-endpoints"))
    endpoints: dict = json.loads(endpoints_json)
    return endpoints


@pytest.mark.abort_on_fail
@pytest.mark.asyncio
@pytest.mark.usefixtures("oauth2_proxy_related")
async def test_auth_proxy_integration_returns_not_authorized(model: Model) -> None:
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request Jenkins.
    assert: a 401 is returned.
    """
    endpoints = await _get_traefik_proxied_endpoints(
        model=model, traefik_app_name="traefik-public"
    )
    jenkins_endpoint = endpoints.get("jenkins-k8s", {}).get("url")
    assert jenkins_endpoint, "Jenkins endpoint not found in proxied endpoints"

    def is_auth_401():
        """Get the status code of application request via ingress.

        Returns:
            Whether the status code of the request is 401.
        """
        response = requests.get(  # nosec
            jenkins_endpoint,
            # The certificate is self signed, so verification is disabled.
            verify=False,
            timeout=5,
        )
        return response.status_code == 401

    await wait_for(
        is_auth_401,
        timeout=60 * 10,
    )


@pytest.mark.abort_on_fail
@pytest.mark.asyncio
@pytest.mark.usefixtures("oauth2_proxy_related")
async def test_auth_proxy_integration_authorized(
    ext_idp_service: str,
    external_user_email: str,
    external_user_password: str,
    page: Page,
    application: Application,
) -> None:
    """
    arrange: Deploy jenkins, the authentication bundle and DEX.
    act: log in via DEX
    assert: the browser is redirected to the Jenkins URL with response code 200
    """
    endpoints = await _get_traefik_proxied_endpoints(
        model=application.model, traefik_app_name="traefik-public"
    )
    jenkins_endpoint = endpoints.get("jenkins-k8s", {}).get("url")
    assert jenkins_endpoint, "Jenkins endpoint not found in proxied endpoints"
    jenkins_url = urllib.parse.urlparse(jenkins_endpoint)
    public_hostname = jenkins_url.hostname
    expected_url = (
        f"https://{public_hostname}/{application.model.name}"
        "-identity-platform-login-ui-operator/ui/login"
    )
    expected_url_regex = re.compile(rf"{expected_url}*")

    async def is_redirected_to_dex() -> Match[str] | None:
        """Wait until dex properly redirects to correct URL.

        Returns:
            A match if found, None otherwise.
        """
        await page.goto(jenkins_endpoint)
        logger.info("Page URL: %s", page.url)
        return expected_url_regex.match(page.url)

    # Dex might take a bit to be ready
    await wait_for(is_redirected_to_dex)
    await expect(page).to_have_url(expected_url_regex)

    # Choose provider
    async with page.expect_navigation():
        # Increase timeout to wait for dex to be ready
        await page.get_by_role("button", name="Dex").click()

    await expect(page).to_have_url(re.compile(rf"{ext_idp_service}*"))

    # Login
    await page.get_by_placeholder("email address").click()
    await page.get_by_placeholder("email address").fill(external_user_email)
    await page.get_by_placeholder("password").click()
    await page.get_by_placeholder("password").fill(external_user_password)
    await page.get_by_role("button", name="Login").click()

    await expect(page).to_have_url(re.compile(rf"{jenkins_endpoint}*"))
