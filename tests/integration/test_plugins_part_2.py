# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import jenkinsapi.plugin
import jenkinsapi.queue
import kubernetes.client
import kubernetes.config
import pytest
import requests
import tenacity
import yaml
from jenkinsapi.custom_exceptions import NotBuiltYet

from .helpers import (
    _log_retry,
    _raise_retry_timeout,
    create_kubernetes_cloud,
    create_secret_file_credentials,
    declarative_pipeline_script,
    gen_test_job_xml,
    gen_test_pipeline_with_custom_script_xml,
    install_plugins,
    kubernetes_test_pipeline_script,
)
from .types_ import KeycloakOIDCMetadata, UnitWebClient

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module", name="jenkins_kube_config")
def jenkins_kube_config_fixture(
    tmp_path_factory: pytest.TempPathFactory,
    kube_config: str,
    kube_core_client: kubernetes.client.CoreV1Api,
) -> Path:
    """Kubeconfig for the Jenkins kubernetes cloud, reachable from inside the pod.

    Canonical Kubernetes kubeconfigs point local clients at a loopback API
    endpoint: ``k8s kubectl config view`` output is only valid on cluster nodes
    where control plane services are available on localhost endpoints
    (https://documentation.ubuntu.com/k8s/latest/snap/howto/troubleshooting/).
    A Jenkins pod cannot reach the runner's loopback interface, so replace
    loopback endpoints with a control-plane node's InternalIP while preserving
    the configured port and credentials.
    """
    kube_config_path = Path(kube_config)
    config = yaml.safe_load(kube_config_path.read_text(encoding="utf-8"))

    loopback_clusters = []
    for cluster_entry in config.get("clusters", []):
        cluster = cluster_entry.get("cluster", {})
        server = cluster.get("server")
        if not server:
            continue
        parsed_server = urlparse(server)
        if parsed_server.hostname in {"127.0.0.1", "::1", "localhost"}:
            loopback_clusters.append((cluster, parsed_server))

    if not loopback_clusters:
        return kube_config_path

    nodes = kube_core_client.list_node().items
    control_plane_nodes = [
        node
        for node in nodes
        if any(
            role in (node.metadata.labels or {})
            for role in (
                "node-role.kubernetes.io/control-plane",
                "node-role.kubernetes.io/master",
            )
        )
    ]
    candidate_nodes = control_plane_nodes or nodes
    node_ip = next(
        (
            address.address
            for node in candidate_nodes
            for address in (node.status.addresses or [])
            if address.type == "InternalIP"
        ),
        None,
    )
    if not node_ip:
        raise RuntimeError("No Kubernetes node InternalIP found for kubeconfig rewrite")

    node_host = f"[{node_ip}]" if ":" in node_ip else node_ip
    for cluster, parsed_server in loopback_clusters:
        port = f":{parsed_server.port}" if parsed_server.port else ""
        cluster["server"] = parsed_server._replace(netloc=f"{node_host}{port}").geturl()

    rewritten_kube_config = tmp_path_factory.mktemp("jenkins-kube-config") / "kubeconfig.yaml"
    rewritten_kube_config.write_text(yaml.safe_dump(config, default_flow_style=False), "utf-8")
    logger.info(
        "Rewrote %d loopback kubeconfig endpoint(s) to Kubernetes node InternalIP",
        len(loopback_clusters),
    )
    return rewritten_kube_config


async def test_docker_build_publish_plugin(unit_web_client: UnitWebClient):
    """arrange: given a Jenkins charm with docker-build-publish plugin installed.
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
    res = requests.get(
        f"{unit_web_client.web}/securityRealm/commenceLogin?from=%2F",
        allow_redirects=False,
        timeout=30,
    )
    assert res.status_code == 302, (
        f"Jenkins login not redirected: status={res.status_code}, url={res.url}"
    )
    location = res.headers.get("location", "")
    assert keycloak_ip in location, f"Login not redirected to keycloak: location={location}"

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


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda result: result is None),
    wait=tenacity.wait_fixed(5),
    stop=tenacity.stop_after_delay(10 * 60),
    retry_error_callback=_raise_retry_timeout,
    before_sleep=_log_retry,
)
def _get_completed_build(
    queue_item: jenkinsapi.queue.QueueItem,
) -> "jenkinsapi.build.Build | None":
    """Return a completed Jenkins build, retrying while it is queued or running."""
    try:
        queue_item.poll()
        build = queue_item.get_build()
    except (NotBuiltYet, requests.HTTPError):
        return None
    return build if not build.is_running() else None


def _log_build_timeout_diagnostics(
    queue_item: jenkinsapi.queue.QueueItem,
    unit_web_client: UnitWebClient,
    kube_core_client: kubernetes.client.CoreV1Api,
) -> None:
    """Log build console, Jenkins system log and agent pod state on build timeout."""
    try:
        queue_item.poll()
        running_build = queue_item.get_build()
    except (NotBuiltYet, requests.HTTPError):
        running_build = None
    if running_build:
        try:
            logger.error(
                "Kubernetes plugin build console (last 10000 characters):\n%s",
                running_build.get_console()[-10000:],
            )
        except requests.RequestException as console_exc:
            logger.warning("Could not fetch Kubernetes plugin build console: %s", console_exc)
    try:
        system_log_resp = unit_web_client.client.requester.get_url(
            f"{unit_web_client.web}/log/all/consoleText"
        )
        logger.error(
            "Jenkins system log (last 10000 characters):\n%s",
            system_log_resp.text[-10000:],
        )
    except requests.RequestException as log_exc:
        logger.warning("Could not fetch Jenkins system log: %s", log_exc)
    _log_k8s_agent_pods(kube_core_client)


async def test_kubernetes_plugin(
    unit_web_client: UnitWebClient,
    jenkins_kube_config: Path,
    kube_core_client: kubernetes.client.CoreV1Api,
):
    """
    arrange: given a Jenkins charm with kubernetes plugin installed and credentials from the k8s backend.
    act: Run a job using an agent provided by the kubernetes plugin.
    assert: Job succeeds.
    """
    # Use plain credentials to be able to create secret-file/secret-text credentials
    await install_plugins(unit_web_client, ("kubernetes", "plain-credentials"))

    plugins = unit_web_client.client.plugins
    logger.info(
        "Installed plugins: %s",
        {name: plugin.version for name, plugin in plugins.iteritems()},
    )

    logger.info("Jenkins version pre-build: %s", unit_web_client.client.version)

    credentials_id = create_secret_file_credentials(unit_web_client, str(jenkins_kube_config))
    assert credentials_id, "Failed to create credentials id"
    kubernetes_cloud_name = create_kubernetes_cloud(unit_web_client, credentials_id)
    assert kubernetes_cloud_name, "Failed to create kubernetes cloud"
    job = unit_web_client.client.create_job(
        "kubernetes_plugin_test",
        gen_test_pipeline_with_custom_script_xml(kubernetes_test_pipeline_script()),
    )

    queue_item = job.invoke()

    try:
        build = _get_completed_build(queue_item)
    except TimeoutError as exc:
        _log_build_timeout_diagnostics(queue_item, unit_web_client, kube_core_client)
        raise TimeoutError("Kubernetes plugin build did not complete within 600 seconds") from exc

    assert build is not None, "Jenkins build did not complete"
    build_status = build.get_status()
    log_stream = build.stream_logs()
    logs = "".join(log_stream)
    logger.info("Build status: %s\nBuild logs:\n%s", build_status, logs)

    try:
        system_log_resp = unit_web_client.client.requester.get_url(
            f"{unit_web_client.web}/log/all"
        )
        logger.info("Jenkins system log:\n%s", system_log_resp.text)
    except Exception as exc:
        logger.warning("Could not fetch Jenkins system log: %s", exc)

    _log_k8s_agent_pods(kube_core_client)

    assert build_status == "SUCCESS"


def _log_k8s_agent_pods(kube_core_client: kubernetes.client.CoreV1Api) -> None:
    """Log K8s pod status, container logs and events for all jenkins agent pods.

    Args:
        kube_core_client: The Kubernetes core API client.
    """
    try:
        pods = kube_core_client.list_pod_for_all_namespaces()
        agent_pods = [
            p
            for p in pods.items
            if any("jenkins" in (c.name or "") for c in (p.spec.containers or []))
            or "jenkins" in (p.metadata.name or "")
        ]
        logger.info("Jenkins-related pods found: %s", [p.metadata.name for p in agent_pods])
        for pod in agent_pods:
            ns = pod.metadata.namespace
            name = pod.metadata.name
            logger.info(
                "Pod %s/%s phase=%s conditions=%s",
                ns,
                name,
                pod.status.phase,
                pod.status.conditions,
            )
            for container in pod.spec.containers or []:
                try:
                    pod_log = kube_core_client.read_namespaced_pod_log(
                        name, ns, container=container.name, tail_lines=100
                    )
                    logger.info("Pod %s container %s logs:\n%s", name, container.name, pod_log)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "Could not get logs for pod %s container %s: %s",
                        name,
                        container.name,
                        exc,
                    )
            try:
                events = kube_core_client.list_namespaced_event(
                    ns, field_selector=f"involvedObject.name={name}"
                )
                for ev in events.items:
                    logger.info("Pod event [%s] %s/%s: %s", ev.type, ns, name, ev.message)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Could not get events for pod %s: %s", name, exc)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Could not list K8s pods: %s", exc)


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
