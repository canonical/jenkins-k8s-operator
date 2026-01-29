# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator with ingress."""

import typing

import pytest
import requests
from juju.application import Application
from juju.model import Model


@pytest.mark.abort_on_fail
async def test_ingress_integration(
    model: Model,
    application: Application,
    traefik_application_and_unit_ip: typing.Tuple[Application, str],
):
    """
    arrange: deploy the Jenkins charm and establish relations via ingress.
    act: send a request to the ingress in /.
    assert: the response succeeds.
    """
    traefik_application, traefik_address = traefik_application_and_unit_ip
    await application.relate("ingress", traefik_application.name)
    await model.wait_for_idle(
        apps=[application.name, traefik_application.name],
        wait_for_active=True,
        timeout=20 * 60,
    )
    response = requests.get(
        f"http://{traefik_address}/{model.name}-{application.name}",
        timeout=5,
    )

    assert "Authentication required" in str(response.content)


@pytest.mark.abort_on_fail
async def test_ingress_system_properties_flag_present(
    model: Model,
    application: Application,
    traefik_application_and_unit_ip: typing.Tuple[Application, str],
):
    """
    Confirm system-properties are appended to the JVM startup flags.

    arrange: deploy Jenkins with Traefik ingress and set system-properties.
    act: set crumb issuer proxy compatibility via config and inspect JVM args.
    assert: the -D flag is present in the running java process.
    """
    traefik_application, _ = traefik_application_and_unit_ip
    # Ensure relation exists
    await application.relate("ingress", traefik_application.name)
    await model.wait_for_idle(
        apps=[application.name, traefik_application.name],
        wait_for_active=True,
        timeout=20 * 60,
    )

    # Apply the system property via charm config
    prop = "jenkins.model.Jenkins.crumbIssuerProxyCompatibility=true"
    await application.set_config({"system-properties": prop})
    await model.wait_for_idle(
        apps=[application.name], wait_for_active=True, timeout=20 * 60, idle_period=30
    )

    # Inspect the running java command line inside the unit
    unit = application.units[0]
    action = await unit.run(command="ps -ef | grep '[j]ava'", timeout=60)
    await action.wait()
    assert action.results.get("return-code") == 0
    stdout = str(action.results.get("stdout"))
    assert f"-D{prop}" in stdout
