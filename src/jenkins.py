# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

# pylint: disable=too-many-lines

import dataclasses
import functools
import itertools
import json
import logging
import re
import secrets
import textwrap
import typing
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import jenkinsapi.custom_exceptions
import jenkinsapi.jenkins
import ops
import requests
from jenkinsapi.node import Node
from pydantic import HttpUrl

import state
from state import JENKINS_HOME_PATH

logger = logging.getLogger(__name__)

WEB_PORT = 8080
LOGIN_PATH = "/login?from=%2F"
EXECUTABLES_PATH = Path("/srv/jenkins/")
# Path to initial Jenkins password file
PASSWORD_FILE_PATH = JENKINS_HOME_PATH / "secrets/initialAdminPassword"
# Path to Jenkins admin API token
API_TOKEN_PATH = JENKINS_HOME_PATH / "secrets/apiToken"
JUJU_API_TOKEN = "juju_api_token"  # nosec
# Path to last executed Jenkins version file, required to override wizard installation
LAST_EXEC_VERSION_PATH = JENKINS_HOME_PATH / Path("jenkins.install.InstallUtil.lastExecVersion")
# Path to Jenkins version file, required to override wizard installation
WIZARD_VERSION_PATH = JENKINS_HOME_PATH / Path("jenkins.install.UpgradeWizard.state")
# The Jenkins bootstrapping config path
CONFIG_FILE_PATH = JENKINS_HOME_PATH / "config.xml"
# The Jenkins plugins installation directory
PLUGINS_PATH = JENKINS_HOME_PATH / "plugins"
# The Jenkins logging configuration path
LOGGING_CONFIG_PATH = JENKINS_HOME_PATH / "logging.properties"
# The Jenkins logging path as defined in templates/logging.properties file
LOGGING_PATH = JENKINS_HOME_PATH / "jenkins.log"
# The plugins that are required for Jenkins to work
REQUIRED_PLUGINS = [
    "instance-identity",  # required to connect agent nodes to server
    "prometheus",  # required for COS integration
    "monitoring",  # required for session invalidation
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
# Java system property to load logging configuration from file
SYSTEM_PROPERTY_LOGGING = f"java.util.logging.config.file={LOGGING_CONFIG_PATH}"
AUTH_PROXY_JENKINS_CONFIG = "templates/jenkins-auth-proxy-config.xml"
DEFAULT_JENKINS_CONFIG = "templates/jenkins-config.xml"
JENKINS_LOGGING_CONFIG = "templates/logging.properties"


class JenkinsError(Exception):
    """Base exception for Jenkins errors."""


class JenkinsPluginError(JenkinsError):
    """An error occurred installing Jenkins plugin."""


class JenkinsBootstrapError(JenkinsError):
    """An error occurred during the bootstrapping process."""


class ValidationError(Exception):
    """An unexpected data is encountered."""


class Environment(typing.TypedDict):
    """Dictionary mapping of Jenkins environment variables.

    Attributes:
        JENKINS_HOME: The Jenkins home directory.
        JENKINS_PREFIX: The prefix in which Jenkins will be accessible.
    """

    JENKINS_HOME: str
    JENKINS_PREFIX: str


@dataclasses.dataclass(frozen=True)
class Credentials:
    """Information needed to log into Jenkins.

    Attributes:
        username: The Jenkins account username used to log into Jenkins.
        password_or_token: The Jenkins API token or account password used to log into Jenkins.
    """

    username: str
    password_or_token: str


def get_admin_credentials(container: ops.Container) -> Credentials:
    """Retrieve admin credentials.

    Args:
        container: The Jenkins workload container to interact with filesystem.

    Returns:
        The Jenkins admin account credentials.
    """
    user = "admin"
    password_file_contents = str(container.pull(PASSWORD_FILE_PATH, encoding="utf-8").read())
    return Credentials(username=user, password_or_token=password_file_contents.strip())


def _get_api_credentials(container: ops.Container) -> Credentials:
    """Retrieve admin API credentials.

    Args:
        container: The Jenkins workload container.

    Returns:
        Credentials: The Jenkins API Credentials.

    Raises:
        JenkinsBootstrapError: if no API credential has been setup yet.
    """
    try:
        token = str(container.pull(API_TOKEN_PATH, encoding="utf-8").read())
        return Credentials(username="admin", password_or_token=token.strip())
    except ops.pebble.PathError as exc:
        logger.debug("Admin API token not yet setup.")
        raise JenkinsBootstrapError("Admin API credentials not yet setup.") from exc


class Jenkins:
    """Wrapper for Jenkins functionality.

    Attrs:
        environment: the Jenkins environment configuration.
        web_url: the Jenkins web URL.
        login_url: the Jenkins login URL.
        version: the Jenkins version.
    """

    environment: Environment

    def __init__(self, environment: Environment):
        """Construct a Jenkins class.

        Args:
            environment: the Jenkins environment.
        """
        self.environment = environment

    @property
    def web_url(self) -> str:
        """Get the Jenkins web URL.

        Returns: the web URL.
        """
        env_dict = typing.cast(typing.Dict[str, str], self.environment)
        return f"http://localhost:{WEB_PORT}{env_dict['JENKINS_PREFIX']}"

    @property
    def login_url(self) -> str:
        """Get the Jenkins login URL.

        Returns: the login URL.
        """
        return f"{self.web_url}{LOGIN_PATH}"

    @property
    def version(self) -> str:
        """Get the Jenkins server version.

        Raises:
            JenkinsError: if Jenkins is unreachable.

        Returns:
            The Jenkins server version.
        """
        try:
            return requests.get(self.web_url, timeout=10).headers["X-Jenkins"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            logger.error("Failed to get Jenkins version, %s", exc)
            raise JenkinsError("Failed to get Jenkins version.") from exc

    def _is_ready(self) -> bool:
        """Check if Jenkins webserver is ready.

        Returns:
            True if Jenkins server is online. False otherwise.
        """
        try:
            return requests.get(self.login_url, timeout=10).ok
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return False

    def wait_ready(self, timeout: int = 300, check_interval: int = 10) -> None:
        """Wait until Jenkins service is up.

        Args:
            timeout: Time in seconds to wait for jenkins to become ready in 10 second intervals.
            check_interval: Time in seconds to wait between ready checks.

        Raises:
            TimeoutError: if Jenkins status check did not pass within the timeout duration.
        """
        try:
            _wait_for(self._is_ready, timeout=timeout, check_interval=check_interval)
        except TimeoutError as exc:
            raise TimeoutError("Timed out waiting for Jenkins to become ready.") from exc

    def _unlock_wizard(self, container: ops.Container) -> None:
        """Write to executed version and updated version file to bypass Jenkins setup wizard.

        Args:
            container: The Jenkins workload container.

        Raises:
            JenkinsBootstrapError: if the wizard can not be unlocked.
        """
        try:
            version = self.version
            container.push(
                LAST_EXEC_VERSION_PATH,
                version,
                encoding="utf-8",
                make_dirs=True,
                user=USER,
                group=GROUP,
            )
            container.push(
                WIZARD_VERSION_PATH,
                version,
                encoding="utf-8",
                make_dirs=True,
                user=USER,
                group=GROUP,
            )
        except (ops.pebble.PathError, JenkinsError) as exc:
            raise JenkinsBootstrapError("Failed to unlock wizard.") from exc

    def _get_client(self, client_credentials: Credentials) -> jenkinsapi.jenkins.Jenkins:
        """Get the Jenkins client.

        Args:
            client_credentials: The credentials of a Jenkins user with access to the Jenkins API.

        Returns:
            The Jenkins client.
        """
        return jenkinsapi.jenkins.Jenkins(
            baseurl=self.web_url,
            username=client_credentials.username,
            password=client_credentials.password_or_token,
            timeout=60,
        )

    def _setup_user_token(self, container: ops.Container) -> None:
        """Configure admin user API token.

        Args:
            container: The Jenkins workload container.

        Raises:
            JenkinsBootstrapError: if the token can not be setup.
        """
        try:
            client = self._get_client(get_admin_credentials(container))
            token: str = client.generate_new_api_token(JUJU_API_TOKEN)
            container.push(API_TOKEN_PATH, token, user=USER, group=GROUP)
        except ops.pebble.PathError as exc:
            raise JenkinsBootstrapError("Failed to setup user token.") from exc

    def _configure_proxy(
        self, container: ops.Container, proxy_config: state.ProxyConfig | None = None
    ) -> None:
        """Configure Jenkins proxy settings if proxy configuration values are provided.

        Args:
            container: The Jenkins workload container
            proxy_config: The proxy settings to apply.

        Raises:
            JenkinsBootstrapError: if an error occurred running proxy configuration script.
        """
        if not proxy_config:
            return

        client = self._get_client(_get_api_credentials(container))
        parsed_args = ", ".join(_get_groovy_proxy_args(proxy_config))
        script = f"proxy = new ProxyConfiguration({parsed_args})\nproxy.save()"
        try:
            client.run_groovy_script(script)
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to configure proxy, %s", exc)
            raise JenkinsBootstrapError("Proxy configuration failed.") from exc

    def bootstrap(
        self,
        container: ops.Container,
        jenkins_config_file: str,
        proxy_config: state.ProxyConfig | None = None,
    ) -> None:
        """Initialize and install Jenkins.

        Args:
            container: The Jenkins workload container.
            jenkins_config_file: the path to the Jenkins configuration file to install.
            proxy_config: The Jenkins proxy configuration settings.

        Raises:
            JenkinsBootstrapError: if there was an error installing the plugins plugins.
        """
        try:
            self._unlock_wizard(container)
            _install_configs(container, jenkins_config_file)
            self._setup_user_token(container)
            self._configure_proxy(container, proxy_config)
            _install_plugins(container, proxy_config)
        except JenkinsBootstrapError as exc:
            raise JenkinsBootstrapError("Failed to bootstrap Jenkins.") from exc

    def get_node_secret(self, node_name: str, container: ops.Container) -> str:
        """Get node secret from jenkins.

        Args:
            node_name: The registered node to fetch the secret from.
            container: The Jenkins workload container.

        Returns:
            The Jenkins agent node secret.

        Raises:
            JenkinsError: if an error occurred running groovy script getting the node secret.
        """
        client = self._get_client(_get_api_credentials(container))
        try:
            script = (
                f"println(jenkins.model.Jenkins.getInstance()"
                f'.getComputer("{node_name}").getJnlpMac())'
            )
            return client.run_groovy_script(script).strip()
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to run get_node_secret groovy script, %s", exc)
            raise JenkinsError("Failed to run groovy script getting node secret.") from exc

    def _get_node_config(
        self,
        agent_meta: state.AgentMeta,
        container: ops.Container,
    ) -> dict[str, typing.Any]:
        """Get agent node configuration dictionary values.

        Args:
            agent_meta: The Jenkins agent metadata to create the node from.
            container: The Jenkins workload container.

        Returns:
            A dictionary mapping of agent configuration values.
        """
        client = self._get_client(_get_api_credentials(container))
        node = Node(
            jenkins_obj=client,
            baseurl=self.web_url,
            nodename=agent_meta.name,
            node_dict={
                "num_executors": int(agent_meta.executors),
                "node_description": agent_meta.name,
                "remote_fs": "/var/lib/jenkins/",
                "labels": agent_meta.labels,
                "exclusive": False,
            },
        )
        attribs = node.get_node_attributes()
        meta = json.loads(attribs["json"])

        meta["launcher"]["webSocket"] = True
        attribs["json"] = json.dumps(meta)
        return attribs

    def add_agent_node(self, agent_meta: state.AgentMeta, container: ops.Container) -> None:
        """Add a Jenkins agent node.

        Args:
            agent_meta: The Jenkins agent metadata to create the node from.
            container: The Jenkins workload container.

        Raises:
            JenkinsError: if an error occurred running groovy script creating the node.
        """
        client = self._get_client(_get_api_credentials(container))
        try:
            config = self._get_node_config(agent_meta=agent_meta, container=container)
            client.create_node_with_config(name=agent_meta.name, config=config)
        except jenkinsapi.custom_exceptions.AlreadyExists:
            pass
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to add agent node, %s", exc)
            raise JenkinsError("Failed to add agent node.") from exc

    def remove_agent_node(self, agent_name: str, container: ops.Container) -> None:
        """Remove a Jenkins agent node.

        Args:
            agent_name: The agent node name to remove.
            container: The Jenkins workload container.

        Raises:
            JenkinsError: if an error occurred running groovy script removing the node.
        """
        client = self._get_client(_get_api_credentials(container))
        try:
            client.delete_node(nodename=agent_name)
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to delete agent node, %s", exc)
            raise JenkinsError("Failed to delete agent node.") from exc

    def _is_shutdown(self, client: jenkinsapi.jenkins.Jenkins) -> bool:
        """Return status of Jenkins whether it is shutting down.

        Args:
            client: The API client used to communicate with the Jenkins server.

        Returns:
            True if the Jenkins server is shutdown, False otherwise.
        """
        try:
            res = client.requester.get_url(self.web_url)
        except requests.ConnectionError:
            # If jenkins is unavailable to connect, it is shutting down.
            return True
        return res.status_code == 503

    def _wait_jenkins_job_shutdown(self, client: jenkinsapi.jenkins.Jenkins) -> None:
        """Wait for jenkins to finish the job and shutdown.

        Args:
            client: The API client used to communicate with the Jenkins server.

        Raises:
            TimeoutError: if it timed out waiting for jenkins to be shutdown. It could be caused by
                a long running job.
        """
        try:
            _wait_for(functools.partial(self._is_shutdown, client), timeout=300, check_interval=1)
        except TimeoutError as exc:
            raise TimeoutError("Timed out waiting for Jenkins to be shutdown.") from exc

    def safe_restart(self, container: ops.Container) -> None:
        """Safely restart Jenkins server after all jobs are done executing.

        Args:
            container: The Jenkins workload container to interact with filesystem.

        Raises:
            JenkinsError: if there was an API error calling safe restart.
        """
        client = self._get_client(_get_api_credentials(container))
        try:
            # Workaround for https://github.com/pycontribs/jenkinsapi/issues/844
            client.safe_restart(wait_for_reboot=False)
            self._wait_jenkins_job_shutdown(client)
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
            jenkinsapi.custom_exceptions.JenkinsAPIException,
        ) as exc:
            logger.error("Failed to restart Jenkins, %s", exc)
            raise JenkinsError("Failed to restart Jenkins safely.") from exc

    # This groovy script is tested in integration test.
    def _invalidate_sessions(self, container: ops.Container) -> None:  # pragma: no cover
        """Invalidate active Jenkins user sessions.

        Args:
            container: The workload container.
        """
        client = self._get_client(get_admin_credentials(container))
        client.run_groovy_script(
            """
    import net.bull.javamelody.*;
    def sess = SessionListener.newInstance();
    sess.invalidateAllSessions();"""
        )

    # This groovy script is tested in integration test.
    def _set_new_password(
        self, container: ops.Container, new_password: str
    ) -> None:  # pragma: no cover
        """Set new password for admin user.

        Args:
            container: The workload container
            new_password: New password to set for admin user.
        """
        client = self._get_client(get_admin_credentials(container))
        client.run_groovy_script(
            'User.getById("admin",false).addProperty(hudson.security.'
            "HudsonPrivateSecurityRealm.Details"
            f'.fromPlainPassword("{new_password}"));'
        )

    def rotate_credentials(self, container: ops.Container) -> str:
        """Invalidate all Jenkins sessions and create new password for admin account.

        Args:
            container: The workload container.

        Raises:
            JenkinsError: if any error happened running the groovy script to invalidate sessions.

        Returns:
            The new generated password.
        """
        new_password = secrets.token_hex(16)
        try:
            self._invalidate_sessions(container)
            self._set_new_password(container, new_password)
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to invalidate sessions, %s", exc)
            raise JenkinsError("Failed to invalidate sessions") from exc
        container.push(
            PASSWORD_FILE_PATH,
            new_password,
            encoding="utf-8",
            user=USER,
            group=GROUP,
        )
        return new_password

    def remove_unlisted_plugins(
        self, plugins: typing.Iterable[str] | None, container: ops.Container
    ) -> None:
        """Remove plugins that are not in the list of desired plugins.

        Args:
            plugins: The list of plugins that can be installed.
            container: The workload container.

        Raises:
            JenkinsPluginError: if there was an error removing unlisted plugin or there are plugins
                currently being installed.
            JenkinsError: if there was an error restarting Jenkins after removing the plugin.
            TimeoutError: if it took too long to restart Jenkins after removing the plugin.
        """
        if not plugins:
            return

        try:
            _wait_plugins_install(container=container)
        except TimeoutError as exc:
            raise JenkinsPluginError("Plugins currently being installed.") from exc

        client = self._get_client(_get_api_credentials(container))
        res = client.run_groovy_script(
            """
    def plugins = jenkins.model.Jenkins.instance.getPluginManager().getPlugins()
    plugins.each {
        println "${it.getShortName()} (${it.getVersion()}) => ${it.getDependencies()}"
    }
    """
        )
        dependency_lookup = _build_dependencies_lookup(res.splitlines())
        allowed_plugins = _get_allowed_plugins(
            itertools.chain(plugins, REQUIRED_PLUGINS), dependency_lookup
        )
        plugins_to_remove = set(dependency_lookup.keys()) - set(allowed_plugins)
        if not plugins_to_remove:
            return

        try:
            client.delete_plugins(plugin_list=plugins_to_remove, restart=False)
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to remove the following plugins: %s, %s", plugins_to_remove, exc)
            raise JenkinsPluginError("Failed to remove plugins.") from exc

        logger.debug("Removed %s", plugins_to_remove)
        top_level_plugins = _filter_dependent_plugins(plugins_to_remove, dependency_lookup)
        try:
            self.safe_restart(container)
            self.wait_ready()
        except (JenkinsError, TimeoutError) as exc:
            logger.error("Failed to restart Jenkins after removing plugins, %s", exc)
            raise

        _set_jenkins_system_message(
            message="The following plugins have been removed by the system administrator: "
            f"{', '.join(top_level_plugins)}\n"
            f"To allow the plugins, please include them in the plugins configuration of the charm.",
            client=client,
        )


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


class StorageMountError(JenkinsBootstrapError):
    """Represents an error probing for Jenkins storage mount.

    Attributes:
        msg: Explanation of the error.
    """

    def __init__(self, msg: str):
        """Initialize a new instance of the StorageMountError exception.

        Args:
            msg: Explanation of the error.
        """
        self.msg = msg


def is_storage_ready(container: typing.Optional[ops.Container]) -> bool:
    """Return whether the Jenkins home directory is mounted and owned by jenkins.

    Args:
        container: The Jenkins workload container.

    Raises:
        StorageMountError: if there was an error getting storage information.

    Returns:
        True if home directory is mounted and owned by jenkins, False otherwise.
    """
    if not container or not container.can_connect():
        return False
    mount_info: str = container.pull("/proc/mounts").read()
    if str(JENKINS_HOME_PATH) not in mount_info:
        return False
    proc: ops.pebble.ExecProcess = container.exec(["stat", "-c", "%U", str(JENKINS_HOME_PATH)])
    try:
        stdout, _ = proc.wait_output()
    except (ops.pebble.ChangeError, ops.pebble.ExecError) as exc:
        raise StorageMountError("Error fetching storage ownership info.") from exc
    return "jenkins" in stdout


def _install_config(container: ops.Container, filename: str, destination_path: Path) -> None:
    """Install jenkins-config.xml.

    Args:
        container: The Jenkins workload container.
        filename: the source file to copy contents from.
        destination_path: the target path.

    Raises:
        JenkinsBootstrapError: if the config can not be installed.

    """
    try:
        jenkins_config_file = Path(filename).read_text(encoding="utf-8")
        container.push(destination_path, jenkins_config_file, user=USER, group=GROUP)
    except ops.pebble.PathError as exc:
        raise JenkinsBootstrapError("Failed to install configuration.") from exc


def _install_configs(container: ops.Container, jenkins_config_file: str) -> None:
    """Install jenkins-config.xml and logging files.

    Args:
        container: The Jenkins workload container.
        jenkins_config_file: the path to the Jenkins configuration file to install.
    """
    _install_config(container, jenkins_config_file, CONFIG_FILE_PATH)
    _install_config(container, JENKINS_LOGGING_CONFIG, LOGGING_CONFIG_PATH)


def install_default_config(container: ops.Container) -> None:
    """Install default jenkins-config.xml.

    Args:
        container: The Jenkins workload container.
    """
    _install_config(container, DEFAULT_JENKINS_CONFIG, CONFIG_FILE_PATH)


def install_auth_proxy_config(container: ops.Container) -> None:
    """Install jenkins-config.xml for auth_proxy.

    Args:
        container: The Jenkins workload container.
    """
    _install_config(container, AUTH_PROXY_JENKINS_CONFIG, CONFIG_FILE_PATH)


def _get_groovy_proxy_args(proxy_config: state.ProxyConfig) -> typing.Iterable[str]:
    """Get proxy arguments for proxy configuration Groovy script.

    Args:
        proxy_config: The proxy settings to apply.

    Yields:
        Groovy script proxy arguments.
    """
    if proxy_config.https_proxy:
        yield f"'{proxy_config.https_proxy.host}'"
        yield f"{proxy_config.https_proxy.port}"
        yield f"'{proxy_config.https_proxy.user or ''}'"
        yield f"'{proxy_config.https_proxy.password or ''}'"
    else:
        # http proxy and https proxy value cannot both be None since proxy_config would be parsed
        # as None.
        proxy_config.http_proxy = typing.cast(HttpUrl, proxy_config.http_proxy)
        yield f"'{proxy_config.http_proxy.host}'"
        yield f"{proxy_config.http_proxy.port}"
        yield f"'{proxy_config.http_proxy.user or ''}'"
        yield f"'{proxy_config.http_proxy.password or ''}'"
    if proxy_config.no_proxy:
        yield f"'{proxy_config.no_proxy}'"


def _get_java_proxy_args(proxy_config: state.ProxyConfig) -> typing.Iterable[str]:
    """Get JVM system property arguments for proxy.

    Args:
        proxy_config: The proxy settings to apply.

    Yields:
        JVM System property proxy arguments.
    """
    if proxy_config.http_proxy:
        yield f"-Dhttp.proxyHost={proxy_config.http_proxy.host}"
        yield f"-Dhttp.proxyPort={proxy_config.http_proxy.port}"
        if proxy_config.http_proxy.user and proxy_config.http_proxy.password:
            yield f"-Dhttp.proxyUser={proxy_config.http_proxy.user}"
            yield f"-Dhttp.proxyPassword={proxy_config.http_proxy.password}"
    if proxy_config.https_proxy:
        yield f"-Dhttps.proxyHost={proxy_config.https_proxy.host}"
        yield f"-Dhttps.proxyPort={proxy_config.https_proxy.port}"
        if proxy_config.https_proxy.user and proxy_config.https_proxy.password:
            yield f"-Dhttps.proxyUser={proxy_config.https_proxy.user}"
            yield f"-Dhttps.proxyPassword={proxy_config.https_proxy.password}"
    if proxy_config.no_proxy:
        formatted_no_proxy_hosts = "|".join(proxy_config.no_proxy.split(","))
        yield f'-Dhttp.nonProxyHosts="{formatted_no_proxy_hosts}"'


def _install_plugins(
    container: ops.Container, proxy_config: state.ProxyConfig | None = None
) -> None:
    """Install Jenkins plugins.

    Download Jenkins plugins. A restart is required for the changes to take effect.

    Args:
        container: The Jenkins workload container.
        proxy_config: The proxy settings to apply.

    Raises:
        JenkinsBootstrapError: if an error occurred installing the plugin.
    """
    proxy_args = [] if not proxy_config else _get_java_proxy_args(proxy_config)
    command = [
        "java",
        *proxy_args,
        "-jar",
        "jenkins-plugin-manager-2.12.13.jar",
        "-w",
        "jenkins.war",
        "-d",
        str(PLUGINS_PATH),
        "-p",
        " ".join(set(REQUIRED_PLUGINS)),
        "--latest",
    ]
    proc: ops.pebble.ExecProcess = container.exec(
        command,
        working_dir=str(EXECUTABLES_PATH),
        timeout=600,
        user=USER,
        group=GROUP,
    )
    try:
        proc.wait_output()
    except (ops.pebble.ChangeError, ops.pebble.ExecError) as exc:
        logger.error("Failed to install plugins, %s", exc)
        raise JenkinsBootstrapError("Failed to install plugins.") from exc


def get_agent_name(unit_name: str) -> str:
    """Infer agent name from unit name.

    Args:
        unit_name: The agent unit name.

    Returns:
        The agent node name registered on Jenkins server.
    """
    return unit_name.replace("/", "-")


PLUGIN_NAME_GROUP = r"^([a-zA-Z0-9-_]+)"
WHITESPACE = r"\s*"
VERSION_GROUP = r"\((.*?)\)"
DEPENDENCIES_GROUP = r"\[(.*?)\]"
PLUGIN_CAPTURE = rf"{PLUGIN_NAME_GROUP}{WHITESPACE}{VERSION_GROUP}"
PLUGIN_LINE_CAPTURE = rf"{PLUGIN_CAPTURE} => {DEPENDENCIES_GROUP}"


def _get_plugin_name(plugin_info: str) -> str:
    """Get plugin name given a plugin info string of format <plugin-shortname> (<plugin-version>).

    Args:
        plugin_info: Text containing plugin name and plugin version.

    Raises:
        ValidationError: if the plugin info string does not conform to expected format.

    Returns:
        The plugin shortname.
    """
    match = re.match(PLUGIN_CAPTURE, plugin_info)
    if not match:
        raise ValidationError(f"No plugin matched in: {plugin_info}")
    return match.group(1)


def _plugin_temporary_files_exist(container: ops.Container) -> bool:
    """Check if plugin temporary file exists in the plugins installation directory.

    Args:
        container: The Jenkins workload container.

    Returns:
        True if temporary plugin download file exists, False otherwise.
    """
    if container.list_files(path=str(PLUGINS_PATH), pattern="*.tmp"):
        logger.warning("Plugins being downloaded, waiting until further actions.")
        return True
    return False


def _wait_plugins_install(container: ops.Container, timeout: int = 60 * 5) -> None:
    """Wait until all plugins are installed.

    This function checks for any .tmp files in the plugins directory which indicates that a user
    might be installing plugins through the UI.

    Args:
        container: The Jenkins workload container.
        timeout: Timeout in seconds to wait for plugins to be installed.
    """
    _wait_for(
        lambda: not _plugin_temporary_files_exist(container),
        timeout=timeout,
        check_interval=5,
    )


def _build_dependencies_lookup(
    plugin_dependency_outputs: typing.Iterable[str],
) -> dict[str, tuple[str, ...]]:
    """Build a lookup table of plugin short name to list of dependency plugin's short names.

    Args:
        plugin_dependency_outputs: The plugin dependency output from Jenkins Groovy script.

    Returns:
        The dependency lookup table.
    """
    dependency_lookup: dict[str, tuple[str, ...]] = {}
    for line in plugin_dependency_outputs:
        match = re.match(PLUGIN_LINE_CAPTURE, line)
        if not match:
            continue
        plugin, dependencies = match.group(1), match.group(3)
        if not dependencies:
            dependency_lookup[plugin] = ()
            continue
        try:
            dependency_lookup[plugin] = tuple(
                _get_plugin_name(dependency) for dependency in dependencies.split(", ")
            )
        except ValidationError as exc:
            logger.error("Invalid plugin dependency, %s", exc)
            continue
    return dependency_lookup


def _get_allowed_plugins(
    allowed_plugins: typing.Iterable[str],
    dependency_lookup: typing.Mapping[str, typing.Iterable[str]],
    seen: set[str] | None = None,
) -> typing.Iterable[str]:
    """Get the plugin short names of allowed plugins and their dependencies.

    Args:
        allowed_plugins: The allowed plugins short names to add to allowed plugins with their
            dependencies.
        dependency_lookup: The plugin dependency lookup table.
        seen: Whether the plugin has been yielded already during recursive traversal.

    Yields:
        The allowed plugin short name.
    """
    if seen is None:
        seen = set()
    for plugin in allowed_plugins:
        if plugin in seen:
            continue
        yield plugin
        seen.add(plugin)
        try:
            dependencies = dependency_lookup[plugin]
        except KeyError:
            logger.warning("Plugin %s not found in dependency lookup.", plugin)
            continue
        yield from _get_allowed_plugins(dependencies, dependency_lookup, seen)


def _filter_dependent_plugins(
    plugins: typing.Iterable[str], dependency_lookup: typing.Mapping[str, typing.Iterable[str]]
) -> set[str]:
    """Filter out dependencies from the iterable consisting of all plugins.

    This method filters out any plugins that is a dependency of another plugin, returning top level
    plugins only.

    Args:
        plugins: Plugins to filter out dependency plugins from.
        dependency_lookup: The dependency lookup table.

    Returns:
        All plugins that are not dependency of another plugin.
    """
    dependent_plugins: set[str] = set()
    for _, dependencies in dependency_lookup.items():
        dependent_plugins = dependent_plugins.union(dependencies)
    return set(plugins) - dependent_plugins


def _set_jenkins_system_message(message: str, client: jenkinsapi.jenkins.Jenkins) -> None:
    """Set a system message on Jenkins.

    Args:
        message: The system message to display.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsError: if the groovy script to set system message failed.
    """
    try:
        # escape newline character to set the message in the script as a single line string.
        message = "\\n".join(message.split("\n"))
        script = textwrap.dedent(
            f"""
            Jenkins j = Jenkins.instance
            j.systemMessage = "{message}"
            """
        )
        client.run_groovy_script(script)
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        logger.error("Failed to set system message, %s", exc)
        raise JenkinsError("Failed to set system message.") from exc
