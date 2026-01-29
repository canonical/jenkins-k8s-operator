# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The module for checking time ranges."""

import typing
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError, model_validator


class InvalidTimeRangeError(Exception):
    """Represents an invalid time range."""


class Range(BaseModel):
    """Time range to allow Jenkins to update version.

    Attributes:
        start: Hour to allow updates from in UTC time, in 24 hour format.
        end: Hour to allow updates until in UTC time, in 24 hour format.
    """

    start: int = Field(..., ge=0, lt=24)
    end: int = Field(..., ge=0, lt=24)

    @model_validator(mode="after")
    def validate_range(self) -> "Range":
        """Validate the time range.

        Returns:
            The validated model instance.

        Raises:
            ValueError: if the time range are out of bounds of 24H format.
        """
        if self.start == self.end:
            raise ValueError("Time range cannot be equal. Minimum 1 hour range is required.")
        return self

    @classmethod
    def from_str(cls, time_range: str) -> "Range":
        """Instantiate the class from string time range.

        Args:
            time_range: The time range string in H(H)-H(H) format, in UTC.

        Raises:
            InvalidTimeRangeError: if invalid time range was given.

        Returns:
            UpdateTimeRange: if a valid time range was given.
        """
        try:
            (start_hour, end_hour) = (int(hour) for hour in time_range.split("-"))
        except ValueError as exc:
            raise InvalidTimeRangeError(
                f"Invalid time range {time_range}, time range must be an integer."
            ) from exc
        try:
            update_range = cls(start=start_hour, end=end_hour)
        except ValidationError as exc:
            raise InvalidTimeRangeError(
                f"Invalid time range {time_range}, time range must be between 0-23"
            ) from exc
        return update_range


def check_now_within_bound_hours(start: int, end: int) -> bool:
    """Check whether the current time is within the defined bounds.

    The bounds are defined as [start, end).

    Args:
        start: The starting bound hour (inclusive).
        end: The ending bound hour (exclusive).

    Returns:
        True if within bounds, False otherwise.
    """
    current_hour = datetime.utcnow().time().hour
    # If the range crosses midnight
    if start > end:
        return current_hour >= start or current_hour < end
    # If the range doesn't cross midnight
    return start <= current_hour < end
