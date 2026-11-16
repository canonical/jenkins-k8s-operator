# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types for integration tests module."""

import dataclasses
from collections.abc import Awaitable, Callable

import jenkinsapi.jenkins
from juju.application import Application
from juju.model import Model
from juju.unit import Unit


@dataclasses.dataclass
class ModelAppUnit:
    """The model, application, unit wrapper dataclass.

    Attributes:
        model: The model under test.
        app: The jenkins application under test.
        unit: The jenkins application unit under test.
    """

    model: Model
    app: Application
    unit: Unit


AddressResolver = Callable[[], Awaitable[str]]
JenkinsConnector = Callable[[str], Awaitable[jenkinsapi.jenkins.Jenkins]]


@dataclasses.dataclass(frozen=True)
class JenkinsConnection:
    """A Jenkins client bound to the URL used to create it."""

    url: str
    client: jenkinsapi.jenkins.Jenkins


@dataclasses.dataclass(frozen=True)
class JenkinsTarget:
    """The information needed to create a fresh Jenkins connection."""

    address_resolver: AddressResolver
    connector: JenkinsConnector

    async def connect(self) -> JenkinsConnection:
        """Resolve the current address and create a client for it."""
        url = await self.address_resolver()
        return JenkinsConnection(url=url, client=await self.connector(url))


@dataclasses.dataclass
class JenkinsSession:
    """A live Jenkins connection that can be recreated from its target."""

    target: JenkinsTarget
    connection: JenkinsConnection

    @property
    def url(self) -> str:
        """The URL used by the current client."""
        return self.connection.url

    @property
    def web(self) -> str:
        """Compatibility alias for the current Jenkins URL."""
        return self.url

    @property
    def client(self) -> jenkinsapi.jenkins.Jenkins:
        """The current Jenkins client."""
        return self.connection.client

    async def refresh(self) -> jenkinsapi.jenkins.Jenkins:
        """Resolve the current target and recreate the client."""
        self.connection = await self.target.connect()
        return self.client


@dataclasses.dataclass
class LDAPSettings:
    """The testing LDAP settings.

    Attributes:
        container_ports: The LDAP server container ports.
        username: The LDAP test user.
        password: The LDAP test user password.
    """

    container_ports: list[int]
    username: str
    password: str


@dataclasses.dataclass
class KeycloakOIDCMetadata:
    """The testing Keycloak user for OIDC testing.

    Attributes:
        username: The login username.
        password: The login password.
        realm: The Keycloak realm name.
        client_id: The Keycloak oidc client identifier.
        client_secret: The Keycloak oidc client secret.
        well_known_endpoint: Well-known registry URI that can be used to automatically configure
            the endpoints.
    """

    username: str
    password: str
    realm: str
    client_id: str
    client_secret: str
    well_known_endpoint: str
