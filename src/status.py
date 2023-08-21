# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The charm status module."""

import typing

import ops

PRIORITY_MAP = {
    ops.ErrorStatus.name: 0,
    ops.BlockedStatus.name: 2,
    ops.MaintenanceStatus.name: 4,
    ops.WaitingStatus.name: 6,
    ops.ActiveStatus.name: 8,
}


def get_priority_status(statuses: typing.Iterable[ops.StatusBase]) -> ops.StatusBase:
    """Get status to display out of all possible statuses returned by charm components.

    Args:
        statuses: Statuses returned by components of the charm.

    Returns:
        The final status to display.
    """

    return sorted(statuses, key=lambda item: (PRIORITY_MAP[item.name] - int(bool(item.message))))[
        0
    ]
