# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper functions used to unit test Jenkins charm."""

import requests


# There aren't enough public methods with this patch class.
class ConnectionExceptionPatch:  # pylint: disable=too-few-public-methods
    """Class to raise ConnectionError exception."""

    def __init__(self, *_, **__) -> None:
        """Placeholder init function to match function signatures.

        Raises:
            ConnectionError: To mock connection error.
        """
        raise requests.ConnectionError
