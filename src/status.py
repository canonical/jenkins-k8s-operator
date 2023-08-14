# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The charm status module."""

import typing

import ops


def get_priority_status(statuses: typing.Iterable[ops.StatusBase]) -> ops.StatusBase:
    """Get status to display out of all possible statuses returned by charm components.

    Args:
        statuses: Statuses returned by components of the charm.

    Returns:
        The final status to display.
    """

    def get_status_priority(status: ops.StatusBase) -> int:
        """Get status priority in numerical value.

        Args:
            status: The status to convert to priority value.

        Returns:
            The status priority value integer.
        """
        priority = {
            ops.ErrorStatus.name: 0,
            ops.BlockedStatus.name: 2,
            ops.MaintenanceStatus.name: 4,
            ops.WaitingStatus.name: 6,
            ops.ActiveStatus.name: 8,
        }.get(status.name)
        priority = typing.cast(int, priority)
        if status.message:
            return priority - 1
        return priority

    return sorted(statuses, key=get_status_priority)[0]
