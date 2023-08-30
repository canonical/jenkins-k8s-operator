# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""
import typing

from juju.unit import Unit
from pytest_operator.plugin import OpsTest

import jenkins


async def install_plugins(ops_test: OpsTest, unit: Unit, plugins: typing.Iterable[str]):
    returncode, stdout, stderr = await ops_test.juju(
        (
            "ssh",
            "--container",
            "jenkins",
            unit.name,
            "java",
            "jar",
            f"{jenkins.EXECUTABLES_PATH / 'jenkins-plugin-manager-2.12.11.jar'}",
            "-w",
            f"{jenkins.EXECUTABLES_PATH / 'jenkins.war'}",
            "-d",
            str(jenkins.PLUGINS_PATH),
            "-p",
            " ".join(plugins),
        )
    )
    assert (
        not returncode
    ), f"Non-zero return code {returncode} received, stdout: {stdout} stderr: {stderr}"
