# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s status unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import typing

import ops
import pytest

from status import get_priority_status


# pylint doesn't quite understand walrus operators
# pylint: disable=unused-variable,undefined-variable,too-many-locals
@pytest.mark.parametrize(
    "statuses, expected_status",
    [
        pytest.param(
            [
                expected_status := ops.BlockedStatus(),
                ops.MaintenanceStatus(),
                ops.WaitingStatus(),
                ops.ActiveStatus(),
            ],
            expected_status,
            id="all statuses in order",
        ),
        pytest.param(
            [
                ops.ActiveStatus(),
                ops.WaitingStatus(),
                ops.MaintenanceStatus(),
                expected_status := ops.BlockedStatus(),
            ],
            expected_status,
            id="all statuses in reverse",
        ),
        pytest.param(
            [
                ops.ActiveStatus(),
                # walrus operator is initialized with another status, mypy complains about
                # incompatible types in assignment
                expected_status := ops.ActiveStatus("I have a message"),  # type: ignore
            ],
            expected_status,
            id="same statuses, one with message",
        ),
        pytest.param(
            [
                expected_status := ops.ActiveStatus("I have a message"),  # type: ignore
                ops.ActiveStatus("I have a message too"),
            ],
            expected_status,
            id="same statuses with messages",
        ),
    ],
)
# pylint: enable=unused-variable,undefined-variable,too-many-locals
def test_get_priority_status(
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
