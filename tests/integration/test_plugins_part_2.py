# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import functools
import json
import logging

import jenkinsapi.plugin
import pytest
import requests

from .helpers import (
    create_kubernetes_cloud,
    create_secret_file_credentials,
    declarative_pipeline_script,
    gen_test_job_xml,
    gen_test_pipeline_with_custom_script_xml,
    install_plugins,
    kubernetes_test_pipeline_script,
    wait_for,
)
from .types_ import KeycloakOIDCMetadata, UnitWebClient

logger = logging.getLogger(__name__)


async def test_docker_build_publish_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with docker-build-publish plugin installed.
    act: when a job configuration page is accessed.
    assert: docker-build-publish plugin option exists.
    """
    await install_plugins(unit_web_client, ("docker-build-publish",))
    unit_web_client.client.create_job("docker_plugin_test", gen_test_job_xml("k8s"))
    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/job/docker_plugin_test/configure"
    )
    config_page = str(res.content, "utf-8")
    assert "Docker Build and Publish" in config_page, (
        f"docker-build-publish configuration option not found. {config_page}"
    )


async def test_reverse_proxy_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with reverse-proxy-auth-plugin plugin installed.
    act: when the security configuration is accessed.
    assert: reverse-proxy-auth-plugin plugin option exists.
    """
    await install_plugins(unit_web_client, ("reverse-proxy-auth-plugin",))

    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/manage/configureSecurity"
    )
    config_page = str(res.content, "utf-8")

    assert "HTTP Header by reverse proxy" in config_page, (
        f"reverse-proxy-auth-plugin configuration option not found. {config_page}"
    )


async def test_dependency_check_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with dependency-check-jenkins-plugin plugin installed.
    act: when a job configuration page is accessed.
    assert: dependency-check-jenkins-plugin plugin option exists.
    """
    await install_plugins(unit_web_client, ("dependency-check-jenkins-plugin",))
    unit_web_client.client.create_job("deps_plugin_test", gen_test_job_xml("k8s"))
    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/job/deps_plugin_test/configure"
    )
    job_page = str(res.content, "utf-8")
    assert "Invoke Dependency-Check" in job_page, (
        f"Dependency check job configuration option not found. {job_page}"
    )
    res = unit_web_client.client.requester.get_url(f"{unit_web_client.web}/manage/configureTools/")
    tools_page = str(res.content, "utf-8")
    assert "Dependency-Check installations" in tools_page, (
        f"Dependency check tool configuration option not found. {tools_page}"
    )


async def test_groovy_libs_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with pipeline-groovy-lib plugin installed.
    act: when a job configuration page is accessed.
    assert: pipeline-groovy-lib plugin option exists.
    """
    await install_plugins(unit_web_client, ("pipeline-groovy-lib",))
    res = unit_web_client.client.requester.get_url(f"{unit_web_client.web}/manage/configure")

    config_page = str(res.content, "utf-8")
    # The string is now "Global Trusted Pipeline Libraries" and
    # "Global Untrusted Pipeline Libraries" for v727.ve832a_9244dfa_
    assert "Pipeline Libraries" in config_page, (
        f"Groovy libs configuration option not found. {config_page}"
    )


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_rebuilder_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with rebuilder plugin installed.
    act: when a job is built and a rebuild is triggered.
    assert: last job is rebuilt.
    """
    await install_plugins(unit_web_client, ("rebuild",))

    job_name = "rebuild_test"
    job = unit_web_client.client.create_job(job_name, gen_test_job_xml("k8s"))
    job.invoke().block_until_complete()

    unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/job/{job_name}/lastCompletedBuild/rebuild/"
    )
    job.get_last_build().block_until_complete()

    assert job.get_last_buildnumber() == 2, "Rebuild not triggered."


async def test_openid_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with openid plugin installed.
    act: when an openid endpoint is validated using the plugin.
    assert: the response returns a 200 status code.
    """
    await install_plugins(unit_web_client, ("openid",))

    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/descriptorByName/hudson.plugins.openid."
        "OpenIdSsoSecurityRealm/validate",
        data={"endpoint": "https://login.ubuntu.com/+openid"},
    )

    assert res.status_code == 200, "Failed to validate openid endpoint using the plugin."


async def test_openid_connect_plugin(
    unit_web_client: UnitWebClient,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
    keycloak_ip: str,
):
    """
    arrange: given a Jenkins charm with oic-auth plugin installed and a Keycloak oidc server.
    act:
        1. when jenkins security realm is configured with oidc server and login page is requested.
        2. when jenkins security realm is reset and login page is requested.
    assert:
        1. a redirection to Keycloak SSO is made.
        2. native Jenkins login ui is loaded.
    """
    await install_plugins(unit_web_client, ("oic-auth",))

    # 1. when jenkins security realm is configured with oidc server and login page is requested.
    payload: dict = {
        "securityRealm": {
            "clientId": keycloak_oidc_meta.client_id,
            "clientSecret": keycloak_oidc_meta.client_secret,
            "automanualconfigure": "auto",
            "serverConfiguration": {
                "wellKnownOpenIDConfigurationUrl": keycloak_oidc_meta.well_known_endpoint,
                "scopesOverride": "",
                "stapler-class": "org.jenkinsci.plugins.oic.OicServerWellKnownConfiguration",
                "$class": "org.jenkinsci.plugins.oic.OicServerWellKnownConfiguration",
            },
            "userNameField": "sub",
            "stapler-class": "org.jenkinsci.plugins.oic.OicSecurityRealm",
            "$class": "org.jenkinsci.plugins.oic.OicSecurityRealm",
        },
        "slaveAgentPort": {"type": "fixed", "value": "50000"},
    }
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/configureSecurity/configure",
        data=[
            (
                "json",
                json.dumps(payload),
            ),
        ],
    )
    res = requests.get(f"{unit_web_client.web}/securityRealm/commenceLogin?from=%2F", timeout=30)
    assert res.history[0].status_code == 302, "Jenkins login not redirected."
    assert keycloak_ip in res.history[0].headers["location"], "Login not redirected to keycloak."

    # 2. when jenkins security realm is reset and login page is requested.
    payload = {
        "securityRealm": {
            "allowsSignup": False,
            "stapler-class": "hudson.security.HudsonPrivateSecurityRealm",
            "$class": "hudson.security.HudsonPrivateSecurityRealm",
        },
        "authorizationStrategy": {
            "allowAnonymousRead": False,
            "stapler-class": "hudson.security.FullControlOnceLoggedInAuthorizationStrategy",
            "$class": "hudson.security.FullControlOnceLoggedInAuthorizationStrategy",
        },
        "slaveAgentPort": {"type": "fixed", "value": "50000"},
    }
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/configureSecurity/configure",
        data=[
            (
                "json",
                json.dumps(payload),
            )
        ],
    )
    res = requests.get(f"{unit_web_client.web}/securityRealm/commenceLogin?from=%2F", timeout=30)
    assert res.status_code == 404, "Security realm login not reset."
    res = requests.get(f"{unit_web_client.web}/login?from=%2F", timeout=30)
    assert res.status_code == 200, "Failed to load Jenkins native login UI."


async def test_kubernetes_plugin(unit_web_client: UnitWebClient, kube_config: str):
    """
    arrange: given a Jenkins charm with kubernetes plugin installed and credentials from microk8s.
    act: Run a job using an agent provided by the kubernetes plugin.
    assert: Job succeeds.
    """
    # Use plain credentials to be able to create secret-file/secret-text credentials
    await install_plugins(unit_web_client, ("kubernetes", "plain-credentials"))
    credentials_id = await wait_for(
        functools.partial(create_secret_file_credentials, unit_web_client, kube_config)
    )
    assert credentials_id, "Failed to create credentials id"
    kubernetes_cloud_name = await wait_for(
        functools.partial(create_kubernetes_cloud, unit_web_client, credentials_id)
    )
    assert kubernetes_cloud_name, "Failed to create kubernetes cloud"
    job = unit_web_client.client.create_job(
        "kubernetes_plugin_test",
        gen_test_pipeline_with_custom_script_xml(kubernetes_test_pipeline_script()),
    )

    queue_item = job.invoke()
    queue_item.block_until_complete()

    build: jenkinsapi.build.Build = queue_item.get_build()
    log_stream = build.stream_logs()
    logs = "".join(log_stream)
    logger.debug("build logs: %s", logs)
    assert build.get_status() == "SUCCESS"


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_pipeline_model_definition_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with declarative pipeline plugin installed.
    act: Run a job using a declarative pipeline script.
    assert: Job succeeds.
    """
    await install_plugins(unit_web_client, ("pipeline-model-definition",))

    job = unit_web_client.client.create_job(
        "pipeline_model_definition_plugin_test",
        gen_test_pipeline_with_custom_script_xml(declarative_pipeline_script()),
    )

    queue_item = job.invoke()
    queue_item.block_until_complete()

    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
