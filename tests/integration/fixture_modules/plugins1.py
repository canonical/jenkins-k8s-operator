# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures used only by the first plugin integration suite."""

import secrets
from typing import AsyncGenerator

import kubernetes
import kubernetes.client
import pytest
import pytest_asyncio
import requests
from juju.application import Application
from juju.model import Model

from ..constants import ALLOWED_PLUGINS
from ..helpers import get_pod_ip
from ..types_ import LDAPSettings


@pytest_asyncio.fixture(scope="function", name="app_with_allowed_plugins")
async def app_with_allowed_plugins_fixture(
    application: Application, web_address: str, model: Model
) -> AsyncGenerator[Application, None]:
    """Jenkins charm with plugins configured."""
    await application.set_config({"allowed-plugins": ",".join(ALLOWED_PLUGINS)})
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
    await model.block_until(
        lambda: requests.get(web_address, timeout=10).status_code == 403,
        timeout=60 * 10,
        wait_period=10,
    )
    yield application
    await application.reset_config(to_default=["allowed-plugins"])


@pytest.fixture(scope="module", name="ldap_settings")
def ldap_settings_fixture() -> LDAPSettings:
    """LDAP user for testing."""
    return LDAPSettings(
        container_ports=[389, 636],
        username="customuser",
        password=secrets.token_hex(16),
    )


@pytest_asyncio.fixture(scope="module", name="ldap_server")
async def ldap_server_fixture(
    model: Model,
    kube_apps_client: kubernetes.client.AppsV1Api,
    ldap_settings: LDAPSettings,
):
    """Testing LDAP server pod."""
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
        metadata=kubernetes.client.V1ObjectMeta(name="ldap", namespace=model.name),
        spec=spec,
    )
    return kube_apps_client.create_namespaced_deployment(namespace=model.name, body=deployment)


@pytest_asyncio.fixture(scope="module", name="ldap_server_ip")
async def ldap_server_ip_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    ldap_server: kubernetes.client.V1Deployment,
) -> str:
    """The LDAP deployment pod ip.

    Localhost is, by default, added to NO_PROXY by juju, hence the pod ip has to be used.
    """
    spec: kubernetes.client.V1DeploymentSpec = ldap_server.spec
    template: kubernetes.client.V1PodTemplateSpec = spec.template
    metadata: kubernetes.client.V1ObjectMeta = template.metadata
    return await get_pod_ip(model, kube_core_client, metadata.labels["app"])
