# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s status unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import typing

import ops
import pytest

from status import get_priority_status


@pytest.mark.parametrize(
    "statuses, expected_status",
    [
        pytest.param(
            [
                ops.BlockedStatus(),
                ops.MaintenanceStatus(),
                ops.WaitingStatus(),
                ops.ActiveStatus(),
            ],
            ops.BlockedStatus(),
            id="all statuses in order",
        ),
        pytest.param(
            [
                ops.ActiveStatus(),
                ops.WaitingStatus(),
                ops.MaintenanceStatus(),
                ops.BlockedStatus(),
            ],
            ops.BlockedStatus(),
            id="all statuses in reverse",
        ),
        pytest.param(
            [
                ops.ActiveStatus(),
                ops.ActiveStatus("I have a message"),
            ],
            ops.ActiveStatus("I have a message"),
            id="same statuses, one with message",
        ),
        pytest.param(
            [
                ops.ActiveStatus("I have a message"),
                ops.ActiveStatus("I have a message too"),
            ],
            ops.ActiveStatus("I have a message"),
            id="same statuses with messages",
        ),
    ],
)
def test__get_priority_status(
    statuses: typing.Iterable[ops.StatusBase],
    expected_status: ops.StatusBase,
):
    """
    arrange: given a statuses with/without status message.
    act: when get_priority_status is called.
    assert: the status message with highest priority is returned.
    """
    status = get_priority_status(statuses)

    assert expected_status == status
