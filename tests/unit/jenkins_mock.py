# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Module for mocking Jenkins Client."""

from typing import Any


class MockedJenkinsClient:
    """Mocked Jenkins Client.

    Attributes:
        version: The mocked Jenkins version string.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        """Init function to match function signature required to instantiate the client.

        Args:
            args: Placeholder arguments.
            kwargs: Placeholder keyword arguments.
        """
        del args, kwargs
        pass

    @property
    def version(self) -> str:
        """Return the Jenkins version."""
        return "2.387"
