# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import requests
from ops.model import Container

from types_ import Credentials, JenkinsEnvironmentMap

JENKINS_WEB_URL = "http://localhost:8080"
JENKINS_HOME_PATH = Path("/var/lib/jenkins")
# Path to initial Jenkins password file
JENKINS_PASSWORD_FILE_PATH = JENKINS_HOME_PATH / "secrets/initialAdminPassword"
# Path to last executed Jenkins version file, required to override wizard installation
LAST_EXEC = JENKINS_HOME_PATH / Path("jenkins.install.InstallUtil.lastExecVersion")
# Path to Jenkins version file, required to override wizard installation
UPDATE_VERSION = JENKINS_HOME_PATH / Path("jenkins.install.UpgradeWizard.state")


def _is_jenkins_ready() -> bool:
    """Check if Jenkins webserver is ready.

    Returns:
        True if Jenkins server is online. False otherwise.
    """
    try:
        return requests.get(f"{JENKINS_WEB_URL}/login", timeout=10).ok
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False


def wait_jenkins_ready(timeout: int = 140, check_interval: int = 10) -> None:
    """Wait until Jenkins service is up.

    Args:
        timeout: Time in seconds to wait for jenkins to become ready in 10 second intervals.
        check_interval: Time in seconds to wait between ready checks.

    Raises:
        TimeoutError: if Jenkins status check did not pass within the timeout duration.
    """
    start_time = datetime.now()
    now = datetime.now()
    min_wait_seconds = timedelta(seconds=timeout)
    while now - start_time < min_wait_seconds:
        if _is_jenkins_ready():
            break
        now = datetime.now()
        sleep(check_interval)
    else:
        raise TimeoutError("Timed out waiting for Jenkins to become ready.")


def get_admin_credentials(connectable_container: Container) -> Credentials:
    """Retrieve admin credentials.

    Args:
        connectable_container: Connectable container to interact with filesystem.

    Returns:
        The Jenkins admin account credentials.
    """
    user = "admin"
    password_file_contents = str(connectable_container.pull(JENKINS_PASSWORD_FILE_PATH).read())
    return Credentials(username=user, password=password_file_contents.strip())


def calculate_env(admin_configured: bool) -> JenkinsEnvironmentMap:
    """Return a dictionary for Jenkins Pebble layer.

    Args:
        admin_configured: Whether admin user has been configured in Jenkins.

    Returns:
        The dictionary mapping of environment variables for the Jenkins service.
    """
    env = JenkinsEnvironmentMap(JENKINS_HOME=str(JENKINS_HOME_PATH))
    env["ADMIN_CONFIGURED"] = str(admin_configured)
    return env


def get_version() -> str:
    """Get the Jenkins server version.

    Returns:
        The Jenkins server version.
    """
    return requests.get(JENKINS_WEB_URL, timeout=10).headers["X-Jenkins"]


def unlock_jenkins(connectable_container: Container) -> None:
    """Write to executed version and updated version file to bypass Jenkins setup wizard.

    Args:
        connectable_container: The connectable Jenkins workload container.
    """
    version = get_version()
    connectable_container.push(LAST_EXEC, version, encoding="utf-8", make_dirs=True)
    connectable_container.push(UPDATE_VERSION, version, encoding="utf-8", make_dirs=True)
