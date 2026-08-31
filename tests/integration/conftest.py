# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import logging
import os
import random
import secrets
import string
from collections.abc import Generator, Iterable
from pathlib import Path

import jenkinsapi.jenkins
import jubilant
import kubernetes.client
import kubernetes.config
import pytest
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
from pytest import FixtureRequest

import state

from .constants import ALLOWED_PLUGINS, K8S_CONTROLLER_NAME, LXD_CONTROLLER_NAME
from .helpers import (
    AuthMethod,
    application_ref,
    generate_jenkins_client,
    get_model_unit_address,
    get_pod_ip,
    short_model_name,
    web_address_for_ip,
)
from .types_ import (
    JujuApplication,
    KeycloakOIDCMetadata,
    LDAPSettings,
    ModelAppUnit,
    UnitWebClient,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_TEST_JCASC_REPOSITORY = "https://github.com/canonical/jenkins-k8s-operator.git"
JENKINS_APP_NAME = "jenkins-k8s"


@pytest.fixture(scope="module", name="model")
def model_fixture(request: FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Connect to the provisioned Canonical Kubernetes model."""
    model_name = request.config.getoption("--model")
    keep_models = bool(request.config.getoption("--keep-models"))
    if model_name:
        model = jubilant.Juju(model=model_name, wait_timeout=30 * 60)
        yield model
        return

    with jubilant.temp_model(
        keep=keep_models,
        controller=K8S_CONTROLLER_NAME,
        cloud="k8s",
    ) as model:
        model.wait_timeout = 30 * 60
        yield model


@pytest.fixture(scope="module", name="test_jcasc_repository")
def test_jcasc_repository_fixture() -> str:
    """Return the trusted repository used by the JCasC integration test."""
    return os.environ.get("TEST_JCASC_REPOSITORY", DEFAULT_TEST_JCASC_REPOSITORY)


@pytest.fixture(scope="module", name="cloud")
def cloud_fixture(model: jubilant.Juju) -> str:
    """Return the cloud used by the Canonical Kubernetes model."""
    return model.status().model.cloud


@pytest.fixture(scope="module", name="jenkins_image")
def jenkins_image_fixture(request: FixtureRequest) -> str:
    """Return the Jenkins OCI image resolved from the artifact manifest."""
    override = request.config.getoption("--jenkins-image")
    if override:
        return override
    resource_images = request.getfixturevalue("resource_images")
    try:
        return resource_images["jenkins-image"]
    except KeyError:
        pytest.fail("The artifact manifest does not contain the jenkins-image resource.")


@pytest.fixture(scope="module", name="num_units")
def num_units_fixture(request: FixtureRequest) -> int:
    """Return the number of machine-agent units used by the tests."""
    return int(request.config.getoption("--num-units"))


@pytest.fixture(scope="module", name="charm")
def charm_fixture(request: FixtureRequest) -> str:
    """Return the localized Ubuntu 24.04 Jenkins charm artifact."""
    override = request.config.getoption("--jenkins-charm-file")
    if override:
        return override
    try:
        charm_paths = request.getfixturevalue("charm_paths")[JENKINS_APP_NAME]
    except pytest.FixtureLookupError:
        pytest.fail(
            "No charm artifact available. Pass --jenkins-charm-file for a local run or "
            "run through charm-ci with artifacts.yaml."
        )
    for base in ("ubuntu@24.04", "ubuntu@22.04"):
        try:
            return charm_paths[base]
        except KeyError:
            continue
    return charm_paths.path


@pytest.fixture(scope="module", name="application")
def application_fixture(
    model: jubilant.Juju,
    charm: str,
    jenkins_image: str,
) -> JujuApplication:
    """Deploy Jenkins with the localized rock image resource."""
    model.deploy(
        charm,
        app=JENKINS_APP_NAME,
        resources={"jenkins-image": jenkins_image},
        trust=True,
    )
    model.wait(
        lambda status: jubilant.all_active(status, JENKINS_APP_NAME),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    return application_ref(model, JENKINS_APP_NAME)


@pytest.fixture(scope="module", name="unit")
def unit_fixture(application: JujuApplication) -> str:
    """Return the Jenkins unit name."""
    return application.units[0]


@pytest.fixture(scope="module", name="model_app_unit")
def model_app_unit_fixture(
    model: jubilant.Juju,
    application: JujuApplication,
    unit: str,
) -> ModelAppUnit:
    """Return the model, application, and unit used by a test."""
    return ModelAppUnit(model=model, app=application, unit=unit)


@pytest.fixture(scope="function", name="unit_ip")
def unit_ip_fixture(model: jubilant.Juju, application: JujuApplication) -> str:
    """Return the Jenkins unit IP address."""
    return get_model_unit_address(model, application.name)


@pytest.fixture(scope="function", name="web_address")
def web_address_fixture(unit_ip: str) -> str:
    """Return the Jenkins web address."""
    return web_address_for_ip(unit_ip)


@pytest.fixture(scope="function", name="jenkins_client")
def jenkins_client_fixture(
    model: jubilant.Juju,
    application: JujuApplication,
    web_address: str,
) -> jenkinsapi.jenkins.Jenkins:
    """Return an authenticated Jenkins API client."""
    return generate_jenkins_client(model, application, web_address)


@pytest.fixture(scope="function", name="jenkins_user_client")
def jenkins_user_client_fixture(
    model: jubilant.Juju,
    application: JujuApplication,
    web_address: str,
) -> jenkinsapi.jenkins.Jenkins:
    """Return a Jenkins client authenticated with the admin password."""
    return generate_jenkins_client(model, application, web_address, method=AuthMethod.PASSWORD)


@pytest.fixture(scope="function", name="unit_web_client")
def unit_web_client_fixture(
    model: jubilant.Juju,
    application: JujuApplication,
    unit: str,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
) -> UnitWebClient:
    """Return the Jenkins unit, web address, and API client."""
    return UnitWebClient(
        model=model,
        unit=unit,
        web=web_address,
        client=jenkins_client,
    )


@pytest.fixture(scope="module", name="app_suffix")
def app_suffix_fixture() -> str:
    """Return a random suffix suitable for a Juju application name."""
    return "".join(random.choices(string.ascii_lowercase, k=4))  # nosec


@pytest.fixture(scope="module", name="jenkins_k8s_agents")
def jenkins_k8s_agents_fixture(model: jubilant.Juju) -> JujuApplication:
    """Deploy a Jenkins Kubernetes agent charm."""
    name = "jenkins-agent-k8s"
    model.deploy(
        "jenkins-agent-k8s",
        app=name,
        base="ubuntu@24.04",
        config={"jenkins_agent_labels": "k8s"},
        channel="latest/edge",
    )
    model.wait(
        lambda status: jubilant.all_blocked(status, name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return application_ref(model, name)


@pytest.fixture(scope="module", name="k8s_agent_related_app")
def k8s_agent_related_app_fixture(
    jenkins_k8s_agents: JujuApplication,
    application: JujuApplication,
    model: jubilant.Juju,
) -> JujuApplication:
    """Relate the Jenkins server and Kubernetes agent charms."""
    model.integrate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}",
    )
    model.wait(
        lambda status: jubilant.all_active(status, application.name, jenkins_k8s_agents.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return application


@pytest.fixture(scope="function", name="extra_jenkins_k8s_agents")
def extra_jenkins_k8s_agents_fixture(model: jubilant.Juju) -> JujuApplication:
    """Deploy a second Jenkins Kubernetes agent charm."""
    name = "jenkins-agent-k8s-extra"
    model.deploy(
        "jenkins-agent-k8s",
        app=name,
        base="ubuntu@24.04",
        config={"jenkins_agent_labels": "k8s-extra"},
        channel="latest/edge",
    )
    model.wait(
        lambda status: jubilant.all_blocked(status, name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return application_ref(model, name)


@pytest.fixture(scope="module", name="machine_model")
def machine_model_fixture(
    request: FixtureRequest,
) -> Generator[jubilant.Juju, None, None]:
    """Create a temporary model on the Concierge LXD controller."""
    model_name = f"jenkins-agent-machine-{secrets.token_hex(2)}"
    machine_model = jubilant.Juju(
        model=f"{LXD_CONTROLLER_NAME}:{model_name}",
        wait_timeout=20 * 60,
    )
    machine_model.add_model(model_name, "localhost", controller=LXD_CONTROLLER_NAME)
    yield machine_model
    if not request.config.getoption("--keep-models"):
        machine_model.destroy_model(
            f"{LXD_CONTROLLER_NAME}:{model_name}", destroy_storage=True, force=True
        )


@pytest.fixture(scope="function", name="jenkins_machine_agents")
def jenkins_machine_agents_fixture(
    machine_model: jubilant.Juju,
    num_units: int,
    app_suffix: str,
) -> JujuApplication:
    """Deploy machine agents and offer their agent endpoint."""
    name = f"jenkins-agent-{app_suffix}"
    machine_model.deploy(
        "jenkins-agent",
        app=name,
        channel="latest/stable",
        config={"jenkins_agent_labels": "machine"},
        num_units=num_units,
    )
    machine_model.offer(
        f"{short_model_name(machine_model)}.{name}",
        controller=LXD_CONTROLLER_NAME,
        endpoint=state.AGENT_RELATION,
        name=state.AGENT_RELATION,
    )
    machine_model.wait(
        lambda status: jubilant.all_blocked(status, name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return application_ref(machine_model, name)


@pytest.fixture(scope="function", name="machine_agent_related_app")
def machine_agent_related_app_fixture(
    jenkins_machine_agents: JujuApplication,
    application: JujuApplication,
    model: jubilant.Juju,
    machine_model: jubilant.Juju,
) -> JujuApplication:
    """Relate the Jenkins server to the offered machine-agent endpoint."""
    model.integrate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{LXD_CONTROLLER_NAME}:admin/{short_model_name(machine_model)}.{state.AGENT_RELATION}",
    )
    machine_model.wait(
        lambda status: jubilant.all_active(status, jenkins_machine_agents.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    return application


@pytest.fixture(scope="module", name="freeze_time")
def freeze_time_fixture() -> str:
    """Return the time string used to freeze charm execution."""
    return "2022-01-01 15:00:00"


@pytest.fixture(scope="function", name="app_with_restart_time_range")
def app_with_restart_time_range_fixture(
    application: JujuApplication,
) -> Generator[JujuApplication, None, None]:
    """Configure a restart time range for one test."""
    application.model.config(application.name, {"restart-time-range": "03-05"})
    yield application
    application.model.config(application.name, reset=["restart-time-range"])


@pytest.fixture(scope="function", name="libfaketime_unit")
def libfaketime_unit_fixture(model: jubilant.Juju, unit: str) -> str:
    """Install libfaketime in the Jenkins workload container."""
    model.ssh(unit, "sudo apt update", container="charm")
    model.ssh(unit, "sudo apt install -y libfaketime", container="charm")
    return unit


@pytest.fixture(scope="function", name="libfaketime_env")
def libfaketime_env_fixture(freeze_time: str) -> Iterable[str]:
    """Return environment assignments for using libfaketime."""
    return (
        'LD_PRELOAD="/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"',
        f'FAKETIME="@{freeze_time}"',
    )


@pytest.fixture(scope="function", name="update_status_env")
def update_status_env_fixture(
    model: jubilant.Juju,
    unit: str,
) -> Iterable[str]:
    """Return environment assignments for running the update-status dispatch."""
    return (
        "JUJU_DISPATCH_PATH=hooks/update-status",
        f"JUJU_MODEL_NAME={short_model_name(model)}",
        f"JUJU_UNIT_NAME={unit}",
    )


@pytest.fixture(scope="module", name="kube_config")
def kube_config_fixture(request: FixtureRequest) -> str:
    """Return the Canonical Kubernetes kubeconfig path."""
    kube_config = request.config.getoption("--kube-config")
    assert kube_config, "--kube-config argument is required"
    return os.path.expanduser(kube_config)


@pytest.fixture(scope="module", name="kube_core_client")
def kube_core_client_fixture(kube_config: str) -> kubernetes.client.CoreV1Api:
    """Create a Kubernetes CoreV1 client."""
    kubernetes.config.load_kube_config(config_file=kube_config)
    return kubernetes.client.CoreV1Api()


@pytest.fixture(scope="module", name="kube_apps_client")
def kube_apps_client_fixture(kube_config: str) -> kubernetes.client.AppsV1Api:
    """Create a Kubernetes AppsV1 client."""
    kubernetes.config.load_kube_config(config_file=kube_config)
    return kubernetes.client.AppsV1Api()


@pytest.fixture(scope="module", name="tinyproxy_port")
def tinyproxy_port_fixture() -> int:
    """Return the tinyproxy port."""
    return 8888


@pytest.fixture(scope="module", name="tiny_proxy_daemonset")
def tiny_proxy_daemonset_fixture(
    model: jubilant.Juju,
    kube_apps_client: kubernetes.client.AppsV1Api,
    tinyproxy_port: int,
) -> kubernetes.client.V1DaemonSet:
    """Create a tiny proxy daemonset."""
    container = kubernetes.client.V1Container(
        name="tinyproxy",
        image="monokal/tinyproxy",
        image_pull_policy="IfNotPresent",
        ports=[
            kubernetes.client.V1ContainerPort(
                container_port=tinyproxy_port,
                host_port=tinyproxy_port,
            )
        ],
        args=["ANY"],
    )
    template = kubernetes.client.V1PodTemplateSpec(
        metadata=kubernetes.client.V1ObjectMeta(labels={"app": "tinyproxy"}),
        spec=kubernetes.client.V1PodSpec(containers=[container]),
    )
    spec = kubernetes.client.V1DaemonSetSpec(
        selector=kubernetes.client.V1LabelSelector(match_labels={"app": "tinyproxy"}),
        template=template,
    )
    daemonset = kubernetes.client.V1DaemonSet(
        api_version="apps/v1",
        kind="DaemonSet",
        metadata=kubernetes.client.V1ObjectMeta(
            name="daemonset-tiny-proxy",
            namespace=short_model_name(model),
        ),
        spec=spec,
    )
    return kube_apps_client.create_namespaced_daemon_set(
        namespace=short_model_name(model), body=daemonset
    )


@pytest.fixture(scope="module", name="tinyproxy_ip")
def tinyproxy_ip_fixture(
    model: jubilant.Juju,
    kube_core_client: kubernetes.client.CoreV1Api,
    tiny_proxy_daemonset: kubernetes.client.V1DaemonSet,
) -> str:
    """Return the ready tinyproxy pod IP."""
    labels = tiny_proxy_daemonset.spec.template.metadata.labels
    assert labels
    return get_pod_ip(model, kube_core_client, labels["app"])


@pytest.fixture(scope="module", name="model_with_proxy")
def model_with_proxy_fixture(
    model: jubilant.Juju,
    tinyproxy_ip: str,
    tinyproxy_port: int,
) -> Generator[jubilant.Juju, None, None]:
    """Configure Juju HTTP and HTTPS proxies for one module."""
    tinyproxy_url = f"http://{tinyproxy_ip}:{tinyproxy_port}"
    model.model_config({"juju-http-proxy": tinyproxy_url, "juju-https-proxy": tinyproxy_url})
    yield model
    model.model_config({"juju-http-proxy": "", "juju-https-proxy": ""})


@pytest.fixture(scope="module", name="jenkins_with_proxy")
def jenkins_with_proxy_fixture(
    model_with_proxy: jubilant.Juju,
    charm: str,
    jenkins_image: str,
) -> Generator[JujuApplication, None, None]:
    """Deploy Jenkins under a model with proxy configuration."""
    name = "jenkins-proxy-k8s"
    model_with_proxy.deploy(
        charm,
        app=name,
        resources={"jenkins-image": jenkins_image},
        trust=True,
    )
    model_with_proxy.wait(
        lambda status: jubilant.all_active(status, name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    application = application_ref(model_with_proxy, name)
    yield application
    model_with_proxy.remove_application(name, force=True)


@pytest.fixture(scope="module", name="proxy_jenkins_unit_ip")
def proxy_jenkins_unit_ip_fixture(
    model_with_proxy: jubilant.Juju,
    jenkins_with_proxy: JujuApplication,
) -> str:
    """Return the Jenkins unit IP under proxy configuration."""
    return get_model_unit_address(model_with_proxy, jenkins_with_proxy.name)


@pytest.fixture(scope="module", name="proxy_jenkins_web_address")
def proxy_jenkins_web_address_fixture(proxy_jenkins_unit_ip: str) -> str:
    """Return the Jenkins web address under proxy configuration."""
    return web_address_for_ip(proxy_jenkins_unit_ip)


@pytest.fixture(scope="module", name="jenkins_with_proxy_client")
def jenkins_with_proxy_client_fixture(
    jenkins_with_proxy: JujuApplication,
    proxy_jenkins_web_address: str,
) -> jenkinsapi.jenkins.Jenkins:
    """Return an API client for the proxied Jenkins instance."""
    return generate_jenkins_client(
        jenkins_with_proxy.model,
        jenkins_with_proxy,
        proxy_jenkins_web_address,
        method=AuthMethod.PASSWORD,
    )


@pytest.fixture(scope="function", name="app_with_allowed_plugins")
def app_with_allowed_plugins_fixture(
    application: JujuApplication,
) -> Generator[JujuApplication, None, None]:
    """Configure Jenkins with the allowed plugin list."""
    application.model.config(
        application.name,
        {"allowed-plugins": ",".join(ALLOWED_PLUGINS)},
    )
    application.model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )
    yield application
    application.model.config(application.name, reset=["allowed-plugins"])


@pytest.fixture(scope="module", name="ldap_settings")
def ldap_settings_fixture() -> LDAPSettings:
    """Return LDAP settings for the test deployment."""
    return LDAPSettings(
        container_ports=[389, 636],
        username="customuser",
        password=secrets.token_hex(16),
    )


@pytest.fixture(scope="module", name="ldap_server")
def ldap_server_fixture(
    model: jubilant.Juju,
    kube_apps_client: kubernetes.client.AppsV1Api,
    ldap_settings: LDAPSettings,
) -> kubernetes.client.V1Deployment:
    """Create the LDAP test deployment."""
    container = kubernetes.client.V1Container(
        name="ldap",
        image="osixia/openldap",
        image_pull_policy="IfNotPresent",
        ports=[
            kubernetes.client.V1ContainerPort(container_port=container_port)
            for container_port in ldap_settings.container_ports
        ],
        env=[
            kubernetes.client.V1EnvVar(name="LDAP_ADMIN_USERNAME", value=ldap_settings.username),
            kubernetes.client.V1EnvVar(name="LDAP_ADMIN_PASSWORD", value=ldap_settings.password),
        ],
    )
    template = kubernetes.client.V1PodTemplateSpec(
        metadata=kubernetes.client.V1ObjectMeta(labels={"app": "ldap"}),
        spec=kubernetes.client.V1PodSpec(containers=[container]),
    )
    spec = kubernetes.client.V1DeploymentSpec(
        selector=kubernetes.client.V1LabelSelector(match_labels={"app": "ldap"}),
        template=template,
    )
    deployment = kubernetes.client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=kubernetes.client.V1ObjectMeta(name="ldap", namespace=short_model_name(model)),
        spec=spec,
    )
    return kube_apps_client.create_namespaced_deployment(
        namespace=short_model_name(model), body=deployment
    )


@pytest.fixture(scope="module", name="ldap_server_ip")
def ldap_server_ip_fixture(
    model: jubilant.Juju,
    kube_core_client: kubernetes.client.CoreV1Api,
    ldap_server: kubernetes.client.V1Deployment,
) -> str:
    """Return the ready LDAP pod IP."""
    labels = ldap_server.spec.template.metadata.labels
    assert labels
    return get_pod_ip(model, kube_core_client, labels["app"])


@pytest.fixture(scope="module", name="prometheus_related")
def prometheus_related_fixture(
    application: JujuApplication,
    model: jubilant.Juju,
) -> JujuApplication:
    """Deploy and relate Prometheus to Jenkins."""
    name = "prometheus-k8s"
    model.deploy(name, app=name, channel="1/stable", trust=True)
    model.wait(
        lambda status: jubilant.all_active(status, name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    model.integrate(f"{application.name}:metrics-endpoint", name)
    model.wait(
        lambda status: jubilant.all_active(status, name, application.name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    return application_ref(model, name)


@pytest.fixture(scope="module", name="loki_related")
def loki_related_fixture(
    application: JujuApplication,
    model: jubilant.Juju,
) -> JujuApplication:
    """Deploy and relate Loki to Jenkins."""
    name = "loki-k8s"
    model.deploy(name, app=name, channel="1/stable", trust=True)
    model.wait(
        lambda status: jubilant.all_active(status, name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    model.integrate(f"{application.name}:logging", name)
    model.wait(
        lambda status: jubilant.all_active(status, name, application.name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    return application_ref(model, name)


@pytest.fixture(scope="module", name="grafana_related")
def grafana_related_fixture(
    application: JujuApplication,
    model: jubilant.Juju,
) -> JujuApplication:
    """Deploy and relate Grafana to Jenkins."""
    name = "grafana-k8s"
    model.deploy(name, app=name, channel="1/stable", trust=True)
    model.wait(
        lambda status: jubilant.all_active(status, name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    model.integrate(f"{application.name}:grafana-dashboard", name)
    model.wait(
        lambda status: jubilant.all_active(status, name, application.name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    return application_ref(model, name)


@pytest.fixture(scope="module", name="keycloak_password")
def keycloak_password_fixture() -> str:
    """Return a random Keycloak admin password."""
    return secrets.token_hex(16)


@pytest.fixture(scope="module", name="keycloak_deployment")
def keycloak_deployment_fixture(
    model: jubilant.Juju,
    kube_apps_client: kubernetes.client.AppsV1Api,
    keycloak_password: str,
) -> kubernetes.client.V1Deployment:
    """Create the Keycloak test deployment."""
    container = kubernetes.client.V1Container(
        name="keycloak",
        image="quay.io/keycloak/keycloak",
        image_pull_policy="IfNotPresent",
        ports=[kubernetes.client.V1ContainerPort(container_port=8080)],
        args=["start-dev"],
        env=[
            kubernetes.client.V1EnvVar(name="KEYCLOAK_ADMIN", value="admin"),
            kubernetes.client.V1EnvVar(name="KEYCLOAK_ADMIN_PASSWORD", value=keycloak_password),
            kubernetes.client.V1EnvVar(name="KC_PROXY", value="edge"),
        ],
        readiness_probe=kubernetes.client.V1Probe(
            http_get=kubernetes.client.V1HTTPGetAction(path="/realms/master", port=8080)
        ),
    )
    template = kubernetes.client.V1PodTemplateSpec(
        metadata=kubernetes.client.V1ObjectMeta(labels={"app": "keycloak"}),
        spec=kubernetes.client.V1PodSpec(containers=[container]),
    )
    spec = kubernetes.client.V1DeploymentSpec(
        selector=kubernetes.client.V1LabelSelector(match_labels={"app": "keycloak"}),
        template=template,
    )
    deployment = kubernetes.client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=kubernetes.client.V1ObjectMeta(
            name="keycloak", namespace=short_model_name(model)
        ),
        spec=spec,
    )
    kube_apps_client.create_namespaced_deployment(
        namespace=short_model_name(model), body=deployment
    )
    return deployment


@pytest.fixture(scope="module", name="keycloak_ip")
def keycloak_ip_fixture(
    model: jubilant.Juju,
    kube_core_client: kubernetes.client.CoreV1Api,
    keycloak_deployment: kubernetes.client.V1Deployment,
) -> str:
    """Return the ready Keycloak pod IP."""
    labels = keycloak_deployment.spec.template.metadata.labels
    assert labels
    return get_pod_ip(model, kube_core_client, labels["app"])


@pytest.fixture(scope="module", name="keycloak_oidc_meta")
def keycloak_oidc_meta_fixture(
    keycloak_ip: str,
    keycloak_password: str,
) -> KeycloakOIDCMetadata:
    """Create the Keycloak realm, client, and test user."""
    server_url = f"http://{keycloak_ip}:8080"
    keycloak_connection = KeycloakOpenIDConnection(
        server_url=server_url,
        username="admin",
        password=keycloak_password,
        realm_name="master",
        verify=True,
    )
    keycloak_admin = KeycloakAdmin(connection=keycloak_connection)
    keycloak_admin.create_realm(
        payload={"realm": (realm := "oidc_test"), "enabled": True}, skip_exists=True
    )
    keycloak_admin.connection.realm_name = "oidc_test"
    keycloak_id = keycloak_admin.create_client(
        payload={
            "protocol": "openid-connect",
            "clientId": (client_id := "oidc_test"),
            "name": "oidc_test",
            "description": "oidc_test",
            "publicClient": False,
            "authorizationServicesEnabled": False,
            "serviceAccountsEnabled": False,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": True,
            "frontchannelLogout": True,
            "attributes": {
                "saml_idp_initiated_sso_url_name": "",
                "oauth2.device.authorization.grant.enabled": False,
                "oidc.ciba.grant.enabled": False,
            },
            "alwaysDisplayInConsole": False,
            "rootUrl": "",
            "baseUrl": "",
            "redirectUris": ["*"],
        },
        skip_exists=True,
    )
    client_secret = keycloak_admin.get_client_secrets(client_id=keycloak_id)["value"]
    keycloak_admin.create_user(
        {
            "email": "example@example.com",
            "username": (username := "example@example.com"),
            "enabled": True,
            "firstName": "Example",
            "lastName": "Example",
            "credentials": [{"value": keycloak_password, "type": "password"}],
        }
    )
    return KeycloakOIDCMetadata(
        username=username,
        password=keycloak_password,
        realm=realm,
        client_id=client_id,
        client_secret=client_secret,
        well_known_endpoint=f"{server_url}/realms/{realm}/.well-known/openid-configuration",
    )


@pytest.fixture(scope="module", name="external_hostname")
def external_hostname_fixture() -> str:
    """Return the external hostname for ingress tests."""
    return "juju.test"


@pytest.fixture(scope="module", name="traefik_application_and_unit_ip")
def traefik_application_fixture(
    model: jubilant.Juju,
) -> tuple[JujuApplication, str]:
    """Deploy Traefik and return its application plus unit address."""
    name = "traefik-k8s"
    model.deploy(
        name,
        app=name,
        channel="edge",
        trust=True,
        config={"routing_mode": "path"},
    )
    model.wait(
        lambda status: jubilant.all_active(status, name),
        error=jubilant.any_error,
        timeout=30 * 60,
    )
    return application_ref(model, name), get_model_unit_address(model, name)
