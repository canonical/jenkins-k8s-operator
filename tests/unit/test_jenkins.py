# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins module tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access


from functools import partial
from typing import Any, Callable

import pytest
import requests

from jenkins import (
    JENKINS_HOME_PATH,
    LAST_EXEC_VERSION_PATH,
    WIZARD_VERSION_PATH,
    _is_jenkins_ready,
    calculate_env,
    get_admin_credentials,
    get_version,
    unlock_jenkins,
    wait_jenkins_ready,
)
from types_ import Credentials

from .helpers import ConnectionExceptionPatch
from .types_ import HarnessWithContainer


def test__is_jenkins_ready_connection_exception(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given mocked requests that raises a connection exception.
    act: send a request to Jenkins login page.
    assert: return false, denoting Jenkins is not ready.
    """
    monkeypatch.setattr(requests, "get", ConnectionExceptionPatch)

    ready = _is_jenkins_ready()

    assert not ready


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


def test_wait_jenkins_ready_last_successful_check(
    monkeypatch: pytest.MonkeyPatch, jenkins_version: str
):
    """
    arrange: given mocked requests that returns a 200 response the third time it's called.
    act: wait for jenkins to become ready for 1 second with 1 second interval.
    assert: No exceptions are raised.
    """

    class MockedResponse(requests.Response):
        """Mocked requests.Response that returns successful status code on 3rd instantiation.

        Attrs:
            num_called: Number of times the class has been instantiated.
        """

        num_called = 0

        def __init__(self, *_args, **_kwargs) -> None:
            """Initialize the response and count the number of instantiations."""
            super().__init__()
            MockedResponse.num_called += 1

            self.status_code = 200 if MockedResponse.num_called == 3 else 503
            self.headers["X-Jenkins"] = jenkins_version

    monkeypatch.setattr(requests, "get", MockedResponse)

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


def test_get_admin_credentials(
    harness_container: HarnessWithContainer, admin_credentials: Credentials
):
    """
    arrange: given a mocked container that returns the admin password file content.
    act: admin credentials are fetched over pebble.
    assert: correct admin credentials from the filesystem are returned.
    """
    assert get_admin_credentials(harness_container.container) == admin_credentials


@pytest.mark.parametrize(
    "admin_configured",
    [
        pytest.param(
            False,
            id="Admin not configured",
        ),
        pytest.param(
            True,
            id="Admin configured",
        ),
    ],
)
def test_calculate_env(admin_configured: bool):
    """
    arrange: given admin_configured boolean state variable.
    act: when calculate_env is called.
    assert: expected environment variable mapping dictionary is returned.
    """
    env = calculate_env(admin_configured=admin_configured)

    assert env == {
        "JENKINS_HOME": str(JENKINS_HOME_PATH),
        "ADMIN_CONFIGURED": "True" if admin_configured else "False",
    }


def test_get_version(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    jenkins_version: str,
):
    """
    arrange: given a monkeypatched request that returns Jenkins version in headers.
    act: when a request is sent to Jenkins server.
    assert: The Jenkins server version is returned.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=200))

    assert get_version() == jenkins_version


def test_unlock_jenkins(
    harness_container: HarnessWithContainer,
    mocked_get_request: Callable[[str, int, Any, Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """
    arrange: given a mocked container and a monkeypatched Jenkins client.
    act: unlock_jenkins is called.
    assert: files necessary to unlock Jenkins are written.
    """
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))

    unlock_jenkins(harness_container.container)

    assert (
        harness_container.container.pull(LAST_EXEC_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )
    assert (
        harness_container.container.pull(WIZARD_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )
