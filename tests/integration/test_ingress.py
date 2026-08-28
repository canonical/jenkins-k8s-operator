# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import jubilant
import requests
import tenacity

from .helpers import _raise_timeout, ensure_relation, exec_in_container, short_model_name
from .types_ import JujuApplication


def test_ingress_integration(
    model: jubilant.Juju,
    application: JujuApplication,
    traefik_application_and_unit_ip: tuple[JujuApplication, str],
) -> None:
    """
    Arrange: Establish the Jenkins-to-Traefik ingress relation.
    Act: Repeatedly request Jenkins at its model-specific ingress path.
    Assert: The response body contains "Authentication required".
    """
    traefik_application, traefik_address = traefik_application_and_unit_ip
    ensure_relation(
        model=model,
        application=application,
        other_application=traefik_application,
        relation="ingress",
    )

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda result: not result),
        stop=tenacity.stop_after_delay(10 * 60),
        wait=tenacity.wait_fixed(10),
        reraise=True,
        retry_error_callback=_raise_timeout,
    )
    def ingress_is_ready() -> bool:
        try:
            response = requests.get(
                f"http://{traefik_address}/{short_model_name(model)}-{application.name}",
                timeout=5,
            )
        except requests.RequestException:
            return False
        return "Authentication required" in response.text

    ingress_is_ready()


def test_ingress_system_properties_flag_present(
    model: jubilant.Juju,
    application: JujuApplication,
    unit: str,
    traefik_application_and_unit_ip: tuple[JujuApplication, str],
) -> None:
    """
    Arrange: Establish the Jenkins-to-Traefik ingress relation and select a Jenkins unit.
    Act: Set the crumb issuer proxy compatibility system property and inspect the Java process command line.
    Assert: The command line contains `-Djenkins.model.Jenkins.crumbIssuerProxyCompatibility=true`.
    """
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

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda result: not result),
        stop=tenacity.stop_after_delay(10 * 60),
        wait=tenacity.wait_fixed(10),
        reraise=True,
        retry_error_callback=_raise_timeout,
    )
    def java_process_has_property() -> bool:
        try:
            stdout = exec_in_container(model, unit, "jenkins", "ps -aux | cat")
        except jubilant.CLIError:
            return False
        return f"-D{prop}" in stdout

    java_process_has_property()
