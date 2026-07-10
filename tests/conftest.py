# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for jenkins-k8s charm tests."""

import pytest


def pytest_addoption(parser: pytest.Parser):
    """Parse additional pytest options.

    Args:
        parser: pytest command line parser.
    """
    # Guard against duplicate registration (e.g., when pytest-operator is installed).
    for option in ("--charm-file", "--jenkins-image", "--kube-config", "--num-units"):
        try:
            parser.addoption(
                option,
                action="append" if option == "--charm-file" else "store",
                default=[],
            )
        except ValueError:
            pass