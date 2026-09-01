# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types for integration tests module."""

import dataclasses

import jenkinsapi.jenkins
import jubilant


@dataclasses.dataclass(frozen=True)
class JujuApplication:
    """Reference to an application managed by a Jubilant model."""

    name: str
    model: jubilant.Juju
    units: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ModelAppUnit:
    """The model, application, and unit used by an integration test."""

    model: jubilant.Juju
    app: JujuApplication
    unit: str


@dataclasses.dataclass(frozen=True)
class UnitWebClient:
    """A Jenkins unit name, URL, and API client."""

    model: jubilant.Juju
    unit: str
    web: str
    client: jenkinsapi.jenkins.Jenkins


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
        client_secret: The Keycloak client secret.
        well_known_endpoint: Well-known registry URI that can be used to automatically configure
            the endpoints.
    """

    username: str
    password: str
    realm: str
    client_id: str
    client_secret: str
    well_known_endpoint: str
