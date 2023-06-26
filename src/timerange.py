# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The module for checking time ranges."""
import typing
from datetime import datetime

from pydantic import BaseModel, ValidationError, root_validator


class UpdateTimeRange(BaseModel):
    """Time range to allow Jenkins to update version.

    Attrs:
        start: Hour to allow updates from in UTC time, in 24 hour format.
        end: Hour to allow updates until in UTC time, in 24 hour format.
    """

    start: int
    end: int

    # Pflake8 & pylint don't quite understand that this is a classmethod using Pydantic.
    @root_validator
    def validate_range(  # pylint: disable=no-self-argument
        cls: "UpdateTimeRange", values: dict  # noqa: N805
    ) -> dict:
        """Validate the time range.

        Args:
            values: The value keys of the model.

        Returns:
            A dictionary validated values.

        Raises:
            ValueError: if the time range are out of bounds of 24H format.
        """
        # it is okay to cast it since the field level validation has ran before root validation.
        start = typing.cast(int, values["start"])
        end = typing.cast(int, values["end"])
        if start < 0 or start > 23 or end < 0 or end > 23:
            raise ValueError("Time range out of 24 hour bounds.")
        if start == end:
            raise ValueError("Time range cannot be equal. Minimum 1 hour range is required.")
        return values

    @classmethod
    def from_str(cls, time_range: typing.Optional[str]) -> typing.Optional["UpdateTimeRange"]:
        """Instantiate the class from string time range.

        Args:
            time_range: The time range string in H(H)-H(H) format, in UTC.

        Raises:
            ValueError: if invalid time range was given.

        Returns:
            UpdateTimeRange: if a valid time range was given.
            None: if the input time range value is None or empty.
        """
        if not time_range:
            return None
        try:
            (start_hour, end_hour) = (int(hour) for hour in time_range.split("-"))
            update_range = cls(start=start_hour, end=end_hour)
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Invalid time range {time_range}, time range must be in 24H format"
            ) from exc
        return update_range

    def check_now(self) -> bool:
        """Check whether the current time is within the defined bounds.

        Returns:
            True if within bounds, False otherwise.
        """
        current_hour = datetime.utcnow().time().hour
        if self.start <= current_hour < self.end:
            return True
        if self.end < self.start:
            if self.end <= current_hour < self.start:
                return False
            return True
        return False
