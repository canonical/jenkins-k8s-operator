# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import dataclasses
import logging

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class State:
    """The Jenkins k8s operator charm state.

    Attrs:
        jenkins_service_name: The Jenkins service name. Note that the container name is the same.
    """

    jenkins_service_name: str = "jenkins"

    @classmethod
    def from_charm(cls) -> "State":
        """Initialize the state from charm.

        Returns:
            Current state of Jenkins.
        """
        return cls()
