# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Module for mocking Jenkins Client."""

from typing import Any


class MockedJenkinsClient:  # pylint: disable=too-few-public-methods
    """Mocked Jenkins Client."""

    def __init__(self, *args: Any, **kwargs: Any):
        """Init function to match function signature required to instantiate the client.

        Args:
            args: Placeholder arguments.
            kwargs: Placeholder keyword arguments.
        """
        del args, kwargs

    def get_version(self) -> str:
        """Return the Jenkins version.

        Returns:
            The Jenkins server version number.
        """
        return "2.400"
