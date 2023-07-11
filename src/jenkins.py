# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

import dataclasses
import functools
import logging
import typing
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

# The only XML getting parsed is from Jenkins RSS feed which is a trusted source hence the stdlib
# xml parser can be used.
from xml.etree import ElementTree  # nosec

import jenkinsapi.custom_exceptions
import jenkinsapi.jenkins
import ops
import requests

logger = logging.getLogger(__name__)

WEB_PORT = 8080
WEB_URL = f"http://localhost:{WEB_PORT}"
LOGIN_URL = f"{WEB_URL}/login?from=%2F"
HOME_PATH = Path("/var/jenkins")
EXECUTABLES_PATH = Path("/srv/jenkins/")
# Path to initial Jenkins password file
PASSWORD_FILE_PATH = HOME_PATH / "secrets/initialAdminPassword"
# Path to last executed Jenkins version file, required to override wizard installation
LAST_EXEC_VERSION_PATH = HOME_PATH / Path("jenkins.install.InstallUtil.lastExecVersion")
# Path to Jenkins version file, required to override wizard installation
WIZARD_VERSION_PATH = HOME_PATH / Path("jenkins.install.UpgradeWizard.state")
# The Jenkins bootstrapping config path
CONFIG_FILE_PATH = HOME_PATH / "config.xml"
# The Jenkins configuration-as-code plugin default config path
JCASC_CONFIG_FILE_PATH = HOME_PATH / "jenkins.yaml"
# The Jenkins plugins installation directory
PLUGINS_PATH = HOME_PATH / "plugins"

# The plugins that are required for Jenkins to work
REQUIRED_PLUGINS = [
    "instance-identity",  # required to connect agent nodes to server
    "configuration-as-code",  # required to disable automatic jenkins update messages
]

USER = "jenkins"
GROUP = "jenkins"

BUILT_IN_NODE_NAME = "Built-In Node"
# The Jenkins stable version RSS feed URL
RSS_FEED_URL = "https://www.jenkins.io/changelog-stable/rss.xml"
# The Jenkins WAR downloads page
WAR_DOWNLOAD_URL = "https://updates.jenkins.io/download/war"

# Java system property to run Jenkins in headless mode
SYSTEM_PROPERTY_HEADLESS = "java.awt.headless=true"


class JenkinsError(Exception):
    """Base exception for Jenkins errors."""


class JenkinsPluginError(JenkinsError):
    """An error occurred installing Jenkins plugin."""


class JenkinsBootstrapError(JenkinsError):
    """An error occurred during the bootstrapping process."""


class ValidationError(Exception):
    """An unexpected data is encountered."""


class JenkinsNetworkError(JenkinsError):
    """An error occurred communicating with the upstream Jenkins server."""


class JenkinsUpdateError(JenkinsError):
    """An error occurred trying to update Jenkins."""


@dataclasses.dataclass(frozen=True)
class AgentMeta:
    """Metadata for registering Jenkins Agent.

    Attributes:
        executors: Number of executors of the agent in string format.
        labels: Comma separated list of labels to be assigned to the agent.
        name: The host name of the agent.
    """

    executors: str
    labels: str
    name: str

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


def _wait_for(
    func: typing.Callable[[], typing.Any], timeout: int = 300, check_interval: int = 10
) -> None:
    """Wait for function execution to become truthy.

    Args:
        func: A callback function to wait to return a truthy value.
        timeout: Time in seconds to wait for function result to become truthy.
        check_interval: Time in seconds to wait between ready checks.

    Raises:
        TimeoutError: if the callback function did not return a truthy value within timeout.
    """
    start_time = now = datetime.now()
    min_wait_seconds = timedelta(seconds=timeout)
    while now - start_time < min_wait_seconds:
        if func():
            break
        now = datetime.now()
        sleep(check_interval)
    else:
        if func():
            return
        raise TimeoutError()


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
    try:
        _wait_for(_is_ready, timeout=timeout, check_interval=check_interval)
    except TimeoutError as exc:
        raise TimeoutError("Timed out waiting for Jenkins to become ready.") from exc


@dataclasses.dataclass(frozen=True)
class Credentials:
    """Information needed to log into Jenkins.

    Attributes:
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

    Attributes:
        JENKINS_HOME: The Jenkins home directory.
        CASC_JENKINS_CONFIG: The Jenkins configuration-as-code plugin config path.
    """

    JENKINS_HOME: str
    CASC_JENKINS_CONFIG: str


def calculate_env() -> Environment:
    """Return a dictionary for Jenkins Pebble layer.

    Returns:
        The dictionary mapping of environment variables for the Jenkins service.
    """
    return Environment(
        JENKINS_HOME=str(HOME_PATH), CASC_JENKINS_CONFIG=str(JCASC_CONFIG_FILE_PATH)
    )


def get_version() -> str:
    """Get the Jenkins server version.

    Raises:
        JenkinsError: if Jenkins is unreachable.

    Returns:
        The Jenkins server version.
    """
    try:
        return requests.get(WEB_URL, timeout=10).headers["X-Jenkins"]
    except (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
    ) as exc:
        logger.error("Failed to get Jenkins version, %s", exc)
        raise JenkinsError("Failed to get Jenkins version.") from exc


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


def _install_configs(connectable_container: ops.Container) -> None:
    """Install jenkins-config.xml.

    Args:
        connectable_container: The connectable Jenkins workload container.
    """
    with open("templates/jenkins-config.xml", encoding="utf-8") as jenkins_config_file:
        connectable_container.push(CONFIG_FILE_PATH, jenkins_config_file, user=USER, group=GROUP)
    with open("templates/jenkins.yaml", encoding="utf-8") as jenkins_casc_config_file:
        connectable_container.push(
            JCASC_CONFIG_FILE_PATH, jenkins_casc_config_file, user=USER, group=GROUP
        )


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
        working_dir=str(EXECUTABLES_PATH),
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
    _install_configs(connectable_container)
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
        logger.error("Failed to run get_node_secret groovy script, %s", exc)
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
            name=agent_meta.name,
            num_executors=int(agent_meta.executors),
            node_description=agent_meta.name,
            labels=agent_meta.labels,
        )
    except jenkinsapi.custom_exceptions.AlreadyExists:
        pass
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        logger.error("Failed to add agent node, %s", exc)
        raise JenkinsError("Failed to add agent node.") from exc


def remove_agent_node(
    agent_name: str,
    credentials: Credentials,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> None:
    """Remove a Jenkins agent node.

    Args:
        agent_name: The agent node name to remove.
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsError: if an error occurred running groovy script removing the node.
    """
    client = client if client is not None else _get_client(credentials)
    try:
        client.delete_node(nodename=agent_name)
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        logger.error("Failed to delete agent node, %s", exc)
        raise JenkinsError("Failed to delete agent node.") from exc


def _get_major_minor_version(version: str) -> str:
    """Extract the major.minor version from semantic version string.

    Args:
        version: The semantic version.

    Returns:
        The version without patch version, i.e. <major>.<minor>
    """
    return ".".join(version.split(".")[0:2])


def _fetch_versions_from_rss() -> typing.Iterable[str]:
    """Fetch and extract Jenkins versions from the stable RSS feed.

    Returns:
        The jenkins versions from the RSS feed.

    Raises:
        JenkinsNetworkError: if there was an error fetching the RSS feed.
        ValidationError: if an invalid RSS feed was received.
    """
    try:
        res = requests.get(RSS_FEED_URL, timeout=30)
        res.raise_for_status()
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError,
    ) as exc:
        logger.error("Failed to fetch latest RSS feed, %s", exc)
        raise JenkinsNetworkError("Failed to fetch RSS feed.") from exc

    try:
        # jenkins xml is a trusted source, hence it can be parsed using stdlib
        xml_tree = ElementTree.fromstring(res.content)  # nosec
    except ElementTree.ParseError as exc:
        logger.error("Invalid RSS feed, %s", exc)
        raise ValidationError("Invalid RSS feed.") from exc

    items = xml_tree.findall("./channel/item")
    # mypy doesn't understand that None type is not possible.
    titles = (
        item.find("title").text  # type: ignore
        for item in items
        if item.find("title") is not None and item.find("title").text is not None  # type: ignore
    )
    versions = (title.removeprefix("Jenkins ") for title in titles)  # type: ignore
    return versions


def _get_latest_patch_version(current_version: str) -> str:
    """Get the latest lts patch version matching with the current version.

    Args:
        current_version: Current LTS semantic version.

    Returns:
        The latest patched version available.

    Raises:
        JenkinsNetworkError: if there was an error fetching the LTS RSS feed.
        ValidationError: if the RSS feed contains no matching LTS version.
    """
    try:
        versions = _fetch_versions_from_rss()
    except (JenkinsNetworkError, ValidationError) as exc:
        logger.error("Failed to fetch Jenkins versions from rss, %s", exc)
        raise

    maj_min_version = _get_major_minor_version(current_version)
    matching_versions = (version for version in versions if version.startswith(maj_min_version))
    sorted_versions = sorted(
        matching_versions, reverse=True, key=lambda x: tuple(map(int, x.split(".")))
    )

    if len(sorted_versions) == 0:
        raise ValidationError(
            f"No matching version with {current_version} found from stable RSS feed."
        )
    return sorted_versions[0]


def get_updatable_version() -> str | None:
    """Get version to update to if available.

    Raises:
        JenkinsUpdateError: if there was an error trying to determine next Jenkins update version.

    Returns:
        Patched version string if the update is available. None if latest version is applied.
    """
    try:
        current_version = get_version()
    except JenkinsError as exc:
        logger.error("Failed to get Jenkins version while fetching update, %s", exc)
        raise JenkinsUpdateError("Failed to get Jenkins version.") from exc

    try:
        latest_version = _get_latest_patch_version(current_version=current_version)
    except (JenkinsNetworkError, ValidationError) as exc:
        logger.error("Failed to fetch latest patch version info, %s", exc)
        raise JenkinsUpdateError("Failed to fetch latest patch version info.") from exc

    if current_version == latest_version:
        return None
    return latest_version


def download_stable_war(connectable_container: ops.Container, version: str) -> None:
    """Download and replace the war executable.

    Args:
        connectable_container: The Jenkins container with jenkins.war executable.
        version: Desired version of the war to download.

    Raises:
        JenkinsNetworkError: if there was an error fetching the jenkins.war executable.
    """
    try:
        res = requests.get(f"{WAR_DOWNLOAD_URL}/{version}/jenkins.war", timeout=300)
        res.raise_for_status()
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError,
    ) as exc:
        logger.error("Failed to download Jenkins war executable, %s", exc)
        raise JenkinsNetworkError(f"Failed to download Jenkins war version {version}") from exc
    connectable_container.push(
        EXECUTABLES_PATH / "jenkins.war", res.content, encoding="utf-8", user=USER, group=GROUP
    )


def _is_shutdown(client: jenkinsapi.jenkins.Jenkins) -> bool:
    """Return status of Jenkins whether it is shutting down.

    Args:
        client: The API client used to communicate with the Jenkins server.

    Returns:
        True if the Jenkins server is shutdown, False otherwise.
    """
    try:
        res = client.requester.get_url(WEB_URL)
    except requests.ConnectionError:
        # If jenkins is unavailable to connect, it is shutting down.
        return True
    if res.status_code == 503:
        return True
    return False


def _wait_jenkins_job_shutdown(client: jenkinsapi.jenkins.Jenkins) -> None:
    """Wait for jenkins to finish the job and shutdown.

    Args:
        client: The API client used to communicate with the Jenkins server.

    Raises:
        TimeoutError: if it timed out waiting for jenkins to be shutdown. It could be caused by
            a long running job.
    """
    try:
        _wait_for(functools.partial(_is_shutdown, client), timeout=300, check_interval=1)
    except TimeoutError as exc:
        raise TimeoutError("Timed out waiting for Jenkins to be shutdown.") from exc


def safe_restart(
    credentials: Credentials, client: jenkinsapi.jenkins.Jenkins | None = None
) -> None:
    """Safely restart Jenkins server after all jobs are done executing.

    Args:
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsError: if there was an API error calling safe restart.
    """
    client = client if client is not None else _get_client(credentials)
    try:
        # There is a bug with wait_for_reboot in the jenkinsapi
        # https://github.com/pycontribs/jenkinsapi/issues/844
        # will resort to custom workaround until the issue is fixed.
        client.safe_restart(wait_for_reboot=False)
        _wait_jenkins_job_shutdown(client)
    except (
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        jenkinsapi.custom_exceptions.JenkinsAPIException,
    ) as exc:
        logger.error("Failed to restart Jenkins, %s", exc)
        raise JenkinsError("Failed to restart Jenkins safely.") from exc


def get_agent_name(unit_name: str) -> str:
    """Infer agent name from unit name.

    Args:
        unit_name: The agent unit name.

    Returns:
        The agent node name registered on Jenkins server.
    """
    return unit_name.replace("/", "-")
