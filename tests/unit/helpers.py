# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions used to unit test Jenkins charm."""

from pathlib import Path

import requests


def make_relative_to_path(tmp_path: Path, root_path: Path) -> Path:
    """Make a root path (/path/from/root) relative to tmp_path.

    If a path starts with "/", the path join operator "/" doesn't append the paths together but
    replaces the path with the latter path. This helper function overrides that behavior.

    Args:
        tmp_path: Temporary path to base off of.
        root_path: Root path beginning with /.

    Returns:
        Path relative to tmp_path.
    """
    if str(root_path).startswith("/"):
        root_path = Path(str(root_path).replace("/", "", 1))
    return tmp_path / root_path


class ConnectionExceptionPatch:  # pylint: disable=too-few-public-methods
    """Class to raise ConnectionError exception."""

    def __init__(self, *args, **kwargs) -> None:
        """Placeholder init function to match function signatures.

        Args:
            args: Placeholder args.
            kwargs: Placeholder kwargs.

        Raises:
            ConnectionError: To mock connection error.
        """
        del args, kwargs
        raise requests.ConnectionError
