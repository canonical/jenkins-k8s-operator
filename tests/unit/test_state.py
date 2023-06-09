# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s state module tests."""

from unittest.mock import MagicMock

import pytest

import state


@pytest.mark.parametrize(
    "time_range",
    [
        pytest.param("-1-3", id="negative time range"),
        pytest.param("00-24", id="Out of 24H scale"),
        pytest.param("23", id="Not a range"),
        pytest.param("23-23", id="Same time given as range"),
    ],
)
def test_update_time_range_invalid_time(time_range: str):
    """
    arrange: given an invalid time ranges.
    act: when UpdateTimeRange class is instantiated through from_string method.
    assert: ValueError is raised.
    """
    with pytest.raises(ValueError):
        state.UpdateTimeRange.from_str(time_range)


@pytest.mark.parametrize(
    "time_range",
    [
        pytest.param("", id="empty string"),
        pytest.param(None, id="None"),
    ],
)
def test_update_time_range_empty_str(time_range):
    """
    arrange: given an empty time range config value.
    act: when UpdateTimeRange class is instantiated through from_string method.
    assert: None is returned.
    """
    assert (
        state.UpdateTimeRange.from_str(time_range) is None
    ), "Time range should not be instantiated."


@pytest.mark.parametrize(
    "time_range, expected_range",
    [
        pytest.param("0-3", (0, 3), id="valid time range single digits"),
        pytest.param("00-03", (0, 3), id="valid time range single digits"),
        pytest.param("21-3", (21, 3), id="overnight"),
        pytest.param("21-03", (21, 3), id="overnight double digit"),
    ],
)
def test_update_time_range_valid_time(time_range: str, expected_range: tuple[int, int]):
    """
    arrange: given a valid time range.
    act: when UpdateTimeRange class is instantiated through from_string method.
    assert: no exceptions are raised.
    """
    update_time_range = state.UpdateTimeRange.from_str(time_range)
    assert update_time_range, "Expected time range to not be None."

    assert update_time_range.start == expected_range[0], "Unexpected start time."
    assert update_time_range.end == expected_range[1], "Unexpected end time."


@pytest.mark.parametrize(
    "patch_hour,time_range,expected_result",
    [
        pytest.param(3, "3-5", True, id="start hour"),
        pytest.param(4, "3-5", True, id="between start-end"),
        pytest.param(5, "3-5", False, id="end hour"),
        pytest.param(0, "23-1", True, id="overnight midnight"),
        pytest.param(1, "23-1", False, id="out of overnight range"),
    ],
)
def test_update_time_range_check_now(
    patch_hour: int, time_range: str, expected_result: bool, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a monkeypatched utcnow and a time range pair.
    act: when check_now is called.
    assert: expected value returning whether now is within time range is returned.
    """
    mock_datetime = MagicMock(spec=state.datetime)
    test_time = state.datetime(2023, 1, 1, patch_hour)
    mock_datetime.utcnow.return_value = test_time
    monkeypatch.setattr(state, "datetime", mock_datetime)

    update_time_range = state.UpdateTimeRange.from_str(time_range)
    assert update_time_range, "Expected time range to not be None."

    assert update_time_range.check_now() == expected_result


def test_state_invalid_time_config():
    """
    arrange: given an invalid time charm config.
    act: when state is initialized through from_charm method.
    assert: CharmConfigInvalidError is raised.
    """
    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm({"update-time-range": "-1"})
