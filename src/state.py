# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import dataclasses
import logging
import typing

import ops

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """An unexpected data is encountered."""


@dataclasses.dataclass(frozen=True)
class AgentMeta:
    """Metadata for registering Jenkins Agent.

    Attrs:
        executors: Number of executors of the agent in string format.
        labels: Comma separated list of labels to be assigned to the agent.
        slavehost: The host name of the agent.
    """

    executors: str
    labels: str
    slavehost: str

    def validate(self) -> None:
        """Validate the agent metadata.

        Raises:
            ValidationError: if the field contains invalid data.
        """
        # Pylint doesn't understand that _fields is implemented in NamedTuple.
        empty_fields = [
            field
            for field in self._fields  # pylint: disable=no-member
            if not getattr(self, field)
        ]
        if empty_fields:
            raise ValidationError(f"Fields {empty_fields} cannot be empty.")
        try:
            int(self.executors)
        except ValueError as exc:
            raise ValidationError(
                f"Number of executors {self.executors} cannot be converted to type int."
            ) from exc


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
