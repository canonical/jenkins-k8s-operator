# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with auth_proxy."""

# pylint: disable=unused-argument

import re
import time

import pytest
import requests
from juju.application import Application
from juju.model import Model
from playwright.async_api import expect
from playwright.async_api._generated import Page


@pytest.mark.abort_on_fail
@pytest.mark.asyncio
async def test_auth_proxy_integration_returns_not_authorized(
    model: Model,
    application: Application,
    oathkeeper_related: Application,
) -> None:
    """
    arrange: deploy the Jenkins charm and establish auth_proxy relations.
    act: send a request Jenkins.
    assert: a 401 is returned.
    """
    status = await model.get_status()
    address = status["applications"]["traefik-public"]["public-address"]
    # The certificate is self signed, so verification is disabled.
    response = requests.get(  # nosec
        f"https://{address}/{application.model.name}-{application.name}/",
        verify=False,
        timeout=5,
    )

    assert response.status_code == 401


# pylint: disable=too-many-arguments
@pytest.mark.abort_on_fail
@pytest.mark.asyncio
async def test_auth_proxy_integration_authorized(
    ext_idp_service: str,
    external_user_email: str,
    external_user_password: str,
    page: Page,
    application: Application,
    oathkeeper_related: Application,
) -> None:
    """
    arrange: Deploy jenkins, the authentication bundle and DEX.
    act: log into via DEX
    assert: the browser is redirected to the Jenkins URL with response code 200
    """
    status = await application.model.get_status()
    address = status["applications"]["traefik-public"]["public-address"]
    jenkins_url = f"https://{address}/{application.model.name}-{application.name}/"

    await page.goto(jenkins_url)

    expected_url = (
        f"https://{address}/{application.model.name}"
        f"-identity-platform-login-ui-operator/ui/login"
    )
    # Dex might take a bit to be ready
    time.sleep(5)
    await expect(page).to_have_url(re.compile(rf"{expected_url}*"))

    # Choose provider
    async with page.expect_navigation():
        await page.get_by_role("button", name="Dex").click()

    await expect(page).to_have_url(re.compile(rf"{ext_idp_service}*"))

    # Login
    await page.get_by_placeholder("email address").click()
    await page.get_by_placeholder("email address").fill(external_user_email)
    await page.get_by_placeholder("password").click()
    await page.get_by_placeholder("password").fill(external_user_password)
    await page.get_by_role("button", name="Login").click()

    await expect(page).to_have_url(re.compile(rf"{jenkins_url}*"))
