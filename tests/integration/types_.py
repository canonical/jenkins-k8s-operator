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


@dataclasses.dataclass
class JenkinsSession:
    """A refreshable connection to one Jenkins endpoint."""

    url: str
    client: jenkinsapi.jenkins.Jenkins
    _client_factory: Callable[[], Awaitable[jenkinsapi.jenkins.Jenkins]]

    async def refresh(self) -> jenkinsapi.jenkins.Jenkins:
        """Recreate the client after Jenkins restarts."""
        self.client = await self._client_factory()
        return self.client


@dataclasses.dataclass
class UnitWebClient:
    """Compatibility wrapper while tests migrate to ``JenkinsSession``."""

    unit: Unit
    session: JenkinsSession

    @property
    def web(self) -> str:
        """The Jenkins endpoint."""
        return self.session.url

    @property
    def client(self) -> jenkinsapi.jenkins.Jenkins:
        """The current Jenkins client."""
        return self.session.client

    async def refresh(self) -> jenkinsapi.jenkins.Jenkins:
        """Refresh the underlying Jenkins session."""
        return await self.session.refresh()


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
