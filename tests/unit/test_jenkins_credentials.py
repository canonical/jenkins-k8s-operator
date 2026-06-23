# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins credentials and token unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

from collections.abc import Iterator
from contextlib import contextmanager
from secrets import token_hex
from unittest.mock import MagicMock, patch

import jenkinsapi
import jenkinsapi.utils.requester
import ops
import pytest
import requests

import jenkins

from .types_ import HarnessWithContainer


def _jenkins_instance(container: ops.Container) -> jenkins.Jenkins:
    """Create Jenkins client wrapper for tests."""
    return jenkins.Jenkins("/", "admin-password", container)


def _token_failure_setup(
    *,
    use_security: bool,
    response_json_side_effect: Exception | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Build common mocks for failed token-generation scenarios.

    Returns:
        Tuple of (mock_client, mock_container, check_response).
    """
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.generate_new_api_token.side_effect = jenkinsapi.utils.requester.JenkinsAPIException

    check_response = MagicMock(spec=requests.Response)
    check_response.status_code = 200
    if response_json_side_effect is not None:
        check_response.json = MagicMock(side_effect=response_json_side_effect)
    else:
        check_response.json.return_value = {"useSecurity": use_security}

    mock_container = MagicMock(ops.Container)
    return mock_client, mock_container, check_response


@contextmanager
def _patch_token_generation_failure(
    mock_client: MagicMock, check_response: MagicMock
) -> Iterator[None]:
    """Unified patch context for token-generation failure tests."""
    with (
        patch.object(jenkins.Jenkins, "get_admin_user_client", return_value=mock_client),
        patch("jenkins.requests.get", return_value=check_response),
    ):
        yield


def test_get_admin_credentials(
    harness_container: HarnessWithContainer, admin_credentials: jenkins.Credentials
):
    """
    arrange: given a mocked container that returns the admin password file content.
    act: admin credentials are fetched over pebble.
    assert: correct admin credentials from the filesystem are returned.
    """
    assert jenkins.get_admin_credentials(harness_container.container) == admin_credentials


def test_get_api_credentials_error():
    """
    arrange: set up a container raising an exception.
    act: admin api credentials are fetched over pebble.
    assert: a JenkinsBootstrapError is raised.
    """
    mock_container = MagicMock(ops.Container)
    mock_container.pull = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.get_api_credentials(mock_container)


def test_get_api_credentials(
    harness_container: HarnessWithContainer, admin_credentials: jenkins.Credentials
):
    """
    arrange: given a mocked container that returns the admin api token file content.
    act: admin credentials are fetched over pebble.
    assert: correct admin credentials from the filesystem are returned.
    """
    assert jenkins.get_api_credentials(harness_container.container) == admin_credentials


def test_get_admin_api_client_raises_when_api_credentials_missing(
    harness_container: HarnessWithContainer,
):
    """get_admin_api_client raises JenkinsBootstrapError when API token is unavailable."""
    with (
        patch.object(jenkins, "get_api_credentials", side_effect=jenkins.JenkinsBootstrapError),
        pytest.raises(
            jenkins.JenkinsBootstrapError, match="Admin API credentials not yet available"
        ),
    ):
        _jenkins_instance(harness_container.container).get_admin_api_client()


def test_generate_admin_user_token(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given a monkeypatched mocked jenkinsapi client.
    act: when generate_admin_user_token is called.
    assert: generate_new_api_token is called and token written to API token path.
    """
    test_api_token = token_hex(8)
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.generate_new_api_token.return_value = test_api_token

    with patch.object(jenkins.Jenkins, "get_admin_user_client", return_value=mock_client):
        _jenkins_instance(harness_container.container).generate_admin_user_token()

    assert (
        harness_container.container.pull(jenkins.API_TOKEN_PATH, encoding="utf-8").read()
        == test_api_token
    )


@pytest.mark.parametrize(
    "use_security, expect_placeholder_push",
    [
        pytest.param(True, False, id="security-enabled-raises"),
        pytest.param(False, True, id="security-disabled-placeholder"),
    ],
)
def test_generate_admin_user_token_security_modes(
    use_security: bool,
    expect_placeholder_push: bool,
):
    """
    arrange: token generation fails and jenkins reports a security mode.
    act: when generate_admin_user_token is called.
    assert: raises when enabled, writes placeholder token when disabled.
    """
    mock_client, mock_container, check_response = _token_failure_setup(use_security=use_security)

    with _patch_token_generation_failure(mock_client, check_response):
        if expect_placeholder_push:
            _jenkins_instance(mock_container).generate_admin_user_token()
            mock_container.push.assert_called_once()
            assert mock_container.push.call_args.args[0] == jenkins.API_TOKEN_PATH
            assert mock_container.push.call_args.args[1].startswith("placeholder-")
        else:
            with pytest.raises(jenkins.JenkinsBootstrapError):
                _jenkins_instance(mock_container).generate_admin_user_token()


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(requests.exceptions.JSONDecodeError, id="decode-error"),
        pytest.param(KeyError, id="keyerror"),
    ],
)
def test_generate_admin_user_token_security_disabled_response_parse_error(
    monkeypatch: pytest.MonkeyPatch, exception: Exception
):
    """
    arrange: given token generation fails and useSecurity response cannot be parsed.
    act: when generate_admin_user_token is called.
    assert: JenkinsBootstrapError is raised.
    """
    monkeypatch.setattr(
        requests.exceptions.JSONDecodeError, "__init__", MagicMock(return_value=None)
    )

    mock_client, mock_container, check_response = _token_failure_setup(
        use_security=True,
        response_json_side_effect=exception,
    )

    with (
        _patch_token_generation_failure(mock_client, check_response),
        pytest.raises(jenkins.JenkinsBootstrapError),
    ):
        _jenkins_instance(mock_container).generate_admin_user_token()


def test_rotate_credentials_error(container: ops.Container):
    """
    arrange: given monkeypatched _invalidate_sessions that raises JenkinsAPIException.
    act: when rotate_credentials is called.
    assert: JenkinsError is raised.
    """
    with patch.object(jenkins.Jenkins, "_invalidate_sessions") as invalidate_sessions_mock:
        invalidate_sessions_mock.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

        with pytest.raises(jenkins.JenkinsError):
            _jenkins_instance(container).rotate_credentials(container)


def test_rotate_credentials(container: ops.Container):
    """
    arrange: given monkeypatched _invalidate_sessions that returns no errors.
    act: when rotate_credentials is called.
    assert: password file is updated and newly generated password is returned.
    """
    with (
        patch.object(jenkins.Jenkins, "_invalidate_sessions"),
        patch.object(jenkins.Jenkins, "_set_new_password"),
    ):
        old_password = container.pull(jenkins.PASSWORD_FILE_PATH, encoding="utf-8").read()
        assert old_password != _jenkins_instance(container).rotate_credentials(container), (
            "Password not newly generated"
        )
        assert old_password != container.pull(jenkins.PASSWORD_FILE_PATH, encoding="utf-8").read()
