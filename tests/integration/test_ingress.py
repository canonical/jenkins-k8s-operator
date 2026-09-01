# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import jubilant
import requests

from .helpers import ensure_relation, exec_in_container, short_model_name, wait_for
from .types_ import JujuApplication


def test_ingress_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    traefik_application_and_unit_ip: tuple[JujuApplication, str],
) -> None:
    """Verify Jenkins is reachable through a Traefik ingress relation."""
    traefik_application, traefik_address = traefik_application_and_unit_ip
    ensure_relation(
        model=model,
        application=application,
        other_application=traefik_application,
        relation="ingress",
    )

    def ingress_is_ready() -> bool:
        try:
            response = requests.get(
                f"http://{traefik_address}/{short_model_name(model)}-{application.name}",
                timeout=5,
            )
        except requests.RequestException:
            return False
        return "Authentication required" in str(response.content)

    wait_for(ingress_is_ready, timeout=10 * 60, check_interval=10)


def test_ingress_system_properties_flag_present(
    model: jubilant.Juju,
    application: JujuApplication,
    unit: str,
    traefik_application_and_unit_ip: tuple[JujuApplication, str],
) -> None:
    """Confirm system properties are present in the running Java process."""
    traefik_application, _ = traefik_application_and_unit_ip
    ensure_relation(
        model=model,
        application=application,
        other_application=traefik_application,
        relation="ingress",
    )

    prop = "jenkins.model.Jenkins.crumbIssuerProxyCompatibility=true"
    model.config(application.name, {"system-properties": prop})
    model.wait(
        lambda status: jubilant.all_active(status, application.name),
        error=jubilant.any_error,
        timeout=20 * 60,
    )

    def java_process_has_property() -> bool:
        try:
            stdout = exec_in_container(model, unit, "jenkins", "ps -aux | cat")
        except jubilant.CLIError:
            return False
        return f"-D{prop}" in stdout

    wait_for(java_process_has_property, timeout=10 * 60, check_interval=10)
