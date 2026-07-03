# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins readiness and version unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import io
import typing
from contextlib import nullcontext
from functools import partial
from unittest.mock import MagicMock

import ops
import pytest
import requests

import jenkins

from .helpers import ConnectionExceptionPatch


def _jenkins_instance(container: ops.Container | None = None) -> jenkins.Jenkins:
    """Create Jenkins client wrapper for tests."""
    return jenkins.Jenkins("/", "admin-password", container or MagicMock(spec=ops.Container))


def _patch_get(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[..., requests.Response],
    *,
    status_code: int,
) -> None:
    """Patch requests.get with a mocked status-code response."""
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=status_code))


def test__is_ready_connection_exception(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given mocked requests that raises a connection exception.
    act: send a request to Jenkins login page.
    assert: return false, denoting Jenkins is not ready.
    """
    monkeypatch.setattr(requests, "get", ConnectionExceptionPatch)

    assert not _jenkins_instance()._is_ready()


@pytest.mark.parametrize(
    "status_code, expected_ready",
    [
        pytest.param(503, False, id="service-unavailable"),
        pytest.param(200, True, id="success"),
    ],
)
def test__is_ready(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[..., requests.Response],
    status_code: int,
    expected_ready: bool,
):
    """
    arrange: given mocked requests that return a response with status_code.
    act: send a request to Jenkins login page.
    assert: return true if ready, false otherwise.
    """
    _patch_get(monkeypatch, mocked_get_request, status_code=status_code)

    assert _jenkins_instance()._is_ready() == expected_ready


@pytest.mark.parametrize(
    "exception_type",
    [
        pytest.param(requests.exceptions.ConnectionError, id="connection-error"),
        pytest.param(requests.exceptions.Timeout, id="timeout"),
        pytest.param(requests.exceptions.JSONDecodeError, id="json-decode-error"),
    ],
)
def test_is_api_ready_handles_exceptions(
    monkeypatch: pytest.MonkeyPatch, exception_type: type[Exception]
):
    """_is_api_ready returns False when crumb endpoint checks error out."""
    if exception_type is requests.exceptions.JSONDecodeError:
        side_effect = exception_type("bad", "{}", 0)
    elif exception_type is ops.pebble.PathError:
        side_effect = ops.pebble.PathError(kind="not-found", message="missing")
    else:
        side_effect = exception_type("err")

    monkeypatch.setattr(requests, "get", MagicMock(side_effect=side_effect))
    assert _jenkins_instance()._is_api_ready() is False


def test_is_api_ready_success(monkeypatch: pytest.MonkeyPatch):
    """_is_api_ready returns True only when response is ok and includes crumb key."""
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"crumb": "abc", "crumbRequestField": ".crumb"}
    monkeypatch.setattr(requests, "get", MagicMock(return_value=response))

    assert _jenkins_instance()._is_api_ready() is True


@pytest.mark.parametrize(
    "status_code, expect_timeout",
    [
        pytest.param(503, True, id="timeout"),
        pytest.param(200, False, id="ready"),
    ],
)
def test_wait_ready_by_status(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[..., requests.Response],
    status_code: int,
    expect_timeout: bool,
):
    """
    arrange: given mocked requests status for readiness checks.
    act: wait for jenkins to become ready.
    assert: timeout or success based on provided status.
    """
    _patch_get(monkeypatch, mocked_get_request, status_code=status_code)
    ctx = pytest.raises(TimeoutError) if expect_timeout else nullcontext()
    with ctx:
        _jenkins_instance().wait_ready(1, 1, api_ready=False)


def test_wait_ready_last_successful_check(monkeypatch: pytest.MonkeyPatch, jenkins_version: str):
    """
    arrange: given mocked requests that returns a 200 response the third time it's called.
    act: wait for jenkins to become ready for 1 second with 1 second interval.
    assert: No exceptions are raised.
    """

    class MockedResponse(requests.Response):
        """Mocked requests.Response that returns successful status code on 3rd instantiation.

        Attributes:
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

    _jenkins_instance().wait_ready(1, 1, api_ready=False)


def test_is_storage_ready_falsey_no_container():
    """
    arrange: given no container.
    act: when is_storage_ready is called.
    assert: Falsy value is returned.
    """
    assert not jenkins.is_storage_ready(container=None)


def test_is_storage_ready_falsey_cant_connect():
    """
    arrange: given a container that cannot connect.
    act: when is_storage_ready is called.
    assert: Falsy value is returned.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.can_connect.return_value = False

    assert not jenkins.is_storage_ready(container=mock_container)


def test_is_storage_ready_falsey_not_mounted():
    """
    arrange: given a container without mounted storage.
    act: when is_storage_ready is called.
    assert: Falsy value is returned.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.pull.return_value = io.StringIO("")

    assert not jenkins.is_storage_ready(container=mock_container)


def test_is_storage_ready_proc_error():
    """
    arrange: given a mocked container exec that raises an error.
    act: when is_storage_ready is called.
    assert: StorageMountError is raised.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.pull.return_value = io.StringIO(str(jenkins.JENKINS_HOME_PATH))
    mock_proc = MagicMock(ops.pebble.ExecProcess)
    mock_proc.wait_output.side_effect = [ops.pebble.ChangeError(err="", change=MagicMock())]
    mock_container.exec.return_value = mock_proc

    with pytest.raises(jenkins.StorageMountError):
        jenkins.is_storage_ready(container=mock_container)


def _parametrize_jenkins_container_states():
    """Parametrize Jenkins container states for test_is_jenkins_ready.

    Returns:
        Mock Jenkins container with different states.
    """
    not_connectable_container = MagicMock()
    not_connectable_container.can_connect.return_value = False

    service_not_ready_container = MagicMock()
    service_not_ready_container.get_check.side_effect = [ops.ModelError()]

    service_not_running_container = MagicMock()
    service_not_running_container.get_check.return_value = (check_mock := MagicMock())
    check_mock.status = ops.pebble.CheckStatus.DOWN

    happy_container = MagicMock()
    happy_container.get_check.return_value = (happy_service_mock := MagicMock())
    happy_service_mock.status = ops.pebble.CheckStatus.UP
    return [
        pytest.param(None, False, id="no-container"),
        pytest.param(not_connectable_container, False, id="container-not-connectable"),
        pytest.param(service_not_ready_container, False, id="service-not-ready"),
        pytest.param(service_not_running_container, False, id="service-not-running"),
        pytest.param(happy_container, True, id="service-running"),
    ]


@pytest.mark.parametrize(
    ("container", "expected_ready_status"), _parametrize_jenkins_container_states()
)
def test_is_jenkins_ready(container: MagicMock, expected_ready_status: bool):
    """
    arrange: given a mocked Jenkins container of different states.
    act: when is_jenkins_ready is called.
    assert: expected status is returned.
    """
    assert jenkins.is_jenkins_ready(container=container) == expected_ready_status


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(requests.exceptions.Timeout, id="timeout"),
        pytest.param(requests.exceptions.ConnectionError, id="connection"),
    ],
)
def test_version_error(monkeypatch: pytest.MonkeyPatch, exception: Exception):
    """
    arrange: given a monkeypatched request that raises exceptions.
    act: when a request is sent to Jenkins server.
    assert: JenkinsError exception is raised.
    """
    monkeypatch.setattr(jenkins.requests, "get", MagicMock(side_effect=exception))
    jenkins_instance = _jenkins_instance()

    with pytest.raises(jenkins.JenkinsError):
        _ = jenkins_instance.version


def test_version(
    monkeypatch: pytest.MonkeyPatch,
    mocked_get_request: typing.Callable[..., requests.Response],
    jenkins_version: str,
):
    """
    arrange: given a monkeypatched request that returns Jenkins version in headers.
    act: when a request is sent to Jenkins server.
    assert: The Jenkins server version is returned.
    """
    _patch_get(monkeypatch, mocked_get_request, status_code=200)

    assert _jenkins_instance().version == jenkins_version
