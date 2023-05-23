# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import logging
import typing

import ops

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """An unexpected data is encountered."""


class AgentMeta(typing.NamedTuple):
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


class State:
    """The Jenkins k8s operator charm state.

    Attrs:
        jnlp_port: The JNLP port to use to communicate with agents.
        num_master_executors: The number of executors for Jenkins server.
        plugins: The Jenkins plugins to install.
    """

    def __init__(
        self,
        jnlp_port: str,
        num_master_executors: int,
        plugins: typing.Iterable[str],
    ) -> None:
        """Initialize the state.

        Args:
            jnlp_port: JNLP port to communicate with agents.
            num_master_executors: The number of executors for Jenkins server.
            plugins: Jenkins plugins to install.
        """
        self._jnlp_port = jnlp_port
        self._num_master_executors = num_master_executors
        self._plugins = plugins

    @classmethod
    def from_charm(cls, charm_config: ops.ConfigData) -> "State":
        """Initialize the state from charm.

        Args:
            charm_config: Current charm configuration data.

        Returns:
            Current state of Jenkins.
        """
        num_master_executors = int(charm_config.get("master_executors", 1))
        jnlp_port = charm_config.get("jnlp_port", "48484")
        plugins_config = charm_config.get("plugins", "")
        plugins = (plugin for plugin in plugins_config.split())
        return cls(jnlp_port, num_master_executors, plugins)

    @property
    def jnlp_port(self) -> str:
        """The JNLP port to use to communicate with agents."""
        return self._jnlp_port

    @property
    def num_master_executors(self) -> int:
        """The number of executors for Jenkins server."""
        return self._num_master_executors

    @property
    def plugins(self) -> typing.Iterable[str]:
        """The Jenkins plugins to install."""
        return self._plugins
