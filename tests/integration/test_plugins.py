# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import functools
import logging
import typing

import jenkinsapi.jenkins
import pytest
import requests.exceptions
from juju.model import Model
from pytest_operator.plugin import OpsTest

from .types_ import PluginsMeta, UnitWebClient

logger = logging.getLogger(__name__)


def try_install_plugins(
    client: jenkinsapi.jenkins.Jenkins, plugins_to_install: typing.Iterable[str]
) -> bool:
    """Try installing plugins.

    This is a helper method wrapping client.install_plugins since this method fails a few times
    before succeeding.

    Args:
        client: The Jenkins API client.
        plugins_to_install: The plugins to install on Jenkins.

    Returns:
        True if plugins installation succeeds. False otherwise.
    """
    try:
        client.install_plugins(plugins_to_install)
    except (
        jenkinsapi.custom_exceptions.JenkinsAPIException,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    ) as exc:
        logger.warning("Failed to install plugins, %s", exc)
        return False
    return True


@pytest.mark.usefixtures("jenkins_with_plugin_config")
async def test_jenkins_plugins_config(
    ops_test: OpsTest,
    model: Model,
    unit_web_client: UnitWebClient,
    plugins_meta: PluginsMeta,
    update_status_env: typing.Iterable[str],
):
    """
    arrange: given a jenkins charm with plugin config and plugins installed not in the config.
    act: when update_status_hook is fired.
    assert: the plugin is uninstalled and the system message is set on Jenkins.
    """
    await model.block_until(
        functools.partial(
            try_install_plugins,
            client=unit_web_client.client,
            plugins_to_install=plugins_meta.install,
        ),
        timeout=600,
        wait_period=10,
    )

    ret_code, _, stderr = await ops_test.juju(
        "run",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    res = unit_web_client.client.requester.get_url(unit_web_client.web)
    page_content = str(res.content, encoding="utf-8")

    assert all(not unit_web_client.client.has_plugin(plugin) for plugin in plugins_meta.config)
    assert all(plugin in page_content for plugin in plugins_meta.remove)
    assert "The following plugins have been removed by the system administrator:" in page_content
    assert (
        "To allow the plugins, please include them in the plugins configuration of the charm."
        in page_content
    )
