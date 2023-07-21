# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s state module tests."""
import typing

import pytest
from ops.testing import Harness

import charm
import state


def test_state_invalid_time_config(harness: Harness):
    """
    arrange: given an invalid time charm config.
    act: when state is initialized through from_charm method.
    assert: CharmConfigInvalidError is raised.
    """
    harness.update_config({"update-time-range": "-1"})
    harness.begin()

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(typing.cast(charm.JenkinsK8sOperatorCharm, harness.charm))


@pytest.mark.parametrize(
    "time_range",
    [
        pytest.param("", id="empty string"),
    ],
)
def test_no_time_range_config(time_range: str, harness: Harness):
    """
    arrange: given an empty time range config value.
    act: when state is instantiated.
    assert: state without time range is returned.
    """
    harness.update_config({"update-time-range": time_range})
    harness.begin()

    assert (
        typing.cast(charm.JenkinsK8sOperatorCharm, harness.charm).state.update_time_range is None
    ), "Update time range should not be instantiated."


class TestAgentMeta(typing.TypedDict):
    """Metadata wrapper for testing.

    Attrs:
        executors: Number of executors.
        labels: Label to be given to agent.
        name: Name of the agent.
    """

    executors: str
    labels: str
    name: str


@pytest.mark.parametrize(
    "invalid_meta",
    [
        pytest.param(
            TestAgentMeta(executors="", labels="abc", name="http://sample-host:8080"),
        ),
        pytest.param(
            TestAgentMeta(executors="abc", labels="abc", name="http://sample-host:8080"),
        ),
    ],
)
def test_agent_meta__validate(invalid_meta: TestAgentMeta):
    """
    arrange: given an invalid agent metadata tuple.
    act: when validate is called.
    assert: ValidationError is raised.
    """
    with pytest.raises(state.ValidationError):
        state.AgentMeta(**invalid_meta)


def test_proxyconfig_invalid(harness: Harness, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a monkeypatched os.environ mapping that contains invalid proxy values.
    act: when charm state is initialized.
    assert: CharmConfigInvalidError is raised.
    """
    monkeypatch.setattr(state.os, "environ", {"HTTP_PROXY": "INVALID_URL"})
    harness.begin()

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(harness.charm)


def test_proxyconfig_none(harness: Harness):
    """
    arrange: given mapping without proxy configuration.
    act: when ProxyConfig.from_charm_config is called.
    assert: None is returned.
    """
    harness.begin()

    assert state.ProxyConfig.from_charm_env({}) is None


def test_proxyconfig_from_charm_env(harness: Harness, proxy_config: state.ProxyConfig):
    """
    arrange: given mapping with proxy configurations.
    act: when ProxyConfig.from_charm_config is called.
    assert: valid proxy configuration is returned.
    """
    harness.begin()

    config = state.ProxyConfig.from_charm_env(
        {
            "HTTP_PROXY": str(proxy_config.http_proxy),
            "HTTPS_PROXY": str(proxy_config.https_proxy),
            "NO_PROXY": str(proxy_config.no_proxy),
        }
    )
    assert config, "Valid proxy config should not return None."
    assert config.http_proxy == proxy_config.http_proxy
    assert config.https_proxy == proxy_config.https_proxy
    assert config.no_proxy == proxy_config.no_proxy
