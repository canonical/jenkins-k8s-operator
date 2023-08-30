# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""
import typing

import requests
from jenkinsapi.jenkins import Jenkins
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

import jenkins


async def install_plugins(
    ops_test: OpsTest, unit: Unit, jenkins_client: Jenkins, plugins: typing.Iterable[str]
) -> None:
    """Install plugins to Jenkins unit.

    Args:
        ops_test: The Ops testing fixture.
        unit: The Jenkins unit to install plugins to.
        jenkins_client: The Jenkins client of given unit.
        plugins: Desired plugins to install.
    """
    plugins = tuple(plugin for plugin in plugins if not jenkins_client.has_plugin(plugin))
    if not plugins:
        return

    returncode, stdout, stderr = await ops_test.juju(
        "ssh",
        "--container",
        "jenkins",
        unit.name,
        "java",
        "-jar",
        f"{jenkins.EXECUTABLES_PATH / 'jenkins-plugin-manager-2.12.11.jar'}",
        "-w",
        f"{jenkins.EXECUTABLES_PATH / 'jenkins.war'}",
        "-d",
        str(jenkins.PLUGINS_PATH),
        "-p",
        " ".join(plugins),
    )
    assert (
        not returncode
    ), f"Non-zero return code {returncode} received, stdout: {stdout} stderr: {stderr}"
    assert "Done" in stdout, f"Failed to install plugins via kube exec, {stdout}"

    # the library will return 503 or other status codes that are not 200, hence restart and
    # wait rather than check for status code.
    jenkins_client.safe_restart()
    model = ops_test.model
    assert model, "Model not initialized."
    await ops_test.model.block_until(
        lambda: requests.get(jenkins_client.baseurl, timeout=10).status_code == 403,
        timeout=300,
        wait_period=10,
    )
