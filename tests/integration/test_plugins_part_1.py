# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import json
import logging
from collections.abc import Iterable

import jenkinsapi.plugin
import jubilant
import kubernetes
import pytest
import requests
import urllib3.exceptions
from jenkinsapi.custom_exceptions import JenkinsAPIException
from jinja2 import Environment, FileSystemLoader
from kubernetes.stream import stream

from .constants import (
    ALLOWED_PLUGINS,
    DEFAULT_SYSTEM_CONFIGURE_PAYLOAD,
    INSTALLED_PLUGINS,
    REMOVED_PLUGINS,
)
from .helpers import (
    dispatch_update_status,
    ensure_plugins,
    exec_in_container,
    gen_git_test_job_xml,
    gen_test_job_xml,
    get_job_invoked_unit,
    short_model_name,
    wait_for,
)
from .types_ import JujuApplication, LDAPSettings, UnitWebClient

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("app_with_allowed_plugins")
def test_plugins_remove_delay(
    model: jubilant.Juju,
    update_status_env: Iterable[str],
    unit_web_client: UnitWebClient,
):
    """
    arrange: given a Jenkins with plugins being installed through UI.
    act: when update_status_hook is fired.
    assert: the plugin removal delayed warning is logged until plugin installation is settled.
    """
    # Arrange
    post_data = {f"plugin.{plugin}.default": "on" for plugin in ALLOWED_PLUGINS}
    post_data["dynamic_load"] = ""

    def _ensure_plugins_via_web_api() -> bool:
        """Install plugins via pluginManager API.

        Returns:
            Whether the plugin installation request has succeeded.
        """
        try:
            res = unit_web_client.client.requester.post_url(
                f"{unit_web_client.web}/manage/pluginManager/install", data=post_data
            )
            return res.ok
        except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError):
            logger.exception("Failed to post plugin installations.")
            return False

    wait_for(_ensure_plugins_via_web_api)

    def has_temp_files() -> bool:
        """Check if temporary files exist in the Jenkins plugins directory."""
        try:
            stdout = exec_in_container(
                model,
                unit_web_client.unit,
                "jenkins",
                "ls /var/lib/jenkins/plugins",
            )
        except jubilant.CLIError:
            return False
        return "tmp" in stdout

    wait_for(has_temp_files)

    # Act
    dispatch_update_status(model, unit_web_client.unit, update_status_env)

    def has_delay_log():
        """Check if juju log contains plugin cleanup delayed log.

        Returns:
            True if plugin cleanup delayed log exists. False otherwise.
        """
        stdout = model.cli(
            "debug-log",
            "--replay",
            "--no-tail",
            "--level",
            "WARNING",
        )
        return "Plugins being downloaded, waiting until further actions." in stdout

    delay_logged = wait_for(has_delay_log)
    unit_web_client.client.safe_restart()

    plugins_ready = wait_for(
        lambda: all(unit_web_client.client.has_plugin(plugin) for plugin in ALLOWED_PLUGINS)
    )

    # Assert
    assert delay_logged
    assert plugins_ready


@pytest.mark.usefixtures("app_with_allowed_plugins")
def test_jenkins_plugins_config(
    model: jubilant.Juju,
    unit_web_client: UnitWebClient,
    update_status_env: Iterable[str],
):
    """
    arrange: given a jenkins charm with plugin config and plugins installed not in the config.
    act: when update_status_hook is fired.
    assert: the plugin is uninstalled and the system message is set on Jenkins.
    """
    # Arrange
    ensure_plugins(unit_web_client, INSTALLED_PLUGINS)

    # Act
    dispatch_update_status(model, unit_web_client.unit, update_status_env)
    res = unit_web_client.client.requester.get_url(unit_web_client.web)
    page_content = str(res.content, encoding="utf-8")

    # Assert
    assert all(plugin in page_content for plugin in REMOVED_PLUGINS), page_content
    assert "The following plugins have been removed by the system administrator:" in page_content
    assert (
        "To allow the plugins, please include them in the plugins configuration of the charm."
        in page_content
    )
    assert all(unit_web_client.client.has_plugin(plugin) for plugin in ALLOWED_PLUGINS)


@pytest.mark.usefixtures("k8s_agent_related_app")
def test_git_plugin_k8s_agent(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins charm with git plugin installed.
    act: when a job is dispatched with a git workflow.
    assert: job completes successfully.
    """
    # Arrange
    ensure_plugins(unit_web_client, INSTALLED_PLUGINS)

    # Act
    job_name = "git-plugin-test-k8s"
    unit_web_client.client.create_job(job_name, gen_git_test_job_xml("k8s"))
    # check that git plugin git repository validation works on Jenkins server
    check_url_res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.client.baseurl}/job/{job_name}/descriptorByName/"
        "hudson.plugins.git.UserRemoteConfig/checkUrl",
        data={
            "value": "https://github.com/canonical/jenkins-k8s-operator",
            "credentialsId": "",
        },
    )
    # Assert
    assert (check_url_content := str(check_url_res.content, encoding="utf-8")) == "<div/>", (
        f"Non-empty error message returned, {check_url_content}"
    )


@pytest.fixture(name="seed_ldap_user")
def seed_ldap_user_fixture(
    model: jubilant.Juju,
    kube_core_client: kubernetes.client.CoreV1Api,
    ldap_settings: LDAPSettings,
):
    """Seed user into ldap server."""
    command = [
        "ldapadd",
        "-x",
        "-H",
        "ldap://localhost:389",
        "-D",
        "cn=admin,dc=example,dc=org",
        "-w",
        f"{ldap_settings.password}",
        f"""<<EOF
dn: uid={ldap_settings.username},dc=example,dc=org
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: organizationalPerson
uid: {ldap_settings.username}
cn: Testing User
sn: Test
userPassword: {ldap_settings.password}
mail: testing@example.org
uidNumber: 1001
gidNumber: 1001
homeDirectory: /home/{ldap_settings.username}
EOF""",
    ]
    pods = kube_core_client.list_namespaced_pod(
        namespace=short_model_name(model), label_selector="app=ldap"
    )
    pod_name = pods.items[0].metadata.name
    response = stream(
        kube_core_client.connect_get_namespaced_pod_exec,
        name=pod_name,
        namespace=short_model_name(model),
        command=["sh", "-c", " ".join(command)],
        stderr=True,
        stdin=True,
        stdout=True,
    )
    assert "adding new entry" in response


@pytest.mark.usefixtures("app_with_allowed_plugins", "seed_ldap_user")
def test_ldap_plugin(
    unit_web_client: UnitWebClient,
    ldap_server_ip: str,
    ldap_settings: LDAPSettings,
):
    """
    arrange: given an ldap server with user setup and ldap plugin installed on Jenkins server.
    act: when ldap plugin is configured and the user is queried.
    assert: the user is authenticated successfully.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("ldap",))

    # This is same as: Manage Jenkins > Configure Global Security > Authentication >
    # Security Realm > LDAP > Test LDAP Settings.
    data = {
        "securityRealm": {
            "configurations": {
                "server": f"ldap://{ldap_server_ip}:{ldap_settings.container_ports[0]}",
                "rootDN": "dc=example,dc=org",  # default example server settings.
                "inhibitInferRootDN": False,
                "userSearchBase": "",
                "userSearch": "uid={0}",
                "groupSearchBase": "",
                "groupSearchFilter": "",
                "groupMembershipStrategy": {
                    "value": "1",
                    "filter": "",
                    "stapler-class": "jenkins.security.plugins.ldap"
                    ".FromGroupSearchLDAPGroupMembershipStrategy",
                    "$class": "jenkins.security.plugins.ldap"
                    ".FromGroupSearchLDAPGroupMembershipStrategy",
                },
                "managerDN": "cn=admin,dc=example,dc=org",  # default example server settings.
                "managerPasswordSecret": ldap_settings.password,
                "$redact": "managerPasswordSecret",
                "displayNameAttributeName": "displayname",
                "mailAddressAttributeName": "mail",
                "ignoreIfUnavailable": False,
            },
            "": ["0", "0"],
            "userIdStrategy": {
                "stapler-class": "jenkins.model.IdStrategy$CaseInsensitive",
                "$class": "jenkins.model.IdStrategy$CaseInsensitive",
            },
            "groupIdStrategy": {
                "stapler-class": "jenkins.model.IdStrategy$CaseInsensitive",
                "$class": "jenkins.model.IdStrategy$CaseInsensitive",
            },
            "disableMailAddressResolver": False,
            "disableRolePrefixing": True,
            "stapler-class": "hudson.security.LDAPSecurityRealm",
            "$class": "hudson.security.LDAPSecurityRealm",
        },
        "testUser": ldap_settings.username,
        "testPassword": ldap_settings.password,
    }
    # Act
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.client.baseurl}/manage/descriptorByName/hudson.security"
        ".LDAPSecurityRealm/validate",
        json=data,
    )

    # Assert
    assert "User lookup: successful" in str(res.content, encoding="utf-8"), (
        f"User lookup unsuccessful, {res.content}"
    )


@pytest.mark.usefixtures("app_with_allowed_plugins")
def test_matrix_combinations_parameter_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins server with matrix-combinations-parameter plugin installed.
    act: when a multi-configuration job is created.
    assert: a matrix based test is created.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("matrix-combinations-parameter",))
    matrix_project_plugin: jenkinsapi.plugin.Plugin = unit_web_client.client.plugins[
        "matrix-project"
    ]
    matrix_combinations_plugin: jenkinsapi.plugin.Plugin = unit_web_client.client.plugins[
        "matrix-combinations-parameter"
    ]
    environment = Environment(loader=FileSystemLoader("tests/integration/files/"), autoescape=True)
    template = environment.get_template("matrix_combinations_plugin_job_xml.j2")
    job_xml = template.render(
        matrix_project_plugin_version=matrix_project_plugin.version,
        matrix_combinations_plugin_version=matrix_combinations_plugin.version,
    )
    test_name = "matrix-combinations-parameter-test"
    # Act
    unit_web_client.client.create_job(test_name, job_xml)

    def configuration_matrix_page() -> str:
        """Wait until Jenkins has finished restarting after plugin changes."""
        try:
            test_page = str(
                unit_web_client.client.requester.get_url(
                    f"{unit_web_client.client.baseurl}/job/{test_name}/"
                ).content,
                encoding="utf-8",
            )
        except (JenkinsAPIException, requests.RequestException):
            return ""
        return test_page if "Configuration Matrix" in test_page else ""

    test_page = wait_for(configuration_matrix_page, timeout=10 * 60)

    # Assert
    assert "Configuration Matrix" in test_page, (
        f"Configuration matrix table not found, {test_page}"
    )


@pytest.mark.usefixtures("k8s_agent_related_app")
def test_postbuildscript_plugin(
    unit_web_client: UnitWebClient,
    jenkins_k8s_agents: JujuApplication,
):
    """
    arrange: given a jenkins charm with postbuildscript plugin installed and related to an agent.
    act: when a postbuildscript job that writes a file to a /tmp folder is dispatched.
    assert: the file is written on the /tmp folder of the job host.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("postbuildscript",))
    postbuildscript_plugin: jenkinsapi.plugin.Plugin = unit_web_client.client.plugins[
        "postbuildscript"
    ]
    environment = Environment(loader=FileSystemLoader("tests/integration/files/"), autoescape=True)
    template = environment.get_template("postbuildscript_plugin_job_xml.j2")
    # tmp directory is fine to use for testing purposes since TemporaryFile cannot be used here.
    test_output_path = "/tmp/postbuildscript_test.txt"  # nosec
    test_output = "postbuildscript test"
    job_xml = template.render(
        postbuildscript_plugin_version=postbuildscript_plugin.version,
        postbuildscript_command=f'echo -n "{test_output}" > {test_output_path}',
    )
    # Act
    job = unit_web_client.client.create_job("postbuildscript-test-k8s", job_xml)
    job.invoke().block_until_complete()

    unit = get_job_invoked_unit(job, jenkins_k8s_agents.units)
    if not unit:
        raise RuntimeError(
            f"Agent unit running the job not found, {job.get_last_build().get_slave()}"
        )
    stdout = exec_in_container(
        jenkins_k8s_agents.model,
        unit,
        "jenkins-agent-k8s",
        f"cat {test_output_path}",
    )

    # Assert
    assert stdout == test_output


def test_ssh_agent_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given jenkins charm with ssh_agent plugin installed.
    act: when a job is being configured.
    assert: ssh-agent configuration is visible.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("ssh-agent",))

    # Act
    unit_web_client.client.create_job("ssh_agent_test", gen_test_job_xml("k8s"))
    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/job/ssh_agent_test/configure"
    )

    config_page = str(res.content, "utf-8")

    # Assert
    assert "SSH Agent" in config_page, f"SSH agent configuration not found. {config_page}"


def test_blueocean_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins charm with blueocean plugin installed.
    act: when blueocean frontend url is accessed.
    assert: 200 response is returned.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("blueocean",))

    # Act
    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/blue/organizations/jenkins/"
    )

    # Assert
    assert res.status_code == 200, (
        f"Failed to access Blueocean frontend, {str(res.content, encoding='utf-8')}"
    )


def test_thinbackup_plugin(model: jubilant.Juju, unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with thinbackup plugin installed and backup configured.
    act: when a backup action is run.
    assert: the backup is made on a configured directory.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("thinBackup",))
    backup_path = "/srv/jenkins/backup/"
    payload = {
        **DEFAULT_SYSTEM_CONFIGURE_PAYLOAD,
        "org-jvnet-hudson-plugins-thinbackup-ThinBackupPluginImpl": {
            "backupPath": backup_path,
        },
    }
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/configSubmit",
        data=[
            (
                "json",
                json.dumps(payload),
            ),
        ],
    )
    res.raise_for_status()

    # Act
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/thinBackup/backupManual"
    )
    res.raise_for_status()

    def has_backup() -> bool:
        """Get whether the backup is created.

        The backup folder of format FULL-<backup-date> should be created.

        Returns:
            Whether the backup file has successfully been created.
        """
        try:
            stdout = exec_in_container(
                model,
                unit_web_client.unit,
                "jenkins",
                f"ls {backup_path}",
            )
        except jubilant.CLIError:
            return False
        logger.info("Run backup path ls result: stdout: %s", stdout)
        return "FULL" in stdout

    backup_ready = wait_for(has_backup)

    # Assert
    assert backup_ready


def test_bzr_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with bazaar plugin installed.
    act: when a job configuration page is accessed.
    assert: bazaar plugin option exists.
    """
    # Arrange
    ensure_plugins(unit_web_client, ("bazaar",))

    # Act
    unit_web_client.client.create_job("bzr_plugin_test", gen_test_job_xml("k8s"))
    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/job/bzr_plugin_test/configure"
    )

    config_page = str(res.content, "utf-8")

    # Assert
    assert "Bazaar" in config_page, f"Bzr configuration option not found. {config_page}"
