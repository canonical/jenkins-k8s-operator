# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The charm precondition checker."""

import logging
from dataclasses import dataclass

import ops

logger = logging.getLogger(__name__)

JENKINS_HOME_STORAGE_NAME = "jenkins-home"


@dataclass
class _CheckResult:
    """Precondition check result.

    Attributes:
        success: Whether precondition requirements have been met.
        reason: Reasons for failure if any.
    """

    success: bool
    reason: str | None


def check(*, container: ops.Container, storages: ops.StorageMapping) -> _CheckResult:
    """Check preconditions for starting charm operations.

    Args:
        container: Jenkins workload container.
        storages: Storages available for the charm unit.

    Returns:
        The condition check result.
    """
    logger.info("Running precondition check")
    failed_components: list[str] = []
    container_connectable = container.can_connect()
    logger.info("Container connectivity status: %s", container_connectable)
    if not container_connectable:
        failed_components.append("pebble")
    jenkins_home_storages = storages.get(JENKINS_HOME_STORAGE_NAME, [])
    logger.info("Available storages %s", jenkins_home_storages)
    if not jenkins_home_storages:
        failed_components.append("storage")

    if not failed_components:
        return _CheckResult(success=True, reason=None)
    return _CheckResult(success=False, reason=f"{', '.join(failed_components)} not yet ready.")
