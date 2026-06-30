# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm plugin reconciliation unit tests."""

# Need access to protected functions for testing
# pylint:disable=protected-access

import datetime
import typing
from unittest.mock import MagicMock

import pytest

import jenkins
import state
import timerange
from charm import REQUIRED_PLUGINS, JenkinsK8sOperatorCharm

from .types_ import HarnessWithContainer


def _make_state(
    *,
    plugins: list[str] | None = None,
    restart_time_range: timerange.Range | None = None,
):
    charm_state = MagicMock(spec=state.State)
    charm_state.plugins = plugins
    charm_state.restart_time_range = restart_time_range
    return charm_state


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(jenkins.JenkinsPluginError("plugin error"), id="plugin-error"),
        pytest.param(jenkins.JenkinsError("jenkins error"), id="jenkins-error"),
        pytest.param(TimeoutError("timeout"), id="timeout"),
    ],
)
def test__reconcile_plugins_catches_removal_errors(
    harness_container: HarnessWithContainer,
    exception: Exception,
):
    """
    arrange: given admin remove_unlisted_plugins raises known exceptions.
    act: when _reconcile_plugins is called.
    assert: exception is swallowed and no error is propagated.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    admin_client.remove_unlisted_plugins.side_effect = exception
    charm_state = _make_state(plugins=["kubernetes"])

    charm._reconcile_plugins(charm_state, admin_client, harness_container.container)


def test__reconcile_plugins_calls_remove_unlisted_plugins(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given plugin config and an admin Jenkins client.
    act: when _reconcile_plugins is called.
    assert: remove_unlisted_plugins is called with configured+required plugin set.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    charm_state = _make_state(plugins=["kubernetes", "blueocean"])

    charm._reconcile_plugins(charm_state, admin_client, harness_container.container)

    admin_client.remove_unlisted_plugins.assert_called_once()
    call_kwargs = admin_client.remove_unlisted_plugins.call_args.kwargs
    actual_plugins = set(call_kwargs["plugins"])
    assert {"kubernetes", "blueocean"}.issubset(actual_plugins)
    assert set(REQUIRED_PLUGINS).issubset(actual_plugins)
    assert call_kwargs["container"] is harness_container.container


def test__reconcile_plugins_skips_outside_restart_window(
    harness_container: HarnessWithContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    arrange: given restart-time-range and current time outside the configured window.
    act: when _reconcile_plugins is called.
    assert: remove_unlisted_plugins is not called.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    admin_client = MagicMock(spec=jenkins.Jenkins)
    charm_state = _make_state(
        plugins=["kubernetes"], restart_time_range=timerange.Range(start=0, end=23)
    )

    mock_datetime = MagicMock(spec=datetime.datetime)
    mock_datetime.utcnow.return_value = datetime.datetime(2023, 1, 1, 23)
    monkeypatch.setattr(timerange, "datetime", mock_datetime)

    charm._reconcile_plugins(charm_state, admin_client, harness_container.container)

    admin_client.remove_unlisted_plugins.assert_not_called()


def test__reconcile_plugins_requires_container_argument(
    harness_container: HarnessWithContainer,
):
    """
    arrange: given a started charm instance.
    act: when _reconcile_plugins is called without container argument.
    assert: Python raises TypeError due to missing required argument.
    """
    harness_container.harness.begin()
    charm = typing.cast(JenkinsK8sOperatorCharm, harness_container.harness.charm)
    charm_state = _make_state(plugins=["kubernetes"])
    admin_client = MagicMock(spec=jenkins.Jenkins)

    reconcile_plugins = typing.cast(typing.Any, charm._reconcile_plugins)

    with pytest.raises(TypeError):
        reconcile_plugins(charm_state, admin_client)
