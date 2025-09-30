# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm storage tests."""

from ops import testing

from charm import JenkinsK8sOperatorCharm
from tests.unit.constants import (
    JENKINS_CONTAINER_NAME,
    JENKINS_HOME_DIR,
    JENKINS_STORAGE_NAME,
    JENKINS_USER,
)


def test_reconcile_storage():
    """
    arrange: given container and storage charm components.
    act: when check is called.
    assert: expected result is returned.
    """
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    state = testing.State(
        containers=[
            testing.Container(
                name=JENKINS_CONTAINER_NAME,
                can_connect=True,  # type: ignore
                execs=[
                    testing.Exec(
                        ["chown", "-R", f"{JENKINS_USER}:{JENKINS_USER}", JENKINS_HOME_DIR],
                        return_code=0,
                        stdout="",
                    ),
                    testing.Exec(
                        ["stat", JENKINS_HOME_DIR],
                        return_code=0,
                        stdout=f"{JENKINS_USER} {JENKINS_USER}",
                    ),
                ],
            )
        ],
        storages=[testing.Storage(name=JENKINS_STORAGE_NAME)],
    )
    with ctx(ctx.on.collect_unit_status(), state) as context:
        container = context.charm.unit.get_container(JENKINS_CONTAINER_NAME)
        reconciler = context.charm.storage
        reconciler.reconcile_storage(container=container)

        out = container.exec(["stat", JENKINS_HOME_DIR]).stdout
        assert out, "No output from stat dir"
        assert JENKINS_USER in out.read()
