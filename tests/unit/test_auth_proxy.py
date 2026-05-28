# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s auth_proxy unit tests."""

# pylint:disable=protected-access

from unittest.mock import MagicMock

from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


def test_reconcile_auth_proxy_updates_config_when_integrated():
    """
    arrange: given a charm with auth_proxy relation and ingress URL available.
    act: when _reconcile_auth_proxy is called.
    assert: auth proxy config is updated with the ingress URL.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()
    harness.set_can_connect(harness.model.unit.containers["jenkins"], True)

    # Mock ingress URL
    harness.charm.server_ingress = MagicMock()
    harness.charm.server_ingress.url = "https://example.com/jenkins"

    # Mock state with auth_proxy_integrated=True
    mock_state = MagicMock()
    mock_state.auth_proxy_integrated = True

    harness.charm._auth_proxy = MagicMock()

    harness.charm._reconcile_auth_proxy(mock_state)

    harness.charm._auth_proxy.update_auth_proxy_config.assert_called_once()
    call_kwargs = harness.charm._auth_proxy.update_auth_proxy_config.call_args
    config = call_kwargs.kwargs["auth_proxy_config"]
    assert config.protected_urls == ["https://example.com/jenkins"]


def test_reconcile_auth_proxy_skips_when_not_integrated():
    """
    arrange: given a charm without auth_proxy relation.
    act: when _reconcile_auth_proxy is called.
    assert: auth proxy config is not updated.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()

    mock_state = MagicMock()
    mock_state.auth_proxy_integrated = False

    harness.charm._auth_proxy = MagicMock()

    harness.charm._reconcile_auth_proxy(mock_state)

    harness.charm._auth_proxy.update_auth_proxy_config.assert_not_called()


def test_reconcile_auth_proxy_clears_config_when_no_ingress_url():
    """
    arrange: given a charm with auth_proxy relation but no ingress URL.
    act: when _reconcile_auth_proxy is called.
    assert: auth proxy config is updated with empty protected_urls.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()

    harness.charm.server_ingress = MagicMock()
    harness.charm.server_ingress.url = None

    mock_state = MagicMock()
    mock_state.auth_proxy_integrated = True

    harness.charm._auth_proxy = MagicMock()

    harness.charm._reconcile_auth_proxy(mock_state)

    harness.charm._auth_proxy.update_auth_proxy_config.assert_called_once()
    config = harness.charm._auth_proxy.update_auth_proxy_config.call_args[1]["auth_proxy_config"]
    assert config.protected_urls == []
