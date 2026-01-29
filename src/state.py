# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins States."""

import dataclasses
import logging
import os
import typing

import ops
from pydantic import BaseModel, Field, HttpUrl, ValidationError, validator

from timerange import InvalidTimeRangeError, Range

logger = logging.getLogger(__name__)

AGENT_RELATION = "agent"
AUTH_PROXY_RELATION = "auth-proxy"
JENKINS_SERVICE_NAME = "jenkins"
JENKINS_HOME_STORAGE_NAME = "jenkins-home"
INGRESS_RELATION_NAME = "ingress"
AGENT_DISCOVERY_INGRESS_RELATION_NAME = "agent-discovery-ingress"


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


def _get_agent_meta_map_from_relation(
    relations: typing.List[ops.Relation],
) -> typing.Optional[typing.Mapping[ops.Relation, list[AgentMeta]]]:
    """Return a mapping of unit name to AgentMetadata from agent relation.

    Args:
        relations: The agent relations.

    Returns:
        A mapping of ops.Unit to AgentMetadata.
    """
    if not relations:
        return None
    relation_agents_map = {}
    for relation in relations:
        agents = [AgentMeta.from_agent_relation(relation.data[unit]) for unit in relation.units]
        relation_agents_map.update({relation: [agent for agent in agents if agent]})
    return relation_agents_map


def _is_auth_proxy_integrated(relation: typing.Optional[ops.Relation]) -> bool:
    """Check if there is an auth proxy integration..

    Args:
        relation: The auth-proxy relation.

    Returns:
        True if an integration for atuh proxy exists.
    """
    # No relation data is written by the provider, so checking the existence suffices.
    return bool(relation)


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
            http_proxy=http_proxy,  # type: ignore[arg-type]
            https_proxy=https_proxy,  # type: ignore[arg-type]
            no_proxy=no_proxy,
        )


@dataclasses.dataclass(frozen=True)
class State:
    """The Jenkins k8s operator charm state.

    Attributes:
        restart_time_range: Time range to allow Jenkins to update version.
        agent_relation_meta: Metadata of all agents from units related through agent relation.
        proxy_config: Proxy configuration to access Jenkins upstream through.
        plugins: The list of allowed plugins to install.
        auth_proxy_integrated: if an auth proxy integrated has been set.
        system_properties: Additional JVM system properties as -D flags.

    """

    restart_time_range: typing.Optional[Range]
    agent_relation_meta: typing.Optional[typing.Mapping[ops.Relation, list[AgentMeta]]]
    proxy_config: typing.Optional[ProxyConfig]
    plugins: typing.Optional[typing.Iterable[str]]
    auth_proxy_integrated: bool
    system_properties: typing.List[str] = dataclasses.field(default_factory=list)

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
        try:
            time_range_str = typing.cast(str, charm.config.get("restart-time-range"))
            restart_time_range = Range.from_str(time_range_str) if time_range_str else None
        except InvalidTimeRangeError as exc:
            logger.error("Invalid config value for restart-time-range, %s", exc)
            raise CharmConfigInvalidError("Invalid config value for restart-time range.") from exc

        try:
            agent_relation_meta_map = _get_agent_meta_map_from_relation(
                charm.model.relations[AGENT_RELATION]
            )
            is_auth_proxy_integrated = _is_auth_proxy_integrated(
                charm.model.get_relation(AUTH_PROXY_RELATION)
            )
        except ValidationError as exc:
            logger.error("Invalid agent relation data received, %s", exc)
            raise CharmRelationDataInvalidError(
                f"Invalid {AGENT_RELATION} relation data."
            ) from exc

        try:
            proxy_config = ProxyConfig.from_env()
        except ValidationError as exc:
            logger.error("Invalid juju model proxy configuration, %s", exc)
            raise CharmConfigInvalidError("Invalid model proxy configuration.") from exc

        plugins_str = typing.cast(str, charm.config.get("allowed-plugins"))
        plugins = (plugin.strip() for plugin in plugins_str.split(",")) if plugins_str else None

        # Parse custom JVM system properties to pass as -D flags
        system_properties_cfg = typing.cast(str, charm.config.get("system-properties"))
        system_properties: list[str] = []
        if system_properties_cfg:
            for entry in (part.strip() for part in system_properties_cfg.split(",")):
                if not entry:
                    continue
                if "=" not in entry or entry.startswith("="):
                    raise CharmConfigInvalidError(
                        "Invalid system-properties entry; expected key=value pairs "
                        "separated by commas."
                    )
                system_properties.append(f"-D{entry}")

        if charm.app.planned_units() > 1:
            raise CharmIllegalNumUnitsError(
                "The Jenkins charm supports only 1 unit of deployment."
            )
        agent_discovery_ingress = charm.model.get_relation(AGENT_DISCOVERY_INGRESS_RELATION_NAME)
        server_ingress = charm.model.get_relation(INGRESS_RELATION_NAME)
        if agent_discovery_ingress and not server_ingress:
            raise CharmConfigInvalidError(
                f"{INGRESS_RELATION_NAME} integration is required when using "
                f"{AGENT_DISCOVERY_INGRESS_RELATION_NAME}"
            )

        return cls(
            restart_time_range=restart_time_range,
            agent_relation_meta=agent_relation_meta_map,
            plugins=plugins,
            proxy_config=proxy_config,
            auth_proxy_integrated=is_auth_proxy_integrated,
            system_properties=system_properties,
        )
