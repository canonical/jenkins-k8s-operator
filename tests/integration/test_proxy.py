# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm proxy settings."""

import jenkinsapi

from .fixture_modules.proxy import (
    jenkins_with_proxy_client_fixture,  # noqa: F401
    jenkins_with_proxy_fixture,  # noqa: F401
    model_with_proxy_fixture,  # noqa: F401
    proxy_jenkins_unit_ip_fixture,  # noqa: F401
    proxy_jenkins_web_address_fixture,  # noqa: F401
    tiny_proxy_daemonset_fixture,  # noqa: F401
    tinyproxy_ip_fixture,  # noqa: F401
    tinyproxy_port_fixture,  # noqa: F401
)


async def test_jenkins_ui_proxy_config(
    jenkins_with_proxy_client: jenkinsapi.jenkins.Jenkins,
    proxy_jenkins_web_address: str,
    tinyproxy_port: int,
    tinyproxy_ip: str,
):
    """
    arrange: given a jenkins deployed under juju model with proxy settings.
    act: when plugin manager page w/ proxy settings is fetched.
    assert: proxy server host and port exists in configuration value.
    """
    res = jenkins_with_proxy_client.requester.get_url(
        f"{proxy_jenkins_web_address}/manage/configure"
    )

    page_content = str(res.content, encoding="utf-8")

    assert tinyproxy_ip in page_content, "Proxy host not configured."
    assert str(tinyproxy_port) in page_content, "Proxy port not configured."
