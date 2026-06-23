# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s jenkins plugins unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access,too-many-lines

import textwrap
import typing
from unittest.mock import MagicMock, patch

import jenkinsapi
import ops
import pytest

import jenkins


def _jenkins_instance(container: ops.Container) -> jenkins.Jenkins:
    """Create Jenkins client wrapper for tests."""
    return jenkins.Jenkins("/", "admin-password", container)


@pytest.mark.parametrize(
    "plugin_str",
    [
        pytest.param("", id="empty plugin name"),
        pytest.param(";;", id="invalid character"),
        pytest.param("too many whitespaces", id="too many whitespaces"),
        pytest.param("no-plugin-version", id="no version"),
        pytest.param("invalid-plugin-version", id="invalid version"),
    ],
)
def test__get_plugin_name_fail(plugin_str: str):
    """_get_plugin_name raises ValidationError for invalid plugin format."""
    with pytest.raises(jenkins.ValidationError):
        jenkins._get_plugin_name(plugin_str)


@pytest.mark.parametrize(
    "plugin_str, expected_name",
    [
        pytest.param("test-plugin (0.1.2)", "test-plugin", id="standard plugin string"),
        pytest.param(
            "test-plugin (any version string is ok)",
            "test-plugin",
            id="non-standard plugin version",
        ),
    ],
)
def test__get_plugin_name(plugin_str: str, expected_name: str):
    """_get_plugin_name extracts plugin short name."""
    assert jenkins._get_plugin_name(plugin_str) == expected_name


@pytest.mark.parametrize(
    "dependency_strs, expected_lookup",
    [
        pytest.param(
            [
                "plugin-a (v0.0.1) => [plugin-b (v0.0.1), plugin-c (v0.0.1)]",
                "plugin-b (v0.0.2) => [plugin-d (v0.0.1)]",
                "plugin-c (v0.0.3) => []",
                "plugin-d (v0.0.4) => []",
            ],
            {
                "plugin-a": ("plugin-b", "plugin-c"),
                "plugin-b": ("plugin-d",),
                "plugin-c": (),
                "plugin-d": (),
            },
            id="valid plugins",
        ),
        pytest.param(
            [
                "plugin-a (v0.0.1) => [plugin-b (v0.0.1), plugin-c (v0.0.1)]",
                "plugin-b (v0.0.2) => [plugin-d (v0.0.1)]",
                "plugin-c (v0.0.3) => []",
                "plugin-d (v0.0.4) => []",
                "skip-invalid-groovy-script-output",
                "invalid-deps (v0.0.01) => [invalid-dep]",
            ],
            {
                "plugin-a": ("plugin-b", "plugin-c"),
                "plugin-b": ("plugin-d",),
                "plugin-c": (),
                "plugin-d": (),
            },
            id="invalid plugin lines skipped",
        ),
    ],
)
def test__build_dependencies_lookup(
    dependency_strs: typing.Iterable[str],
    expected_lookup: typing.Mapping[str, typing.Iterable[str]],
):
    """_build_dependencies_lookup parses plugin/dependency map from groovy lines."""
    assert jenkins._build_dependencies_lookup(dependency_strs) == expected_lookup


@pytest.mark.parametrize(
    "top_level_plugins, plugins_lookup, expected_allowed_plugins",
    [
        pytest.param((), {}, (), id="all empty"),
        pytest.param(("plugin-a",), {}, ("plugin-a",), id="single top level, no lookup"),
        pytest.param(
            ("plugin-a",),
            {"plugin-b": ()},
            ("plugin-a",),
            id="single top level, different lookup",
        ),
        pytest.param(
            ("plugin-a",),
            {"plugin-a": ()},
            ("plugin-a",),
            id="single top level, lookup with no dependencies",
        ),
        pytest.param(
            ("plugin-a",),
            {"plugin-a": ("plugin-a-a",), "plugin-a-a": ()},
            ("plugin-a", "plugin-a-a"),
            id="single top level, lookup with one dependency",
        ),
        pytest.param(
            ("plugin-a",),
            {
                "plugin-a": ("plugin-a-a",),
                "plugin-a-a": ("plugin-a-a-a",),
                "plugin-a-a-a": (),
            },
            ("plugin-a", "plugin-a-a", "plugin-a-a-a"),
            id="single top level, lookup with one nested dependency",
        ),
        pytest.param(
            ("plugin-a",),
            {
                "plugin-a": ("plugin-a-a", "plugin-a-b"),
                "plugin-a-a": (),
                "plugin-a-b": (),
            },
            ("plugin-a", "plugin-a-a", "plugin-a-b"),
            id="single top level, lookup with multiple dependencies",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {"plugin-a": (), "plugin-b": ()},
            ("plugin-a", "plugin-b"),
            id="two top levels, no dependencies",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {"plugin-a": ("plugin-a-a",), "plugin-b": (), "plugin-a-a": ()},
            ("plugin-a", "plugin-a-a", "plugin-b"),
            id="two top levels, plugin-a dependency exists",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {"plugin-a": (), "plugin-b": ("plugin-b-a",), "plugin-b-a": ()},
            ("plugin-a", "plugin-b", "plugin-b-a"),
            id="two top levels, plugin-b dependency exists",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("plugin-a-a",),
                "plugin-a-a": (),
                "plugin-b": ("plugin-b-a",),
                "plugin-b-a": (),
            },
            ("plugin-a", "plugin-a-a", "plugin-b", "plugin-b-a"),
            id="two top levels, both have single dependency",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("shared",),
                "plugin-b": ("shared",),
                "shared": (),
            },
            ("plugin-a", "shared", "plugin-b"),
            id="two top levels, both share a dependency",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("plugin-a-a", "plugin-a-b"),
                "plugin-b": ("plugin-b-a", "plugin-b-b"),
                "plugin-a-a": (),
                "plugin-a-b": (),
                "plugin-b-a": (),
                "plugin-b-b": (),
            },
            (
                "plugin-a",
                "plugin-a-a",
                "plugin-a-b",
                "plugin-b",
                "plugin-b-a",
                "plugin-b-b",
            ),
            id="two top levels, both have multiple dependencies",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("plugin-a-a", "shared"),
                "plugin-b": ("plugin-b-a", "shared"),
                "plugin-a-a": (),
                "plugin-b-a": (),
                "shared": (),
            },
            ("plugin-a", "plugin-a-a", "shared", "plugin-b", "plugin-b-a"),
            id="two top levels, both have multiple dependencies, single shared",
        ),
        pytest.param(
            ("plugin-a", "plugin-b"),
            {
                "plugin-a": ("shared-a", "shared-b"),
                "plugin-b": ("shared-a", "shared-b"),
                "shared-a": (),
                "shared-b": (),
            },
            ("plugin-a", "shared-a", "shared-b", "plugin-b"),
            id="two top levels, both have multiple dependencies, both shared",
        ),
    ],
)
def test__get_allowed_plugins(
    top_level_plugins: typing.Iterable[str],
    plugins_lookup: typing.Mapping[str, typing.Iterable[str]],
    expected_allowed_plugins: tuple[str, ...],
):
    """_get_allowed_plugins includes top-level plugins and dependencies recursively."""
    allowed_plugins = jenkins._get_allowed_plugins(top_level_plugins, plugins_lookup)
    assert tuple(allowed_plugins) == expected_allowed_plugins


@pytest.mark.parametrize(
    "all_plugins, plugins_lookup, expected_top_level_plugins",
    [
        pytest.param(
            ("plugin-a", "dep-a-a", "dep-a-b", "plugin-b", "dep-b-a", "dep-b-b"),
            {
                "plugin-a": ("dep-a-a", "dep-a-b"),
                "plugin-b": ("dep-b-a", "dep-b-b"),
                "dep-a-a": ("dep-a-b",),
                "dep-a-b": (),
                "dep-b-a": ("dep-b-b",),
                "dep-b-b": (),
            },
            {"plugin-a", "plugin-b"},
            id="plugins a, b",
        ),
    ],
)
def test__get_top_level_plugins(
    all_plugins: typing.Iterable[str],
    plugins_lookup: typing.Mapping[str, typing.Iterable[str]],
    expected_top_level_plugins: set[str],
):
    """_filter_dependent_plugins returns only non-dependent top-level plugins."""
    top_level_plugins = jenkins._filter_dependent_plugins(all_plugins, plugins_lookup)
    assert top_level_plugins == expected_top_level_plugins


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


def test__plugin_temporary_files_exist():
    """_plugin_temporary_files_exist detects pending *.tmp plugin files."""
    mock_container = MagicMock(spec=ops.Container)
    mock_container.list_files.return_value = [MagicMock(spec=ops.pebble.FileInfo)]

    assert jenkins._plugin_temporary_files_exist(container=mock_container)


def test_remove_unlisted_plugins_wait_plugins_install_timeout(
    monkeypatch: pytest.MonkeyPatch,
    container: ops.Container,
):
    """remove_unlisted_plugins raises JenkinsPluginError when plugin install wait times out."""
    monkeypatch.setattr(jenkins, "_wait_plugins_install", MagicMock(side_effect=TimeoutError))

    with pytest.raises(jenkins.JenkinsPluginError):
        _jenkins_instance(container).remove_unlisted_plugins(("plugin-a", "plugin-b"), container)


def test_remove_unlisted_plugins_delete_error(
    mock_client: MagicMock,
    container: ops.Container,
    plugin_groovy_script_result: str,
):
    """remove_unlisted_plugins raises JenkinsPluginError when delete_plugins fails."""
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    mock_groovy_script.return_value = plugin_groovy_script_result
    mock_client.delete_plugins.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()

    with (
        patch.object(jenkins.Jenkins, "safe_restart"),
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
        pytest.raises(jenkins.JenkinsPluginError),
    ):
        _jenkins_instance(container).remove_unlisted_plugins(("plugin-a", "plugin-b"), container)


@pytest.mark.parametrize(
    "expected_exception",
    [
        pytest.param(jenkins.JenkinsError, id="JenkinsError"),
        pytest.param(TimeoutError, id="TimeoutError"),
    ],
)
def test_remove_unlisted_plugins_restart_error(
    mock_client: MagicMock,
    container: ops.Container,
    plugin_groovy_script_result: str,
    expected_exception: type[Exception],
):
    """remove_unlisted_plugins re-raises restart-related errors."""
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    mock_groovy_script.return_value = plugin_groovy_script_result

    with (
        patch.object(jenkins.Jenkins, "safe_restart") as safe_restart_mock,
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
    ):
        safe_restart_mock.side_effect = expected_exception
        with pytest.raises(expected_exception):
            _jenkins_instance(container).remove_unlisted_plugins(
                ("plugin-a", "plugin-b"), container
            )


@pytest.mark.parametrize(
    "desired_plugins, groovy_script_output, expected_delete_plugins",
    [
        pytest.param(
            ("plugin-a", "plugin-b"),
            textwrap.dedent("""
                plugin-a (v0.0.1) => [dep-a-a (v0.0.1), dep-a-b (v0.0.1)]
                plugin-b (v0.0.2) => [dep-b-a (v0.0.2), dep-b-b (v0.0.2)]
                plugin-c (v0.0.5) => []
                dep-a-a (v0.0.3) => []
                dep-a-b (v0.0.3) => []
                dep-b-a (v0.0.4) => []
                dep-b-b (v0.0.4) => []
                Result: [Plugin:plugin-a, Plugin:plugin-b, Plugin:dep-a-a, \
                    Plugin:dep-a-b, Plugin:dep-b-a, Plugin:dep-b-b]
                """),
            {"plugin-c"},
            id="plugin-c not expected",
        ),
        pytest.param(
            ("plugin-a", "plugin-b", "plugin-c"),
            textwrap.dedent("""
                plugin-a (v0.0.1) => [dep-a-a (v0.0.1), dep-a-b (v0.0.1)]
                plugin-b (v0.0.2) => [dep-b-a (v0.0.2), dep-b-b (v0.0.2)]
                plugin-c (v0.0.5) => []
                dep-a-a (v0.0.3) => []
                dep-a-b (v0.0.3) => []
                dep-b-a (v0.0.4) => []
                dep-b-b (v0.0.4) => []
                Result: [Plugin:plugin-a, Plugin:plugin-b, Plugin:dep-a-a, \
                    Plugin:dep-a-b, Plugin:dep-b-a, Plugin:dep-b-b]
                """),
            set(),
            id="no undesired plugins",
        ),
        pytest.param(
            ("plugin-a", "plugin-b", "plugin-c"),
            "Result: []",
            set(),
            id="no plugins installed",
        ),
        pytest.param(
            (),
            "",
            set(),
            id="plugins config not set (all allowed)",
        ),
    ],
)
def test_remove_unlisted_plugins(
    mock_client: MagicMock,
    container: ops.Container,
    desired_plugins: tuple[str, ...],
    groovy_script_output: str,
    expected_delete_plugins: set[str],
):
    """remove_unlisted_plugins deletes only plugins outside desired set+deps."""
    mock_client.run_groovy_script = (
        mock_groovy_script := MagicMock(spec=jenkinsapi.jenkins.Jenkins.run_groovy_script)
    )
    mock_groovy_script.return_value = groovy_script_output

    with (
        patch.object(jenkins.Jenkins, "safe_restart"),
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client),
    ):
        _jenkins_instance(container).remove_unlisted_plugins(desired_plugins, container)

        if expected_delete_plugins:
            mock_client.delete_plugins.assert_called_once_with(
                plugin_list=expected_delete_plugins, restart=False
            )
        else:
            mock_client.delete_plugins.assert_not_called()
