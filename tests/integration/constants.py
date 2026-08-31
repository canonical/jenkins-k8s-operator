# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Constants for Jenkins-k8s-operator charm integration tests."""

# Concierge names the controller bootstrapped on its LXD provider this way.
# The Kubernetes tests run on ``concierge-k8s`` while machine agents run on
# this separate controller.
LXD_CONTROLLER_NAME = "concierge-lxd"
K8S_CONTROLLER_NAME = "concierge-k8s"

ALLOWED_PLUGINS = ("git", "blueocean", "openid")
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
