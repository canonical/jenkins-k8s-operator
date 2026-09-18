# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Jenkins-k8s-operator charm integration tests."""

import logging
import os
import random
import secrets
import string
from pathlib import Path
from typing import Any, AsyncGenerator, Iterable, Optional

import jenkinsapi.jenkins
import kubernetes.config
import pytest
import pytest_asyncio
from juju.application import Application
from juju.controller import Controller
from juju.model import Model
from juju.unit import Unit
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
from pytest import FixtureRequest
from pytest_operator.plugin import OpsTest

import state

from .constants import MACHINE_CONTROLLER_NAME
from .helpers import (
    AuthMethod,
    generate_jenkins_client,
    get_model_unit_addresses,
    get_pod_ip,
)
from .types_ import KeycloakOIDCMetadata, ModelAppUnit, UnitWebClient

logger = logging.getLogger(__name__)

KUBECONFIG = os.environ.get("TESTING_KUBECONFIG", "~/.kube/config")
DATA_DIR = Path(__file__).parent / "data"


async def charm_exec(ops_test: OpsTest, unit_name: str, cmd: str) -> None:
    """Execute a command in the charm container via juju ssh.

    Args:
        ops_test: OpsTest fixture for juju CLI access.
        unit_name: Name of the unit (e.g., "jenkins-k8s/0").
        cmd: Command to execute in the charm container.

    Raises:
        AssertionError: If the command fails (non-zero exit code).
    """
    ret, _, stderr = await ops_test.juju(
        "ssh", "--container", "charm", unit_name, "bash", "-c", cmd
    )
    assert ret == 0, f"Command failed in charm container: {cmd}\nstderr: {stderr}"


@pytest.fixture(scope="module", name="model")
def model_fixture(ops_test: OpsTest) -> Model:
    """The testing model."""
    assert ops_test.model
    return ops_test.model


@pytest.fixture(scope="module", name="cloud")
def cloud_fixture(ops_test: OpsTest) -> Optional[str]:
    """The cloud the k8s model is running on."""
    return ops_test.cloud_name


@pytest.fixture(scope="module", name="jenkins_image")
def jenkins_image_fixture(request: FixtureRequest) -> str:
    """The OCI image for Jenkins charm (from pytest-opcli artifacts or --jenkins-image)."""
    jenkins_image = (
        request.config.getoption("--jenkins-image")
        or request.getfixturevalue("resource_images")["jenkins-image"]
    )
    assert jenkins_image, (
        "Jenkins OCI image not resolved: pass --jenkins-image or run 'opcli artifacts build' "
        "so pytest-opcli can resolve resources from artifacts.build.yaml."
    )
    return jenkins_image


@pytest.fixture(scope="module", name="num_units")
def num_units_fixture(request: FixtureRequest) -> int:
    """The OCI image for Jenkins charm."""
    return int(request.config.getoption("--num-units"))


def _select_charm_path(paths: Any) -> str:
    """Return the charm path, choosing the newest base when several are built."""
    if len(paths) == 1:
        return paths.path
    return paths[sorted(paths.bases)[-1]]


@pytest_asyncio.fixture(scope="module", name="charm")
async def charm_fixture(request: FixtureRequest, ops_test: OpsTest) -> str | Path:
    """The path to the built charm (from pytest-opcli artifacts or built locally)."""
    charm_files = request.config.getoption("--charm-file", default=None)
    if charm_files:
        return Path(request.getfixturevalue("charm_paths")["jenkins-k8s"].path)
    try:
        paths = request.getfixturevalue("charm_paths")["jenkins-k8s"]
    except (pytest.FixtureLookupError, pytest.UsageError):
        charm = await ops_test.build_charm(".")
        assert charm, "Charm not built"
        return charm
    return Path(_select_charm_path(paths))


@pytest_asyncio.fixture(scope="module", name="application")
async def application_fixture(
    ops_test: OpsTest, charm: str, model: Model, jenkins_image: str
) -> AsyncGenerator[Application, None]:
    """Deploy the charm using GitHub-hosted JCasC test data."""
    resources = {"jenkins-image": jenkins_image}
    # Deploy the charm and wait for active/idle status
    application = await model.deploy(charm, resources=resources)
    await model.wait_for_idle(
        apps=[application.name],
        raise_on_error=False,
        wait_for_active=True,
        raise_on_blocked=True,
        timeout=30 * 60,
        idle_period=30,
    )

    # slow down update-status so that it doesn't intervene currently running tests
    # don't yield inside the context since juju cleanup is not reliable.
    # model.set_config(...) also doesn't work as well as the following code.
    async with ops_test.fast_forward(fast_interval="5h", slow_interval="5h"):
        pass
    yield application


@pytest.fixture(scope="module", name="unit")
def unit_fixture(application: Application) -> Unit:
    """The Jenkins-k8s charm application unit."""
    return application.units[0]


@pytest.fixture(scope="module", name="model_app_unit")
def model_app_unit_fixture(model: Model, application: Application, unit: Unit):
    """The packaged model, application, unit of Jenkins to reduce number of parameters in tests."""
    return ModelAppUnit(model=model, app=application, unit=unit)


@pytest_asyncio.fixture(scope="function", name="unit_ip")
async def unit_ip_fixture(model: Model, application: Application):
    """Get Jenkins charm unit IP."""
    unit_ips = await get_model_unit_addresses(model=model, app_name=application.name)
    assert unit_ips, f"Unit IP address not found for {application.name}"
    logger.info(
        "phase=unit_ip_fixture model=%s app=%s resolved_ips=%s",
        model.name,
        application.name,
        unit_ips,
    )
    return unit_ips[0]


@pytest.fixture(scope="function", name="web_address")
def web_address_fixture(unit_ip: str):
    """Get Jenkins charm web address."""
    address = f"http://{unit_ip}:8080"
    logger.info("phase=web_address_fixture address=%s", address)
    return address


@pytest_asyncio.fixture(scope="function", name="jenkins_client")
async def jenkins_client_fixture(
    ops_test: OpsTest,
    application: Application,
    web_address: str,
) -> jenkinsapi.jenkins.Jenkins:
    """The Jenkins API client."""
    logger.info(
        "phase=jenkins_client_fixture start model=%s app=%s web_address=%s",
        ops_test.model_name,
        application.name,
        web_address,
    )
    try:
        jenkins_client = await generate_jenkins_client(ops_test, application, web_address)
    except Exception as exc:
        logger.error(
            "phase=jenkins_client_fixture failed model=%s app=%s web_address=%s exc_type=%s exc=%s",
            ops_test.model_name,
            application.name,
            web_address,
            type(exc).__name__,
            exc,
        )
        model = ops_test.model
        if model is not None:
            try:
                status = await model.get_status()
                app_status = status.applications.get(application.name)
                unit_keys = []
                if app_status is not None and app_status.units:
                    unit_keys = sorted(app_status.units.keys())
                logger.error(
                    "phase=jenkins_client_fixture model_snapshot app=%s app_status=%s app_message=%s units=%s",
                    application.name,
                    getattr(app_status, "status", None),
                    getattr(app_status, "status_info", None),
                    unit_keys,
                )
            except Exception as status_exc:
                logger.error(
                    "phase=jenkins_client_fixture model_snapshot_failed exc_type=%s exc=%s",
                    type(status_exc).__name__,
                    status_exc,
                )
        raise
    logger.info(
        "phase=jenkins_client_fixture success model=%s app=%s web_address=%s client_baseurl=%s",
        ops_test.model_name,
        application.name,
        web_address,
        jenkins_client.baseurl,
    )
    return jenkins_client


@pytest_asyncio.fixture(scope="function", name="jenkins_user_client")
async def jenkins_user_client_fixture(
    ops_test: OpsTest, application: Application, web_address: str
) -> jenkinsapi.jenkins.Jenkins:
    """The Jenkins user client for mocking web browsing behavior."""
    # Use generic helper with admin password to reduce duplication and add retry.
    return await generate_jenkins_client(
        ops_test, application, web_address, method=AuthMethod.PASSWORD
    )


@pytest.fixture(scope="function", name="unit_web_client")
def unit_web_client_fixture(
    unit: Unit, web_address: str, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """The wrapper around unit, web_address and jenkins_client."""
    return UnitWebClient(unit=unit, web=web_address, client=jenkins_client)


@pytest.fixture(scope="function", name="app_suffix")
def app_suffix_fixture():
    """Get random 4 char length application suffix."""
    # secrets random hex cannot be used because it has chances to generate numeric only suffix
    # which will return "<application-name> is not a valid application tag"
    return "".join(random.choices(string.ascii_lowercase, k=4))  # nosec


@pytest_asyncio.fixture(scope="module", name="jenkins_k8s_agents")
async def jenkins_k8s_agents_fixture(model: Model):
    """The Jenkins k8s agent."""
    agent: Application = await model.deploy(
        "jenkins-agent-k8s",
        base="ubuntu@24.04",
        config={"jenkins_agent_labels": "k8s"},
        channel="latest/edge",
    )
    await model.wait_for_idle(apps=[agent.name], status="blocked")
    return agent


@pytest_asyncio.fixture(scope="module", name="k8s_agent_related_app")
async def k8s_agent_related_app_fixture(
    jenkins_k8s_agents: Application, application: Application, model: Model
):
    """The Jenkins-k8s server charm related to Jenkins-k8s agent charm through agent relation."""
    await model.integrate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{jenkins_k8s_agents.name}:{state.AGENT_RELATION}",
    )
    await model.wait_for_idle(
        apps=[application.name, jenkins_k8s_agents.name],
        wait_for_active=True,
        check_freq=5,
    )
    return application


@pytest_asyncio.fixture(scope="module", name="machine_controller")
async def machine_controller_fixture() -> AsyncGenerator[Controller, None]:
    """The lxd controller."""
    controller = Controller()
    await controller.connect_controller(MACHINE_CONTROLLER_NAME)
    yield controller
    await controller.disconnect()


@pytest_asyncio.fixture(scope="module", name="machine_model")
async def machine_model_fixture(
    request: pytest.FixtureRequest,
    machine_controller: Controller,
) -> AsyncGenerator[Model, None]:
    """The machine model for jenkins agent machine charm."""
    machine_model_name = f"jenkins-agent-machine-{secrets.token_hex(2)}"
    model = await machine_controller.add_model(machine_model_name)
    await model.connect(f"{MACHINE_CONTROLLER_NAME}:admin/{model.name}")
    yield model
    if not request.config.option.keep_models:
        await machine_controller.destroy_models(
            model.name, destroy_storage=True, force=True, max_wait=10 * 60
        )
    await model.disconnect()


@pytest_asyncio.fixture(scope="function", name="jenkins_machine_agents")
async def jenkins_machine_agents_fixture(
    machine_model: Model, num_units: int, app_suffix: str
) -> AsyncGenerator[Application, None]:
    """The jenkins machine agent with 3 units to be used for new agent relation."""
    # 2023-06-02 use the edge version of jenkins agent until the changes have been promoted to
    # stable.
    app: Application = await machine_model.deploy(
        "jenkins-agent",
        channel="latest/edge",
        config={"jenkins_agent_labels": "machine"},
        application_name=f"jenkins-agent-{app_suffix}",
        num_units=num_units,
    )
    await machine_model.create_offer(f"{app.name}:{state.AGENT_RELATION}", state.AGENT_RELATION)
    await machine_model.wait_for_idle(
        apps=[app.name], status="blocked", idle_period=30, timeout=1200, check_freq=5
    )
    yield app


@pytest_asyncio.fixture(scope="function", name="machine_agent_related_app")
async def machine_agent_related_app_fixture(
    jenkins_machine_agents: Application, application: Application, model: Model
):
    """The Jenkins-k8s server charm related to Jenkins agent charm through agent relation."""
    machine_model: Model = jenkins_machine_agents.model
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, check_freq=5
    )
    await model.integrate(
        f"{application.name}:{state.AGENT_RELATION}",
        f"{MACHINE_CONTROLLER_NAME}:admin/{machine_model.name}.{state.AGENT_RELATION}",
    )
    await machine_model.wait_for_idle(
        apps=[jenkins_machine_agents.name], wait_for_active=True, check_freq=5
    )
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
    yield application


@pytest.fixture(scope="function", name="update_status_env")
def update_status_env_fixture(model: Model, unit: Unit) -> Iterable[str]:
    """The environment variables for executing Juju hooks."""
    return (
        "JUJU_DISPATCH_PATH=hooks/update-status",
        f"JUJU_MODEL_NAME={model.name}",
        f"JUJU_UNIT_NAME={unit.name}",
    )


@pytest.fixture(scope="module", name="kube_config")
def kube_config_fixture(request: FixtureRequest) -> str:
    """The kubernetes config file path."""
    kube_config = request.config.getoption("--kube-config")
    assert kube_config, (
        "--kube-confg argument is required which should contain the path to kube config."
    )
    return kube_config


@pytest.fixture(scope="module", name="kube_core_client")
def kube_core_client_fixture(kube_config: str) -> kubernetes.client.CoreV1Api:
    """Create a kubernetes client for core v1 API."""
    kubernetes.config.load_kube_config(config_file=kube_config)
    return kubernetes.client.CoreV1Api()


@pytest.fixture(scope="module", name="kube_apps_client")
def kube_apps_client_fixture(kube_config: str) -> kubernetes.client.AppsV1Api:
    """Create a kubernetes client for apps v1 API."""
    kubernetes.config.load_kube_config(config_file=kube_config)
    return kubernetes.client.AppsV1Api()


@pytest.fixture(scope="module", name="keycloak_password")
def keycloak_password_fixture() -> str:
    """The keycloak admin user password."""
    return secrets.token_hex(16)


@pytest_asyncio.fixture(scope="module", name="keycloak_deployment")
async def keycloak_deployment_fixture(
    model: Model, kube_apps_client: kubernetes.client.AppsV1Api, keycloak_password: str
) -> kubernetes.client.V1Deployment:
    """Testing Keycloak server deployment for oidc."""
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
        metadata=kubernetes.client.V1ObjectMeta(name="keycloak", namespace=model.name),
        spec=spec,
    )
    kube_apps_client.create_namespaced_deployment(namespace=model.name, body=deployment)
    return deployment


@pytest_asyncio.fixture(scope="module", name="keycloak_ip")
async def keycloak_ip_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    keycloak_deployment: kubernetes.client.V1Deployment,
) -> str:
    """The keycloak deployment pod IP."""
    return await get_pod_ip(
        model,
        kube_core_client,
        keycloak_deployment.spec.template.metadata.labels["app"],
    )


@pytest_asyncio.fixture(scope="module", name="keycloak_oidc_meta")
async def keycloak_oidc_meta_fixture(
    keycloak_ip: str,
    keycloak_password: str,
) -> KeycloakOIDCMetadata:
    """The keycloak user."""
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
            "credentials": [
                {
                    "value": keycloak_password,
                    "type": "password",
                }
            ],
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


@pytest_asyncio.fixture(scope="module", name="external_hostname")
def external_hostname_fixture() -> str:
    """Return the external hostname for ingress-related tests."""
    return "juju.test"
