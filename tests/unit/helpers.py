# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions used to unit test Jenkins charm."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

ACTIVE_STATUS_NAME = "active"
BLOCKED_STATUS_NAME = "blocked"
MAINTENANCE_STATUS_NAME = "maintenance"
WAITING_STATUS_NAME = "waiting"


# There aren't enough public methods with this patch class.
class ConnectionExceptionPatch:  # pylint: disable=too-few-public-methods
    """Class to raise ConnectionError exception."""

    def __init__(self, *_args, **_kwargs) -> None:
        """Placeholder init function to match function signatures.

        Raises:
            ConnectionError: To mock connection error.
        """
        raise requests.ConnectionError


def combine_root_paths(root_path: Path, relative_path: Path) -> Path:
    """Helper function to combine two root paths.

    If two root paths are combined, e.g. /tmp/..., /var/..., the latter will override the prioir
    resulting in /var/... . This function helps combine the two root paths as relative path.

    i.e. Path(/root_path/...) / Path(/relative_path/...) => Path(/root_path/.../relative_path/...)

    Args:
        root_path: The root path to append relative path to.
        relative_path: The path to concatenate to root path.

    Returns:
        The combined paths.
    """
    return root_path / str(relative_path).removeprefix("/")


@contextmanager
def patch_reconcile_pipeline(
    charm: object, *, patch_agents: bool = True, agents_return: bool = True
) -> Iterator[dict[str, MagicMock]]:
    """Patch common reconcile pipeline methods and return their mocks.

    Args:
        charm: Charm instance or class to patch methods on.
        patch_agents: Whether to patch ``_reconcile_agents``.
        agents_return: Return value for ``_reconcile_agents`` when patched.

    Yields:
        Mapping of patched method labels to mocks.
    """
    with ExitStack() as stack:
        mocks: dict[str, MagicMock] = {}
        mocks["reconcile_storage"] = stack.enter_context(patch.object(charm, "_reconcile_storage"))
        mocks["reconcile_bootstrap_prestart"] = stack.enter_context(
            patch.object(charm, "_reconcile_bootstrap_prestart", return_value=True)
        )
        mocks["reconcile_pebble"] = stack.enter_context(patch.object(charm, "_reconcile_pebble"))
        mocks["reconcile_bootstrap_poststart"] = stack.enter_context(
            patch.object(charm, "_reconcile_bootstrap_poststart", return_value=True)
        )
        if patch_agents:
            mocks["reconcile_agents"] = stack.enter_context(
                patch.object(charm, "_reconcile_agents", return_value=agents_return)
            )
        yield mocks
