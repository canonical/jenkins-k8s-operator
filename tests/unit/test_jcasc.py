# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm JCasC reconciliation unit tests."""

import typing
from unittest.mock import MagicMock, patch

import ops
import pytest
import yaml
from ops.testing import Harness

import jenkins
import state
from charm import JenkinsK8sOperatorCharm

from .types_ import HarnessWithContainer


VALID_JCASC_CONFIG = yaml.dump(
    {
        "jenkins": {
            "systemMessage": "Managed by Juju",
            "numExecutors": 0,
        }
    }
)

JCASC_WITH_SECURITY_REALM = yaml.dump(
    {
        "jenkins": {
            "securityRealm": {
                "local": {
                    "allowsSignup": False,
                    "users": [{"id": "custom", "password": "secret"}],
                }
            }
        }
    }
)


@pytest.fixture(name="harness_with_jcasc")
def harness_with_jcasc_fixture(harness_container: HarnessWithContainer):
    """Provide a harness with JCasC config set and Jenkins home dir ready."""
    harness = harness_container.harness
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

    # Set the jcasc-config option
    harness.update_config({"jcasc-config": VALID_JCASC_CONFIG})

    return harness, jenkins_charm, harness_container.container


class TestReconcileJcascSkips:
    """Tests for _reconcile_jcasc early-exit conditions."""

    def test_skips_when_jenkins_home_not_ready(self, harness_container: HarnessWithContainer):
        """
        arrange: given a charm with container that has no Jenkins home dir.
        act: when _reconcile_jcasc is called.
        assert: returns without error (no-op).
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.side_effect = ops.pebble.APIError(
            body={}, code=404, status="Not Found", message="not found"
        )
        mock_state = MagicMock(spec=state.State)

        # Should not raise
        charm._reconcile_jcasc(mock_container, mock_state)

    def test_blocks_on_empty_config(self, harness_container: HarnessWithContainer):
        """
        arrange: given jcasc-config is whitespace-only.
        act: when _reconcile_jcasc is called.
        assert: unit status is BlockedStatus.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = "   "

        charm._reconcile_jcasc(mock_container, mock_state)

        assert isinstance(charm.unit.status, ops.BlockedStatus)
        assert "must not be empty" in charm.unit.status.message

    def test_blocks_on_invalid_yaml(self, harness_container: HarnessWithContainer):
        """
        arrange: given jcasc-config is invalid YAML.
        act: when _reconcile_jcasc is called.
        assert: unit status is BlockedStatus.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = "{{invalid: yaml: [["

        charm._reconcile_jcasc(mock_container, mock_state)

        assert isinstance(charm.unit.status, ops.BlockedStatus)
        assert "Invalid jcasc-config YAML" in charm.unit.status.message

    def test_blocks_on_non_dict_yaml(self, harness_container: HarnessWithContainer):
        """
        arrange: given jcasc-config is a YAML list (not dict).
        act: when _reconcile_jcasc is called.
        assert: unit status is BlockedStatus.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = "- item1\n- item2"

        charm._reconcile_jcasc(mock_container, mock_state)

        assert isinstance(charm.unit.status, ops.BlockedStatus)
        assert "YAML mapping" in charm.unit.status.message


class TestReconcileJcascConflicts:
    """Tests for JCasC auth_proxy conflict detection."""

    def test_blocks_security_realm_with_auth_proxy(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given auth_proxy is integrated and jcasc-config has securityRealm.
        act: when _reconcile_jcasc is called.
        assert: unit status is BlockedStatus with conflict message.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = JCASC_WITH_SECURITY_REALM
        mock_state.auth_proxy_integrated = True

        charm._reconcile_jcasc(mock_container, mock_state)

        assert isinstance(charm.unit.status, ops.BlockedStatus)
        assert "JCasC conflict" in charm.unit.status.message

    def test_allows_security_realm_without_auth_proxy(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given auth_proxy is NOT integrated and jcasc-config has securityRealm.
        act: when _reconcile_jcasc is called.
        assert: config is written (no conflict).
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
        mock_container.push.return_value = None
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = JCASC_WITH_SECURITY_REALM
        mock_state.auth_proxy_integrated = False

        with patch.object(charm.jenkins, "check_jcasc", side_effect=jenkins.JenkinsError):
            charm._reconcile_jcasc(mock_container, mock_state)

        # Should have attempted to push the config
        mock_container.push.assert_called_once()


class TestReconcileJcascWrite:
    """Tests for JCasC config writing and credential injection."""

    def test_injects_admin_credentials_when_no_security_realm(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given jcasc-config without securityRealm.
        act: when _reconcile_jcasc writes config.
        assert: securityRealm with admin/${JENKINS_ADMIN_PASSWORD} is injected.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
        mock_container.push.return_value = None
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = VALID_JCASC_CONFIG
        mock_state.auth_proxy_integrated = False

        with patch.object(charm.jenkins, "check_jcasc", side_effect=jenkins.JenkinsError):
            charm._reconcile_jcasc(mock_container, mock_state)

        # Verify push was called and content has securityRealm injected
        push_call = mock_container.push.call_args
        written_content = push_call[1].get("source") or push_call[0][1]
        parsed = yaml.safe_load(written_content)
        assert "securityRealm" in parsed["jenkins"]
        realm = parsed["jenkins"]["securityRealm"]
        assert realm["local"]["allowsSignup"] is False
        assert realm["local"]["users"][0]["password"] == "${JENKINS_ADMIN_PASSWORD}"

    def test_no_write_when_config_unchanged(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given container already has the desired JCasC yaml.
        act: when _reconcile_jcasc is called.
        assert: container.push is NOT called (idempotent).
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)

        # Build the expected yaml (with injected securityRealm)
        user_config = yaml.safe_load(VALID_JCASC_CONFIG)
        user_config.setdefault("jenkins", {})["securityRealm"] = {
            "local": {
                "allowsSignup": False,
                "users": [{"id": "admin", "password": "${JENKINS_ADMIN_PASSWORD}"}],
            }
        }
        expected_yaml = yaml.dump(user_config, default_flow_style=False, sort_keys=False)

        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_pull = MagicMock()
        mock_pull.read.return_value = expected_yaml
        mock_container.pull.return_value = mock_pull
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = VALID_JCASC_CONFIG
        mock_state.auth_proxy_integrated = False

        charm._reconcile_jcasc(mock_container, mock_state)

        # push should NOT be called since content is unchanged
        mock_container.push.assert_not_called()

    def test_writes_with_make_dirs(self, harness_container: HarnessWithContainer):
        """
        arrange: given first-time JCasC write (file doesn't exist).
        act: when _reconcile_jcasc writes config.
        assert: push is called with make_dirs=True.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
        mock_container.push.return_value = None
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = VALID_JCASC_CONFIG
        mock_state.auth_proxy_integrated = False

        with patch.object(charm.jenkins, "check_jcasc", side_effect=jenkins.JenkinsError):
            charm._reconcile_jcasc(mock_container, mock_state)

        push_kwargs = mock_container.push.call_args[1]
        assert push_kwargs.get("make_dirs") is True


class TestReconcileJcascValidation:
    """Tests for JCasC validation and rollback."""

    def test_reload_on_successful_validation(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given check_jcasc returns True.
        act: when _reconcile_jcasc writes config.
        assert: reload_jcasc is called.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
        mock_container.push.return_value = None
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = VALID_JCASC_CONFIG
        mock_state.auth_proxy_integrated = False

        with (
            patch.object(charm.jenkins, "check_jcasc", return_value=True),
            patch.object(charm.jenkins, "reload_jcasc") as reload_mock,
        ):
            charm._reconcile_jcasc(mock_container, mock_state)

        reload_mock.assert_called_once_with(mock_container)

    def test_rollback_on_validation_failure(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given check_jcasc returns False and there's a previous config.
        act: when _reconcile_jcasc writes config.
        assert: previous config is restored and reload is called.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        previous_config = "jenkins:\n  systemMessage: old\n"

        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_pull = MagicMock()
        mock_pull.read.return_value = previous_config
        mock_container.pull.return_value = mock_pull
        mock_container.push.return_value = None
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = VALID_JCASC_CONFIG
        mock_state.auth_proxy_integrated = False

        with (
            patch.object(charm.jenkins, "check_jcasc", return_value=False),
            patch.object(charm.jenkins, "reload_jcasc") as reload_mock,
        ):
            charm._reconcile_jcasc(mock_container, mock_state)

        # Should be blocked
        assert isinstance(charm.unit.status, ops.BlockedStatus)
        assert "validation failed" in charm.unit.status.message

        # Should have pushed twice: new config + rollback
        assert mock_container.push.call_count == 2
        # Second push should be the previous config
        rollback_call = mock_container.push.call_args_list[1]
        rollback_content = rollback_call[0][1]
        assert rollback_content == previous_config

        # reload should be called to apply rollback
        reload_mock.assert_called_once_with(mock_container)

    def test_skips_validation_when_jenkins_not_ready(
        self, harness_container: HarnessWithContainer
    ):
        """
        arrange: given check_jcasc raises JenkinsError (API not ready).
        act: when _reconcile_jcasc writes config.
        assert: config stays on disk, no reload attempted, no blocked status.
        """
        harness = harness_container.harness
        harness.begin()
        charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
        mock_container = MagicMock(spec=ops.Container)
        mock_container.list_files.return_value = []
        mock_container.pull.side_effect = ops.pebble.PathError("not-found", "not found")
        mock_container.push.return_value = None
        mock_state = MagicMock(spec=state.State)
        mock_state.jcasc_config = VALID_JCASC_CONFIG
        mock_state.auth_proxy_integrated = False

        with (
            patch.object(charm.jenkins, "check_jcasc", side_effect=jenkins.JenkinsError),
            patch.object(charm.jenkins, "reload_jcasc") as reload_mock,
        ):
            charm._reconcile_jcasc(mock_container, mock_state)

        # Config was pushed but reload was skipped
        mock_container.push.assert_called_once()
        reload_mock.assert_not_called()
        # Status should not be Blocked
        assert not isinstance(charm.unit.status, ops.BlockedStatus)


class TestJenkinsJcascMethods:
    """Tests for Jenkins.reload_jcasc and Jenkins.check_jcasc methods."""

    @staticmethod
    def _make_jenkins_instance() -> jenkins.Jenkins:
        """Create a Jenkins instance with a test environment."""
        env: jenkins.Environment = {
            "JENKINS_HOME": str(jenkins.JENKINS_HOME_PATH),
            "JENKINS_PREFIX": "",
            "CASC_JENKINS_CONFIG": str(jenkins.JCASC_CONFIG_PATH),
            "JENKINS_ADMIN_PASSWORD": "",
        }
        return jenkins.Jenkins(env)

    def test_reload_jcasc_success(self):
        """
        arrange: given a working Jenkins API.
        act: when reload_jcasc is called.
        assert: POST to /configuration-as-code/reload is made.
        """
        mock_container = MagicMock(spec=ops.Container)
        mock_requester = MagicMock()
        mock_client = MagicMock()
        mock_client.requester = mock_requester

        j = self._make_jenkins_instance()
        with (
            patch.object(j, "_get_client", return_value=mock_client),
            patch("jenkins._get_api_credentials") as creds_mock,
        ):
            creds_mock.return_value = jenkins.Credentials("admin", "token")
            j.reload_jcasc(mock_container)

        mock_requester.post_url.assert_called_once_with(
            "http://localhost:8080/configuration-as-code/reload"
        )

    def test_reload_jcasc_raises_jenkins_error(self):
        """
        arrange: given Jenkins API that returns an error.
        act: when reload_jcasc is called.
        assert: JenkinsError is raised.
        """
        mock_container = MagicMock(spec=ops.Container)

        j = self._make_jenkins_instance()
        with (
            patch("jenkins._get_api_credentials", side_effect=Exception("conn refused")),
            pytest.raises(jenkins.JenkinsError),
        ):
            j.reload_jcasc(mock_container)

    def test_check_jcasc_valid_config(self):
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

        j = self._make_jenkins_instance()
        with (
            patch.object(j, "_get_client", return_value=mock_client),
            patch("jenkins._get_api_credentials") as creds_mock,
        ):
            creds_mock.return_value = jenkins.Credentials("admin", "token")
            result = j.check_jcasc(mock_container, "jenkins: {}")

        assert result is True

    def test_check_jcasc_raises_on_failure(self):
        """
        arrange: given Jenkins API is unreachable.
        act: when check_jcasc is called.
        assert: JenkinsError is raised.
        """
        mock_container = MagicMock(spec=ops.Container)

        j = self._make_jenkins_instance()
        with (
            patch(
                "jenkins._get_api_credentials",
                side_effect=jenkins.JenkinsBootstrapError("not ready"),
            ),
            pytest.raises(jenkins.JenkinsError),
        ):
            j.check_jcasc(mock_container, "jenkins: {}")
