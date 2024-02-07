# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s state module tests."""
import typing
from unittest.mock import MagicMock

import ops
import pytest

import state


def test_state_invalid_time_config():
    """
    arrange: given an invalid time charm config.
    act: when state is initialized through from_charm method.
    assert: CharmConfigInvalidError is raised.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_charm.config = {"restart-time-range": "-1"}

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(mock_charm)


@pytest.mark.parametrize(
    "time_range",
    [
        pytest.param("", id="empty string"),
    ],
)
def test_no_time_range_config(time_range: str, mock_charm: MagicMock):
    """
    arrange: given an empty time range config value.
    act: when state is instantiated.
    assert: state without time range is returned.
    """
    mock_charm.config = {"restart-time-range": time_range}

    returned_state = state.State.from_charm(mock_charm)

    assert (
        returned_state.restart_time_range is None
    ), "Restart time range should not be instantiated."


class AgentMeta(typing.TypedDict):
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
            AgentMeta(executors="", labels="abc", name="http://sample-host:8080"),
        ),
        pytest.param(
            AgentMeta(executors="abc", labels="abc", name="http://sample-host:8080"),
        ),
    ],
)
def test_agent_meta__validate(invalid_meta: AgentMeta):
    """
    arrange: given an invalid agent metadata tuple.
    act: when validate is called.
    assert: ValidationError is raised.
    """
    with pytest.raises(state.ValidationError):
        state.AgentMeta(**invalid_meta)


def test_proxyconfig_invalid(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a monkeypatched os.environ mapping that contains invalid proxy values.
    act: when charm state is initialized.
    assert: CharmConfigInvalidError is raised.
    """
    monkeypatch.setattr(state.os, "environ", {"JUJU_CHARM_HTTP_PROXY": "INVALID_URL"})
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_charm.config = {}

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(mock_charm)


def test_proxyconfig_none(monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given mapping without proxy configuration.
    act: when ProxyConfig.from_charm_config is called.
    assert: None is returned.
    """
    # has to be monkeypatched to empty value since Github Runner will pick up squid.internal proxy.
    monkeypatch.setattr(state.os, "environ", {})

    assert state.ProxyConfig.from_env() is None


def test_proxyconfig_from_charm_env(
    monkeypatch: pytest.MonkeyPatch,
    proxy_config: state.ProxyConfig,
    mock_charm: MagicMock,
):
    """
    arrange: given a monkeypatched os.environ with proxy configurations.
    act: when ProxyConfig.from_charm_config is called.
    assert: valid proxy configuration is returned.
    """
    monkeypatch.setattr(
        state.os,
        "environ",
        {
            "JUJU_CHARM_HTTP_PROXY": str(proxy_config.http_proxy),
            "JUJU_CHARM_HTTPS_PROXY": str(proxy_config.https_proxy),
            "JUJU_CHARM_NO_PROXY": str(proxy_config.no_proxy),
        },
    )
    mock_charm.config = {}

    config = state.State.from_charm(mock_charm).proxy_config
    assert config, "Valid proxy config should not return None."
    assert config.http_proxy == proxy_config.http_proxy
    assert config.https_proxy == proxy_config.https_proxy
    assert config.no_proxy == proxy_config.no_proxy


def test_plugins_config_none(mock_charm: MagicMock):
    """
    arrange: given a charm with no plugins config.
    act: when state is initialized from charm.
    assert: plugin state is None.
    """
    mock_charm.config = {}

    config = state.State.from_charm(mock_charm)
    assert config.plugins is None


def test_plugins_config(mock_charm: MagicMock):
    """
    arrange: given a charm with comma separated plugins.
    act: when state is initialized from charm.
    assert: plugin state contains an iterable of plugins.
    """
    mock_charm.config = {"allowed-plugins": "hello, world"}

    config = state.State.from_charm(mock_charm)
    assert config.plugins is not None
    assert tuple(config.plugins) == ("hello", "world")


def test_invalid_num_units(mock_charm: MagicMock):
    """
    arrange: given a mock charm with more than 1 unit of deployment.
    act: when state is initialized from charm.
    assert: CharmIllegalNumUnitsError is raised.
    """
    mock_charm.app.planned_units.return_value = 2

    with pytest.raises(state.CharmIllegalNumUnitsError):
        state.State.from_charm(mock_charm)


def test_remotingconfig_invalid(mock_charm: MagicMock):
    """
    arrange: given a mock charm with invalid remoting configuration.
    act: when charm state is initialized.
    assert: CharmConfigInvalidError is raised.
    """
    mock_charm.config = {
        "remoting-external-url": "invalid",
        "remoting-enable-websocket": "invalid",
    }

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(mock_charm)
