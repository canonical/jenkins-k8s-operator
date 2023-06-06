# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

import dataclasses
import logging
import typing
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import jenkinsapi.custom_exceptions
import jenkinsapi.jenkins
import ops
import requests

logger = logging.getLogger(__name__)

WEB_PORT = 8080
WEB_URL = f"http://localhost:{WEB_PORT}"
HOME_PATH = Path("/var/jenkins")
WAR_PATH = Path("/srv/jenkins/")
# Path to initial Jenkins password file
PASSWORD_FILE_PATH = HOME_PATH / "secrets/initialAdminPassword"
# Path to last executed Jenkins version file, required to override wizard installation
LAST_EXEC_VERSION_PATH = HOME_PATH / Path("jenkins.install.InstallUtil.lastExecVersion")
# Path to Jenkins version file, required to override wizard installation
WIZARD_VERSION_PATH = HOME_PATH / Path("jenkins.install.UpgradeWizard.state")
# The Jenkins bootstrapping config path
CONFIG_FILE_PATH = HOME_PATH / "config.xml"
# The Jenkins plugins installation directory
PLUGINS_PATH = HOME_PATH / "plugins"

# The plugins that are required for Jenkins to work
REQUIRED_PLUGINS = [
    "instance-identity",  # required to connect agent nodes to server
]

USER = "jenkins"
GROUP = "jenkins"

BUILT_IN_NODE_NAME = "Built-In Node"


class JenkinsError(Exception):
    """Base exception for Jenkins errors."""


class JenkinsPluginError(JenkinsError):
    """An error occurred installing Jenkins plugin."""


class JenkinsBootstrapError(JenkinsError):
    """An error occurred during the bootstrapping process."""


class ValidationError(Exception):
    """An unexpected data is encountered."""


@dataclasses.dataclass(frozen=True)
class AgentMeta:
    """Metadata for registering Jenkins Agent.

    Attrs:
        executors: Number of executors of the agent in string format.
        labels: Comma separated list of labels to be assigned to the agent.
        slavehost: The host name of the agent.
    """

    executors: str
    labels: str
    slavehost: str

    def validate(self) -> None:
        """Validate the agent metadata.

        Raises:
            ValidationError: if the field contains invalid data.
        """
        empty_fields = [
            field
            # Pylint doesn't understand that __annotations__ is implemented in a Python class.
            for field in self.__annotations__.keys()  # pylint: disable=no-member
            if not getattr(self, field)
        ]
        if empty_fields:
            raise ValidationError(f"Fields {empty_fields} cannot be empty.")
        try:
            int(self.executors)
        except ValueError as exc:
            raise ValidationError(
                f"Number of executors {self.executors} cannot be converted to type int."
            ) from exc


def _is_ready() -> bool:
    """Check if Jenkins webserver is ready.

    Returns:
        True if Jenkins server is online. False otherwise.
    """
    try:
        return requests.get(f"{WEB_URL}/login", timeout=10).ok
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return False


def wait_ready(timeout: int = 300, check_interval: int = 10) -> None:
    """Wait until Jenkins service is up.

    Args:
        timeout: Time in seconds to wait for jenkins to become ready in 10 second intervals.
        check_interval: Time in seconds to wait between ready checks.

    Raises:
        TimeoutError: if Jenkins status check did not pass within the timeout duration.
    """
    start_time = now = datetime.now()
    min_wait_seconds = timedelta(seconds=timeout)
    while now - start_time < min_wait_seconds:
        if _is_ready():
            break
        now = datetime.now()
        sleep(check_interval)
    else:
        if _is_ready():
            return
        raise TimeoutError("Timed out waiting for Jenkins to become ready.")


@dataclasses.dataclass(frozen=True)
class Credentials:
    """Information needed to log into Jenkins.

    Attrs:
        username: The Jenkins account username used to log into Jenkins.
        password: The Jenkins account password used to log into Jenkins.
    """

    username: str
    password: str


def get_admin_credentials(connectable_container: ops.Container) -> Credentials:
    """Retrieve admin credentials.

    Args:
        connectable_container: Connectable container to interact with filesystem.

    Returns:
        The Jenkins admin account credentials.
    """
    user = "admin"
    password_file_contents = str(
        connectable_container.pull(PASSWORD_FILE_PATH, encoding="utf-8").read()
    )
    return Credentials(username=user, password=password_file_contents.strip())


class Environment(typing.TypedDict):
    """Dictionary mapping of Jenkins environment variables.

    Attrs:
        JENKINS_HOME: The Jenkins home directory.
    """

    JENKINS_HOME: str


def calculate_env() -> Environment:
    """Return a dictionary for Jenkins Pebble layer.

    Returns:
        The dictionary mapping of environment variables for the Jenkins service.
    """
    return Environment(JENKINS_HOME=str(HOME_PATH))


def get_version() -> str:
    """Get the Jenkins server version.

    Returns:
        The Jenkins server version.
    """
    return requests.get(WEB_URL, timeout=10).headers["X-Jenkins"]


def _unlock_wizard(connectable_container: ops.Container) -> None:
    """Write to executed version and updated version file to bypass Jenkins setup wizard.

    Args:
        connectable_container: The connectable Jenkins workload container.
    """
    version = get_version()
    connectable_container.push(
        LAST_EXEC_VERSION_PATH,
        version,
        encoding="utf-8",
        make_dirs=True,
        user=USER,
        group=GROUP,
    )
    connectable_container.push(
        WIZARD_VERSION_PATH,
        version,
        encoding="utf-8",
        make_dirs=True,
        user=USER,
        group=GROUP,
    )


def _install_config(connectable_container: ops.Container) -> None:
    """Install jenkins-config.xml.

    Args:
        connectable_container: The connectable Jenkins workload container.
    """
    with open("templates/jenkins-config.xml", encoding="utf-8") as jenkins_config_file:
        connectable_container.push(CONFIG_FILE_PATH, jenkins_config_file, user=USER, group=GROUP)


def _install_plugins(connectable_container: ops.Container) -> None:
    """Install Jenkins plugins.

    Download Jenkins plugins. A restart is required for the changes to take effect.

    Args:
        connectable_container: The connectable Jenkins workload container.

    Raises:
        JenkinsPluginError: if an error occurred installing the plugin.
    """
    plugins = " ".join(set(REQUIRED_PLUGINS))
    proc: ops.pebble.ExecProcess = connectable_container.exec(
        [
            "java",
            "-jar",
            "jenkins-plugin-manager-2.12.11.jar",
            "-w",
            "jenkins.war",
            "-d",
            str(PLUGINS_PATH),
            "-p",
            plugins,
        ],
        working_dir=str(WAR_PATH),
        timeout=600,
        user=USER,
        group=GROUP,
    )
    try:
        proc.wait_output()
    except (ops.pebble.ChangeError, ops.pebble.ExecError) as exc:
        logger.error("Failed to install plugins, %s", exc)
        raise JenkinsPluginError("Failed to install plugins.") from exc


def bootstrap(
    connectable_container: ops.Container,
) -> None:
    """Initialize and install Jenkins.

    Args:
        connectable_container: The connectable Jenkins workload container.

    Raises:
        JenkinsBootstrapError: if there was an error installing given plugins or required plugins.
    """
    _unlock_wizard(connectable_container)
    _install_config(connectable_container)
    try:
        _install_plugins(connectable_container)
    except JenkinsPluginError as exc:
        raise JenkinsBootstrapError("Failed to bootstrap Jenkins.") from exc


def _get_client(client_credentials: Credentials) -> jenkinsapi.jenkins.Jenkins:
    """Get the Jenkins client.

    Args:
        client_credentials: The credentials of a Jenkins user with access to the Jenkins API.

    Returns:
        The Jenkins client.
    """
    return jenkinsapi.jenkins.Jenkins(
        baseurl=WEB_URL,
        username=client_credentials.username,
        password=client_credentials.password,
        timeout=60,
    )


def get_node_secret(
    node_name: str,
    credentials: Credentials,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> str:
    """Get node secret from jenkins.

    Args:
        node_name: The registered node to fetch the secret from.
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.

    Returns:
        The Jenkins agent node secret.

    Raises:
        JenkinsError: if an error occurred running groovy script getting the node secret.
    """
    client = client if client is not None else _get_client(credentials)
    try:
        return client.run_groovy_script(
            f'println(jenkins.model.Jenkins.getInstance().getComputer("{node_name}").getJnlpMac())'
        ).strip()
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        raise JenkinsError("Failed to run groovy script getting node secret.") from exc


def add_agent_node(
    agent_meta: AgentMeta,
    credentials: Credentials,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> None:
    """Add a Jenkins agent node.

    Args:
        agent_meta: The Jenkins agent metadata to create the node from.
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsError: if an error occurred running groovy script creating the node.
    """
    client = client if client is not None else _get_client(credentials)
    try:
        client.create_node(
            name=agent_meta.slavehost,
            num_executors=int(agent_meta.executors),
            node_description=agent_meta.slavehost,
            labels=agent_meta.labels,
        )
    except jenkinsapi.custom_exceptions.AlreadyExists:
        pass
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        raise JenkinsError("Failed to add agent node.") from exc
