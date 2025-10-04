# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm precondition tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import pytest
from ops import testing

import precondition
from charm import JenkinsK8sOperatorCharm
from tests.unit.constants import JENKINS_CONTAINER_NAME, JENKINS_STORAGE_NAME


def _generate_precondition_check_test_parameters():
    """Generate precondition check test parameters.

    Returns:
        Combinations of container and storage states.
    """
    # mypy thinks this can_connect argument does not exist.
    ready_container = testing.Container(
        name=JENKINS_CONTAINER_NAME,
        can_connect=True,  # type: ignore
    )
    not_ready_container = testing.Container(
        name=JENKINS_CONTAINER_NAME,
        can_connect=False,  # type: ignore
    )
    storage = testing.Storage(name=JENKINS_STORAGE_NAME)
    no_container_no_storage = testing.State(
        containers=[
            not_ready_container,  # type: ignore
        ],
        storages=[],
    )
    container_no_storage = testing.State(
        containers=[
            ready_container,  # type: ignore
        ],
        storages=[],
    )
    no_container_storage = testing.State(
        containers=[
            not_ready_container,  # type: ignore
        ],
        storages=[storage],
    )
    container_storage = testing.State(
        containers=[
            ready_container,  # type: ignore
        ],
        storages=[storage],
    )
    return [
        pytest.param(
            no_container_no_storage,
            precondition._CheckResult(success=False, reason="pebble, storage not yet ready."),
            id="container not ready, storage not ready",
        ),
        pytest.param(
            container_no_storage,
            precondition._CheckResult(success=False, reason="storage not yet ready."),
            id="container ready, storage not ready",
        ),
        pytest.param(
            no_container_storage,
            precondition._CheckResult(success=False, reason="pebble not yet ready."),
            id="container not ready, storage ready",
        ),
        pytest.param(
            container_storage,
            precondition._CheckResult(success=True, reason=None),
            id="container ready, storage ready",
        ),
    ]


@pytest.mark.parametrize(("state", "expected"), _generate_precondition_check_test_parameters())
def test_precondition_check(state: testing.State, expected: precondition._CheckResult):
    """
    arrange: given container and storage charm components.
    act: when check is called.
    assert: expected result is returned.
    """
    ctx = testing.Context(JenkinsK8sOperatorCharm)
    with ctx(ctx.on.collect_unit_status(), state) as context:
        container = context.charm.unit.get_container(JENKINS_CONTAINER_NAME)
        storages = context.charm.model.storages

        assert precondition.check(container=container, storages=storages) == expected
