# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types for integration tests module."""

import dataclasses

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
class UnitWebClient:
    """The unit, web address, jenkins client wrapper dataclass.

    Attributes:
        unit: The jenkins application unit.
        web: The jenkins unit web address.
        client: The client connected to jenkins unit.
    """

    unit: Unit
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
