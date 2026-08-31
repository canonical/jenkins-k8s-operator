# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for jenkins-k8s charm tests."""

import pytest


def pytest_addoption(parser: pytest.Parser):
    """Parse additional pytest options.

    Args:
        parser: pytest command line parser.
    """
    # The model to use. The CI spread task supplies the pre-provisioned
    # Canonical Kubernetes model.
    parser.addoption("--model", action="store", default=None)
    parser.addoption("--keep-models", action="store_true", default=False)
    # Optional local charm artifact override. CI resolves the charm from
    # artifacts.build.yaml through pytest-opcli.
    parser.addoption("--jenkins-charm-file", action="store", default="")
    # Optional Jenkins image name:tag override for local runs. CI resolves it
    # from artifacts.build.yaml through pytest-opcli.
    parser.addoption("--jenkins-image", action="store", default="")
    # The path to Kubernetes config.
    parser.addoption("--kube-config", action="store", default="~/.kube/config")
    # The number of jenkins agents to deploy and relate.
    parser.addoption("--num-units", action="store", default="2")
