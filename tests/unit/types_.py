# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types used for unit testing Jenkins."""

from pathlib import Path
from typing import NamedTuple

from ops.model import Container


class ContainerWithPath(NamedTuple):
    """Charm container with temp path to mock container filesystem.

    Attrs:
        container: The mocked charm container.
        path: The mocked container filesystem path.
    """

    container: Container
    path: Path
