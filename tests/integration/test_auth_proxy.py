# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

import logging
import re
from typing import Any, AsyncGenerator, Callable, Coroutine, Match, cast

import pytest
import pytest_asyncio
import requests
from juju.application import Application
from juju.client._definitions import DetailedStatus, UnitStatus
from juju.model import Model
from playwright.async_api import async_playwright, expect
from playwright.async_api._generated import Browser, BrowserContext, BrowserType, Page
from playwright.async_api._generated import Playwright as AsyncPlaywright

from .helpers import wait_for

logger = logging.getLogger(__name__)


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


@pytest.mark.abort_on_fail
@pytest.mark.asyncio
@pytest.mark.usefixtures("oathkeeper_related")
async def test_auth_proxy_integration_returns_not_authorized(
    model: Model,
    application: Application,
) -> None:
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request Jenkins.
    assert: a 401 is returned.
    """
    unit_status = await get_application_unit_status(model=model, application="traefik-public")
    workload_message = str(cast(DetailedStatus, unit_status.workload_status).info)
    # The message is: Serving at <external loadbalancer IP>
    address = workload_message.removeprefix("Serving at ")

    def is_auth_401():
        """Get the status code of application request via ingress.

        Returns:
            Whether the status code of the request is 401.
        """
        response = requests.get(  # nosec
            f"https://{address}/{application.model.name}-{application.name}/",
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
@pytest.mark.usefixtures("oathkeeper_related")
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
    unit_status = await get_application_unit_status(
        model=application.model, application="traefik-public"
    )
    workload_message = str(cast(DetailedStatus, unit_status.workload_status).info)
    # The message is: Serving at <external loadbalancer IP>
    address = workload_message.removeprefix("Serving at ")
    jenkins_url = f"https://{address}/{application.model.name}-{application.name}/"
    expected_url = (
        f"https://{address}/{application.model.name}"
        "-identity-platform-login-ui-operator/ui/login"
    )
    expected_url_regex = re.compile(rf"{expected_url}*")

    async def is_redirected_to_dex() -> Match[str] | None:
        """Wait until dex properly redirects to correct URL.

        Returns:
            A match if found, None otherwise.
        """
        await page.goto(jenkins_url)
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

    await expect(page).to_have_url(re.compile(rf"{jenkins_url}*"))
