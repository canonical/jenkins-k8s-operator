# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import dataclasses
import logging
import typing

from timerange import UpdateTimeRange

if typing.TYPE_CHECKING:
    from charm import JenkinsK8SOperatorCharm

logger = logging.getLogger(__name__)


class CharmStateBaseException(Exception):
    """Represents error with charm state."""


class CharmConfigInvalidError(CharmStateBaseException):
    """Exception raised when a charm configuration is found to be invalid.

    Attrs:
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

    Attrs:
        jenkins_service_name: The Jenkins service name. Note that the container name is the same.
        update_time_range: Time range to allow Jenkins to update version.
    """

    update_time_range: typing.Optional[UpdateTimeRange]
    jenkins_service_name: str = "jenkins"

    @classmethod
    def from_charm(cls, charm: "JenkinsK8SOperatorCharm") -> "State":
        """Initialize the state from charm.

        Args:
            config: The charm configuration mapping.

        Returns:
            Current state of Jenkins.

        Raises:
            CharmConfigInvalidError: if invalid state values were encountered.
        """
        time_range_str = charm.config.get("update-time-range")
        try:
            update_time_range = UpdateTimeRange.from_str(time_range_str)
        except ValueError as exc:
            logger.error("Invalid config value for update-time-range, %s", exc)
            raise CharmConfigInvalidError("Invalid config value for update-time-range.") from exc

        return cls(update_time_range=update_time_range)
