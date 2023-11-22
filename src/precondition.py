# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The Jenkins charm precondition checking module."""
import ops

import state


class ConditionCheckError(Exception):
    """Represents an error with charm state."""

    def __init__(self, msg: str = ""):
        """Initialize a new instance of the ConditionCheckBaseError exception.

        Args:
            msg: Explanation of the error.
        """
        self.msg = msg


def _check_storage(charm: ops.CharmBase, charm_state: state.State) -> None:
    """Check if the storage has been mounted.

    Args:
        charm: The Jenkins charm.
        charm_state: The charm state.

    Raises:
        ConditionCheckError: if the storage has not yet been mounted.
    """
    storages = charm.model.storages.get(charm_state.storage_name)
    if not storages:
        raise ConditionCheckError(f"Charm storage {charm_state.storage_name} not yet ready.")


def _check_container(charm: ops.CharmBase, charm_state: state.State) -> None:
    """Check if the pebble workload container is ready.

    Args:
        charm: The Jenkins charm.
        charm_state: The charm state.

    Raises:
        ConditionCheckError: if the pebble workload container is not yet ready.
    """
    container = charm.unit.get_container(charm_state.jenkins_service_name)
    if not container or not container.can_connect():
        raise ConditionCheckError(
            f"Workload container {charm_state.jenkins_service_name} not yet ready."
        )


def check(charm: ops.CharmBase, charm_state: state.State) -> None:
    """Check all preconditions required to start the Jenkins service.

    Args:
        charm: The Jenkins charm.
        charm_state: The charm state.
    """
    _check_container(charm, charm_state)
    _check_storage(charm, charm_state)
