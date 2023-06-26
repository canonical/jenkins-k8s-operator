# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s state module tests."""
import typing

import pytest
from ops.testing import Harness

import charm
import state


def test_state_invalid_time_config(harness: Harness):
    """
    arrange: given an invalid time charm config.
    act: when state is initialized through from_charm method.
    assert: CharmConfigInvalidError is raised.
    """
    harness.update_config({"update-time-range": "-1"})
    harness.begin()

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(typing.cast(charm.JenkinsK8sOperatorCharm, harness.charm))


@pytest.mark.parametrize(
    "time_range",
    [
        pytest.param("", id="empty string"),
        pytest.param(None, id="None"),
    ],
)
def test_no_time_range_config(time_range: typing.Optional[str], harness: Harness):
    """
    arrange: given an empty time range config value.
    act: when state is instantiated.
    assert: state without time range is returned.
    """
    harness.update_config({"update-time-range": time_range})
    harness.begin()

    assert (
        typing.cast(charm.JenkinsK8sOperatorCharm, harness.charm).state.update_time_range is None
    ), "Update time range should not be instantiated."
