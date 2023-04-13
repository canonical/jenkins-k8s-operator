# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for jenkins-k8s charm tests."""

import pytest


def pytest_addoption(parser: pytest.Parser):
    """Parse additional pytest options.

    Args:
        parser: pytest command line parser.
    """
    parser.addoption("--jenkins-image", action="store", default="")
    parser.addoption("--series", action="store", default="")
