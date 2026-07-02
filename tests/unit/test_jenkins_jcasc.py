# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins JCasC and config-install unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import base64
import re
import secrets
from functools import partial
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import jenkinsapi
import ops
import pytest
import requests

import jenkins

from .helpers import combine_root_paths
from .types_ import HarnessWithContainer


def _failing_container() -> ops.Container:
    """Return container mock failing on push()."""
    mock_container = MagicMock(ops.Container)
    mock_container.push = MagicMock(
        side_effect=ops.pebble.PathError(kind="not-found", message="Path not found.")
    )
    return mock_container


def _stage_workload_clone(harness, container, monkeypatch, files, config_path="jcasc"):
    """Stage YAML files on the workload FS and wire git/find/rm exec handlers.

    Args:
        harness: The ops testing Harness.
        container: The jenkins workload container.
        monkeypatch: pytest monkeypatch fixture.
        files: Mapping of path-relative-to-config_path -> YAML text.
        config_path: Repo subdir/file the charm will read (default "jcasc").

    Returns:
        A dict with the recorded exec calls under keys "git", "find", "rm".
    """
    random_token = secrets.token_hex(8)
    dest = f"/tmp/jcasc-clone-{random_token}"  # nosec: B108 (transient test dir with dynamic suffix)
    base = dest if config_path == "." else f"{dest}/{config_path}"

    jenkins_root = harness.get_filesystem_root("jenkins")
    staged_paths = []
    for rel, body in files.items():
        wpath = f"{base}/{rel}" if rel else base
        fs_path = combine_root_paths(jenkins_root, Path(wpath))
        fs_path.parent.mkdir(parents=True, exist_ok=True)
        fs_path.write_text(body, encoding="utf-8")
        staged_paths.append(wpath)

    calls: dict[str, list[list[str]]] = {"git": [], "find": [], "rm": []}

    def git_handler(argv):
        calls["git"].append(argv)
        return (0, "", "")

    def find_handler(argv):
        calls["find"].append(argv)
        return (0, "".join(f"{p}\n" for p in staged_paths), "")

    def rm_handler(argv):
        calls["rm"].append(argv)
        return (0, "", "")

    for name, handler in (("git", git_handler), ("find", find_handler), ("rm", rm_handler)):
        harness.register_command_handler(  # type: ignore # pylint: disable=no-member
            container=container, executable=name, handler=handler
        )
    return calls


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


def test_fetch_jcasc_repository_clones_and_merges(
    harness_container, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository clones repo and returns merged YAML content."""
    harness_container.harness.begin()
    container = harness_container.container

    files = {"jenkins.yaml": "jenkins:\n  numExecutors: 5\n"}
    calls = _stage_workload_clone(harness_container.harness, container, monkeypatch, files)

    result = jenkins.fetch_jcasc_repository(container, "https://example.com/repo.git", token=None)

    assert "jenkins" in result.lower()
    assert "numExecutors" in result or "5" in result
    # Verify git clone was called (no auth header when token is None)
    assert len(calls["git"]) == 1
    git_cmd = calls["git"][0]
    assert "git" in git_cmd and "clone" in git_cmd


def test_fetch_jcasc_repository_with_token(harness_container, monkeypatch: pytest.MonkeyPatch):
    """fetch_jcasc_repository accepts (username, token) tuple for auth."""
    harness_container.harness.begin()
    container = harness_container.container

    files = {"config.yaml": "jenkins:\n  securityRealm: admin\n"}
    calls = _stage_workload_clone(harness_container.harness, container, monkeypatch, files)

    result = jenkins.fetch_jcasc_repository(
        container, "https://example.com/private.git", token=("git", "ghp_secret")
    )

    assert "jenkins" in result.lower()
    # Verify auth header was set with base64-encoded credentials (not in URL)
    assert len(calls["git"]) == 1
    git_cmd = calls["git"][0]
    assert "-c" in git_cmd
    auth_idx = git_cmd.index("-c") + 1
    # The header should contain Authorization: Basic {base64(git:ghp_secret)}
    expected_creds = base64.b64encode(b"git:ghp_secret").decode("ascii")
    assert f"http.extraHeader=Authorization: Basic {expected_creds}" in git_cmd[auth_idx]
    # Plain token should NOT be in the URL or command
    assert "ghp_secret" not in " ".join(git_cmd)


def test_fetch_jcasc_repository_git_clone_fails(
    harness_container, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository raises JenkinsBootstrapError on git clone failure."""
    harness_container.harness.begin()
    container = harness_container.container

    def git_fail_handler(argv):
        raise ops.pebble.ExecError(
            command=argv, exit_code=1, stdout="", stderr="fatal: authentication failed"
        )

    def rm_handler(argv):
        return (0, "", "")

    monkeypatch.setattr(jenkins.secrets, "token_hex", lambda _n: "deadbeefcafe")

    harness_container.harness.register_command_handler(
        container=container, executable="git", handler=git_fail_handler
    )
    harness_container.harness.register_command_handler(
        container=container, executable="rm", handler=rm_handler
    )

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.fetch_jcasc_repository(container, "https://example.com/repo.git", token=None)


def test_fetch_jcasc_repository_merges_multiple_yaml_files(
    harness_container, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository merges YAML files from repository."""
    harness_container.harness.begin()
    container = harness_container.container

    files = {
        "01-jenkins.yaml": "jenkins:\n  numExecutors: 5\n",
        "02-security.yaml": "jenkins:\n  securityRealm: admin\n",
    }
    _stage_workload_clone(harness_container.harness, container, monkeypatch, files)

    result = jenkins.fetch_jcasc_repository(container, "https://example.com/repo.git", token=None)

    assert isinstance(result, str)
    assert "jenkins" in result.lower()
    # Both config keys should be present (deep merged)
    assert "numExecutors" in result or "5" in result
    assert "securityRealm" in result or "admin" in result


def test_fetch_jcasc_repository_custom_config_path(
    harness_container, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository uses custom config_path parameter."""
    harness_container.harness.begin()
    container = harness_container.container

    files = {"jenkins.yaml": "jenkins:\n  numExecutors: 10\n"}
    calls = _stage_workload_clone(
        harness_container.harness, container, monkeypatch, files, config_path="config"
    )

    result = jenkins.fetch_jcasc_repository(
        container, "https://example.com/repo.git", token=None, config_path="config"
    )

    assert isinstance(result, str)
    assert "jenkins" in result.lower()
    assert "numExecutors" in result or "10" in result
    # Verify find was called with correct path
    assert len(calls["find"]) == 1
    assert "config" in " ".join(calls["find"][0])


def test_fetch_jcasc_repository_config_path_root_directory(
    harness_container, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository loads YAML from root when config_path is '.'."""
    harness_container.harness.begin()
    container = harness_container.container

    files = {"config.yaml": "jenkins:\n  systemMessage: from root\n"}
    _stage_workload_clone(
        harness_container.harness, container, monkeypatch, files, config_path="."
    )

    result = jenkins.fetch_jcasc_repository(
        container, "https://example.com/repo.git", token=None, config_path="."
    )

    assert isinstance(result, str)
    assert "systemMessage" in result or "from root" in result


def test_fetch_jcasc_repository_missing_config_path(
    harness_container, monkeypatch: pytest.MonkeyPatch
):
    """fetch_jcasc_repository raises JenkinsBootstrapError when custom config_path doesn't exist."""
    harness_container.harness.begin()
    container = harness_container.container

    # Stage with no files, so find will return empty
    def find_empty_handler(argv):
        return (0, "", "")

    def git_noop_handler(argv):
        return (0, "", "")

    def rm_noop_handler(argv):
        return (0, "", "")

    harness_container.harness.register_command_handler(
        container=container, executable="git", handler=git_noop_handler
    )
    harness_container.harness.register_command_handler(
        container=container, executable="find", handler=find_empty_handler
    )
    harness_container.harness.register_command_handler(
        container=container, executable="rm", handler=rm_noop_handler
    )
    monkeypatch.setattr(jenkins.secrets, "token_hex", lambda _n: "deadbeefcafe")

    with pytest.raises(jenkins.JenkinsBootstrapError):
        jenkins.fetch_jcasc_repository(
            container, "https://example.com/repo.git", token=None, config_path="nonexistent"
        )


@pytest.mark.parametrize(
    "config_path,files",
    [
        ("jcasc", {"jenkins.yaml": "jenkins:\n  systemMessage: test\n"}),
        ("jenkins.yaml", {"jenkins.yaml": "jenkins:\n  systemMessage: test\n"}),
    ],
    ids=["directory_with_yaml_files", "single_yaml_file"],
)
def test_fetch_jcasc_repository_config_path_types(
    harness_container, monkeypatch: pytest.MonkeyPatch, config_path: str, files: dict
):
    """fetch_jcasc_repository handles both directory and single file config paths."""
    harness_container.harness.begin()
    container = harness_container.container

    _stage_workload_clone(
        harness_container.harness, container, monkeypatch, files, config_path=config_path
    )

    result = jenkins.fetch_jcasc_repository(
        container, "https://example.com/repo.git", token=None, config_path=config_path
    )

    assert isinstance(result, str)
    assert "jenkins" in result.lower()
    assert "jenkins:" in result
    assert "systemMessage: test" in result
