# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm JCasC reconciliation unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import hashlib
import typing
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ops
import pytest
import yaml

import jenkins
import state
from charm import JenkinsK8sOperatorCharm, ReconcileBlockedError

from .types_ import HarnessWithContainer

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


def test_build_jcasc_config_auth_proxy_bypasses_security():
    """
    arrange: given user jcasc config and auth-proxy integrated.
    act: when build_jcasc_config is called.
    assert: securityRealm and authorizationStrategy are set as siblings for auth-proxy bypass.
    """
    result = jenkins.build_jcasc_config(
        VALID_JCASC_CONFIG,
        proxy_config=None,
        auth_proxy=True,
    )

    assert result["jenkins"]["securityRealm"] == "none"
    assert result["jenkins"]["authorizationStrategy"] == "unsecured"


def test_build_jcasc_config_default_injects_admin_realm():
    """
    arrange: given user jcasc config and auth-proxy not integrated.
    act: when build_jcasc_config is called.
    assert: admin securityRealm with local users is injected.
    """
    result = jenkins.build_jcasc_config(
        VALID_JCASC_CONFIG,
        proxy_config=None,
        auth_proxy=False,
    )

    assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "admin"


def test_build_jcasc_config_preserves_existing_security_realm_without_mutation():
    """
    arrange: given user jcasc config with existing securityRealm.
    act: when build_jcasc_config is called.
    assert: user-provided securityRealm is preserved.
    """
    result = jenkins.build_jcasc_config(
        JCASC_WITH_SECURITY_REALM,
        proxy_config=None,
        auth_proxy=False,
    )

    assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "custom"


def test_build_jcasc_config_auth_proxy_preserves_user_security_realm_and_warns():
    """
    arrange: given user config already defines securityRealm and auth-proxy is integrated.
    act: when build_jcasc_config is called.
    assert: user securityRealm is preserved and warning branch is logged.
    """
    with patch.object(jenkins.logger, "warning") as warning_mock:
        result = jenkins.build_jcasc_config(
            JCASC_WITH_SECURITY_REALM,
            proxy_config=None,
            auth_proxy=True,
        )

    assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "custom"
    warning_mock.assert_called_once_with(
        "Jenkins security is managed by user-provided jcasc-config; "
        "auth-proxy bypass not injected."
    )


def test_build_jcasc_config_injects_proxy_settings():
    """
    arrange: given proxy settings in state.ProxyConfig.
    act: when build_jcasc_config is called.
    assert: proxy host/port are injected into jenkins section.
    """
    proxy = typing.cast(
        state.ProxyConfig,
        SimpleNamespace(
            http_proxy="http://proxy.example.com:3128",
            https_proxy=None,
            no_proxy=None,
        ),
    )

    result = jenkins.build_jcasc_config(
        VALID_JCASC_CONFIG,
        proxy_config=proxy,
        auth_proxy=False,
    )

    assert result["jenkins"]["proxy"] == {"name": "proxy.example.com", "port": "3128"}


def test_build_jcasc_config_injects_proxy_name_without_port():
    """
    arrange: given proxy settings without explicit port.
    act: when build_jcasc_config is called.
    assert: only proxy host name is injected.
    """
    proxy = typing.cast(
        state.ProxyConfig,
        SimpleNamespace(
            http_proxy="http://proxy-no-port.example.com",
            https_proxy=None,
            no_proxy=None,
        ),
    )

    result = jenkins.build_jcasc_config(
        VALID_JCASC_CONFIG,
        proxy_config=proxy,
        auth_proxy=False,
    )

    assert result["jenkins"]["proxy"] == {"name": "proxy-no-port.example.com"}


def test_reconcile_jcasc_config_skips_when_no_config(harness_container: HarnessWithContainer):
    """
    arrange: given charm_state.jcasc_config is None.
    act: when _reconcile_jcasc_config is called.
    assert: admin baseline config is applied and sync_jcasc_config is called.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    charm_state = MagicMock(spec=state.State)
    charm_state.jcasc_config = None
    charm_state.proxy_config = None
    charm_state.auth_proxy_integrated = False

    with patch("jenkins.sync_jcasc_config", return_value="hash123") as sync_mock:
        result = charm._reconcile_jcasc_config(harness_container.container, charm_state)

    assert result == "hash123"
    sync_mock.assert_called_once()
    # Verify the config passed to sync contains admin securityRealm
    called_yaml = sync_mock.call_args[0][1]
    assert "securityRealm" in called_yaml
    assert "admin" in called_yaml


def test_reconcile_jcasc_config_serialization_error_raises_blocked(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given yaml serialization fails.
    act: when _reconcile_jcasc_config is called.
    assert: ReconcileBlockedError is raised.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    charm_state = MagicMock(spec=state.State)
    charm_state.jcasc_config = VALID_JCASC_CONFIG
    charm_state.proxy_config = None
    charm_state.auth_proxy_integrated = False

    with (
        patch("yaml.dump", side_effect=yaml.YAMLError("bad-yaml")),
        pytest.raises(
            ReconcileBlockedError,
            match=r"Failed to serialize JCasC config\.",
        ),
    ):
        charm._reconcile_jcasc_config(harness_container.container, charm_state)


def test_reconcile_jcasc_config_calls_sync_with_rendered_yaml(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given valid state with jcasc_config.
    act: when _reconcile_jcasc_config is called.
    assert: sync_jcasc_config is called with rendered yaml and hash returned.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    charm_state = MagicMock(spec=state.State)
    charm_state.jcasc_config = VALID_JCASC_CONFIG
    charm_state.proxy_config = None
    charm_state.auth_proxy_integrated = False

    with patch("jenkins.sync_jcasc_config") as sync_mock:
        sync_mock.return_value = "hash123"
        result = charm._reconcile_jcasc_config(harness_container.container, charm_state)

    assert result == "hash123"
    sync_mock.assert_called_once()
    call_yaml = sync_mock.call_args.args[1]
    assert "jenkins:" in call_yaml


def test_reconcile_jcasc_config_jenkins_error_raises_blocked(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given sync_jcasc_config raises JenkinsError.
    act: when _reconcile_jcasc_config is called.
    assert: ReconcileBlockedError is raised wrapping the JenkinsError.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)

    charm_state = MagicMock(spec=state.State)
    charm_state.jcasc_config = VALID_JCASC_CONFIG
    charm_state.proxy_config = None
    charm_state.auth_proxy_integrated = False

    with (
        patch(
            "jenkins.sync_jcasc_config",
            side_effect=jenkins.JenkinsError("API unreachable"),
        ),
        pytest.raises(
            ReconcileBlockedError,
            match=r"Failed to sync JCasC configuration\.",
        ),
    ):
        charm._reconcile_jcasc_config(harness_container.container, charm_state)


def test_sync_jcasc_config_no_write_when_unchanged(harness_container: HarnessWithContainer):
    """
    arrange: given container has identical current JCasC config.
    act: when sync_jcasc_config is called.
    assert: push is not called and current hash is returned.
    """
    desired = "jenkins:\n  systemMessage: test\n"
    mock_pull = MagicMock()
    mock_pull.read.return_value = desired

    with (
        patch.object(harness_container.container, "pull", return_value=mock_pull),
        patch.object(harness_container.container, "push") as push_mock,
    ):
        result = jenkins.sync_jcasc_config(harness_container.container, desired)

    assert result == hashlib.sha256(desired.encode("utf-8")).hexdigest()
    push_mock.assert_not_called()


def test_sync_jcasc_config_writes_when_changed(harness_container: HarnessWithContainer):
    """
    arrange: given current config differs from desired config.
    act: when sync_jcasc_config is called.
    assert: push is called with make_dirs=True and hash is returned.
    """
    current = "jenkins:\n  systemMessage: old\n"
    desired = "jenkins:\n  systemMessage: new\n"

    mock_pull = MagicMock()
    mock_pull.read.return_value = current

    with (
        patch.object(harness_container.container, "pull", return_value=mock_pull),
        patch.object(harness_container.container, "push") as push_mock,
    ):
        result = jenkins.sync_jcasc_config(harness_container.container, desired)

    expected_hash = hashlib.sha256(desired.encode("utf-8")).hexdigest()
    assert result == expected_hash
    push_mock.assert_called_once_with(
        str(jenkins.JCASC_CONFIG_PATH),
        desired,
        encoding="utf-8",
        user=jenkins.USER,
        group=jenkins.GROUP,
        make_dirs=True,
    )


def test_sync_jcasc_config_writes_when_file_missing(harness_container: HarnessWithContainer):
    """
    arrange: given current config file is missing.
    act: when sync_jcasc_config is called.
    assert: push is called and hash is returned.
    """
    desired = "jenkins:\n  test: true\n"

    with (
        patch.object(
            harness_container.container,
            "pull",
            side_effect=ops.pebble.PathError(kind="not-found", message="not found"),
        ),
        patch.object(harness_container.container, "push") as push_mock,
    ):
        result = jenkins.sync_jcasc_config(harness_container.container, desired)

    assert result == hashlib.sha256(desired.encode("utf-8")).hexdigest()
    push_mock.assert_called_once()


@pytest.mark.parametrize(
    "jcasc_input",
    [
        pytest.param({"jenkins": None}, id="jenkins-none"),
        pytest.param({}, id="jenkins-missing"),
        pytest.param({"jenkins": {}}, id="jenkins-empty"),
    ],
)
def test_build_jcasc_config_handles_empty_jenkins_section(jcasc_input: dict):
    """
    arrange: given various empty/None jenkins section configurations.
    act: when build_jcasc_config is called.
    assert: no crash and admin securityRealm is injected.
    """
    result = jenkins.build_jcasc_config(jcasc_input, proxy_config=None, auth_proxy=False)

    assert "jenkins" in result
    assert "securityRealm" in result["jenkins"]
    assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "admin"
    assert "disabledAdministrativeMonitors" in result["jenkins"]
