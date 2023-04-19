# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from typing import cast

import requests

from types_ import Credentials, JenkinsEnvironmentMap

JENKINS_WEB_URL = "http://localhost:8080"
JENKINS_HOME = Path("/var/lib/jenkins")


def _is_jenkins_ready() -> bool:
    """Check if Jenkins webserver is ready.

    Returns:
        True if Jenkins server is online. False otherwise.
    """
    return requests.get(f"{JENKINS_WEB_URL}/login", timeout=10).ok


def wait_jenkins_ready(timeout: int = 140, check_interval: int = 10) -> None:
    """Wait until Jenkins service is up.

    Args:
        timeout: Time in seconds to wait for jenkins to become ready in 10 second intervals.
        check_interval: Time in seconds to wait between ready checks.

    Raises:
        TimeoutError: if Jenkins status check did not pass within the timeout duration.
    """
    start_time = datetime.now()
    min_wait_seconds = timedelta(seconds=timeout)
    while True:
        if _is_jenkins_ready():
            break
        now = datetime.now()
        if now - start_time > min_wait_seconds:
            raise TimeoutError("Timed out waiting for Jenkins to become ready.")
        sleep(check_interval)


def get_admin_credentials(password_file_contents: str) -> Credentials:
    """Retrieve admin credentials.

    Args:
        password_file_contents: The contents inside `$JENKINS_HOME/secrets/initialAdminPassword`
        file.

    Returns:
        The Jenkins admin account credentials.
    """
    user = "admin"
    return Credentials(username=user, password=password_file_contents.strip())


def calculate_env(admin_configured: bool) -> dict[str, str]:
    """Return a dictionary for Jenkins Pebble layer.

    Args:
        admin_configured: Whether admin user has been configured in Jenkins.

    Returns:
        The dictionary mapping of environment variables for the Jenkins pebble service layer.
    """
    env = JenkinsEnvironmentMap(JENKINS_HOME=str(JENKINS_HOME))
    env["ADMIN_CONFIGURED"] = str(admin_configured)
    # Mypy type doesn't recognize TypedDict to be compatible with dict.
    return cast(dict[str, str], env)
