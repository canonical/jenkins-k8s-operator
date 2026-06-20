# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the pebble module."""

from unittest.mock import MagicMock

import jenkins
import pebble
import state

from .types_ import HarnessWithContainer


def test_replan_jenkins_applies_layer(harness_container: HarnessWithContainer):
    """
    arrange: given a container, Jenkins instance, and charm state.
    act: when the a replan is executed.
    assert: the layer is applied and replanned.
    """
    harness = harness_container.harness
    harness.begin()

    env = jenkins.Environment(
        JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
        JENKINS_PREFIX="/",
    )

    pebble.replan_jenkins(
        harness_container.container,
        jenkins.Jenkins(env),
        state.State.from_charm(harness.charm),
    )

    assert harness_container.container.get_plan().services


def test_replan_jenkins_does_not_bootstrap(harness_container: HarnessWithContainer, monkeypatch):
    """
    arrange: given patched bootstrap methods.
    act: when the a replan is executed.
    assert: bootstrap methods are not invoked by Pebble replan.
    """
    harness = harness_container.harness
    harness.begin()
    wait_ready_mock = MagicMock()
    bootstrap_mock = MagicMock()
    monkeypatch.setattr(jenkins.Jenkins, "wait_ready", wait_ready_mock)
    monkeypatch.setattr(jenkins.Jenkins, "bootstrap", bootstrap_mock)
    env = jenkins.Environment(
        JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
        JENKINS_PREFIX="/",
    )

    pebble.replan_jenkins(
        harness_container.container,
        jenkins.Jenkins(env),
        state.State.from_charm(harness.charm),
    )

    wait_ready_mock.assert_not_called()
    bootstrap_mock.assert_not_called()
