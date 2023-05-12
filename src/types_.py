# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types used by the Jenkins charm."""

from typing import NamedTuple, TypedDict


class Credentials(NamedTuple):
    """Information needed to log into Jenkins.

    Attrs:
        username: The Jenkins account username used to log into Jenkins.
        password: The Jenkins account password used to log into Jenkins.
    """

    username: str
    password: str


class JenkinsEnvironmentMap(TypedDict):
    """Dictionary mapping of Jenkins environment variables.

    Attrs:
        JENKINS_HOME: The Jenkins home directory.
        ADMIN_CONFIGURED: Boolean string "true" or "false", representing whether the Jenkins admin
            account has been configured.
    """

    JENKINS_HOME: str
    ADMIN_CONFIGURED: str
