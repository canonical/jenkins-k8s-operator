# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm proxy settings."""

import jenkinsapi


def test_jenkins_ui_proxy_config(
    jenkins_with_proxy_client: jenkinsapi.jenkins.Jenkins,
    proxy_jenkins_web_address: str,
    tinyproxy_port: int,
    tinyproxy_ip: str,
) -> None:
    """
    Arrange: Use a Jenkins client configured with the proxy host and port fixtures.
    Act: Fetch the Jenkins configuration page.
    Assert: The page contains the configured proxy host and port.
    """
    response = jenkins_with_proxy_client.requester.get_url(
        f"{proxy_jenkins_web_address}/manage/configure"
    )
    page_content = str(response.content, encoding="utf-8")
    assert tinyproxy_ip in page_content, "Proxy host not configured."
    assert str(tinyproxy_port) in page_content, "Proxy port not configured."
