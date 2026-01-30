# Copyright 2025 Canonical Ltd.
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

    assert returned_state.restart_time_range is None, (
        "Restart time range should not be instantiated."
    )


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


def test_auth_proxy_integrated_false(mock_charm: MagicMock):
    """
    arrange: given a charm with no auth proxy integration.
    act: when state is initialized from charm.
    assert: auth_proxy_integrated is False.
    """
    mock_charm.config = {}
    mock_charm.model.get_relation.return_value = {}

    config = state.State.from_charm(mock_charm)
    assert not config.auth_proxy_integrated


def test_auth_proxy_integrated_true(mock_charm: MagicMock):
    """
    arrange: given a charm with auth proxy integration.
    act: when state is initialized from charm.
    assert: auth_proxy_integrated is True.
    """
    mock_charm.config = {}

    config = state.State.from_charm(mock_charm)
    assert not config.auth_proxy_integrated


def test_agent_discovery_ingress_without_server_ingress(
    mock_charm: MagicMock, monkeypatch: pytest.MonkeyPatch
):
    """
    arrange: a charm with agent discovery ingress but no server ingress.
    act: when state.from_charm is called.
    assert: CharmConfigInvalidError is raised.
    """
    monkeypatch.setattr(
        mock_charm.model,
        "get_relation",
        lambda relation_name: (
            None if relation_name == state.INGRESS_RELATION_NAME else MagicMock()
        ),
    )

    with pytest.raises(state.CharmConfigInvalidError):
        state.State.from_charm(mock_charm)


def test_invalid_num_units(mock_charm: MagicMock, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: given a mock charm with more than 1 unit of deployment.
    act: when state is initialized from charm.
    assert: CharmIllegalNumUnitsError is raised.
    """
    mock_charm.config = {}
    mock_charm.model.get_relation.return_value = None
    monkeypatch.setattr(mock_charm.app, "planned_units", MagicMock(return_value=2))

    with pytest.raises(state.CharmIllegalNumUnitsError):
        state.State.from_charm(mock_charm)


def test_system_properties_no_config(mock_charm: MagicMock):
    """
    arrange: given no system-properties config set.
    act: when state is initialized from charm.
    assert: system_properties is an empty list.
    """
    mock_charm.config = {}
    # Ensure no auth-proxy integration is detected
    mock_charm.model.get_relation.return_value = None

    config = state.State.from_charm(mock_charm)
    assert config.system_properties == []


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty string"),
        pytest.param(" , , ", id="whitespace and commas"),
    ],
)
def test_system_properties_empty_values_ignored(mock_charm: MagicMock, value: str):
    """
    arrange: given empty or whitespace-only system-properties entries.
    act: when state is initialized from charm.
    assert: system_properties is an empty list.
    """
    mock_charm.config = {"system-properties": value}
    mock_charm.model.get_relation.return_value = None

    config = state.State.from_charm(mock_charm)
    assert config.system_properties == []


def test_system_properties_parsing_and_trimming(mock_charm: MagicMock):
    """
    arrange: given mixed system-properties with spaces and empties.
    act: when state is initialized from charm.
    assert: properties are trimmed, ordered, and prefixed with -D.
    """
    mock_charm.config = {"system-properties": "a=b, foo.bar=true , ,baz=qux"}
    mock_charm.model.get_relation.return_value = None

    config = state.State.from_charm(mock_charm)
    assert config.system_properties == ["-Da=b", "-Dfoo.bar=true", "-Dbaz=qux"]


def test_system_properties_empty_value_allowed(mock_charm: MagicMock):
    """
    arrange: given a key with an empty value.
    act: when state is initialized from charm.
    assert: entry is accepted and prefixed with -D.
    """
    mock_charm.config = {"system-properties": "x="}
    mock_charm.model.get_relation.return_value = None

    config = state.State.from_charm(mock_charm)
    assert config.system_properties == ["-Dx="]


@pytest.mark.parametrize(
    "bad_value",
    [
        pytest.param("bad", id="missing equals"),
        pytest.param("=bad", id="starts with equals"),
    ],
)
def test_system_properties_invalid_entries_raise(mock_charm: MagicMock, bad_value: str):
    """
    arrange: given invalid system-properties entries.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised with message about key=value pairs.
    """
    mock_charm.config = {"system-properties": bad_value}
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmConfigInvalidError) as excinfo:
        state.State.from_charm(mock_charm)

    assert "expected key=value" in str(excinfo.value.msg)
