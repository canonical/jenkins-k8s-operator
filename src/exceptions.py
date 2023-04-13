# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Exceptions raised by the jenkins-k8s charm."""


class TimeoutError(Exception):
    """Execution timed out."""
