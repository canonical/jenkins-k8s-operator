# Copyright 2023 Canonical Ltd.
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
class TestLDAPSettings:
    """The testing LDAP settings.

    Attributes:
        container_port: The LDAP server container port.
        username: The LDAP test user.
        password: The LDAP test user password.
    """

    container_port: int
    username: str
    password: str
