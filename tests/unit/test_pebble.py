# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the pebble module."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import ops
import pytest

import jenkins
import pebble


@pytest.mark.parametrize(
    "prefix, system_properties, expected_present, expected_absent",
    [
        pytest.param(
            "/jenkins",
            [],
            [
                f"-D{jenkins.SYSTEM_PROPERTY_HEADLESS}",
                f"-D{jenkins.SYSTEM_PROPERTY_LOGGING}",
                f"-jar {jenkins.EXECUTABLES_PATH}/jenkins.war",
                "--prefix=/jenkins",
            ],
            [],
            id="required-java-flags-and-prefix",
        ),
        pytest.param(
            "",
            ["-Dfoo=bar", "-Dbaz=qux"],
            ["-Dfoo=bar", "-Dbaz=qux", "--prefix="],
            [],
            id="system-properties-present",
        ),
        pytest.param(
            "",
            [],
            ["--prefix="],
            ["  -XX:MaxRAMPercentage=50.0"],
            id="no-extra-space-when-no-system-properties",
        ),
    ],
)
def test_get_pebble_layer_command(
    prefix: str,
    system_properties: list[str],
    expected_present: list[str],
    expected_absent: list[str],
):
    """
    arrange: given Jenkins environment and system properties from parameterized inputs.
    act: when get_pebble_layer is called.
    assert: command includes expected fragments and excludes forbidden fragments.
    """
    env = {
        "JENKINS_HOME": str(jenkins.JENKINS_HOME_PATH),
        "JENKINS_PREFIX": prefix,
        "CASC_JENKINS_CONFIG": str(jenkins.JCASC_CONFIG_PATH),
        "JENKINS_ADMIN_PASSWORD": "secret",
        "CONFIGURATION_HASH": "hash123",
    }
    fake_state = SimpleNamespace(system_properties=system_properties)

    layer = pebble.get_pebble_layer(env, fake_state)  # type: ignore[arg-type]
    layer_dict = cast(dict[str, Any], layer.to_dict())
    command = layer_dict["services"]["jenkins"]["command"]

    for fragment in expected_present:
        assert fragment in command
    for fragment in expected_absent:
        assert fragment not in command


@pytest.mark.parametrize(
    "prefix, expected_url",
    [
        pytest.param("/prefix", f"http://localhost:{jenkins.WEB_PORT}/prefix", id="with-prefix"),
        pytest.param("", f"http://localhost:{jenkins.WEB_PORT}", id="without-prefix"),
    ],
)
def test_get_pebble_layer_sets_check_url_with_prefix(prefix: str, expected_url: str):
    """
    arrange: given an ingress prefix in Jenkins environment.
    act: when get_pebble_layer is called.
    assert: the readiness check URL includes the same prefix.
    """
    env = {
        "JENKINS_HOME": str(jenkins.JENKINS_HOME_PATH),
        "JENKINS_PREFIX": prefix,
        "CASC_JENKINS_CONFIG": str(jenkins.JCASC_CONFIG_PATH),
        "JENKINS_ADMIN_PASSWORD": "secret",
        "CONFIGURATION_HASH": "hash123",
    }
    fake_state = SimpleNamespace(system_properties=[])

    layer = pebble.get_pebble_layer(env, fake_state)  # type: ignore[arg-type]
    layer_dict = cast(dict[str, Any], layer.to_dict())
    check_url = layer_dict["checks"][jenkins.ONLINE_CHECK_NAME]["http"]["url"]

    assert check_url == expected_url


@pytest.mark.parametrize(
    "stdout, expected",
    [
        pytest.param("2.504.1\n", "2.504.1", id="trailing-newline"),
        pytest.param(" 2.504.1 \n", "2.504.1", id="surrounding-whitespace"),
    ],
)
def test_get_jenkins_version_executes_expected_command(stdout: str, expected: str):
    """
    arrange: given a container whose exec process returns a Jenkins version string.
    act: when get_jenkins_version is called.
    assert: expected command is executed and stdout is stripped.
    """
    process = MagicMock(spec=ops.pebble.ExecProcess)
    process.wait_output.return_value = (stdout, "")
    container = MagicMock(spec=ops.Container)
    container.exec.return_value = process

    version = pebble.get_jenkins_version(container)

    container.exec.assert_called_once_with(
        ["java", "-jar", str(pebble.JENKINS_WAR_PATH), "--version"],
        timeout=30,
        user=jenkins.USER,
        group=jenkins.GROUP,
    )
    assert version == expected
