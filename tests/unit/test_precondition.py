# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests."""

import typing
import unittest.mock

# Need access to protected functions for testing
# pylint:disable=protected-access
import pytest
from ops.testing import Harness

import precondition
from charm import JenkinsK8sOperatorCharm


def test__check_storage_exception(harness: Harness):
    """
    arrange: given a charm with no storage attached.
    act: when _check_storage is called.
    assert: a ConditionCheckError is raised.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    with pytest.raises(precondition.ConditionCheckError):
        precondition._check_storage(charm=jenkins_charm, charm_state=jenkins_charm.state)


def test__check_container_exception(harness: Harness):
    """
    arrange: given a charm with no container ready.
    act: when _check_container is called.
    assert: a ConditionCheckError is raised.
    """
    harness.begin()
    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    with pytest.raises(precondition.ConditionCheckError):
        precondition._check_container(charm=jenkins_charm, charm_state=jenkins_charm.state)


@pytest.mark.parametrize(
    "condition_func",
    [
        pytest.param("_check_storage", id="storage attached check"),
        pytest.param("_check_container", id="workload container ready check"),
    ],
)
def test_check_exception(harness: Harness, monkeypatch: pytest.MonkeyPatch, condition_func: str):
    """
    arrange: given a monkeypatched conditions that raise an exception.
    act: when check is called.
    assert: a ConditionCheckError is raised.
    """
    monkeypatch.setattr(
        precondition,
        condition_func,
        unittest.mock.MagicMock(side_effect=precondition.ConditionCheckError),
    )
    harness.begin()

    jenkins_charm = typing.cast(JenkinsK8sOperatorCharm, harness.charm)
    with pytest.raises(precondition.ConditionCheckError):
        precondition.check(jenkins_charm, jenkins_charm.state)
