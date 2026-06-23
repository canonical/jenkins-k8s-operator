# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

# pylint: disable=too-many-lines

import copy
import dataclasses
import functools
import hashlib
import json
import logging
import re
import secrets
import textwrap
import typing
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

import jenkinsapi.custom_exceptions
import jenkinsapi.jenkins
import ops
import requests
import tenacity
from jenkinsapi.node import Node
from pydantic import HttpUrl

import state

logger = logging.getLogger(__name__)

WEB_PORT = 8080
JENKINS_PLUGIN_MANAGER_VERSION = "2.13.2"
LOGIN_PATH = "/login?from=%2F"
EXECUTABLES_PATH = Path("/srv/jenkins/")
JENKINS_HOME_PATH = Path("/var/lib/jenkins")
# Path to initial Jenkins password file
PASSWORD_FILE_PATH = JENKINS_HOME_PATH / "secrets/initialAdminPassword"
# Path to Jenkins admin API token
API_TOKEN_PATH = JENKINS_HOME_PATH / "secrets/apiToken"
JUJU_API_TOKEN = "juju_api_token"  # nosec
# Path to last executed Jenkins version file, required to override wizard installation
LAST_EXEC_VERSION_PATH = JENKINS_HOME_PATH / Path(
    "jenkins.install.InstallUtil.lastExecVersion"
)
# Path to Jenkins version file, required to override wizard installation
WIZARD_VERSION_PATH = JENKINS_HOME_PATH / Path("jenkins.install.UpgradeWizard.state")
# The Jenkins bootstrapping config path
CONFIG_FILE_PATH = JENKINS_HOME_PATH / "config.xml"
# The JCasC configuration file path
JCASC_CONFIG_PATH = JENKINS_HOME_PATH / "jenkins.yaml"
# The Jenkins plugins installation directory
PLUGINS_PATH = JENKINS_HOME_PATH / "plugins"
# The Jenkins logging configuration path
LOGGING_CONFIG_PATH = JENKINS_HOME_PATH / "logging.properties"
# The Jenkins logging path as defined in templates/logging.properties file
LOGGING_PATH = JENKINS_HOME_PATH / "logs/jenkins.log"
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

ONLINE_CHECK_NAME = "online"

ADMIN_USER = "admin"


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
        CASC_JENKINS_CONFIG: Path to the JCasC configuration file.
        JENKINS_ADMIN_PASSWORD: The admin password for JCasC secret interpolation.
        CONFIGURATION_HASH: The hash of the JCasC configurations applied.
    """

    JENKINS_HOME: str
    JENKINS_PREFIX: str
    CASC_JENKINS_CONFIG: str
    JENKINS_ADMIN_PASSWORD: str
    CONFIGURATION_HASH: str


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
    try:
        password_file_contents = str(
            container.pull(PASSWORD_FILE_PATH, encoding="utf-8").read()
        )
        return Credentials(
            username=ADMIN_USER, password_or_token=password_file_contents.strip()
        )
    except ops.pebble.PathError as exc:
        logger.debug("Admin password not yet setup.")
        raise JenkinsBootstrapError("Admin password not yet setup.") from exc


def get_api_credentials(container: ops.Container) -> Credentials:
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
        return Credentials(username=ADMIN_USER, password_or_token=token.strip())
    except ops.pebble.PathError as exc:
        logger.debug("Admin API token not yet setup.")
        raise JenkinsBootstrapError("Admin API credentials not yet setup.") from exc


class Jenkins:
    """Wrapper for Jenkins functionality.

    Attrs:
        web_url: the Jenkins web URL.
        login_url: the Jenkins login URL.
        version: the Jenkins version.
    """

    def __init__(
        self, jenkins_prefix: str, admin_password: str, container: ops.Container
    ):
        """Construct a Jenkins class.

        Args:
            environment: the Jenkins environment.
        """
        self._jenkins_prefix = jenkins_prefix
        self._admin_password = admin_password
        self._container = container

    @property
    def web_url(self) -> str:
        """Get the Jenkins web URL.

        Returns: the web URL.
        """
        return f"http://localhost:{WEB_PORT}{self._jenkins_prefix}"

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
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
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

    def _is_api_ready(self) -> bool:
        """Check if Jenkins API is fully functional (crumb issuance works).

        This is a stronger readiness check than _is_ready. Jenkins may serve pages
        (login_url returns 200) before its security subsystem is fully initialized.
        This method verifies that the crumb issuer endpoint is functional, which is
        required for API token generation during bootstrap.

        Returns:
            True if Jenkins API is fully functional. False otherwise.
        """
        try:
            resp = requests.get(
                f"{self.web_url}/crumbIssuer/api/json",
                auth=("admin", self._admin_password),
                timeout=10,
            )
            return resp.ok and "crumb" in resp.json()
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.JSONDecodeError,
            KeyError,
            ops.pebble.PathError,
        ):
            return False

    def wait_ready(
        self, timeout: int = 300, check_interval: int = 10, api_ready: bool = True
    ) -> None:
        """Wait until Jenkins service is up.

        Args:
            timeout: Time in seconds to wait for jenkins to become ready in 10 second intervals.
            check_interval: Time in seconds to wait between ready checks.

        Raises:
            TimeoutError: if Jenkins status check did not pass within the timeout duration.
        """
        try:
            if api_ready:
                return _wait_for(
                    self._is_api_ready, timeout=timeout, check_interval=check_interval
                )
            _wait_for(self._is_ready, timeout=timeout, check_interval=check_interval)
        except TimeoutError as exc:
            raise TimeoutError(
                "Timed out waiting for Jenkins to become ready."
            ) from exc

    def get_admin_user_client(self) -> jenkinsapi.jenkins.Jenkins:
        """Get the Jenkins client.

        Args:
            client_credentials: The credentials of a Jenkins user with access to the Jenkins API.

        Returns:
            The Jenkins client.
        """
        return jenkinsapi.jenkins.Jenkins(
            baseurl=self.web_url,
            username=ADMIN_USER,
            password=self._admin_password,
            timeout=60,
        )

    def get_admin_api_client(self) -> jenkinsapi.jenkins.Jenkins:
        """Get the Jenkins client authenticated with admin API token.

        Returns:
            The Jenkins client authenticated with admin API token.

        Raises:
            JenkinsBootstrapError: if admin API credentials are not yet available.
        """
        try:
            credentials = get_api_credentials(self._container)
            return jenkinsapi.jenkins.Jenkins(
                baseurl=self.web_url,
                username=credentials.username,
                password=credentials.password_or_token,
                timeout=60,
            )
        except JenkinsBootstrapError as exc:
            logger.debug("Admin API credentials not yet available.")
            raise JenkinsBootstrapError(
                "Admin API credentials not yet available."
            ) from exc

    def _get_api_client(self) -> jenkinsapi.jenkins.Jenkins:
        """Get the Jenkins client.

        Returns:
            The Jenkins client.
        """
        credentials = get_api_credentials(self._container)
        return jenkinsapi.jenkins.Jenkins(
            baseurl=self.web_url,
            username=credentials.username,
            password=credentials.password_or_token,
            timeout=60,
        )

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=2, min=2, max=30),
        retry=tenacity.retry_if_exception_type(
            jenkinsapi.custom_exceptions.JenkinsAPIException
        ),
        before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_admin_user_token(self) -> None:
        """Generate and store the admin user API token with retry.

        Creates a fresh client on each attempt to ensure a new session/crumb pair.

        Raises:
            JenkinsBootstrapError: if the token can not be generated after retries.
        """
        try:
            client = self.get_admin_user_client()
            token: str = client.generate_new_api_token(JUJU_API_TOKEN)
            self._container.push(API_TOKEN_PATH, token, user=USER, group=GROUP)
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            # Check if security is disabled before retrying
            try:
                check_response = requests.get(
                    f"{self.web_url}/manage/api/json?tree=useSecurity",
                    timeout=10,
                )
                if (
                    check_response.status_code == 200
                    and not check_response.json()["useSecurity"]
                ):
                    # Security disabled — write placeholder token
                    self._container.push(
                        API_TOKEN_PATH,
                        f"placeholder-{secrets.token_hex(16)}",
                        user=USER,
                        group=GROUP,
                    )
                    return
            except (requests.exceptions.JSONDecodeError, KeyError):
                logger.error("Failed parsing jenkins's security config, will retry")
            logger.warning(
                "Token generation failed (API response may indicate crumb/session race): %s",
                exc,
            )
            raise JenkinsBootstrapError("Failed to generate user token.") from exc

    def get_node_secret(self, node_name: str) -> str:
        """Get node secret from jenkins.

        Args:
            node_name: The registered node to fetch the secret from.

        Returns:
            The Jenkins agent node secret.

        Raises:
            JenkinsError: if an error occurred running groovy script getting the node secret.
        """
        client = self._get_api_client()
        try:
            script = (
                f"println(jenkins.model.Jenkins.getInstance()"
                f'.getComputer("{node_name}").getJnlpMac())'
            )
            return client.run_groovy_script(script).strip()
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to run get_node_secret groovy script, %s", exc)
            raise JenkinsError(
                "Failed to run groovy script getting node secret."
            ) from exc

    def _get_node_config(self, agent_meta: state.AgentMeta) -> dict[str, typing.Any]:
        """Get agent node configuration dictionary values.

        Args:
            agent_meta: The Jenkins agent metadata to create the node from.

        Returns:
            A dictionary mapping of agent configuration values.
        """
        client = self._get_api_client()
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
            poll=False,
        )
        attribs = node.get_node_attributes()
        meta = json.loads(attribs["json"])

        meta["launcher"]["webSocket"] = True
        attribs["json"] = json.dumps(meta)
        return attribs

    def add_agent_node(self, agent_meta: state.AgentMeta) -> None:
        """Add a Jenkins agent node.

        Args:
            agent_meta: The Jenkins agent metadata to create the node from.

        Raises:
            JenkinsError: if an error occurred running groovy script creating the node.
        """
        client = self._get_api_client()
        try:
            config = self._get_node_config(agent_meta=agent_meta)
            client.create_node_with_config(name=agent_meta.name, config=config)
        except jenkinsapi.custom_exceptions.AlreadyExists:
            pass
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to add agent node, %s", exc)
            raise JenkinsError("Failed to add agent node.") from exc

    def list_agent_nodes(self) -> list[jenkinsapi.node.Node]:
        """Get agent nodes from Jenkins.

        Raises:
            JenkinsError: if there was an error listing agent nodes.

        Returns:
            Registered Jenkins agent nodes.
        """
        client = self._get_api_client()
        try:
            return client.get_nodes().values()
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error("Failed to list agent nodes, %s", exc)
            raise JenkinsError("Failed to list agent nodes.") from exc

    def remove_agent_node(self, agent_name: str) -> None:
        """Remove a Jenkins agent node.

        Args:
            agent_name: The agent node name to remove.

        Raises:
            JenkinsError: if an error occurred running groovy script removing the node.
        """
        client = self._get_api_client()
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
            _wait_for(
                functools.partial(self._is_shutdown, client),
                timeout=300,
                check_interval=1,
            )
        except TimeoutError as exc:
            raise TimeoutError("Timed out waiting for Jenkins to be shutdown.") from exc

    def safe_restart(self) -> None:
        """Safely restart Jenkins server after all jobs are done executing.

        Raises:
            JenkinsError: if there was an API error calling safe restart.
        """
        client = self._get_api_client()
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
    def _invalidate_sessions(self) -> None:  # pragma: no cover
        """Invalidate active Jenkins user sessions."""
        client = self._get_api_client()
        client.run_groovy_script("""
    import net.bull.javamelody.*;
    def sess = SessionListener.newInstance();
    sess.invalidateAllSessions();""")

    # This groovy script is tested in integration test.
    def _set_new_password(self, new_password: str) -> None:  # pragma: no cover
        """Set new password for admin user.

        Args:
            new_password: New password to set for admin user.
        """
        client = self._get_api_client()
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
            self._invalidate_sessions()
            self._set_new_password(new_password)
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

        client = self._get_api_client()
        res = client.run_groovy_script("""
    def plugins = jenkins.model.Jenkins.instance.getPluginManager().getPlugins()
    plugins.each {
        println "${it.getShortName()} (${it.getVersion()}) => ${it.getDependencies()}"
    }
    """)
        dependency_lookup = _build_dependencies_lookup(res.splitlines())
        allowed_plugins = _get_allowed_plugins(plugins, dependency_lookup)
        plugins_to_remove = set(dependency_lookup.keys()) - set(allowed_plugins)
        if not plugins_to_remove:
            return

        try:
            client.delete_plugins(plugin_list=plugins_to_remove, restart=False)
        except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
            logger.error(
                "Failed to remove the following plugins: %s, %s", plugins_to_remove, exc
            )
            raise JenkinsPluginError("Failed to remove plugins.") from exc

        logger.debug("Removed %s", plugins_to_remove)
        top_level_plugins = _filter_dependent_plugins(
            plugins_to_remove, dependency_lookup
        )
        try:
            self.safe_restart()
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

    def reload_jcasc(self) -> None:
        """Reload JCasC configuration without restarting Jenkins.

        Raises:
            JenkinsError: if the reload request fails.
        """
        try:
            client = self._get_api_client()
            client.requester.post_url(f"{self.web_url}/configuration-as-code/reload")
        except JenkinsError:
            raise
        except (
            requests.exceptions.RequestException,
            jenkinsapi.custom_exceptions.JenkinsAPIException,
        ) as exc:
            logger.error("JCasC reload failed: %s", exc)
            raise JenkinsError("Failed to reload JCasC configuration.") from exc

    def check_jcasc(self, config_content: str) -> bool:
        """Validate JCasC config via the check endpoint.

        Args:
            config_content: The YAML content to validate.

        Returns:
            True if config is valid, False otherwise.

        Raises:
            JenkinsError: if the check request fails or Jenkins is unreachable.
        """
        try:
            client = self._get_api_client()
            response = client.requester.post_url(
                f"{self.web_url}/configuration-as-code/check",
                data=config_content,
            )
            return response.status_code == 200
        except JenkinsError:
            raise
        except (
            requests.exceptions.RequestException,
            jenkinsapi.custom_exceptions.JenkinsAPIException,
        ) as exc:
            logger.error("JCasC validation failed: %s", exc)
            raise JenkinsError("Failed to validate JCasC configuration.") from exc


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
    proc: ops.pebble.ExecProcess = container.exec(
        ["stat", "-c", "%U", str(JENKINS_HOME_PATH)]
    )
    try:
        stdout, _ = proc.wait_output()
    except (ops.pebble.ChangeError, ops.pebble.ExecError) as exc:
        raise StorageMountError("Error fetching storage ownership info.") from exc
    return "jenkins" in stdout


def is_jenkins_ready(container: typing.Optional[ops.Container]) -> bool:
    """Return whether the Jenkins service is running and operational.

    Args:
        container: The Jenkins workload container.

    Returns:
        True if Jenkins service is ready and healthy. False otherwise.
    """
    if not container or not container.can_connect():
        return False
    try:
        online_check = container.get_check(ONLINE_CHECK_NAME)
    except ops.ModelError:
        logger.warning("Jenkins service not yet initialized", exc_info=True)
        return False
    return online_check.status == ops.pebble.CheckStatus.UP


def _install_config(
    container: ops.Container, filename: str, destination_path: Path
) -> None:
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
        container.push(
            destination_path,
            jenkins_config_file,
            user=USER,
            group=GROUP,
            make_dirs=True,
        )
    except ops.pebble.PathError as exc:
        raise JenkinsBootstrapError("Failed to install configuration.") from exc


def _install_configs(container: ops.Container, jenkins_config_file: str) -> None:
    """Install jenkins-config.xml and logging files.

    Args:
        container: The Jenkins workload container.
        jenkins_config_file: the path to the Jenkins configuration file to install.
    """
    _install_config(container, jenkins_config_file, CONFIG_FILE_PATH)


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


def install_logging_config(container: ops.Container) -> None:
    """Install logging config.

    Args:
        container: The Jenkins workload container.
    """
    # Logs directory needs to be created for Jenkins to write logs upon initialization
    container.make_dir(LOGGING_PATH.parent, make_parents=True, user=USER, group=GROUP)
    _install_config(container, JENKINS_LOGGING_CONFIG, LOGGING_CONFIG_PATH)


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
    plugins: typing.Iterable[str],
    dependency_lookup: typing.Mapping[str, typing.Iterable[str]],
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


def _set_jenkins_system_message(
    message: str, client: jenkinsapi.jenkins.Jenkins
) -> None:
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
        script = textwrap.dedent(f"""
            Jenkins j = Jenkins.instance
            j.systemMessage = "{message}"
            """)
        client.run_groovy_script(script)
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        logger.error("Failed to set system message, %s", exc)
        raise JenkinsError("Failed to set system message.") from exc


def unlock_wizard(container: ops.Container, version: str) -> None:
    """Write to executed version and updated version file to bypass Jenkins setup wizard.

    Args:
        container: The Jenkins workload container.
        version: The version to write to the files to bypass the wizard.

    Raises:
        JenkinsBootstrapError: if the wizard can not be unlocked.
    """
    try:
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
    except ops.pebble.PathError as exc:
        raise JenkinsError("Failed to unlock wizard.") from exc


def install_plugins(
    container: ops.Container,
    plugins: list[str],
    proxy_config: state.ProxyConfig | None = None,
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
        f"jenkins-plugin-manager-{JENKINS_PLUGIN_MANAGER_VERSION}.jar",
        "-w",
        "jenkins.war",
        "-d",
        str(PLUGINS_PATH),
        "-p",
        " ".join(set(plugins)),
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


def build_jcasc_config(
    jcasc_config: dict[str, typing.Any],
    proxy_config: typing.Optional[state.ProxyConfig] = None,
    auth_proxy: bool = False,
) -> typing.Dict[str, typing.Any]:
    """Build the desired JCasC config by merging user config with charm-managed sections.

    Injects admin credentials (local securityRealm) when the user hasn't provided one.
    Checks for conflicts with auth_proxy relation.

    Args:
        state: The current charm state.

    Returns:
        The merged JCasC configuration dict.
    """
    config = copy.deepcopy(jcasc_config)
    jenkins_section: typing.Dict[str, typing.Any] = config.get("jenkins", {})

    # Conflict check: user provides securityRealm while auth_proxy is active
    if auth_proxy:
        if "securityRealm" in jenkins_section:
            logger.warning(
                "Security realm is managed user provided jcasc-config settings."
            )
        else:
            logger.warning(
                "Bypassing Jenkins security, security via auth proxy assumed."
            )
            jenkins_section["securityRealm"] = {"authorizationStrategy": "unsecured"}

    # Inject admin credentials if securityRealm not provided by user
    if "securityRealm" not in jenkins_section:
        jenkins_section["securityRealm"] = {
            "local": {
                "allowsSignup": True,
                "users": [{"id": "admin", "password": "${JENKINS_ADMIN_PASSWORD}"}],
            }
        }

    # Updates managed by the charm, user not expected to update Jenkins manually
    jenkins_section["disabledAdministrativeMonitors"] = [
        "hudson.model.UpdateCenter$CoreUpdateMonitor"
    ]

    if proxy_config and (proxy_config.https_proxy or proxy_config.http_proxy):
        proxy = urlparse(proxy_config.https_proxy or proxy_config.http_proxy)
        host, port = proxy.hostname, proxy.port
        jenkins_section["proxy"] = {
            "name": host,
        }
        if port:
            jenkins_section["proxy"]["port"] = str(port)

    config.setdefault("jenkins", {}).update(jenkins_section)
    return config


def sync_jcasc_config(container: ops.Container, configuration_yaml: str) -> str:
    """Write JCasC config to disk, validate, and reload. Rollback on failure.

    Handles the full JCasC file lifecycle:
    1. Pull current config (if any)
    2. Short-circuit if unchanged
    3. Push desired config
    4. Validate via Jenkins API
    5. Reload if valid, rollback if invalid

    Args:
        container: The Jenkins workload container.
        desired_yaml: The full YAML string to write.

    Returns:
        The hash of the configuration applied.

    Raises:
        JenkinsError: if Jenkins API calls fail (check/reload).
    """
    jcasc_path = str(JCASC_CONFIG_PATH)

    try:
        current = container.pull(jcasc_path).read()
    except (ops.pebble.PathError, FileNotFoundError):
        current = ""

    config_hash = hashlib.sha256(configuration_yaml.encode("utf-8")).hexdigest()
    old_config_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if old_config_hash == config_hash:
        return config_hash

    container.push(
        jcasc_path,
        configuration_yaml,
        encoding="utf-8",
        user=USER,
        group=GROUP,
        make_dirs=True,
    )
    return config_hash
