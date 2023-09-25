# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Constants for Jenkins-k8s-operator charm integration tests."""

ALLOWED_PLUGINS = ("git",)
INSTALLED_PLUGINS = ("git", "timestamper")
REMOVED_PLUGINS = set(INSTALLED_PLUGINS) - set(ALLOWED_PLUGINS)
