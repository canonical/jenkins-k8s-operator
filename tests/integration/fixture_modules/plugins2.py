# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures used only by the second plugin integration suite."""

import logging
from pathlib import Path
from urllib.parse import urlparse

import kubernetes.client
import pytest
import yaml

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
