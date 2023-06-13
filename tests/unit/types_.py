# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types used for unit testing Jenkins."""

from typing import NamedTuple

from ops.model import Container
from ops.testing import Harness


class HarnessWithContainer(NamedTuple):
    """Charm container with temp path to mock container filesystem.

    Attrs:
        harness: The ops testing Harness.
        container: Connectable jenkins harness container.
    """

    harness: Harness
    container: Container


class Versions(NamedTuple):
    """Jenkins versions fixture wrapper to reduce number of fixture arguments.

    Attrs:
        current: The current Jenkins version.
        patched: The patched Jenkins version.
        minor_update: The minor updated Jenkins version.
    """

    current: str
    patched: str
    minor_update: str
