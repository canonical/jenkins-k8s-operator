# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures used only by the core Jenkins integration tests."""

import os
from typing import Iterable

import pytest
import pytest_asyncio
from juju.application import Application
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from ..conftest import DEFAULT_TEST_JCASC_REPOSITORY


@pytest.fixture(scope="module", name="test_jcasc_repository")
def test_jcasc_repository_fixture() -> str:
    """Return the trusted repository used by the JCasC integration test."""
    return os.environ.get("TEST_JCASC_REPOSITORY", DEFAULT_TEST_JCASC_REPOSITORY)


@pytest.fixture(scope="module", name="freeze_time")
def freeze_time_fixture() -> str:
    """The time string to freeze the charm time."""
    return "2022-01-01 15:00:00"


@pytest_asyncio.fixture(scope="function", name="app_with_restart_time_range")
async def app_with_restart_time_range_fixture(application: Application):
    """Application with restart-time-range configured."""
    await application.set_config({"restart-time-range": "03-05"})
    yield application
    await application.reset_config(["restart-time-range"])


@pytest_asyncio.fixture(scope="function", name="libfaketime_unit")
async def libfaketime_unit_fixture(ops_test: OpsTest, unit: Unit) -> Unit:
    """Unit with libfaketime installed."""
    await ops_test.juju("run", "--unit", f"{unit.name}", "--", "apt", "update")
    await ops_test.juju(
        "run", "--unit", f"{unit.name}", "--", "apt", "install", "-y", "libfaketime"
    )
    return unit


@pytest.fixture(scope="function", name="libfaketime_env")
def libfaketime_env_fixture(freeze_time: str) -> Iterable[str]:
    """The environment variables for using libfaketime."""
    return (
        'LD_PRELOAD="/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"',
        f'FAKETIME="@{freeze_time}"',
    )
