# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Constants for Jenkins-k8s-operator charm integration tests."""

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
