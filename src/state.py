# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import dataclasses
import logging

import ops

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class State:
    """The Jenkins k8s operator charm state.

    Attrs:
        jnlp_port: The JNLP port to use to communicate with agents.
        jenkins_service_name: The Jenkins service name. Note that the container name is the same.
    """

    jnlp_port: str
    jenkins_service_name: str = "jenkins"

    @classmethod
    def from_charm(cls, charm_config: ops.ConfigData) -> "State":
        """Initialize the state from charm.

        Args:
            charm_config: Current charm configuration data.

        Returns:
            Current state of Jenkins.
        """
        jnlp_port = charm_config.get("jnlp_port", "50000")
        return cls(jnlp_port=jnlp_port)
