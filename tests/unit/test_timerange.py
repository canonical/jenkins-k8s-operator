# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s time range module tests."""

import unittest.mock

import pytest

import timerange


@pytest.mark.parametrize(
    "time_range",
    [
        pytest.param("-1-0", id="invalid time range"),
        pytest.param("-1-3", id="negative time range"),
        pytest.param("00-24", id="Out of 24H scale"),
        pytest.param("23", id="Not a range"),
        pytest.param("23-23", id="Same time given as range"),
        pytest.param("00:01-00:02", id="Hour:minute format"),
        pytest.param("3PM-4PM", id="Non 24H format"),
        pytest.param("01--02", id="Invalid input (extra dash)"),
        pytest.param("2023‐06‐20T15:31:23Z-2023‐09‐20T15:31:23Z", id="ISO timestamp range"),
    ],
)
def test_restart_time_range_invalid_time(time_range: str):
    """
    arrange: given an invalid time ranges.
    act: when timerange.Range class is instantiated through from_string method.
    assert: ValueError is raised.
    """
    with pytest.raises(timerange.InvalidTimeRangeError):
        timerange.Range.from_str(time_range)


@pytest.mark.parametrize(
    "time_range, expected_range",
    [
        pytest.param("00-03", (0, 3), id="valid time range single digits"),
        pytest.param("0-1", (0, 1), id="valid time range single digits(single hour)"),
        pytest.param("21-3", (21, 3), id="overnight"),
        pytest.param("21-03", (21, 3), id="overnight double digit"),
        pytest.param("23-00", (23, 0), id="midnight edge probe"),
    ],
)
def test_restart_time_range_valid_time(time_range: str, expected_range: tuple[int, int]):
    """
    arrange: given a valid time range.
    act: when UpdateTimeRange class is instantiated through from_string method.
    assert: no exceptions are raised.
    """
    restart_time_range = timerange.Range.from_str(time_range)
    assert restart_time_range, "Expected time range to not be None."

    assert restart_time_range.start == expected_range[0], "Unexpected start time."
    assert restart_time_range.end == expected_range[1], "Unexpected end time."


@pytest.mark.parametrize(
    "patch_hour,time_range,expected_result",
    [
        pytest.param(2, "3-5", False, id="before start hour"),
        pytest.param(3, "3-5", True, id="start hour"),
        pytest.param(4, "3-5", True, id="between start-end"),
        pytest.param(5, "3-5", False, id="end hour"),
        pytest.param(22, "23-1", False, id="overnight(before cutoff)"),
        pytest.param(23, "23-1", True, id="overnight(on start hour)"),
        pytest.param(0, "23-1", True, id="overnight(midnight)"),
        pytest.param(1, "23-1", False, id="out of overnight range(edge)"),
        pytest.param(2, "23-1", False, id="out of overnight range(after)"),
    ],
)
def test_restart_time_range_check_now(
    patch_hour: int, time_range: str, expected_result: bool, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: given a monkeypatched utcnow and a time range pair.
    act: when check_now is called.
    assert: expected value returning whether now is within time range is returned.
    """
    mock_datetime = unittest.mock.MagicMock(spec=timerange.datetime)
    test_time = timerange.datetime(2023, 1, 1, patch_hour)
    mock_datetime.utcnow.return_value = test_time
    monkeypatch.setattr(timerange, "datetime", mock_datetime)

    restart_time_range = timerange.Range.from_str(time_range)
    assert restart_time_range, "Expected time range to not be None."

    assert (
        timerange.check_now_within_bound_hours(restart_time_range.start, restart_time_range.end)
        == expected_result
    )
