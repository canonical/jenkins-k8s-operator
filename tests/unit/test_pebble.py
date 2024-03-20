# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the pebble module."""

import functools
import typing
from unittest.mock import patch

import pytest
import requests

import jenkins
import pebble
import state

from .types_ import HarnessWithContainer


def test_replan_jenkins_pebble_error(
    harness_container: HarnessWithContainer,
    mocked_get_request: typing.Callable[[str, int, typing.Any, typing.Any], requests.Response],
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given a patched jenkins bootstrap method that raises an exception.
    act: when the a replan is executed.
    assert: an error is raised.
    """
    # speed up waiting by changing default argument values
    monkeypatch.setattr(requests, "get", functools.partial(mocked_get_request, status_code=200))
    with (
        patch.object(jenkins.Jenkins, "wait_ready"),
        patch.object(jenkins.Jenkins, "bootstrap") as bootstrap_mock,
    ):
        bootstrap_mock.side_effect = jenkins.JenkinsBootstrapError
        harness = harness_container.harness
        harness.begin()

        env = jenkins.Environment(
            JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
            JENKINS_PREFIX="/",
        )

        with pytest.raises(jenkins.JenkinsBootstrapError):
            pebble.replan_jenkins(
                harness_container.container,
                jenkins.Jenkins(env),
                state.State.from_charm(harness.charm),
            )


@pytest.mark.usefixtures("patch_os_environ")
def test_replan_jenkins_when_not_ready(harness_container: HarnessWithContainer):
    """
    arrange: given a mocked jenkins version raises TimeoutError on the second call.
    act: when the a replan is executed.
    assert: an error is raised.
    """
    harness = harness_container.harness
    harness.begin()
    with patch.object(jenkins.Jenkins, "wait_ready") as wait_ready_mock:
        wait_ready_mock.side_effect = TimeoutError

        env = jenkins.Environment(
            JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
            JENKINS_PREFIX="/",
        )

        with pytest.raises(jenkins.JenkinsBootstrapError):
            pebble.replan_jenkins(
                harness_container.container,
                jenkins.Jenkins(env),
                state.State.from_charm(harness.charm),
            )
