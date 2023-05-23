# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins-k8s charm unit tests for state module."""
import pytest

import state


@pytest.mark.parametrize(
    "invalid_meta,expected_err_message",
    [
        pytest.param(
            state.AgentMeta(executors="", labels="abc", slavehost="http://sample-host:8080"),
            "Fields ['executors'] cannot be empty.",
        ),
        pytest.param(
            state.AgentMeta(executors="abc", labels="abc", slavehost="http://sample-host:8080"),
            "Number of executors abc cannot be converted to type int.",
        ),
    ],
)
def test_agent_meta__validate(invalid_meta: state.AgentMeta, expected_err_message: str):
    """
    arrange: given an invalid agent metadata tuple.
    act: when validate is called.
    assert: ValidationError is raised with error messages.
    """
    with pytest.raises(state.ValidationError) as exc:
        invalid_meta.validate()

    assert expected_err_message in str(exc.value)
