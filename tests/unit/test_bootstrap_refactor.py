# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for Jenkins bootstrap refactor helpers."""

from unittest.mock import MagicMock, patch

import jenkinsapi.jenkins
import ops
import pytest

import jenkins
import pebble
import state

from .types_ import HarnessWithContainer


def test_store_admin_password_creates_secret_when_missing():
    """
    arrange: given no existing admin credentials secret.
    act: when storing the admin password.
    assert: a labelled application secret is created.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_charm.model.get_secret.side_effect = ops.model.SecretNotFoundError

    state.store_admin_password(mock_charm, "password")

    mock_charm.app.add_secret.assert_called_once_with(
        {"admin-password": "password"}, label=state.SECRET_LABEL
    )


def test_store_admin_password_updates_existing_secret():
    """
    arrange: given an existing admin credentials secret with token content.
    act: when storing the admin password.
    assert: the existing secret content is preserved and updated.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    secret = mock_charm.model.get_secret.return_value
    secret.get_content.return_value = {"admin-token": "token"}

    state.store_admin_password(mock_charm, "password")

    secret.set_content.assert_called_once_with(
        {"admin-token": "token", "admin-password": "password"}
    )


def test_get_stored_admin_password_returns_none_when_missing():
    """
    arrange: given no existing admin credentials secret.
    act: when retrieving the stored admin password.
    assert: None is returned.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_charm.model.get_secret.side_effect = ops.model.SecretNotFoundError

    assert state.get_stored_admin_password(mock_charm) is None


def test_get_stored_admin_password_falls_back_to_legacy_password_file(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given no existing admin credentials secret and a legacy password file.
    act: when retrieving the stored admin password.
    assert: the password is read from the legacy workload file.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_charm.model.get_secret.side_effect = ops.model.SecretNotFoundError

    assert state.get_stored_admin_password(
        mock_charm, harness_container.container
    ) == harness_container.container.pull(
        jenkins.PASSWORD_FILE_PATH, encoding="utf-8"
    ).read().strip()


def test_store_admin_token_updates_existing_secret():
    """
    arrange: given an existing admin credentials secret with password content.
    act: when storing the admin token.
    assert: the existing secret content is preserved and updated.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    secret = mock_charm.model.get_secret.return_value
    secret.get_content.return_value = {"admin-password": "password"}

    state.store_admin_token(mock_charm, "token")

    secret.set_content.assert_called_once_with(
        {"admin-password": "password", "admin-token": "token"}
    )


def test_replan_jenkins_only_applies_layer(harness_container: HarnessWithContainer):
    """
    arrange: given a ready container and valid charm state.
    act: when the Jenkins pebble layer is replanned.
    assert: only layer application and replan happen; bootstrap is not called.
    """
    harness = harness_container.harness
    harness.begin()
    env = jenkins.Environment(
        JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
        JENKINS_PREFIX="/",
    )

    with (
        patch.object(jenkins, "install_logging_config") as install_logging_config_mock,
        patch.object(jenkins.Jenkins, "wait_ready") as wait_ready_mock,
        patch.object(jenkins.Jenkins, "bootstrap") as bootstrap_mock,
        patch.object(harness_container.container, "add_layer") as add_layer_mock,
        patch.object(harness_container.container, "replan") as replan_mock,
    ):
        pebble.replan_jenkins(
            harness_container.container,
            jenkins.Jenkins(env),
            state.State.from_charm(harness.charm),
        )

    install_logging_config_mock.assert_called_once_with(container=harness_container.container)
    add_layer_mock.assert_called_once()
    replan_mock.assert_called_once_with()
    wait_ready_mock.assert_not_called()
    bootstrap_mock.assert_not_called()


def test_get_jenkins_version():
    """
    arrange: given a container whose Java command returns a Jenkins version.
    act: when get_jenkins_version is called.
    assert: the stripped WAR version output is returned.
    """
    container = MagicMock(spec=ops.Container)
    process = container.exec.return_value
    process.wait_output.return_value = ("2.401.1\n", "")

    assert pebble.get_jenkins_version(container) == "2.401.1"
    container.exec.assert_called_once_with(
        ["java", "-jar", str(pebble.JENKINS_WAR_PATH), "--version"], timeout=30
    )


def test_unlock_wizard_skips_when_state_matches(harness_container: HarnessWithContainer):
    """
    arrange: given an existing wizard state file containing the Jenkins version.
    act: when unlock_wizard is called.
    assert: the file is not rewritten.
    """
    harness_container.container.push(
        jenkins.WIZARD_STATE_FILE,
        "2.401.1",
        make_dirs=True,
        user=jenkins.USER,
        group=jenkins.GROUP,
    )
    with patch.object(harness_container.container, "push") as push_mock:
        jenkins.unlock_wizard(harness_container.container, "2.401.1")

    push_mock.assert_not_called()


def test_prepare_admin_user_creates_password_and_groovy(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given no stored password and no admin init Groovy script.
    act: when prepare_admin_user is called.
    assert: a generated password is stored and written into the Groovy script.
    """
    harness_container.harness.begin()
    with (
        patch("state.get_stored_admin_password", return_value=None),
        patch("state.generate_admin_password", return_value="generated-password"),
        patch("state.store_admin_password") as store_password_mock,
    ):
        password = jenkins.prepare_admin_user(
            harness_container.container, harness_container.harness.charm
        )

    assert password == "generated-password"
    store_password_mock.assert_called_once_with(harness_container.harness.charm, "generated-password")
    script = harness_container.container.pull(
        jenkins.INIT_GROOVY_PATH / "01-create-admin.groovy", encoding="utf-8"
    ).read()
    assert 'securityRealm.createAccount("admin", "generated-password")' in script


def test_install_plugins_if_missing_skips_when_plugins_present(harness_container: HarnessWithContainer):
    """
    arrange: given all required plugins already present in the plugins directory.
    act: when install_plugins_if_missing is called.
    assert: the plugin manager is not executed.
    """
    for plugin in jenkins.REQUIRED_PLUGINS:
        harness_container.container.push(jenkins.PLUGINS_PATH / f"{plugin}.jpi", "", make_dirs=True)

    with patch.object(harness_container.container, "exec") as exec_mock:
        jenkins.install_plugins_if_missing(
            harness_container.container, MagicMock(proxy_config=None)
        )

    exec_mock.assert_not_called()


def test_setup_user_token_if_missing_stores_generated_token():
    """
    arrange: given no stored token and a Jenkins API client that generates a token.
    act: when setup_user_token_if_missing is called.
    assert: the generated token is stored in Juju secrets.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_client = MagicMock(spec=jenkinsapi.jenkins.Jenkins)
    mock_client.generate_new_api_token.return_value = "generated-token"

    with (
        patch("state.get_stored_admin_token", return_value=None),
        patch("jenkinsapi.jenkins.Jenkins", return_value=mock_client) as client_mock,
        patch("state.store_admin_token") as store_token_mock,
    ):
        jenkins.setup_user_token_if_missing(
            mock_charm, "http://localhost:8080", "admin-password"
        )

    client_mock.assert_called_once_with(
        baseurl="http://localhost:8080",
        username=jenkins.ADMIN_USERNAME,
        password="admin-password",
        timeout=60,
    )
    store_token_mock.assert_called_once_with(mock_charm, "generated-token")


def test_cleanup_init_groovy_removes_script_when_token_exists(harness_container: HarnessWithContainer):
    """
    arrange: given a stored token and an existing admin init Groovy script.
    act: when cleanup_init_groovy is called.
    assert: the init Groovy script is removed.
    """
    harness_container.harness.begin()
    path = jenkins.INIT_GROOVY_PATH / "01-create-admin.groovy"
    harness_container.container.push(path, "script", make_dirs=True)

    with patch("state.get_stored_admin_token", return_value="token"):
        jenkins.cleanup_init_groovy(harness_container.container, harness_container.harness.charm)

    with pytest.raises(ops.pebble.PathError):
        harness_container.container.pull(path)
