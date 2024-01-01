# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""
import dataclasses
import functools
import logging
import os
import typing
from pathlib import Path

import ops
from pydantic import BaseModel, Field, HttpUrl, ValidationError, validator

from timerange import InvalidTimeRangeError, Range

logger = logging.getLogger(__name__)

AGENT_RELATION = "agent"
DEPRECATED_AGENT_RELATION = "agent-deprecated"
JENKINS_SERVICE_NAME = "jenkins"
JENKINS_HOME_STORAGE_NAME = "jenkins-home"
JENKINS_HOME_PATH = Path("/var/lib/jenkins")


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


class CharmRelationDataInvalidError(CharmStateBaseError):
    """Represents an error with invalid data in relation data.

    Attributes:
        msg: Explanation of the error.
    """

    def __init__(self, msg: str):
        """Initialize a new instance of the CharmRelationDataInvalidError exception.

        Args:
            msg: Explanation of the error.
        """
        self.msg = msg


class CharmIllegalNumUnitsError(CharmStateBaseError):
    """Represents an error with invalid number of units deployed.

    Attributes:
        msg: Explanation of the error.
    """

    def __init__(self, msg: str):
        """Initialize a new instance of the CharmIllegalNumUnitsError exception.

        Args:
            msg: Explanation of the error.
        """
        self.msg = msg


class AgentMeta(BaseModel):
    """Metadata for registering Jenkins Agent.

    Attributes:
        executors: Number of executors of the agent in string format.
        labels: Comma separated list of labels to be assigned to the agent.
        name: The host name of the agent.
    """

    executors: str = Field(..., min_length=1)
    labels: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)

    @validator("executors")
    # The decorated method does not need a self argument.
    def numeric_executors(cls, value: str) -> int:  # noqa: N805 pylint: disable=no-self-argument
        """Validate executors field can be converted to int.

        Args:
            value: The value of executors field.

        Returns:
            Coerced numerical value of executors.
        """
        return int(value)

    @classmethod
    def from_deprecated_agent_relation(
        cls, relation_data: ops.RelationDataContent
    ) -> typing.Optional["AgentMeta"]:
        """Instantiate AgentMeta from charm relation databag.

        Args:
            relation_data: The unit relation databag.

        Returns:
            AgentMeta if complete values(executors, labels, slavehost) are set. None otherwise.
        """
        num_executors = relation_data.get("executors")
        labels = relation_data.get("labels")
        name = relation_data.get("slavehost")
        if not num_executors or not labels or not name:
            return None
        return cls(executors=num_executors, labels=labels, name=name)

    @classmethod
    def from_agent_relation(
        cls, relation_data: ops.RelationDataContent
    ) -> typing.Optional["AgentMeta"]:
        """Instantiate AgentMeta from charm relation databag.

        Args:
            relation_data: The unit relation databag.

        Returns:
            AgentMeta if complete values(executors, labels, slavehost) are set. None otherwise.
        """
        num_executors = relation_data.get("executors")
        labels = relation_data.get("labels")
        name = relation_data.get("name")
        if not num_executors or not labels or not name:
            return None
        return cls(executors=num_executors, labels=labels, name=name)


def _is_remote_unit(app_name: str, unit: ops.Unit) -> bool:
    """Return whether the unit is a remote unit in a relation.

    Args:
        app_name: The current application name.
        unit: The unit to check in a relation.

    Returns:
        True if is remote unit. False otherwise.
    """
    return app_name not in unit.name


def _get_agent_meta_map_from_relation(
    relations: typing.List[ops.Relation], current_app_name: str
) -> typing.Optional[typing.Mapping[str, typing.Optional[AgentMeta]]]:
    """Return a mapping of unit name to AgentMetadata from agent or deprecated agent relation.

    Args:
        relations: The agent or deprecated agent relations.
        current_app_name: Current application name, i.e. "jenkins-k8s-operator".

    Returns:
        A mapping of ops.Unit to AgentMetadata.
    """
    if not relations:
        return None
    unit_metadata_mapping = {}
    for relation in relations:
        remote_units = filter(functools.partial(_is_remote_unit, current_app_name), relation.units)
        if relation.name == DEPRECATED_AGENT_RELATION:
            unit_metadata_mapping.update(
                {
                    unit.name: AgentMeta.from_deprecated_agent_relation(relation.data[unit])
                    for unit in remote_units
                }
            )
            continue
        unit_metadata_mapping.update(
            {
                unit.name: AgentMeta.from_agent_relation(relation.data[unit])
                for unit in remote_units
            }
        )
    return unit_metadata_mapping


class ProxyConfig(BaseModel):
    """Configuration for accessing Jenkins through proxy.

    Attributes:
        http_proxy: The http proxy URL.
        https_proxy: The https proxy URL.
        no_proxy: Comma separated list of hostnames to bypass proxy.
    """

    http_proxy: typing.Optional[HttpUrl]
    https_proxy: typing.Optional[HttpUrl]
    no_proxy: typing.Optional[str]

    @classmethod
    def from_env(cls) -> typing.Optional["ProxyConfig"]:
        """Instantiate ProxyConfig from juju charm environment.

        Returns:
            ProxyConfig if proxy configuration is provided, None otherwise.
        """
        http_proxy = os.environ.get("JUJU_CHARM_HTTP_PROXY")
        https_proxy = os.environ.get("JUJU_CHARM_HTTPS_PROXY")
        no_proxy = os.environ.get("JUJU_CHARM_NO_PROXY")
        if not http_proxy and not https_proxy:
            return None
        # Mypy doesn't understand str is supposed to be converted to HttpUrl by Pydantic.
        return cls(
            http_proxy=http_proxy, https_proxy=https_proxy, no_proxy=no_proxy  # type: ignore
        )


def _is_storage_ready(charm: ops.CharmBase) -> bool:
    """Return whether the Jenkins home storage is mounted.

    Args:
        charm: The Jenkins k8s charm.

    Returns:
        True if storage is mounted, False otherwise.
    """
    container = charm.unit.get_container(JENKINS_SERVICE_NAME)
    if not container.can_connect():
        return False
    mount_info: str = container.pull("/proc/mounts").read()
    return str(JENKINS_HOME_PATH) in mount_info


@dataclasses.dataclass(frozen=True)
class State:
    """The Jenkins k8s operator charm state.

    Attributes:
        restart_time_range: Time range to allow Jenkins to update version.
        agent_relation_meta: Metadata of all agents from units related through agent relation.
        deprecated_agent_relation_meta: Metadata of all agents from units related through
            deprecated agent relation.
        is_storage_ready: Whether the Jenkins home storage is mounted.
        proxy_config: Proxy configuration to access Jenkins upstream through.
        plugins: The list of allowed plugins to install.
    """

    restart_time_range: typing.Optional[Range]
    agent_relation_meta: typing.Optional[typing.Mapping[str, typing.Optional[AgentMeta]]]
    deprecated_agent_relation_meta: typing.Optional[
        typing.Mapping[str, typing.Optional[AgentMeta]]
    ]
    proxy_config: typing.Optional[ProxyConfig]
    plugins: typing.Optional[typing.Iterable[str]]
    is_storage_ready: bool

    @classmethod
    def from_charm(cls, charm: ops.CharmBase) -> "State":
        """Initialize the state from charm.

        Args:
            charm: The charm root JenkinsK8SOperatorCharm.

        Returns:
            Current state of Jenkins.

        Raises:
            CharmConfigInvalidError: if invalid state values were encountered.
            CharmRelationDataInvalidError: if invalid relation data was received.
            CharmIllegalNumUnitsError: if more than 1 unit of Jenkins charm is deployed.
        """
        time_range_str = charm.config.get("restart-time-range")
        if time_range_str:
            try:
                restart_time_range = Range.from_str(time_range_str)
            except InvalidTimeRangeError as exc:
                logger.error("Invalid config value for restart-time-range, %s", exc)
                raise CharmConfigInvalidError(
                    "Invalid config value for restart-time-range."
                ) from exc
        else:
            restart_time_range = None

        try:
            agent_relation_meta_map = _get_agent_meta_map_from_relation(
                charm.model.relations[AGENT_RELATION], charm.app.name
            )
            deprecated_agent_meta_map = _get_agent_meta_map_from_relation(
                charm.model.relations[DEPRECATED_AGENT_RELATION], charm.app.name
            )
        except ValidationError as exc:
            logger.error("Invalid agent relation data received, %s", exc)
            raise CharmRelationDataInvalidError(
                f"Invalid {DEPRECATED_AGENT_RELATION} relation data."
            ) from exc

        try:
            proxy_config = ProxyConfig.from_env()
        except ValidationError as exc:
            logger.error("Invalid juju model proxy configuration, %s", exc)
            raise CharmConfigInvalidError("Invalid model proxy configuration.") from exc

        plugins_str = charm.config.get("allowed-plugins")
        plugins = (plugin.strip() for plugin in plugins_str.split(",")) if plugins_str else None

        if charm.app.planned_units() > 1:
            raise CharmIllegalNumUnitsError(
                "The Jenkins charm supports only 1 unit of deployment."
            )

        return cls(
            restart_time_range=restart_time_range,
            agent_relation_meta=agent_relation_meta_map,
            deprecated_agent_relation_meta=deprecated_agent_meta_map,
            is_storage_ready=_is_storage_ready(charm=charm),
            plugins=plugins,
            proxy_config=proxy_config,
        )
