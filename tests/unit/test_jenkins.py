# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins module tests."""

# pylint:disable=protected-access


from functools import partial
from secrets import token_hex
from typing import Any, Callable

import pytest
import requests

from jenkins import (
    JENKINS_HOME,
    _is_jenkins_ready,
    calculate_env,
    get_admin_credentials,
    wait_jenkins_ready,
)
from types_ import Credentials, JenkinsEnvironmentMap


@pytest.mark.parametrize(
    "status_code, expected_ready",
    [pytest.param(503, False, id="Service unavailable"), pytest.param(200, True, id="Success")],
)
def test__is_jenkins_ready(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    status_code: int,
    expected_ready: bool,
):
    """
    arrange: given mocked requests that return a response with status_code.
    act: send a request to Jenkins login page.
    assert: return true if ready, false otherwise.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))

    ready = _is_jenkins_ready()

    assert ready == expected_ready


def test__wait_jenkins_ready_timeout(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
):
    """
    arrange: given mocked requests that returns a 503 response.
    act: wait for jenkins to become ready.
    assert: a TimeoutError is raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=503))

    with pytest.raises(TimeoutError):
        wait_jenkins_ready(1, 1)


def test_wait_jenkins_ready(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
):
    """
    arrange: given mocked requests that returns a 200 response.
    act: wait for jenkins to become ready.
    assert: No exceptions are raised.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))

    wait_jenkins_ready(1, 1)


# Pylint diesn't understand how the walrus operator works
# pylint: disable=undefined-variable,unused-variable
@pytest.mark.parametrize(
    "init_password_file_content, expected_credentials",
    [
        pytest.param(
            password_content := token_hex(),
            Credentials(username="admin", password=password_content),
            id="random password",
        ),
        pytest.param(
            f"{(password_content:=token_hex())}\n",
            Credentials(username="admin", password=password_content),
            id="random password with newline",
        ),
    ],
)
def test_get_admin_credentials(init_password_file_content: str, expected_credentials: Credentials):
    """
    arrange: given a mocked container that returns the admin password file content.
    act: admin credentials are fetched over pebble.
    assert: correct admin credentials from the filesystem are returned.
    """
    assert get_admin_credentials(init_password_file_content) == expected_credentials


@pytest.mark.parametrize(
    "admin_configured, expected_map",
    [
        pytest.param(
            False,
            {"JENKINS_HOME": str(JENKINS_HOME), "ADMIN_CONFIGURED": "False"},
            id="Admin not configured",
        ),
        pytest.param(
            True,
            {"JENKINS_HOME": str(JENKINS_HOME), "ADMIN_CONFIGURED": "True"},
            id="Admin configured",
        ),
    ],
)
def test_calculate_env(admin_configured: bool, expected_map: JenkinsEnvironmentMap):
    """
    arrange: given admin_configured boolean state variable.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    env = calculate_env(admin_configured=admin_configured)

    assert env == expected_map
