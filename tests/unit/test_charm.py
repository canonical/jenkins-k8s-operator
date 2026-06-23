# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import datetime
import functools
import typing
from unittest.mock import MagicMock, PropertyMock, patch

import ops
import pytest
import requests
import yaml

import jenkins
import state
import timerange
from charm import JenkinsK8sOperatorCharm, ReconcileBlockedError

from .helpers import ACTIVE_STATUS_NAME
from .types_ import HarnessWithContainer

# Reconcile/config and event-routing tests moved to:
# - tests/unit/test_charm_reconcile.py
# - tests/unit/test_charm_events.py
# for module simplicity

def test__on_jenkins_pebble_ready_get_version_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[..., requests.Response],
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a patched jenkins.version property that raises an exception.
    act: when the jenkins_pebble_ready event is fired.
    assert: the charm raises an error.
    """
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))
    harness = harness_container.harness
    harness.begin()

    with (
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
        patch.object(jenkins.Jenkins, "bootstrap"),
    ):
        version_mock.side_effect = jenkins.JenkinsError

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

        with pytest.raises(jenkins.JenkinsError):
            jenkins_charm._on_jenkins_pebble_ready(MagicMock(spec=ops.PebbleReadyEvent))


@pytest.mark.usefixtures("patch_os_environ")
def test__on_jenkins_pebble_ready(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked jenkins client and a patched requests instance.
    act: when the Jenkins pebble ready event is fired.
    assert: the unit status should show expected status and the jenkins port should be open.
    """
    harness = harness_container.harness
    with (
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "bootstrap"),
        patch.object(jenkins.Jenkins, "version", new_callable=PropertyMock) as version_mock,
    ):
        version_mock.return_value = "1"
        harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        jenkins_charm._on_jenkins_pebble_ready(MagicMock(spec=ops.PebbleReadyEvent))

        assert jenkins_charm.unit.status.name == ACTIVE_STATUS_NAME, (
            f"unit should be in {ACTIVE_STATUS_NAME}"
        )


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(jenkins.JenkinsPluginError, id="plugin error"),
        pytest.param(jenkins.JenkinsError, id="jenkins error"),
        pytest.param(TimeoutError, id="timeout error"),
    ],
)
def test__remove_unlisted_plugins_error(
    harness_container: HarnessWithContainer,
    exception: Exception,
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that raises exceptions.
    act: when _reconcile_plugins is called.
    assert: no unhandled exception is raised (errors are logged internally).
    """
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_unlisted_plugins_mock:
        remove_unlisted_plugins_mock.side_effect = exception
        harness_container.harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
        dummy_state = state.State.from_charm(jenkins_charm)
        # _reconcile_plugins catches exceptions internally and logs them
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)


def test__remove_unlisted_plugins(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm and monkeypatched remove_unlisted_plugins that succeeds.
    act: when _reconcile_plugins is called.
    assert: remove_unlisted_plugins is called without error.
    """
    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 12)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    harness_container.harness.update_config({"restart-time-range": "02-22"})
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_mock:
        harness_container.harness.begin()

        jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
        dummy_state = state.State.from_charm(jenkins_charm)
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)

        remove_mock.assert_called_once()


def test__on_update_status_not_in_time_range(
    harness_container: HarnessWithContainer, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a charm with restart-time-range 0-23 and monkeypatched datetime with hour 23.
    act: when _reconcile_plugins is called directly.
    assert: remove_unlisted_plugins is not called since we're outside the time range.
    """
    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 23)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)
    harness_container.harness.update_config({"restart-time-range": "00-23"})
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    dummy_state = state.State.from_charm(jenkins_charm)
    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as remove_unlisted_plugins_mock:
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)

        remove_unlisted_plugins_mock.assert_not_called()


# pylint doesn't quite understand walrus operators
# pylint: disable=unused-variable,undefined-variable,too-many-locals
@pytest.mark.parametrize(
    "exception, log_message",
    [
        pytest.param(
            jenkins.JenkinsPluginError("plugin err"),
            "Failed to remove unlisted plugin",
            id="Failed plugin remove status.",
        ),
        pytest.param(
            jenkins.JenkinsError("jenkins err"),
            "Failed to remove unlisted plugin",
            id="Failed plugin remove status (blocked status).",
        ),
        pytest.param(
            TimeoutError("timeout"),
            "Failed to remove plugins",
            id="Failed plugin remove status (maintenance status).",
        ),
        pytest.param(
            jenkins.JenkinsPluginError("plugin err 2"),
            "Failed to remove unlisted plugin",
            id="Failed update jenkins status (waiting status).",
        ),
        pytest.param(
            jenkins.JenkinsError("jenkins err 2"),
            "Failed to remove unlisted plugin",
            id="Both failed (active status)",
        ),
    ],
)
# pylint: enable=unused-variable,undefined-variable,too-many-locals
def test__on_update_status(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    log_message: str,
):
    """
    arrange: given patched remove_unlisted_plugins that raises an exception.
    act: when _reconcile_plugins is called.
    assert: no unhandled exception is raised (error is logged internally).
    """
    harness_container.harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    dummy_state = state.State.from_charm(jenkins_charm)

    with patch.object(jenkins.Jenkins, "remove_unlisted_plugins") as mock_remove:
        mock_remove.side_effect = exception
        # Should not raise - errors are caught and logged
        jenkins_charm._reconcile_plugins(harness_container.container, dummy_state)


## Reconcile/config tests moved to tests/unit/test_charm_reconcile.py


def test__remove_unlisted_plugins_requires_state(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given a started charm instance.
    act: when _reconcile_plugins is called without state.
    assert: python rejects the call because state is required.
    """
    harness_container.harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    reconcile_plugins = typing.cast(typing.Any, jenkins_charm._reconcile_plugins)

    with pytest.raises(TypeError):
        reconcile_plugins(harness_container.container)


## Event-routing tests moved to tests/unit/test_charm_events.py


VALID_JCASC_CONFIG = {
    "jenkins": {
        "systemMessage": "Managed by Juju",
        "numExecutors": 0,
    }
}

JCASC_WITH_SECURITY_REALM = {
    "jenkins": {
        "securityRealm": {
            "local": {
                "allowsSignup": False,
                "users": [{"id": "custom", "password": "secret"}],
            }
        }
    }
}


@pytest.fixture(name="harness_with_jcasc")
def harness_with_jcasc_fixture(harness_container: HarnessWithContainer):
    """Provide a harness with JCasC config set and Jenkins home dir ready."""
    harness = harness_container.harness
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    # Set the jcasc-config option
    harness.update_config(
        {"jcasc-config": yaml.dump(VALID_JCASC_CONFIG, default_flow_style=False)}
    )

    return harness, jenkins_charm, harness_container.container


def _make_jenkins_instance() -> jenkins.Jenkins:
    """Create a Jenkins instance with a test environment."""
    env: jenkins.Environment = {
        "JENKINS_HOME": str(jenkins.JENKINS_HOME_PATH),
        "JENKINS_PREFIX": "",
        "CASC_JENKINS_CONFIG": str(jenkins.JCASC_CONFIG_PATH),
        "JENKINS_ADMIN_PASSWORD": "",
    }
    return jenkins.Jenkins(env)


def test_build_jcasc_config_blocks_security_realm_with_auth_proxy(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given auth_proxy is integrated and jcasc-config has securityRealm.
    act: when _build_jcasc_config is called.
    assert: ReconcileBlockedError is raised with conflict message.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_state = MagicMock(spec=state.State)
    mock_state.jcasc_config = JCASC_WITH_SECURITY_REALM
    mock_state.auth_proxy_integrated = True

    with pytest.raises(ReconcileBlockedError, match="JCasC conflict"):
        charm._build_jcasc_config(mock_state)


def test_build_jcasc_config_allows_security_realm_without_auth_proxy(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given auth_proxy is NOT integrated and jcasc-config has securityRealm.
    act: when _build_jcasc_config is called.
    assert: config is returned with user's securityRealm preserved.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_state = MagicMock(spec=state.State)
    mock_state.jcasc_config = JCASC_WITH_SECURITY_REALM
    mock_state.auth_proxy_integrated = False

    result = charm._build_jcasc_config(mock_state)
    assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "custom"


def test_build_jcasc_config_injects_admin_credentials(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given jcasc-config without securityRealm.
    act: when _build_jcasc_config is called.
    assert: securityRealm with admin/${JENKINS_ADMIN_PASSWORD} is injected.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_state = MagicMock(spec=state.State)
    mock_state.jcasc_config = VALID_JCASC_CONFIG
    mock_state.auth_proxy_integrated = False

    result = charm._build_jcasc_config(mock_state)
    assert "securityRealm" in result["jenkins"]
    realm = result["jenkins"]["securityRealm"]
    assert realm["local"]["allowsSignup"] is False
    assert realm["local"]["users"][0]["password"] == "${JENKINS_ADMIN_PASSWORD}"


def test_reconcile_jcasc_skips_when_no_config(harness_container: HarnessWithContainer):
    """
    arrange: given jcasc_config is None.
    act: when _reconcile_jcasc is called.
    assert: returns without calling sync_jcasc_config.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_container = MagicMock(spec=ops.Container)
    mock_state = MagicMock(spec=state.State)
    mock_state.jcasc_config = None

    with patch.object(charm.jenkins, "sync_jcasc_config") as sync_mock:
        charm._reconcile_jcasc(mock_container, mock_state)

    sync_mock.assert_not_called()


@pytest.mark.parametrize(
    "sync_return,expect_blocked",
    [
        pytest.param(True, False, id="sync_success"),
        pytest.param(False, True, id="sync_failure"),
    ],
)
def test_reconcile_jcasc_sync_result(
    harness_container: HarnessWithContainer, sync_return: bool, expect_blocked: bool
):
    """
    arrange: given valid config and sync_jcasc_config returns sync_return.
    act: when _reconcile_jcasc is called.
    assert: raises ReconcileBlockedError only when sync fails.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    mock_container = MagicMock(spec=ops.Container)
    mock_state = MagicMock(spec=state.State)
    mock_state.jcasc_config = VALID_JCASC_CONFIG
    mock_state.auth_proxy_integrated = False

    with patch.object(charm.jenkins, "sync_jcasc_config", return_value=sync_return):
        if expect_blocked:
            with pytest.raises(ReconcileBlockedError, match="validation failed"):
                charm._reconcile_jcasc(mock_container, mock_state)
        else:
            charm._reconcile_jcasc(mock_container, mock_state)


def test_sync_jcasc_config_no_write_when_unchanged():
    """
    arrange: given container already has the desired config.
    act: when sync_jcasc_config is called.
    assert: push is NOT called, returns True.
    """
    j = _make_jenkins_instance()
    desired = "jenkins:\n  systemMessage: test\n"
    mock_container = MagicMock(spec=ops.Container)
    mock_pull = MagicMock()
    mock_pull.read.return_value = desired
    mock_container.pull.return_value = mock_pull

    result = j.sync_jcasc_config(mock_container, desired)

    assert result is True
    mock_container.push.assert_not_called()


def test_sync_jcasc_config_successful_write():
    """
    arrange: given first-time write (file doesn't exist) and check_jcasc passes.
    act: when sync_jcasc_config is called.
    assert: push uses make_dirs=True, reload is called, returns True.
    """
    j = _make_jenkins_instance()
    mock_container = MagicMock(spec=ops.Container)
    mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
    mock_container.push.return_value = None

    with (
        patch.object(j, "check_jcasc", return_value=True),
        patch.object(j, "reload_jcasc") as reload_mock,
    ):
        result = j.sync_jcasc_config(mock_container, "jenkins:\n  test: true\n")

    assert result is True
    push_kwargs = mock_container.push.call_args[1]
    assert push_kwargs.get("make_dirs") is True
    reload_mock.assert_called_once_with(mock_container)


@pytest.mark.parametrize(
    "has_previous",
    [
        pytest.param(True, id="rollback_to_previous"),
        pytest.param(False, id="remove_file"),
    ],
)
def test_sync_jcasc_config_validation_failure(has_previous: bool):
    """
    arrange: given check_jcasc returns False.
    act: when sync_jcasc_config writes config.
    assert: rolls back to previous config or removes file, returns False.
    """
    j = _make_jenkins_instance()
    previous = "jenkins:\n  systemMessage: old\n"
    mock_container = MagicMock(spec=ops.Container)
    mock_container.push.return_value = None

    if has_previous:
        mock_pull = MagicMock()
        mock_pull.read.return_value = previous
        mock_container.pull.return_value = mock_pull
    else:
        mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")

    with (
        patch.object(j, "check_jcasc", return_value=False),
        patch.object(j, "reload_jcasc") as reload_mock,
    ):
        result = j.sync_jcasc_config(mock_container, "jenkins:\n  test: new\n")

    assert result is False
    if has_previous:
        assert mock_container.push.call_count == 2
        rollback_call = mock_container.push.call_args_list[1]
        assert rollback_call[0][1] == previous
        reload_mock.assert_called_once_with(mock_container)
    else:
        mock_container.remove_path.assert_called_once()


def test_sync_jcasc_config_skips_validation_when_not_bootstrapped():
    """
    arrange: given check_jcasc raises JenkinsBootstrapError.
    act: when sync_jcasc_config writes config.
    assert: config stays on disk, returns True (optimistic).
    """
    j = _make_jenkins_instance()
    mock_container = MagicMock(spec=ops.Container)
    mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
    mock_container.push.return_value = None

    with (
        patch.object(
            j,
            "check_jcasc",
            side_effect=jenkins.JenkinsBootstrapError("not ready"),
        ),
        patch.object(j, "reload_jcasc") as reload_mock,
    ):
        result = j.sync_jcasc_config(mock_container, "jenkins:\n  test: true\n")

    assert result is True
    mock_container.push.assert_called_once()
    reload_mock.assert_not_called()


def test_reload_jcasc_success():
    """
    arrange: given a working Jenkins API.
    act: when reload_jcasc is called.
    assert: POST to /configuration-as-code/reload is made.
    """
    mock_container = MagicMock(spec=ops.Container)
    mock_requester = MagicMock()
    mock_client = MagicMock()
    mock_client.requester = mock_requester

    j = _make_jenkins_instance()
    with (
        patch.object(j, "_get_client", return_value=mock_client),
        patch("jenkins._get_api_credentials") as creds_mock,
    ):
        creds_mock.return_value = jenkins.Credentials("admin", "token")
        j.reload_jcasc(mock_container)

    mock_requester.post_url.assert_called_once_with(
        "http://localhost:8080/configuration-as-code/reload"
    )


def test_reload_jcasc_raises_jenkins_error():
    """
    arrange: given Jenkins API that returns an error.
    act: when reload_jcasc is called.
    assert: JenkinsError is raised.
    """
    mock_container = MagicMock(spec=ops.Container)

    j = _make_jenkins_instance()
    with (
        patch(
            "jenkins._get_api_credentials",
            side_effect=requests.exceptions.ConnectionError("conn refused"),
        ),
        pytest.raises(jenkins.JenkinsError),
    ):
        j.reload_jcasc(mock_container)


def test_check_jcasc_valid_config():
    """
    arrange: given Jenkins API returns 200 for check endpoint.
    act: when check_jcasc is called.
    assert: returns True.
    """
    mock_container = MagicMock(spec=ops.Container)
    mock_requester = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_requester.post_url.return_value = mock_response
    mock_client = MagicMock()
    mock_client.requester = mock_requester

    j = _make_jenkins_instance()
    with (
        patch.object(j, "_get_client", return_value=mock_client),
        patch("jenkins._get_api_credentials") as creds_mock,
    ):
        creds_mock.return_value = jenkins.Credentials("admin", "token")
        result = j.check_jcasc(mock_container, "jenkins: {}")

    assert result is True


def test_check_jcasc_raises_on_failure():
    """
    arrange: given Jenkins API is unreachable.
    act: when check_jcasc is called.
    assert: JenkinsError is raised.
    """
    mock_container = MagicMock(spec=ops.Container)

    j = _make_jenkins_instance()
    with (
        patch(
            "jenkins._get_api_credentials",
            side_effect=jenkins.JenkinsBootstrapError("not ready"),
        ),
        pytest.raises(jenkins.JenkinsError),
    ):
        j.check_jcasc(mock_container, "jenkins: {}")
