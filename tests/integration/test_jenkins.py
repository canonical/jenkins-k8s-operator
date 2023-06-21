# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import tempfile
import time

import jenkinsapi
from juju.application import Application
from juju.client import client
from juju.model import Model
from pytest_operator.plugin import OpsTest

from .substrings import assert_substrings_not_in_string
from .types_ import ModelAppUnit


async def test_jenkins_update_ui_disabled(
    web_address: str, jenkins_client: jenkinsapi.jenkins.Jenkins
):
    """
    arrange: a Jenkins deployment.
    act: -
    assert: The UI with update suggestion does not pop out
    """
    res = jenkins_client.requester.get_url(f"{web_address}/manage")

    page_content = str(res.content, encoding="utf-8")
    assert_substrings_not_in_string(
        ("New version of Jenkins", "is available", "download"), page_content
    )


# The code under test requires all the variables.
async def test_jenkins_automatic_update_out_of_range(  # pylint: disable=too-many-locals
    ops_test: OpsTest,
    model_app_unit: ModelAppUnit,
    jenkins_version: str,
    freeze_time: str,
):
    """
    arrange: given jenkins charm with frozen time to 15:00 UTC.
    act: when update-time-range between 3AM to 5AM is applied.
    assert: the update does not take place.
    """
    await model_app_unit.model.wait_for_idle()
    await model_app_unit.app.set_config({"update-time-range": "03-05"})
    unit_name: str = model_app_unit.unit.name
    charm_path = f"/var/lib/juju/agents/unit-{unit_name.replace('/', '-')}/charm"

    # Overwrite requirements.txt
    with tempfile.NamedTemporaryFile("wt", encoding="utf-8") as temp_requirements_txt, open(
        "requirements.txt", encoding="utf-8"
    ) as orig_requirements_txt:
        requirements = "\n".join((orig_requirements_txt.read(), "freezegun"))
        temp_requirements_txt.write(requirements)
        temp_requirements_txt.flush()

        await ops_test.juju(
            "scp", temp_requirements_txt.name, f"{unit_name}:{charm_path}/requirements.txt"
        )

        # Install requirements.txt
        await ops_test.juju(
            "ssh",
            unit_name,
            "/usr/local/bin/pip",
            "install",
            "--target",
            f"{charm_path}/venv",
            "-r",
            f"{charm_path}/requirements.txt",
        )

    # Overwrite charm.py
    with tempfile.NamedTemporaryFile(mode="wt", encoding="utf-8") as temp_charm_py, open(
        "src/charm.py", encoding="utf-8"
    ) as orig_charm_py:
        shebang_delimeter = "#!/usr/bin/env python3"
        class_delimeter = "class JenkinsK8SOperatorCharm(CharmBase):"
        charm_code = orig_charm_py.read()
        split_code = charm_code.split(shebang_delimeter, 1)
        split_code.insert(0, f"{shebang_delimeter}\nfrom freezegun import freeze_time\n")
        charm_code = "".join(split_code)
        split_code = charm_code.split(class_delimeter, 1)
        split_code.insert(1, f'freeze_time("{freeze_time}").start()\n{class_delimeter}\n')
        temp_charm_py.write("".join(split_code))
        temp_charm_py.flush()

        # unit.scp_to currently doesn't support k8s charms
        # https://github.com/juju/python-libjuju/issues/885
        (ret, _, stderr) = await ops_test.juju(
            "scp", temp_charm_py.name, f"{unit_name}:{charm_path}/src/charm.py"
        )
        assert not ret, f"failed to scp modified charm, {stderr}"
        (ret, _, stderr) = await ops_test.juju(
            "ssh", unit_name, "/usr/bin/chmod", "755", f"{charm_path}/src/charm.py"
        )
        assert not ret, f"failed to chmod modified charm, {stderr}"
        (ret, _, stderr) = await ops_test.juju(
            "ssh", unit_name, "/usr/bin/chown", "root:root", f"{charm_path}/src/charm.py"
        )
        assert not ret, f"failed to chown modified charm, {stderr}"

    # Wait for model update-status hook
    await model_app_unit.model.set_config({"update-status-hook-interval": "10s"})
    time.sleep(15)
    await model_app_unit.model.wait_for_idle(status="active")

    model_status: client.FullStatus = await model_app_unit.model.get_status()
    app_status = model_status.applications.get(model_app_unit.app.name)
    assert app_status, "application status not found."

    assert app_status.workload_version == jenkins_version

    # Reset charm.py & model hook interval
    await model_app_unit.model.set_config({"update-status-hook-interval": "5m"})
    await model_app_unit.app.reset_config(["update-time-range"])
    await ops_test.juju("scp", "src/charm.py", f"{unit_name}:{charm_path}/src/charm.py")


async def test_jenkins_automatic_update(
    application: Application, model: Model, jenkins_version: str, latest_jenkins_lts_version: str
):
    """
    arrange: a Jenkins deployment.
    act: update status hook is triggered.
    assert: The latest LTS Jenkins version is set as workload version.
    """
    # get original application workload version
    status: client.FullStatus = await model.get_status()
    app_status = status.applications.get(application.name)
    assert app_status, "application status not found."
    original_workload_version = app_status.workload_version

    # patch model and wait for update-status-hook trigger
    await model.set_config({"update-status-hook-interval": "10s"})
    time.sleep(15)
    await model.wait_for_idle(status="active")

    # get patched application workload version
    patched_status: client.FullStatus = await model.get_status()
    patched_app_status = patched_status.applications.get(application.name)
    assert patched_app_status, "patched application status not found."

    assert original_workload_version == jenkins_version
    assert patched_app_status.workload_version == latest_jenkins_lts_version

    # reset model hook interval
    await model.set_config({"update-status-hook-interval": "5m"})
