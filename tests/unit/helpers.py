# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions used to unit test Jenkins charm."""

from pathlib import Path

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
