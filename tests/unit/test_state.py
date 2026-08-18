# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s state module tests."""

import secrets
import typing
from unittest.mock import MagicMock

import ops
import pytest

import state


def make_mock_get_secret(
    secrets_by_id: dict[str, dict[str, str]] | None = None,
    admin_password_secret_content: dict[str, str] | None = None,
) -> typing.Callable:
    """Create a mock get_secret side_effect handler.

    Handles both id= and label= parameters for secret lookups.

    Args:
        secrets_by_id: Mapping of secret IDs to their content dicts.
        admin_password_secret_content: Content returned for admin password label lookups.

    Returns:
        A callable suitable for mock_charm.model.get_secret side_effect.

    Raises:
        ops.SecretNotFoundError: When secret is not found.
    """
    secrets_by_id = secrets_by_id or {}
    admin_password_secret_content = admin_password_secret_content or {}

    def mock_get_secret(**kwargs: typing.Any) -> MagicMock:
        """Mock implementation of model.get_secret.

        Args:
            **kwargs: Keyword arguments including 'id' or 'label'.

        Returns:
            Mocked secret object with get_content method.

        Raises:
            ops.SecretNotFoundError: When secret is not found.
        """
        if secret_id := kwargs.get("id"):
            if secret_id in secrets_by_id:
                mock_secret = MagicMock()
                mock_secret.get_content.return_value = secrets_by_id[secret_id]
                return mock_secret
            raise ops.SecretNotFoundError()

        if kwargs.get("label"):
            admin_secret = MagicMock()
            admin_secret.get_content.return_value = admin_password_secret_content
            return admin_secret

        raise ops.SecretNotFoundError()

    return mock_get_secret


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


@pytest.mark.parametrize(
    "config_value, expected",
    [
        pytest.param({}, [], id="no config set"),
        pytest.param({"system-properties": ""}, [], id="empty string"),
        pytest.param({"system-properties": " , , "}, [], id="whitespace and commas"),
        pytest.param(
            {"system-properties": "a=b, foo.bar=true , ,baz=qux"},
            ["-Da=b", "-Dfoo.bar=true", "-Dbaz=qux"],
            id="mixed with spaces and empties",
        ),
        pytest.param({"system-properties": "x="}, ["-Dx="], id="empty value allowed"),
    ],
)
def test_system_properties_parsing(mock_charm: MagicMock, config_value: dict, expected: list[str]):
    """
    arrange: given various system-properties config values.
    act: when state is initialized from charm.
    assert: system_properties are correctly parsed, trimmed, and prefixed with -D.
    """
    mock_charm.config = config_value
    mock_charm.model.get_relation.return_value = None

    config = state.State.from_charm(mock_charm)

    assert config.system_properties == expected


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


def test_agent_meta_from_relation_data_missing_fields():
    """
    arrange: given relation data missing required fields.
    act: when from_agent_relation is called.
    assert: None is returned.
    """
    result = state.AgentMeta.from_agent_relation({"executors": "1", "labels": "linux"})
    assert result is None


def test_agent_meta_from_relation_data_complete():
    """
    arrange: given relation data with all required fields.
    act: when from_agent_relation is called.
    assert: AgentMeta is returned without a remote filesystem opinion.
    """
    result = state.AgentMeta.from_agent_relation(
        {"executors": "1", "labels": "linux", "name": "agent-0"}
    )
    assert result is not None
    assert result.name == "agent-0"
    assert result.remote_fs is None


def test_agent_meta_from_relation_data_remote_fs():
    """An explicitly supplied remote filesystem is propagated to AgentMeta."""
    result = state.AgentMeta.from_agent_relation(
        {
            "executors": "1",
            "labels": "linux",
            "name": "agent-0",
            "remote_fs": "/workspace/jenkins",
        }
    )
    assert result is not None
    assert result.remote_fs == "/workspace/jenkins"


def test_get_relation_state_invalid_agent_data_raises_relation_error():
    """
    arrange: given relation data containing invalid agent metadata.
    act: when _get_relation_state is called.
    assert: CharmRelationDataInvalidError is raised.
    """
    mock_charm = MagicMock(spec=ops.CharmBase)
    mock_unit = MagicMock(spec=ops.Unit)
    mock_relation = MagicMock(spec=ops.Relation)
    mock_relation.units = [mock_unit]
    mock_relation.data = {
        mock_unit: {
            "executors": "not-an-int",
            "labels": "linux",
            "name": "agent-0",
        }
    }
    mock_charm.model.relations = {state.AGENT_RELATION: [mock_relation]}
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmRelationDataInvalidError, match="Invalid agent relation data"):
        state._get_relation_state(mock_charm)


def test_jcasc_config_from_charm(mock_charm: MagicMock):
    """
    arrange: given a charm with valid jcasc-config set.
    act: when state is initialized from charm.
    assert: jcasc_config contains the parsed dict.
    """
    test_config = "jenkins:\n  systemMessage: test\n"
    mock_charm.config = {"jcasc-config": test_config}

    result = state.State.from_charm(mock_charm)
    assert result.jcasc_config == {"jenkins": {"systemMessage": "test"}}


@pytest.mark.parametrize(
    "config_value",
    [
        pytest.param({}, id="not set"),
        pytest.param({"jcasc-config": ""}, id="empty string"),
        pytest.param({"jcasc-config": "   "}, id="whitespace only"),
    ],
)
def test_jcasc_config_none_cases(mock_charm: MagicMock, config_value: dict):
    """
    arrange: given a charm with no/empty jcasc-config.
    act: when state is initialized from charm.
    assert: jcasc_config is None.
    """
    mock_charm.config = config_value

    result = state.State.from_charm(mock_charm)

    assert result.jcasc_config is None


@pytest.mark.parametrize(
    "invalid_config, error_match",
    [
        pytest.param(
            "{{invalid: yaml: [[",
            "Invalid jcasc-config YAML",
            id="malformed YAML",
        ),
        pytest.param(
            "- item1\n- item2",
            "YAML mapping",
            id="list instead of dict",
        ),
    ],
)
def test_jcasc_config_invalid_yaml_raises(
    mock_charm: MagicMock, invalid_config: str, error_match: str
):
    """
    arrange: given a charm with invalid YAML in jcasc-config.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised with appropriate message.
    """
    mock_charm.config = {"jcasc-config": invalid_config}

    with pytest.raises(state.CharmConfigInvalidError, match=error_match):
        state.State.from_charm(mock_charm)


def test_jcasc_config_with_none_jenkins_section(mock_charm: MagicMock):
    """
    arrange: given a charm with 'jenkins:' (None value) in jcasc-config.
    act: when state is initialized from charm.
    assert: state parses successfully and jcasc_config has the None jenkins entry.
    """
    mock_charm.config = {"jcasc-config": "jenkins:"}

    result = state.State.from_charm(mock_charm)

    assert result.jcasc_config == {"jenkins": None}


def test_jcasc_config_with_non_dict_jenkins_section(mock_charm: MagicMock):
    """
    arrange: given a charm with non-dict jenkins section (e.g. jenkins: 'string').
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised (defence in depth validation).
    """
    mock_charm.config = {"jcasc-config": "jenkins: not_a_dict"}

    with pytest.raises(state.CharmConfigInvalidError, match=r"jenkins.*section must be a mapping"):
        state.State.from_charm(mock_charm)


def test_jcasc_repository_and_config_conflict_raises(mock_charm: MagicMock):
    """
    arrange: given a charm with both jcasc-config and jcasc-repository set.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised matching "mutually exclusive".
    """
    mock_charm.config = {
        "jcasc-config": "jenkins:\n  numExecutors: 0\n",
        "jcasc-repository": "https://example.com/repo.git",
    }
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmConfigInvalidError, match="mutually exclusive"):
        state.State.from_charm(mock_charm)


def test_jcasc_repository_url_stored(mock_charm: MagicMock):
    """
    arrange: given a charm with jcasc-repository set and jcasc-config empty.
    act: when state is initialized from charm.
    assert: jcasc_repository field contains the URL and jcasc_config is None.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "https://example.com/repo.git",
    }
    mock_charm.model.get_relation.return_value = None

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.jcasc_repository == "https://example.com/repo.git"
    assert charm_state.jcasc_config is None


def test_jcasc_repository_token_secret_parsed(mock_charm: MagicMock):
    """
    arrange: given a charm with jcasc-repository-token secret URI set.
    act: when state is initialized from charm.
    assert: jcasc_repository_token field contains (username, token) tuple.
    """
    secret_id = f"secret:{secrets.token_hex(4)}"
    mock_secret = MagicMock()
    mock_secret.get_content.return_value = {"username": "git", "token": "ghp_x"}
    mock_charm.model.get_secret.return_value = mock_secret
    mock_charm.config = {
        "jcasc-repository": "https://example.com/r.git",
        "jcasc-repository-token": secret_id,
    }
    mock_charm.model.get_relation.return_value = None

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.jcasc_repository_token == ("git", "ghp_x")


def test_jcasc_repository_token_missing_keys_blocks(mock_charm: MagicMock):
    """
    arrange: given a charm with jcasc-repository-token missing required keys.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised matching "username and token".
    """
    secret_id = f"secret:{secrets.token_hex(4)}"
    mock_secret = MagicMock()
    mock_secret.get_content.return_value = {"username": "git"}  # missing 'token'
    mock_charm.model.get_secret.return_value = mock_secret
    mock_charm.config = {
        "jcasc-repository": "https://example.com/r.git",
        "jcasc-repository-token": secret_id,
    }
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmConfigInvalidError, match="username and token"):
        state.State.from_charm(mock_charm)


def test_jcasc_repository_token_secret_not_found_blocks(mock_charm: MagicMock):
    """
    arrange: given a charm with jcasc-repository-token pointing to missing secret.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised mentioning token secret not found.
    """
    secret_id = f"secret:{secrets.token_hex(4)}"
    mock_charm.model.get_secret.side_effect = ops.SecretNotFoundError()
    mock_charm.config = {
        "jcasc-repository": "https://example.com/r.git",
        "jcasc-repository-token": secret_id,
    }
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmConfigInvalidError, match="token secret not found"):
        state.State.from_charm(mock_charm)


@pytest.mark.parametrize(
    "config_path_value, expected",
    [
        pytest.param("", "jcasc", id="empty defaults to jcasc"),
        pytest.param("jenkins/config", "jenkins/config", id="custom path"),
        pytest.param(".", ".", id="root directory"),
    ],
)
def test_jcasc_repository_config_path(
    mock_charm: MagicMock, config_path_value: str, expected: str
):
    """
    arrange: given a charm with jcasc-repository-config-path set to various values.
    act: when state is initialized from charm.
    assert: jcasc_repository_config_path matches expected value.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "https://example.com/repo.git",
        "jcasc-repository-config-path": config_path_value,
    }
    mock_charm.model.get_relation.return_value = None

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.jcasc_repository_config_path == expected


def test_jcasc_repository_config_path_absolute_path_raises(mock_charm: MagicMock):
    """
    arrange: given a charm with jcasc-repository-config-path set to absolute path.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "https://example.com/repo.git",
        "jcasc-repository-config-path": "/absolute/path",
    }
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(
        state.CharmConfigInvalidError,
        match="jcasc-repository-config-path must be relative",
    ):
        state.State.from_charm(mock_charm)


def test_jcasc_environment_secrets_unset(mock_charm: MagicMock):
    """
    arrange: given a charm with jcasc-environment-secrets not set.
    act: when state is initialized from charm.
    assert: jcasc_environment_secrets field is None.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "",
        "jcasc-environment-secrets": "",
    }
    mock_charm.model.get_relation.return_value = None

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.jcasc_environment_secrets is None


def test_jcasc_environment_secrets_secret_parsed(mock_charm: MagicMock, secret_id: str):
    """
    arrange: given a charm with jcasc-environment-secrets secret URI set.
    act: when state is initialized from charm.
    assert: jcasc_environment_secrets field contains the secret content dict.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "",
        "jcasc-environment-secrets": secret_id,
    }
    mock_charm.model.get_secret = make_mock_get_secret(
        secrets_by_id={secret_id: {"VAR1": "value1", "VAR2": "value2"}}
    )
    mock_charm.model.get_relation.return_value = None

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.jcasc_environment_secrets == {"VAR1": "value1", "VAR2": "value2"}


def test_jcasc_environment_secrets_empty_secret_ignored(mock_charm: MagicMock, secret_id: str):
    """
    arrange: given a charm with jcasc-environment-secrets pointing to empty secret.
    act: when state is initialized from charm.
    assert: jcasc_environment_secrets field is None.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "",
        "jcasc-environment-secrets": secret_id,
    }
    mock_charm.model.get_secret = make_mock_get_secret(secrets_by_id={secret_id: {}})
    mock_charm.model.get_relation.return_value = None

    charm_state = state.State.from_charm(mock_charm)

    assert charm_state.jcasc_environment_secrets is None


def test_jcasc_environment_secrets_missing_secret_blocks(mock_charm: MagicMock, secret_id: str):
    """
    arrange: given a charm with jcasc-environment-secrets pointing to missing secret.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised mentioning secret not found.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "",
        "jcasc-environment-secrets": secret_id,
    }
    # Don't include secret_id in the secrets dict so lookup fails
    mock_charm.model.get_secret = make_mock_get_secret(secrets_by_id={})
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmConfigInvalidError, match="secret not found"):
        state.State.from_charm(mock_charm)


def test_jcasc_environment_secrets_invalid_env_var_names_blocks(
    mock_charm: MagicMock, secret_id: str
):
    """
    arrange: given a charm with jcasc-environment-secrets containing invalid env var names.
    act: when state is initialized from charm.
    assert: CharmConfigInvalidError is raised mentioning invalid names.
    """
    mock_charm.config = {
        "jcasc-config": "",
        "jcasc-repository": "",
        "jcasc-environment-secrets": secret_id,
    }
    # Keys with invalid characters: spaces, hyphens, starting with digit
    mock_charm.model.get_secret = make_mock_get_secret(
        secrets_by_id={
            secret_id: {
                "VALID_VAR": "val",
                "123INVALID": "val",
                "NO-HYPHEN": "val",
            }
        }
    )
    mock_charm.model.get_relation.return_value = None

    with pytest.raises(state.CharmConfigInvalidError, match="invalid environment variable names"):
        state.State.from_charm(mock_charm)


@pytest.mark.parametrize(
    "remote_fs",
    ["relative/path", "/", "//", "///", "/var/lib/../etc/jenkins", "/var/lib/jenkins\n"],
)
def test_agent_meta_rejects_unsafe_remote_fs(remote_fs: str):
    """Reject unsafe workspace roots from relation metadata."""
    with pytest.raises(state.ValidationError, match="remote_fs"):
        state.AgentMeta(
            executors="1",
            labels="linux",
            name="agent-0",
            remote_fs=remote_fs,
        )
