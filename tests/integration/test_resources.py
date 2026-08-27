# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Deterministic tests for the integration resource arrangements."""

from dataclasses import dataclass, field
from typing import Any, cast

import jubilant

from .resources import (
    ensure_application,
    ensure_configuration,
    ensure_consume,
    ensure_integration,
    ensure_model,
    ensure_offer,
)


@dataclass
class _AppStatus:
    """Small status double containing only the fields used by arrangements."""

    units: dict[str, object] = field(default_factory=dict)


@dataclass
class _ModelStatus:
    """Small model status double for the recording Juju client."""

    apps: dict[str, _AppStatus] = field(default_factory=dict)


class _RecordingJuju:
    """Juju double that records resource operations without a controller."""

    def __init__(self, *, race_on_deploy: bool = False) -> None:
        self.apps: dict[str, _AppStatus] = {}
        self.relations: set[tuple[str, str]] = set()
        self.offers: set[tuple[str, str]] = set()
        self.consumed: set[str] = set()
        self.events: list[tuple[str, Any]] = []
        self.race_on_deploy = race_on_deploy
        self.model = "testing"

    def status(self) -> _ModelStatus:
        self.events.append(("status", None))
        return _ModelStatus(apps=dict(self.apps))

    def wait(self, ready: Any, **kwargs: Any) -> _ModelStatus:
        del ready
        self.events.append(("wait", kwargs))
        return self.status()

    def deploy(self, charm: str, *, app: str, **kwargs: Any) -> None:
        self.events.append(("deploy", (charm, app, kwargs)))
        if app in self.apps:
            raise jubilant.CLIError(1, ["juju", "deploy"], stderr="application already exists")
        self.apps[app] = _AppStatus(units={f"{app}/0": object()})
        if self.race_on_deploy:
            raise jubilant.CLIError(1, ["juju", "deploy"], stderr="application already exists")

    def config(self, app: str, values: dict[str, object]) -> None:
        self.events.append(("config", (app, values)))

    def model_config(self, values: dict[str, object]) -> None:
        self.events.append(("model_config", values))

    def integrate(self, endpoint: str, related_endpoint: str) -> None:
        relation = (endpoint, related_endpoint)
        self.events.append(("integrate", relation))
        if relation in self.relations:
            raise jubilant.CLIError(1, ["juju", "integrate"], stderr="relation already exists")
        self.relations.add(relation)

    def remove_relation(self, endpoint: str, related_endpoint: str) -> None:
        relation = (endpoint, related_endpoint)
        self.events.append(("remove_relation", relation))
        if relation not in self.relations:
            raise jubilant.CLIError(1, ["juju", "remove-relation"], stderr="relation not found")
        self.relations.remove(relation)

    def offer(self, application: str, **kwargs: str) -> None:
        offer = (application, kwargs["name"])
        self.events.append(("offer", (application, kwargs)))
        if offer in self.offers:
            raise jubilant.CLIError(1, ["juju", "offer"], stderr="offer already exists")
        self.offers.add(offer)

    def consume(self, offer_url: str, *, alias: str) -> None:
        self.events.append(("consume", (offer_url, alias)))
        if alias in self.consumed:
            raise jubilant.CLIError(1, ["juju", "consume"], stderr="application already exists")
        self.consumed.add(alias)

    def add_model(self, name: str, cloud: str, *, controller: str) -> None:
        self.events.append(("add_model", (name, cloud, controller)))


def _events(model: _RecordingJuju, name: str) -> list[tuple[str, Any]]:
    """Return recorded events with one operation name."""
    return [event for event in model.events if event[0] == name]


def test_application_arrangement_converges_on_replay() -> None:
    """Repeated application arrangement does not redeploy the application."""
    model = _RecordingJuju()
    juju = cast(jubilant.Juju, model)

    # Arrange
    first = ensure_application(juju, "jenkins-k8s", name="jenkins", config={"foo": "bar"})
    second = ensure_application(juju, "jenkins-k8s", name="jenkins", config={"foo": "bar"})

    # Act
    units = second.units

    # Assert
    assert first.units == units
    assert len(_events(model, "deploy")) == 1
    assert len(_events(model, "config")) == 2


def test_application_arrangement_recovers_from_deploy_race() -> None:
    """A create race is treated as convergence, not as a failed arrangement."""
    model = _RecordingJuju(race_on_deploy=True)
    juju = cast(jubilant.Juju, model)

    # Arrange
    application = ensure_application(juju, "jenkins-k8s", name="jenkins")

    # Act
    units = application.units

    # Assert
    assert units == ("jenkins/0",)
    assert len(_events(model, "deploy")) == 1


def test_integration_arrangement_is_idempotent_and_renewable() -> None:
    """Integrations can be replayed and explicitly renewed."""
    model = _RecordingJuju()
    juju = cast(jubilant.Juju, model)
    endpoints = ("jenkins:agent", "agent:agent")

    # Arrange
    ensure_integration(juju, *endpoints, applications=("jenkins", "agent"))
    ensure_integration(juju, *endpoints, applications=("jenkins", "agent"), renew=True)

    # Act
    relations = model.relations

    # Assert
    assert len(_events(model, "integrate")) == 2
    assert len(_events(model, "remove_relation")) == 1
    assert endpoints in relations


def test_configuration_arrangement_targets_model_or_application() -> None:
    """The configuration helper selects the requested Juju target."""
    model = _RecordingJuju()
    juju = cast(jubilant.Juju, model)
    model.apps["jenkins"] = _AppStatus(units={"jenkins/0": object()})

    # Arrange
    ensure_configuration(juju, application="jenkins", configuration={"foo": "bar"})
    ensure_configuration(juju, configuration={"juju-http-proxy": "http://proxy"})

    # Act
    config_events = _events(model, "config")
    model_config_events = _events(model, "model_config")

    # Assert
    assert config_events[0][1] == ("jenkins", {"foo": "bar"})
    assert model_config_events[0][1] == {"juju-http-proxy": "http://proxy"}


def test_offer_and_consume_arrangement_are_idempotent() -> None:
    """Cross-model offers and consumption do not duplicate on replay."""
    model = _RecordingJuju()
    juju = cast(jubilant.Juju, model)

    # Arrange
    ensure_offer(juju, "jenkins", controller="controller", endpoint="agent", name="agent")
    ensure_consume(juju, "testing.agent", alias="agent")
    ensure_offer(juju, "jenkins", controller="controller", endpoint="agent", name="agent")
    ensure_consume(juju, "testing.agent", alias="agent")

    # Act
    offer_events = _events(model, "offer")
    consume_events = _events(model, "consume")

    # Assert
    assert len(offer_events) == 2
    assert len(consume_events) == 2
    assert len(model.offers) == 1
    assert model.consumed == {"agent"}


def test_model_arrangement_preserves_controller_and_cloud() -> None:
    """Model arrangement forwards its explicit cloud and controller."""
    model = _RecordingJuju()
    juju = cast(jubilant.Juju, model)

    # Arrange
    ensure_model(juju, "machine", cloud="localhost", controller="concierge-lxd")

    # Act
    event = _events(model, "add_model")[0]

    # Assert
    assert event[1] == ("machine", "localhost", "concierge-lxd")
