# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Idempotent Juju resource arrangements for integration tests."""

from collections.abc import Iterable, Mapping
from typing import Any, Literal

import jubilant

from .helpers import short_model_name
from .types_ import JujuApplication

ApplicationStatus = Literal["active", "blocked"]


def application_ref(model: jubilant.Juju, name: str) -> JujuApplication:
    """Return a fresh application reference from model status."""
    app_status = model.status().apps.get(name)
    assert app_status, f"Application status {name} not found"
    return JujuApplication(name=name, model=model, units=tuple(app_status.units))


def _wait_for_application(
    model: jubilant.Juju,
    applications: Iterable[str],
    expected_status: ApplicationStatus,
    timeout: int,
) -> None:
    """Wait for applications to reach their expected Juju status."""
    apps = tuple(applications)
    if expected_status == "active":

        def predicate(status: Any) -> bool:
            return jubilant.all_active(status, *apps)
    else:

        def predicate(status: Any) -> bool:
            return jubilant.all_blocked(status, *apps)

    model.wait(predicate, error=jubilant.any_error, timeout=timeout)


def _deployment_kwargs(
    *,
    name: str,
    channel: str | None,
    revision: int | None,
    base: str | None,
    resources: Mapping[str, str] | None,
    trust: bool | None,
    num_units: int | None,
) -> dict[str, Any]:
    """Build only the explicit deployment options requested by a test."""
    kwargs: dict[str, Any] = {"app": name}
    if channel is not None:
        kwargs["channel"] = channel
    if revision is not None:
        kwargs["revision"] = revision
    if base is not None:
        kwargs["base"] = base
    if resources is not None:
        kwargs["resources"] = dict(resources)
    if trust is not None:
        kwargs["trust"] = trust
    if num_units is not None:
        kwargs["num_units"] = num_units
    return kwargs


def ensure_application(
    model: jubilant.Juju,
    charm: str,
    *,
    name: str,
    channel: str | None = None,
    revision: int | None = None,
    base: str | None = None,
    config: Mapping[str, Any] | None = None,
    resources: Mapping[str, str] | None = None,
    trust: bool | None = None,
    num_units: int | None = None,
    expected_status: ApplicationStatus | None = "active",
    timeout: int = 20 * 60,
) -> JujuApplication:
    """Ensure a charm application exists, is configured, and has settled.

    The deployment is only performed when the named application is absent.
    Configuration is applied on every call so a repeated arrangement converges
    to the requested state.  The returned reference is read after the final
    wait, avoiding stale unit data from before deployment.
    """
    if name not in model.status().apps:
        deploy_kwargs = _deployment_kwargs(
            name=name,
            channel=channel,
            revision=revision,
            base=base,
            resources=resources,
            trust=trust,
            num_units=num_units,
        )
        try:
            model.deploy(charm, **deploy_kwargs)
        except jubilant.CLIError as exc:
            if "already exists" not in str(exc).lower():
                raise

    if config:
        model.config(name, dict(config))
    if expected_status is not None:
        _wait_for_application(model, (name,), expected_status, timeout)
    return application_ref(model, name)


def ensure_configuration(
    model: jubilant.Juju,
    *,
    configuration: Mapping[str, Any],
    application: str | JujuApplication | None = None,
    expected_status: ApplicationStatus | None = "active",
    timeout: int = 20 * 60,
) -> None:
    """Ensure application or model configuration and wait for convergence."""
    if application is None:
        model.model_config(dict(configuration))
        model.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=timeout)
        return

    application_name = application if isinstance(application, str) else application.name
    model.config(application_name, dict(configuration))
    if expected_status is not None:
        _wait_for_application(model, (application_name,), expected_status, timeout)


def ensure_integration(
    model: jubilant.Juju,
    endpoint: str,
    related_endpoint: str,
    *,
    applications: Iterable[str] = (),
    expected_status: ApplicationStatus = "active",
    timeout: int = 20 * 60,
    renew: bool = False,
) -> None:
    """Ensure an integration exists and its affected applications settle."""
    app_names = tuple(applications)
    if renew:
        try:
            model.remove_relation(endpoint, related_endpoint)
        except jubilant.CLIError as exc:
            message = str(exc).lower()
            if "not found" not in message and "no relation" not in message:
                raise
        else:
            if app_names:
                model.wait(
                    lambda status: jubilant.all_agents_idle(status, *app_names),
                    error=jubilant.any_error,
                    timeout=timeout,
                )
            else:
                model.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=timeout)

    try:
        model.integrate(endpoint, related_endpoint)
    except jubilant.CLIError as exc:
        if "already exists" not in str(exc).lower():
            raise

    if app_names:
        _wait_for_application(model, app_names, expected_status, timeout)


def ensure_relation(
    *,
    model: jubilant.Juju,
    application: JujuApplication,
    other_application: JujuApplication,
    relation: str | tuple[str, str] | None = None,
    renew: bool = False,
    applications: Iterable[str] | None = None,
    expected_status: ApplicationStatus = "active",
    timeout: int = 20 * 60,
) -> None:
    """Ensure a relation between two local applications."""
    if relation is None:
        source_endpoint = target_endpoint = "agent"
    elif isinstance(relation, tuple):
        source_endpoint, target_endpoint = relation
    else:
        source_endpoint = target_endpoint = relation

    ensure_integration(
        model,
        f"{application.name}:{source_endpoint}",
        f"{other_application.name}:{target_endpoint}",
        applications=applications or (application.name, other_application.name),
        expected_status=expected_status,
        timeout=timeout,
        renew=renew,
    )


def ensure_offer(
    model: jubilant.Juju,
    application: str | JujuApplication,
    *,
    controller: str,
    endpoint: str,
    name: str | None = None,
) -> None:
    """Ensure a Juju offer exists for an application endpoint."""
    application_name = application if isinstance(application, str) else application.name
    offer_name = name or endpoint
    try:
        model.offer(
            f"{short_model_name(model)}.{application_name}",
            controller=controller,
            endpoint=endpoint,
            name=offer_name,
        )
    except jubilant.CLIError as exc:
        if "already exists" not in str(exc).lower():
            raise


def ensure_consume(model: jubilant.Juju, offer_url: str, *, alias: str) -> None:
    """Ensure a cross-model offer is consumed under a stable alias."""
    try:
        model.consume(offer_url, alias=alias)
    except jubilant.CLIError as exc:
        if "already exists" not in str(exc).lower():
            raise


def ensure_model(
    model: jubilant.Juju,
    name: str,
    *,
    cloud: str,
    controller: str,
) -> jubilant.Juju:
    """Ensure a model exists and return its connected Jubilant client."""
    try:
        model.add_model(name, cloud, controller=controller)
    except jubilant.CLIError as exc:
        if "already exists" not in str(exc).lower():
            raise
    return model
