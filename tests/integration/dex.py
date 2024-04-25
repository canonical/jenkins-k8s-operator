# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""DEX deployment and utilities for testing."""

import logging
from os.path import join
from pathlib import Path
from time import sleep
from typing import List, Optional

import requests
from lightkube import Client, codecs
from lightkube.core.exceptions import ApiError, ObjectDeleted
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import Pod, Service
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


DEX_MANIFESTS = Path(__file__).parent / "files" / "dex.yaml"


def get_dex_manifest(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    issuer_url: Optional[str] = None,
) -> List[codecs.AnyResource]:
    """Get the DEX manifest interpolating the needed variables.

    Args:
        client_id: client ID.
        client_secret: client secret.
        redirect_uri: redirect URI.
        issuer_url: issuer URL.

    Returns:
        the list of created resources.
    """
    with open(DEX_MANIFESTS, "r", encoding="utf-8") as file:
        return codecs.load_all_yaml(
            file,
            context={
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "issuer_url": issuer_url,
            },
        )


def _restart_dex(client: Client) -> None:
    """Restart the DEX pods.

    Args:
        client: k8s client.
    """
    for pod in client.list(Pod, namespace="dex", labels={"app": "dex"}):
        # mypy doesn't work well with lightkube
        client.delete(Pod, pod.metadata.name, namespace="dex")  # type: ignore


def _wait_until_dex_is_ready(client: Client, issuer_url: Optional[str] = None) -> None:
    """Wait for DEX to be up.

    Args:
        client: k8s client.
        issuer_url: issuer URL.

    Raises:
        RuntimeError: if DEX fails to start.
    """
    for pod in client.list(Pod, namespace="dex", labels={"app": "dex"}):
        # Some pods may be deleted, if we are restarting
        try:
            # mypy doesn't work well with lightkube
            client.wait(
                Pod,
                pod.metadata.name,  # type: ignore
                for_conditions=["Ready", "Deleted"],
                namespace="dex",
            )
        except ObjectDeleted:
            pass
    client.wait(Deployment, "dex", namespace="dex", for_conditions=["Available"])
    if not issuer_url:
        issuer_url = get_dex_service_url(client)

    resp = requests.get(join(issuer_url, ".well-known/openid-configuration"), timeout=5)
    if resp.status_code != 200:
        raise RuntimeError("Failed to deploy dex")


def wait_until_dex_is_ready(client: Client, issuer_url: Optional[str] = None) -> None:
    """Wait for DEX to be up.

    Args:
        client: k8s client.
        issuer_url: issuer URL.
    """
    try:
        _wait_until_dex_is_ready(client, issuer_url)
    except (RuntimeError, RequestException):
        # It may take some time for dex to restart, so we sleep a little
        # and try again
        sleep(3)
        _wait_until_dex_is_ready(client, issuer_url)


def _apply_dex_manifests(
    client: Client,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    issuer_url: Optional[str],
) -> None:
    """Apply the DEX manifest definitions.

    Args:
        client: k8s client.
        client_id: client ID.
        client_secret: client secret.
        redirect_uri: redirect URI.
        issuer_url: issuer URL.
    """
    objs = get_dex_manifest(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        issuer_url=issuer_url,
    )

    for obj in objs:
        client.apply(obj, force=True)


def create_dex_resources(
    client: Client,
    client_id: str = "client_id",
    client_secret: str = "client_secret",  # nosec
    redirect_uri: str = "",
    issuer_url: Optional[str] = None,
):
    """Apply the DEX manifest definitions and wait for DEX to be up.

    Args:
        client: k8s client.
        client_id: client ID.
        client_secret: client secret.
        redirect_uri: redirect URI.
        issuer_url: issuer URL.
    """
    _apply_dex_manifests(
        client,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        issuer_url=issuer_url,
    )

    logger.info("Waiting for dex to be ready")
    wait_until_dex_is_ready(client, issuer_url)


def apply_dex_resources(
    client: Client,
    client_id: str = "client_id",
    client_secret: str = "client_secret",  # nosec
    redirect_uri: str = "",
    issuer_url: Optional[str] = None,
) -> None:
    """Apply the DEX manifest definitions and wait for DEX to start up.

    Args:
        client: k8s client.
        client_id: client ID.
        client_secret: client secret.
        redirect_uri: redirect URI.
        issuer_url: issuer URL.
    """
    if not issuer_url:
        try:
            issuer_url = get_dex_service_url(client)
        except ApiError:
            logger.info("No service found for dex")

    _apply_dex_manifests(
        client,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        issuer_url=issuer_url,
    )

    logger.info("Restarting dex")
    _restart_dex(client)

    logger.info("Waiting for dex to be ready")
    wait_until_dex_is_ready(client, issuer_url)


def update_redirect_uri(client: Client, redirect_uri: str) -> None:
    """Update DEX's redirect URI.

    Args:
        client: k8s client.
        redirect_uri: THE NEW REDIRECT uri.
    """
    apply_dex_resources(client, redirect_uri=redirect_uri)


def get_dex_service_url(client: Client) -> str:
    """Get the DEX service URL.

    Args:
        client: k8s client.

    Returns:
        the service URL.
    """
    service = client.get(Service, "dex", namespace="dex")
    # mypy doesn't work well with lightkube
    return f"http://{service.status.loadBalancer.ingress[0].ip}:5556/"  # type: ignore
