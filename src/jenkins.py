# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Functions to operate Jenkins."""

import dataclasses
import functools
import itertools
import logging
import re
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
import yaml
from pydantic import HttpUrl

import state

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


class JenkinsProxyError(JenkinsError):
    """An error occurred configuring Jenkins proxy."""


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


def get_admin_credentials(container: ops.Container) -> Credentials:
    """Retrieve admin credentials.

    Args:
        container: The Jenkins workload container to interact with filesystem.

    Returns:
        The Jenkins admin account credentials.
    """
    user = "admin"
    password_file_contents = str(container.pull(PASSWORD_FILE_PATH, encoding="utf-8").read())
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


def _unlock_wizard(container: ops.Container) -> None:
    """Write to executed version and updated version file to bypass Jenkins setup wizard.

    Args:
        container: The Jenkins workload container.
    """
    version = get_version()
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


def _install_configs(container: ops.Container) -> None:
    """Install jenkins-config.xml.

    Args:
        container: The Jenkins workload container.
    """
    with open("templates/jenkins-config.xml", encoding="utf-8") as jenkins_config_file:
        container.push(CONFIG_FILE_PATH, jenkins_config_file, user=USER, group=GROUP)
    with open("templates/jenkins.yaml", encoding="utf-8") as jenkins_casc_config_file:
        container.push(JCASC_CONFIG_FILE_PATH, jenkins_casc_config_file, user=USER, group=GROUP)


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


def _configure_proxy(
    container: ops.Container,
    proxy_config: state.ProxyConfig | None = None,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> None:
    """Configure Jenkins proxy settings if proxy configuration values are provided.

    Args:
        container: The Jenkins workload container
        proxy_config: The proxy settings to apply.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsProxyError: if an error occurred running proxy configuration script.
    """
    if not proxy_config:
        return

    client = client if client is not None else _get_client(get_admin_credentials(container))
    parsed_args = ", ".join(_get_groovy_proxy_args(proxy_config))
    try:
        client.run_groovy_script(f"proxy = new ProxyConfiguration({parsed_args})\nproxy.save()")
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        logger.error("Failed to configure proxy, %s", exc)
        raise JenkinsProxyError("Proxy configuration failed.") from exc


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
        JenkinsPluginError: if an error occurred installing the plugin.
    """
    proxy_args = [] if not proxy_config else _get_java_proxy_args(proxy_config)
    command = [
        "java",
        *proxy_args,
        "-jar",
        "jenkins-plugin-manager-2.12.11.jar",
        "-w",
        "jenkins.war",
        "-d",
        str(PLUGINS_PATH),
        "-p",
        " ".join(set(REQUIRED_PLUGINS)),
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
        raise JenkinsPluginError("Failed to install plugins.") from exc


def bootstrap(container: ops.Container, proxy_config: state.ProxyConfig | None = None) -> None:
    """Initialize and install Jenkins.

    Args:
        container: The Jenkins workload container.
        proxy_config: The Jenkins proxy configuration settings.

    Raises:
        JenkinsBootstrapError: if there was an error installing given plugins or required plugins.
    """
    _unlock_wizard(container)
    _install_configs(container)
    try:
        _configure_proxy(container, proxy_config)
        _install_plugins(container, proxy_config)
    except (JenkinsProxyError, JenkinsPluginError) as exc:
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
    container: ops.Container,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> str:
    """Get node secret from jenkins.

    Args:
        node_name: The registered node to fetch the secret from.
        container: The Jenkins workload container.
        client: The API client used to communicate with the Jenkins server.

    Returns:
        The Jenkins agent node secret.

    Raises:
        JenkinsError: if an error occurred running groovy script getting the node secret.
    """
    client = client if client is not None else _get_client(get_admin_credentials(container))
    try:
        return client.run_groovy_script(
            f'println(jenkins.model.Jenkins.getInstance().getComputer("{node_name}").getJnlpMac())'
        ).strip()
    except jenkinsapi.custom_exceptions.JenkinsAPIException as exc:
        logger.error("Failed to run get_node_secret groovy script, %s", exc)
        raise JenkinsError("Failed to run groovy script getting node secret.") from exc


def add_agent_node(
    agent_meta: state.AgentMeta,
    container: ops.Container,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> None:
    """Add a Jenkins agent node.

    Args:
        agent_meta: The Jenkins agent metadata to create the node from.
        container: The Jenkins workload container.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsError: if an error occurred running groovy script creating the node.
    """
    client = client if client is not None else _get_client(get_admin_credentials(container))
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


def _fetch_versions_from_rss(proxy: state.ProxyConfig | None = None) -> typing.Iterable[str]:
    """Fetch and extract Jenkins versions from the stable RSS feed.

    Args:
        proxy: Proxy server to route the requests through.

    Returns:
        The jenkins versions from the RSS feed.

    Raises:
        JenkinsNetworkError: if there was an error fetching the RSS feed.
        ValidationError: if an invalid RSS feed was received.
    """
    if proxy:
        proxies = {"http": str(proxy.http_proxy), "https": str(proxy.https_proxy)}
    else:
        proxies = None
    try:
        res = requests.get(RSS_FEED_URL, timeout=30, proxies=proxies)
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


def _get_latest_patch_version(current_version: str, proxy: state.ProxyConfig | None = None) -> str:
    """Get the latest lts patch version matching with the current version.

    Args:
        current_version: Current LTS semantic version.
        proxy: Proxy server to route the requests through.

    Returns:
        The latest patched version available.

    Raises:
        JenkinsNetworkError: if there was an error fetching the LTS RSS feed.
        ValidationError: if the RSS feed contains no matching LTS version.
    """
    try:
        versions = _fetch_versions_from_rss(proxy=proxy)
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


def get_updatable_version(proxy: state.ProxyConfig | None = None) -> str | None:
    """Get version to update to if available.

    Args:
        proxy: Proxy server to route the requests through.

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
        latest_version = _get_latest_patch_version(current_version=current_version, proxy=proxy)
    except (JenkinsNetworkError, ValidationError) as exc:
        logger.error("Failed to fetch latest patch version info, %s", exc)
        raise JenkinsUpdateError("Failed to fetch latest patch version info.") from exc

    if current_version == latest_version:
        return None
    return latest_version


def download_stable_war(container: ops.Container, version: str) -> None:
    """Download and replace the war executable.

    Args:
        container: The Jenkins container with jenkins.war executable.
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
    container.push(
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
    container: ops.Container, client: jenkinsapi.jenkins.Jenkins | None = None
) -> None:
    """Safely restart Jenkins server after all jobs are done executing.

    Args:
        container: The Jenkins workload container to interact with filesystem.
        client: The API client used to communicate with the Jenkins server.

    Raises:
        JenkinsError: if there was an API error calling safe restart.
    """
    client = client if client is not None else _get_client(get_admin_credentials(container))
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
    # mypy doesn't understand that we can reassign the type and it cannot be None aftwards.
    if seen is None:
        seen: set[str] = set()  # type: ignore
    for plugin in allowed_plugins:
        if plugin in seen:  # type: ignore
            continue
        yield plugin
        seen.add(plugin)  # type: ignore
        try:
            yield from _get_allowed_plugins(dependency_lookup[plugin], dependency_lookup, seen)
        except KeyError:
            logger.warning("Plugin %s not found in dependency lookup.", plugin)


def _get_top_level_plugins(
    plugins: typing.Iterable[str], dependency_lookup: typing.Mapping[str, typing.Iterable[str]]
) -> typing.Iterable[str]:
    """Get top level plugins that are not dependencies of other plugins.

    Args:
        plugins: Plugins to extract top level plugins from.
        dependency_lookup: The dependency lookup table.

    Returns:
        All plugins that are not dependency of another plugin.
    """
    dependent_plugins: set[str] = set()
    for _, dependencies in dependency_lookup.items():
        dependent_plugins = dependent_plugins.union(dependencies)

    return set(plugins) - dependent_plugins


def _set_jenkins_system_message(message: str, container: ops.Container) -> None:
    """Set a system message on Jenkins.

    Args:
        message: The system message to display.
        container: The Jenkins workload container.
    """
    jcasc_yaml = container.pull(JCASC_CONFIG_FILE_PATH, encoding="utf-8").read()
    config = yaml.safe_load(jcasc_yaml)
    config["jenkins"]["systemMessage"] = message
    container.push(
        JCASC_CONFIG_FILE_PATH, yaml.dump(config), encoding="utf-8", user=USER, group=GROUP
    )


def remove_unlisted_plugins(
    plugins: typing.Iterable[str] | None,
    container: ops.Container,
    client: jenkinsapi.jenkins.Jenkins | None = None,
) -> None:
    """Remove plugins that are not in the list of desired plugins.

    Args:
        plugins: The list of plugins that can be installed.
        container: The workload container.
        client: The Jenkins API client.

    Raises:
        JenkinsPluginError: if there was an error removing unlisted plugin.
        JenkinsError: if there was an error restarting Jenkins after removing the plugin.
        TimeoutError: if it took too long to restart Jenkins after removing the plugin.
    """
    if not plugins:
        return

    client = client if client is not None else _get_client(get_admin_credentials(container))
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

    top_level_plugins = _get_top_level_plugins(plugins_to_remove, dependency_lookup)
    _set_jenkins_system_message(
        message="The following plugins have been removed by the system administrator: "
        f"{', '.join(top_level_plugins)}\n"
        f"To allow the plugins, please include them in the plugins configuration of the charm.",
        container=container,
    )

    try:
        safe_restart(container, client)
        wait_ready()
    except (JenkinsError, TimeoutError) as exc:
        logger.error("Failed to restart Jenkins after removing plugins, %s", exc)
        raise
