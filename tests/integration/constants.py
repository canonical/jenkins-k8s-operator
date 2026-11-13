# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Constants for Jenkins-k8s-operator charm integration tests."""

import enum

ALLOWED_PLUGINS = ("git", "blueocean", "openid")
# LXD controller name provisioned by concierge in charm-ci (local and CI runs).
MACHINE_CONTROLLER_NAME = "concierge-lxd"
TINYPROXY_PORT = 8888
INSTALLED_PLUGINS = ("git", "timestamper", "blueocean", "openid")
REMOVED_PLUGINS = set(INSTALLED_PLUGINS) - set(ALLOWED_PLUGINS)
ALL_PLUGINS = [
    "bazaar",
    "blueocean",
    "dependency-check-jenkins-plugin",
    "docker-build-publish",
    "git",
    "kubernetes",
    "ldap",
    "matrix-combinations-parameter",
    "oic-auth",
    "openid",
    "pipeline-groovy-lib",
    "postbuildscript",
    "rebuild",
    "ssh-agent",
    "thinBackup",
]
DEFAULT_SYSTEM_CONFIGURE_PAYLOAD = {
    "jenkins-model-MasterBuildConfiguration": {"numExecutors": "0"},
    "jenkins-model-GlobalComputerRetentionCheckIntervalConfiguration": {
        "computerRetentionCheckInterval": "60"
    },
    "jenkins-model-GlobalQuietPeriodConfiguration": {"quietPeriod": "5"},
    "jenkins-model-GlobalSCMRetryCountConfiguration": {"scmCheckoutRetryCount": "0"},
    "com-sonyericsson-rebuild-RebuildDescriptor": {"rememberPasswordEnabled": True},
}


class ServerRoute(enum.Enum):
    """The route that serves the Jenkins UI and API."""

    NONE = "none"
    INGRESS_ROOT = "ingress-root"
    INGRESS_PATH = "ingress-path"
    HAPROXY = "haproxy-route"


class AgentRoute(enum.Enum):
    """The route that serves agent discovery and the agent connection."""

    NONE = "none"
    SUBDOMAIN = "subdomain"
    PATH = "path"


# The server route combined with the agent route defines the single Jenkins prefix.
JenkinsRouteTopology = tuple[ServerRoute, AgentRoute]

# Mirrors the matrix in docs/adr/001_agent_ingress_path_prefix.md. Path-mode routes
# publish `/{model}-{app}`, subdomain routes publish a bare hostname.
EXPECTED_JENKINS_PREFIX: dict[JenkinsRouteTopology, str] = {
    (ServerRoute.NONE, AgentRoute.NONE): "",
    (ServerRoute.NONE, AgentRoute.SUBDOMAIN): "",
    (ServerRoute.NONE, AgentRoute.PATH): "/{model}-{app}",
    (ServerRoute.INGRESS_ROOT, AgentRoute.NONE): "",
    (ServerRoute.INGRESS_ROOT, AgentRoute.SUBDOMAIN): "",
    (ServerRoute.INGRESS_PATH, AgentRoute.PATH): "/{model}-{app}",
    (ServerRoute.HAPROXY, AgentRoute.SUBDOMAIN): "",
    (ServerRoute.HAPROXY, AgentRoute.PATH): "/{model}-{app}",
}


def expected_jenkins_prefix(
    model_name: str, application_name: str, topology: JenkinsRouteTopology
) -> str:
    """Return the Jenkins prefix the charm must apply for a route topology.

    Args:
        model_name: The model name, used by path-mode routes.
        application_name: The application name, used by path-mode routes.
        topology: The server route and agent route combination under test.

    Returns:
        The expected prefix, or an empty string for the root.
    """
    try:
        template = EXPECTED_JENKINS_PREFIX[topology]
    except KeyError as exc:
        raise KeyError(
            f"No expected Jenkins prefix for topology {topology}. "
            "Add the combination to EXPECTED_JENKINS_PREFIX and the ADR matrix."
        ) from exc
    return template.format(model=model_name, app=application_name)
