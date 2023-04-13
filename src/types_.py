# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types used by the Jenkins charm."""

from typing import NamedTuple


class Credentials(NamedTuple):
    """Information needed to log into Jenkins.

    Attrs:
        username: The Jenkins account username used to log into Jenkins.
        password: The Jenkins account password used to log into Jenkins.
    """

    username: str
    password: str
