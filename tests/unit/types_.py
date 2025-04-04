# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types used for unit testing Jenkins."""

from typing import NamedTuple

from ops.model import Container
from ops.testing import Harness


class HarnessWithContainer(NamedTuple):
    """Charm container with temp path to mock container filesystem.

    Attributes:
        harness: The ops testing Harness.
        container: Connectable jenkins harness container.
    """

    harness: Harness
    container: Container
