# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import pytest
from pytest_operator.plugin import OpsTest

from .types_ import PluginsMeta, UnitWebClient


@pytest.mark.usefixtures("install_plugins")
async def test_jenkins_plugins_config(
    ops_test: OpsTest,
    unit_web_client: UnitWebClient,
    plugins_meta: PluginsMeta,
    update_status_env: typing.Iterable[str],
):
    """
    arrange: given a jenkins charm with plugin config and plugins installed not in the config.
    act: when update_status_hook is fired.
    assert: the plugin is uninstalled and the system message is set on Jenkins.
    """
    ret_code, _, stderr = await ops_test.juju(
        "exec",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    res = unit_web_client.client.requester.get_url(unit_web_client.web)
    page_content = str(res.content, encoding="utf-8")

    assert all(plugin in page_content for plugin in plugins_meta.remove), page_content
    assert "The following plugins have been removed by the system administrator:" in page_content
    assert (
        "To allow the plugins, please include them in the plugins configuration of the charm."
        in page_content
    )
    assert all(unit_web_client.client.has_plugin(plugin) for plugin in plugins_meta.config)
