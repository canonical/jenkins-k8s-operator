# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import json
import typing

import jenkinsapi.plugin
import pytest
import requests
from jinja2 import Environment, FileSystemLoader
from juju.application import Application
from pytest_operator.plugin import OpsTest

from .constants import ALLOWED_PLUGINS, INSTALLED_PLUGINS, REMOVED_PLUGINS
from .helpers import (
    create_kubernetes_cloud,
    create_secret_file_credentials,
    gen_git_test_job_xml,
    gen_test_job_xml,
    gen_test_pipeline_with_custom_script_xml,
    get_job_invoked_unit,
    install_plugins,
    kubernetes_test_pipeline_script,
    wait_for,
)
from .types_ import KeycloakOIDCMetadata, LDAPSettings, UnitWebClient


@pytest.mark.usefixtures("app_with_allowed_plugins")
async def test_plugins_remove_delay(
    ops_test: OpsTest, update_status_env: typing.Iterable[str], unit_web_client: UnitWebClient
):
    """
    arrange: given a Jenkins with plugins being installed through UI.
    act: when update_status_hook is fired.
    assert: the plugin removal is delayed warning is logged until plugin installation is settled.
    """
    post_data = {f"plugin.{plugin}.default": "on" for plugin in ALLOWED_PLUGINS}
    post_data["dynamic_load"] = ""
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/pluginManager/install", data=post_data
    )
    assert res.status_code == 200, "Failed to request plugins install"

    async def has_temp_files():
        """Check if tempfiles exist in Jenkins plugins directory.

        Returns:
            True if .tmp file exists, False otherwise.
        """
        ret_code, stdout, stderr = await ops_test.juju(
            "exec", "--unit", unit_web_client.unit.name, "ls /var/lib/jenkins/plugins"
        )
        assert not ret_code, f"Failed to check for tmp files, {stderr}"
        return "tmp" in stdout

    await wait_for(has_temp_files)
    ret_code, _, stderr = await ops_test.juju(
        "exec",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"

    async def has_delay_log():
        """Check if juju log contains plugin cleanup delayed log.

        Returns:
            True if plugin cleanup delayed log exists. False otherwise.
        """
        ret_code, stdout, stderr = await ops_test.juju(
            "debug-log",
            "--replay",
            "--no-tail",
            "--level",
            "WARNING",
        )
        assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
        return "Plugins being downloaded, waiting until further actions." in stdout

    await wait_for(has_delay_log)
    unit_web_client.client.safe_restart()

    await wait_for(
        lambda: all(unit_web_client.client.has_plugin(plugin) for plugin in ALLOWED_PLUGINS)
    )


@pytest.mark.usefixtures("app_with_allowed_plugins")
async def test_jenkins_plugins_config(
    ops_test: OpsTest,
    unit_web_client: UnitWebClient,
    update_status_env: typing.Iterable[str],
):
    """
    arrange: given a jenkins charm with plugin config and plugins installed not in the config.
    act: when update_status_hook is fired.
    assert: the plugin is uninstalled and the system message is set on Jenkins.
    """
    await install_plugins(unit_web_client, INSTALLED_PLUGINS)

    ret_code, _, stderr = await ops_test.juju(
        "exec",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    res = unit_web_client.client.requester.get_url(unit_web_client.web)
    page_content = str(res.content, encoding="utf-8")

    assert all(plugin in page_content for plugin in REMOVED_PLUGINS), page_content
    assert "The following plugins have been removed by the system administrator:" in page_content
    assert (
        "To allow the plugins, please include them in the plugins configuration of the charm."
        in page_content
    )
    assert all(unit_web_client.client.has_plugin(plugin) for plugin in ALLOWED_PLUGINS)


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_git_plugin_k8s_agent(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins charm with git plugin installed.
    act: when a job is dispatched with a git workflow.
    assert: job completes successfully.
    """
    await install_plugins(unit_web_client, INSTALLED_PLUGINS)

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
    assert (
        check_url_content := str(check_url_res.content, encoding="utf-8")
    ) == "<div/>", f"Non-empty error message returned, {check_url_content}"


@pytest.mark.usefixtures("app_with_allowed_plugins")
async def test_ldap_plugin(
    unit_web_client: UnitWebClient,
    ldap_server_ip: str,
    ldap_settings: LDAPSettings,
):
    """
    arrange: given an ldap server with user setup and ldap plugin installed on Jenkins server.
    act: when ldap plugin is configured and the user is queried.
    assert: the user is authenticated successfully.
    """
    await install_plugins(unit_web_client, ("ldap",))

    # This is same as: Manage Jenkins > Configure Global Security > Authentication >
    # Security Realm > LDAP > Test LDAP Settings.
    data = {
        "securityRealm": {
            "configurations": {
                "server": f"ldap://{ldap_server_ip}:{ldap_settings.container_port}",
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
                "managerDN": "",
                "managerPasswordSecret": "",
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
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.client.baseurl}/manage/descriptorByName/hudson.security"
        ".LDAPSecurityRealm/validate",
        json=data,
    )

    assert "User lookup: successful" in str(
        res.content, encoding="utf-8"
    ), f"User lookup unsuccessful, {res.content}"


@pytest.mark.usefixtures("app_with_allowed_plugins")
async def test_matrix_combinations_parameter_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins server with matrix-combinations-parameter plugin installed.
    act: when a multi-configuration job is created.
    assert: a matrix based test is created.
    """
    await install_plugins(unit_web_client, ("matrix-combinations-parameter",))
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
    unit_web_client.client.create_job(test_name, job_xml)

    test_page = str(
        unit_web_client.client.requester.get_url(
            f"{unit_web_client.client.baseurl}/job/{test_name}/"
        ).content,
        encoding="utf-8",
    )
    assert (
        "Configuration Matrix" in test_page
    ), f"Configuration matrix table not found, {test_page}"


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_postbuildscript_plugin(
    ops_test: OpsTest, unit_web_client: UnitWebClient, jenkins_k8s_agents: Application
):
    """
    arrange: given a jenkins charm with postbuildscript plugin installed and related to an agent.
    act: when a postbuildscript job that writes a file to a /tmp folder is dispatched.
    assert: the file is written on the /tmp folder of the job host.
    """
    await install_plugins(unit_web_client, ("postbuildscript",))
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
    job = unit_web_client.client.create_job("postbuildscript-test-k8s", job_xml)
    job.invoke().block_until_complete()

    unit = get_job_invoked_unit(job, jenkins_k8s_agents.units)
    assert unit, f"Agent unit running the job not found, {job.get_last_build().get_slave()}"
    ret, stdout, stderr = await ops_test.juju(
        "ssh", "--container", "jenkins-k8s-agent", unit.name, "cat", test_output_path
    )
    assert ret == 0, f"Failed to scp test output file, {stderr}"
    assert stdout == test_output


async def test_ssh_agent_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given jenkins charm with ssh_agent plugin installed.
    act: when a job is being configured.
    assert: ssh-agent configuration is visible.
    """
    await install_plugins(unit_web_client, ("ssh-agent",))
    unit_web_client.client.create_job("ssh_agent_test", gen_test_job_xml("k8s"))

    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/job/ssh_agent_test/configure"
    )

    config_page = str(res.content, "utf-8")
    assert "SSH Agent" in config_page, f"SSH agent configuration not found. {config_page}"


async def test_blueocean_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins charm with blueocean plugin installed.
    act: when blueocean frontend url is accessed.
    assert: 200 response is returned.
    """
    await install_plugins(unit_web_client, ("blueocean",))

    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/blue/organizations/jenkins/"
    )

    assert (
        res.status_code == 200
    ), f"Failed to access Blueocean frontend, {str(res.content, encoding='utf-8')}"


async def test_thinbackup_plugin(ops_test: OpsTest, unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with thinbackup plugin installed and backup configured.
    act: when a backup action is run.
    assert: the backup is made on a configured directory.
    """
    await install_plugins(unit_web_client, ("thinBackup",))
    backup_path = "/srv/jenkins/backup/"
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/thinBackup/saveSettings",
        data={
            "backupPath": backup_path,
            "fullBackupSchedule": "",
            "diffBackupSchedule": "",
            "nrMaxStoredFull": -1,
            "excludedFilesRegex": "",
            "forceQuietModeTimeout": 120,
            "failFast": "on",
            "Submit": "",
        },
    )
    res.raise_for_status()
    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/manage/thinBackup/backupManual"
    )
    res.raise_for_status()

    ret, stdout, stderr = await ops_test.juju(
        "ssh", "--container", "jenkins", unit_web_client.unit.name, "ls", backup_path
    )
    assert ret == 0, f"Failed to ls backup path, {stderr}"
    assert "FULL" in stdout, "The backup folder of format FULL-<backup-date> not found."


async def test_bzr_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with bazaar plugin installed.
    act: when a job configuration page is accessed.
    assert: bazaar plugin option exists.
    """
    await install_plugins(unit_web_client, ("bazaar",))
    unit_web_client.client.create_job("bzr_plugin_test", gen_test_job_xml("k8s"))

    res = unit_web_client.client.requester.get_url(
        f"{unit_web_client.web}/job/bzr_plugin_test/configure"
    )

    config_page = str(res.content, "utf-8")
    assert "Bazaar" in config_page, f"Bzr configuration option not found. {config_page}"


@pytest.mark.usefixtures("k8s_agent_related_app")
async def test_rebuilder_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with rebuilder plugin installed.
    act: when a job is built and a rebuild is triggered.
    assert: last job is rebuilt.
    """
    await install_plugins(unit_web_client, ("rebuild",))

    job_name = "rebuild_test"
    job = unit_web_client.client.create_job(job_name, gen_test_job_xml("k8s"))
    job.invoke().block_until_complete()

    unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/job/{job_name}/lastCompletedBuild/rebuild/"
    )
    job.get_last_build().block_until_complete()

    assert job.get_last_buildnumber() == 2, "Rebuild not triggered."


async def test_openid_plugin(unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with openid plugin installed.
    act: when an openid endpoint is validated using the plugin.
    assert: the response returns a 200 status code.
    """
    await install_plugins(unit_web_client, ("openid",))

    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/descriptorByName/hudson.plugins.openid."
        "OpenIdSsoSecurityRealm/validate",
        data={"endpoint": "https://login.ubuntu.com/+openid"},
    )

    assert res.status_code == 200, "Failed to validate openid endpoint using the plugin."


async def test_openid_connect_plugin(
    unit_web_client: UnitWebClient,
    keycloak_oidc_meta: KeycloakOIDCMetadata,
    keycloak_ip: str,
):
    """
    arrange: given a Jenkins charm with oic-auth plugin installed and a Keycloak oidc server.
    act:
        1. when jenkins security realm is configured with oidc server and login page is requested.
        2. when jenkins security realm is reset and login page is requested.
    assert:
        1. a redirection to Keycloak SSO is made.
        2. native Jenkins login ui is loaded.
    """
    await install_plugins(unit_web_client, ("oic-auth",))

    # 1. when jenkins security realm is configured with oidc server and login page is requested.
    payload: dict = {
        "securityRealm": {
            "clientId": keycloak_oidc_meta.client_id,
            "clientSecret": keycloak_oidc_meta.client_secret,
            "automanualconfigure": "auto",
            "wellKnownOpenIDConfigurationUrl": keycloak_oidc_meta.well_known_endpoint,
            "userNameField": "sub",
            "stapler-class": "org.jenkinsci.plugins.oic.OicSecurityRealm",
            "$class": "org.jenkinsci.plugins.oic.OicSecurityRealm",
        },
        "slaveAgentPort": {"type": "fixed", "value": "50000"},
    }
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/configureSecurity/configure",
        data=[
            (
                "json",
                json.dumps(payload),
            ),
        ],
    )
    res = requests.get(f"{unit_web_client.web}/securityRealm/commenceLogin?from=%2F", timeout=30)
    assert res.history[0].status_code == 302, "Jenkins login not redirected."
    assert keycloak_ip in res.history[0].headers["location"], "Login not redirected to keycloak."

    # 2. when jenkins security realm is reset and login page is requested.
    payload = {
        "securityRealm": {
            "allowsSignup": False,
            "stapler-class": "hudson.security.HudsonPrivateSecurityRealm",
            "$class": "hudson.security.HudsonPrivateSecurityRealm",
        },
        "authorizationStrategy": {
            "allowAnonymousRead": False,
            "stapler-class": "hudson.security.FullControlOnceLoggedInAuthorizationStrategy",
            "$class": "hudson.security.FullControlOnceLoggedInAuthorizationStrategy",
        },
        "slaveAgentPort": {"type": "fixed", "value": "50000"},
    }
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/configureSecurity/configure",
        data=[
            (
                "json",
                json.dumps(payload),
            )
        ],
    )
    res = requests.get(f"{unit_web_client.web}/securityRealm/commenceLogin?from=%2F", timeout=30)
    assert res.status_code == 404, "Security realm login not reset."
    res = requests.get(f"{unit_web_client.web}/login?from=%2F", timeout=30)
    assert res.status_code == 200, "Failed to load Jenkins native login UI."


async def test_kuberentes_plugin(unit_web_client: UnitWebClient, kube_config: str):
    """
    arrange: given a Jenkins charm with kubernetes plugin installed and credentials from microk8s.
    act: Run a job using an agent provided by the kubernetes plugin.
    assert: Job succeeds.
    """
    # Use plain credentials to be able to create secret-file/secret-text credentials
    await install_plugins(unit_web_client, ("kubernetes", "plain-credentials"))

    # Create credentials
    credentials_id = create_secret_file_credentials(unit_web_client, kube_config)
    assert credentials_id
    kubernetes_cloud_name = create_kubernetes_cloud(unit_web_client, credentials_id)
    assert kubernetes_cloud_name
    job = unit_web_client.client.create_job(
        "kubernetes_plugin_test",
        gen_test_pipeline_with_custom_script_xml(kubernetes_test_pipeline_script()),
    )
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"
