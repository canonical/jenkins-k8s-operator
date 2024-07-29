# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for jenkins-k8s charm tests."""

import pytest


def pytest_addoption(parser: pytest.Parser):
    """Parse additional pytest options.

    Args:
        parser: pytest command line parser.
    """
    # The prebuilt charm file.
    parser.addoption("--charm-file", action="append", default=[])
    # The Jenkins image name:tag.
    parser.addoption("--jenkins-image", action="store", default="")
    # The path to kubernetes config.
    parser.addoption("--kube-config", action="store", default="~/.kube/config")
    # The number of jenkins agents to deploy and relate.
    parser.addoption("--num-units", action="store", default="2")
