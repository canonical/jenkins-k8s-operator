# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import dataclasses
import logging
import typing

from ops.charm import CharmBase

from timerange import InvalidTimeRangeError, Range

logger = logging.getLogger(__name__)

AGENT_RELATION = "agent"
SLAVE_RELATION = "slave"


class CharmStateBaseError(Exception):
    """Represents an error with charm state."""


class CharmConfigInvalidError(CharmStateBaseError):
    """Exception raised when a charm configuration is found to be invalid.

    Attributes:
        msg: Explanation of the error.
    """

    def __init__(self, msg: str):
        """Initialize a new instance of the CharmConfigInvalidError exception.

        Args:
            msg: Explanation of the error.
        """
        self.msg = msg


@dataclasses.dataclass(frozen=True)
class State:
    """The Jenkins k8s operator charm state.

    Attributes:
        jenkins_service_name: The Jenkins service name. Note that the container name is the same.
        update_time_range: Time range to allow Jenkins to update version.
    """

    update_time_range: typing.Optional[Range]
    jenkins_service_name: str = "jenkins"

    @classmethod
    def from_charm(cls, charm: CharmBase) -> "State":
        """Initialize the state from charm.

        Args:
            charm: The charm root JenkinsK8SOperatorCharm.

        Returns:
            Current state of Jenkins.

        Raises:
            CharmConfigInvalidError: if invalid state values were encountered.
        """
        time_range_str = charm.config.get("update-time-range")
        if time_range_str:
            try:
                update_time_range = Range.from_str(time_range_str)
            except InvalidTimeRangeError as exc:
                logger.error("Invalid config value for update-time-range, %s", exc)
                raise CharmConfigInvalidError(
                    "Invalid config value for update-time-range."
                ) from exc
        else:
            update_time_range = None

        return cls(update_time_range=update_time_range)
