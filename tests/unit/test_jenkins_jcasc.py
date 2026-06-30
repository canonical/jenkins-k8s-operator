# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins JCasC and config-install unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import re

# subprocess module is used in git clone, imported to patch with mocks in tests
import subprocess  # nosec: B404
import tempfile
from functools import partial
from typing import Callable
from unittest.mock import MagicMock

import jenkinsapi
import ops
import pytest
import requests

import jenkins

from .types_ import HarnessWithContainer


def _failing_container() -> ops.Container:
    """Return container mock failing on push()."""
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )
    return mock_container


def _mock_tempdir(tmp_path):
    """Factory for mock TemporaryDirectory context manager.

    Args:
        tmp_path: pytest tmp_path fixture

    Returns:
        Callable returning context manager that yields tmp_path string.
    """

    def factory():
        class MockTempDir:
            def __enter__(self):
                return str(tmp_path)

            def __exit__(self, *args):
                pass

        return MockTempDir()

    return factory


def _mock_subprocess_run(returncode: int = 0, stderr: str = ""):
    """Factory for mock subprocess.run function.

    Args:
        returncode: Exit code to return
        stderr: Error message to return

    Returns:
        Mock function that records call args and returns configured result.
    """

    def mock_run(*args, **kwargs):
        return MagicMock(returncode=returncode, stderr=stderr)

    return mock_run


def test__unlock_wizard(
    harness_container: HarnessWithContainer,
    mocked_get_request,
    monkeypatch: pytest.MonkeyPatch,
    jenkins_version: str,
):
    """unlock_wizard writes both wizard bypass version files."""
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))

    jenkins.unlock_wizard(harness_container.container, jenkins_version)

    assert (
        harness_container.container.pull(jenkins.LAST_EXEC_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )
    assert (
        harness_container.container.pull(jenkins.WIZARD_VERSION_PATH, encoding="utf-8").read()
        == jenkins_version
    )


def test__unlock_wizard_raises_exception(
    mocked_get_request,
    monkeypatch: pytest.MonkeyPatch,
):
    """unlock_wizard raises JenkinsError on container push failure."""
    monkeypatch.setattr(requests, "get", partial(mocked_get_request, status_code=403))

    with pytest.raises(jenkins.JenkinsError):
        jenkins.unlock_wizard(_failing_container(), "2.401.1")


def test_install_config(harness_container: HarnessWithContainer):
    """_install_configs writes Jenkins config file with default JNLP port."""
    jenkins._install_configs(harness_container.container, jenkins.DEFAULT_JENKINS_CONFIG)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )

    jnlp_match = re.search(r"<slaveAgentPort>(\d+)</slaveAgentPort>", config_xml)
    assert jnlp_match, "Configuration for jnlp port not found."
    assert jnlp_match.group(1) == "50000", "jnlp not set as default port."


@pytest.mark.parametrize(
    "installer, expected_security_snippet",
    [
        pytest.param(
            jenkins.install_auth_proxy_config,
            "<useSecurity>false</useSecurity>",
            id="auth-proxy-config",
        ),
        pytest.param(
            jenkins.install_default_config,
            "<useSecurity>true</useSecurity>",
            id="default-config",
        ),
    ],
)
def test_install_security_configs(
    harness_container: HarnessWithContainer,
    installer: Callable[[ops.Container], None],
    expected_security_snippet: str,
):
    """Security config installers write expected <useSecurity> value."""
    installer(harness_container.container)

    config_xml = str(
        harness_container.container.pull(jenkins.CONFIG_FILE_PATH, encoding="utf-8").read()
    )
    assert expected_security_snippet in config_xml


@pytest.mark.parametrize(
    "installer, install_args",
    [
        pytest.param(
            jenkins._install_configs,
            (jenkins.DEFAULT_JENKINS_CONFIG,),
            id="install-config",
        ),
        pytest.param(jenkins.install_auth_proxy_config, (), id="install-auth-proxy-config"),
        pytest.param(jenkins.install_default_config, (), id="install-default-config"),
    ],
)
def test_installers_raise_bootstrap_error_on_write_failure(
    installer: Callable[..., None],
    install_args: tuple,
):
    """Config installers raise JenkinsBootstrapError when container push fails."""
    with pytest.raises(jenkins.JenkinsBootstrapError):
        installer(_failing_container(), *install_args)


def test__set_jenkins_system_message_error(mock_client: MagicMock):
    """_set_jenkins_system_message raises JenkinsError on groovy API failure."""
    mock_client.run_groovy_script.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException

    with pytest.raises(jenkins.JenkinsError):
        jenkins._set_jenkins_system_message("test", mock_client)


def test__set_jenkins_system_message(mock_client: MagicMock):
    """_set_jenkins_system_message sends groovy script to client."""
    message = "hello world!"
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    jenkins._set_jenkins_system_message(message, mock_client)

    mock_groovy_script.assert_called()


def test_install_plugins_executes_plugin_manager_command():
    """install_plugins invokes jenkins plugin manager with expected command layout."""
    mock_container = MagicMock(spec=ops.Container)
    mock_process = MagicMock(spec=ops.pebble.ExecProcess)
    mock_process.wait_output.return_value = ("Done", "")
    mock_container.exec.return_value = mock_process

    jenkins.install_plugins(mock_container, ["plugin-a", "plugin-b"])

    executed_command = mock_container.exec.call_args.args[0]
    assert executed_command[0] == "java"
    assert "-jar" in executed_command
    assert (
        f"jenkins-plugin-manager-{jenkins.JENKINS_PLUGIN_MANAGER_VERSION}.jar" in executed_command
    )
    assert "--latest" in executed_command
    plugins_arg = executed_command[executed_command.index("-p") + 1]
    assert set(plugins_arg.split(" ")) == {"plugin-a", "plugin-b"}


def test_install_plugins_raises_bootstrap_error_on_exec_failure():
    """install_plugins raises JenkinsBootstrapError when command execution fails."""
    mock_container = MagicMock(spec=ops.Container)
    mock_process = MagicMock(spec=ops.pebble.ExecProcess)
    mock_process.wait_output.side_effect = ops.pebble.ExecError(
        command=["java"],
        exit_code=1,
        stdout="",
        stderr="failed",
    )
    mock_container.exec.return_value = mock_process

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.install_plugins(mock_container, ["plugin-a"])


def test_get_java_proxy_args_with_auth_and_no_proxy(proxy_config):
    """_get_java_proxy_args renders JVM flags for authenticated proxy with no_proxy list."""
    args = tuple(jenkins._get_java_proxy_args(proxy_config))

    assert any(flag.startswith("-Dhttp.proxyUser=") for flag in args)
    assert any(flag.startswith("-Dhttp.proxyPassword=") for flag in args)
    assert any(flag.startswith("-Dhttps.proxyUser=") for flag in args)
    assert any(flag.startswith("-Dhttps.proxyPassword=") for flag in args)
    assert any(flag.startswith("-Dhttp.nonProxyHosts=") for flag in args)


def test_get_java_proxy_args_without_credentials_omits_auth_flags(partial_proxy_config):
    """_get_java_proxy_args omits user/password flags when proxy credentials are absent."""
    args = tuple(jenkins._get_java_proxy_args(partial_proxy_config))

    assert not any(flag.startswith("-Dhttp.proxyUser=") for flag in args)
    assert not any(flag.startswith("-Dhttp.proxyPassword=") for flag in args)
    assert not any(flag.startswith("-Dhttps.proxyUser=") for flag in args)
    assert not any(flag.startswith("-Dhttps.proxyPassword=") for flag in args)


def test_get_groovy_proxy_args_uses_https_proxy_first(proxy_config):
    """_get_groovy_proxy_args prefers https proxy values when both proxies are present."""
    args = tuple(jenkins._get_groovy_proxy_args(proxy_config))

    assert args[0] == f"'{proxy_config.https_proxy.host}'"
    assert args[1] == f"{proxy_config.https_proxy.port}"
    assert args[2] == f"'{proxy_config.https_proxy.user}'"
    assert args[3] == f"'{proxy_config.https_proxy.password}'"
    assert args[4] == f"'{proxy_config.no_proxy}'"


def test_get_groovy_proxy_args_http_fallback_without_https(http_partial_proxy_config):
    """_get_groovy_proxy_args falls back to http proxy when https proxy is absent."""
    args = tuple(jenkins._get_groovy_proxy_args(http_partial_proxy_config))

    assert args == (
        f"'{http_partial_proxy_config.http_proxy.host}'",
        f"{http_partial_proxy_config.http_proxy.port}",
        "''",
        "''",
    )


def test_fetch_jcasc_repository_clones_and_merges(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """fetch_jcasc_repository clones repo and returns merged YAML content."""
    # Create fake repo structure with YAML file
    repo_dir = tmp_path / "repo"
    jcasc_dir = repo_dir / "jcasc"
    jcasc_dir.mkdir(parents=True)

    yaml_file = jcasc_dir / "jenkins.yaml"
    yaml_file.write_text("jenkins:\n  numExecutors: 5\n", encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run())
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    result = jenkins.fetch_jcasc_repository("https://example.com/repo.git", token=None)

    assert "jenkins" in result.lower()
    assert "numExecutors" in result or "5" in result


def test_fetch_jcasc_repository_with_token(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """fetch_jcasc_repository accepts (username, token) tuple for auth."""
    # Create fake repo structure
    repo_dir = tmp_path / "repo"
    jcasc_dir = repo_dir / "jcasc"
    jcasc_dir.mkdir(parents=True)

    yaml_file = jcasc_dir / "config.yaml"
    yaml_file.write_text("jenkins:\n  securityRealm: admin\n", encoding="utf-8")

    # Track if auth URL was used
    auth_url_used = []

    def mock_run_with_auth(*args, **kwargs):
        # args is [["git", "clone", "--depth", "1", URL, dest], ...]
        if isinstance(args[0], list) and len(args[0]) >= 5:
            # URL is at index 4
            auth_url_used.append(args[0][4])
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run_with_auth)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    jenkins.fetch_jcasc_repository("https://example.com/private.git", token=("git", "ghp_secret"))

    # Verify token was used in URL
    assert len(auth_url_used) > 0
    assert "git:ghp_secret" in auth_url_used[0]


def test_fetch_jcasc_repository_git_clone_fails(monkeypatch: pytest.MonkeyPatch):
    """fetch_jcasc_repository raises JenkinsBootstrapError on git clone failure."""
    monkeypatch.setattr(
        subprocess,
        "run",
        _mock_subprocess_run(returncode=1, stderr="fatal: authentication failed"),
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.fetch_jcasc_repository("https://example.com/repo.git", token=None)


def test_fetch_jcasc_repository_merges_multiple_yaml_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository merges YAML files from repository."""
    # Create multiple YAML files in repo
    repo_dir = tmp_path / "repo"
    jcasc_dir = repo_dir / "jcasc"
    jcasc_dir.mkdir(parents=True)

    # Create multiple YAML files
    (jcasc_dir / "01-jenkins.yaml").write_text("jenkins:\n  numExecutors: 5\n", encoding="utf-8")
    (jcasc_dir / "02-security.yaml").write_text(
        "jenkins:\n  securityRealm: admin\n", encoding="utf-8"
    )

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run())
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    result = jenkins.fetch_jcasc_repository("https://example.com/repo.git", token=None)

    assert isinstance(result, str)
    assert "jenkins" in result.lower()
    # Both config keys should be present
    assert "numExecutors" in result or "5" in result
    assert "securityRealm" in result or "admin" in result


def test_fetch_jcasc_repository_custom_config_path(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """fetch_jcasc_repository uses custom config_path parameter."""
    # Create repo structure with custom config directory
    repo_dir = tmp_path / "repo"
    config_dir = repo_dir / "config"
    config_dir.mkdir(parents=True)

    # Create YAML in custom directory
    (config_dir / "jenkins.yaml").write_text("jenkins:\n  numExecutors: 10\n", encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run())
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    result = jenkins.fetch_jcasc_repository(
        "https://example.com/repo.git", token=None, config_path="config"
    )

    assert isinstance(result, str)
    assert "jenkins" in result.lower()
    assert "numExecutors" in result or "10" in result


def test_fetch_jcasc_repository_config_path_root_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository loads YAML from root when config_path is '.'."""
    # Create YAML files in repo root
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)

    (repo_dir / "config.yaml").write_text(
        "jenkins:\n  systemMessage: from root\n", encoding="utf-8"
    )

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run())
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    result = jenkins.fetch_jcasc_repository(
        "https://example.com/repo.git", token=None, config_path="."
    )

    assert isinstance(result, str)
    assert "systemMessage" in result or "from root" in result


def test_fetch_jcasc_repository_missing_config_path(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """fetch_jcasc_repository raises JenkinsBootstrapError when custom config_path doesn't exist."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run())
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.fetch_jcasc_repository(
            "https://example.com/repo.git", token=None, config_path="nonexistent"
        )


@pytest.mark.parametrize(
    "config_path,setup_func",
    [
        (
            "jcasc",
            lambda p: (p / "jcasc").mkdir()
            or (p / "jcasc" / "jenkins.yaml").write_text("jenkins:\n  systemMessage: test"),
        ),
        (
            "jenkins.yaml",
            lambda p: (p / "jenkins.yaml").write_text("jenkins:\n  systemMessage: test"),
        ),
    ],
    ids=["directory_with_yaml_files", "single_yaml_file"],
)
def test_fetch_jcasc_repository_config_path_types(
    tmp_path, monkeypatch: pytest.MonkeyPatch, config_path: str, setup_func: Callable
):
    """fetch_jcasc_repository handles both directory and single file config paths."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)

    setup_func(repo_dir)

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run())
    monkeypatch.setattr(tempfile, "TemporaryDirectory", _mock_tempdir(tmp_path))

    result = jenkins.fetch_jcasc_repository(
        "https://example.com/repo.git", token=None, config_path=config_path
    )

    assert isinstance(result, str)
    assert "jenkins" in result.lower()
    assert "jenkins:" in result
    assert "systemMessage: test" in result
