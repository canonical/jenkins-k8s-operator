# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s auth_proxy unit tests."""

# pylint:disable=protected-access

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from charms.oauth2_proxy_k8s.v0.auth_proxy import AuthProxyConfig
from ops.testing import Harness

from charm import JenkinsK8sOperatorCharm


@pytest.mark.parametrize(
    "integrated, ingress_url, should_call, expected_protected_urls",
    [
        pytest.param(
            True,
            "https://example.com/jenkins",
            True,
            ["https://example.com/jenkins"],
            id="integrated-with-ingress",
        ),
        pytest.param(True, None, True, [], id="integrated-without-ingress"),
        pytest.param(
            False,
            "https://example.com/jenkins",
            False,
            None,
            id="not-integrated-with-ingress",
        ),
        pytest.param(False, None, False, None, id="not-integrated-without-ingress"),
    ],
)
def test_reconcile_auth_proxy(
    integrated: bool,
    ingress_url: str | None,
    should_call: bool,
    expected_protected_urls: list[str] | None,
):
    """
    arrange: given auth-proxy integration and ingress URL combinations.
    act: when _reconcile_auth_proxy is called.
    assert: auth-proxy configuration update behavior matches expected matrix.
    """
    harness = Harness(JenkinsK8sOperatorCharm)
    harness.begin()

    harness.charm.server_ingress = MagicMock()
    harness.charm.server_ingress.url = ingress_url
    harness.charm._auth_proxy = MagicMock()

    state = SimpleNamespace(auth_proxy_integrated=integrated)

    harness.charm._reconcile_auth_proxy(state=state)  # type: ignore[arg-type]

    if not should_call:
        harness.charm._auth_proxy.update_auth_proxy_config.assert_not_called()
        return

    harness.charm._auth_proxy.update_auth_proxy_config.assert_called_once()
    call_kwargs = cast(
        dict[str, Any],
        harness.charm._auth_proxy.update_auth_proxy_config.call_args.kwargs,
    )
    config = cast(AuthProxyConfig, call_kwargs["auth_proxy_config"])

    assert config.protected_urls == expected_protected_urls
    assert config.allowed_endpoints == []
    assert config.headers == ["X-Auth-Request-User"]
