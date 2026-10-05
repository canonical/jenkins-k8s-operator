# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import json
import logging
import secrets
import typing
from typing import AsyncGenerator

import jenkinsapi.plugin
import kubernetes
import kubernetes.client
import pytest
import pytest_asyncio
import requests
import tenacity
import urllib3.exceptions
from jinja2 import Environment, FileSystemLoader
from juju.application import Application
from juju.model import Model
from kubernetes.stream import stream
from pytest_operator.plugin import OpsTest

from .constants import (
    ALLOWED_PLUGINS,
    DEFAULT_SYSTEM_CONFIGURE_PAYLOAD,
    INSTALLED_PLUGINS,
    REMOVED_PLUGINS,
)
from .helpers import (
    _log_retry,
    _raise_retry_timeout,
    gen_git_test_job_xml,
    gen_test_job_xml,
    get_job_invoked_unit,
    get_pod_ip,
    install_plugins,
)
from .types_ import LDAPSettings, UnitWebClient

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture(scope="function", name="app_with_allowed_plugins")
async def app_with_allowed_plugins_fixture(
    application: Application, web_address: str, model: Model
) -> AsyncGenerator[Application, None]:
    """Jenkins charm with plugins configured."""
    await application.set_config({"allowed-plugins": ",".join(ALLOWED_PLUGINS)})
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)
    await model.block_until(
        lambda: requests.get(web_address, timeout=10).status_code == 403,
        timeout=60 * 10,
        wait_period=10,
    )
    yield application
    await application.reset_config(to_default=["allowed-plugins"])
    await model.wait_for_idle(apps=[application.name], wait_for_active=True)


@pytest.fixture(scope="module", name="ldap_settings")
def ldap_settings_fixture() -> LDAPSettings:
    """LDAP user for testing."""
    return LDAPSettings(
        container_ports=[389, 636],
        username="customuser",
        password=secrets.token_hex(16),
    )


@pytest_asyncio.fixture(scope="module", name="ldap_server")
async def ldap_server_fixture(
    model: Model,
    kube_apps_client: kubernetes.client.AppsV1Api,
    ldap_settings: LDAPSettings,
):
    """Testing LDAP server pod."""
    container = kubernetes.client.V1Container(
        name="ldap",
        image="osixia/openldap",
        image_pull_policy="IfNotPresent",
        ports=[
            kubernetes.client.V1ContainerPort(container_port=container_port)
            for container_port in ldap_settings.container_ports
        ],
        env=[
            kubernetes.client.V1EnvVar(name="LDAP_ADMIN_USERNAME", value=ldap_settings.username),
            kubernetes.client.V1EnvVar(name="LDAP_ADMIN_PASSWORD", value=ldap_settings.password),
        ],
    )
    template = kubernetes.client.V1PodTemplateSpec(
        metadata=kubernetes.client.V1ObjectMeta(labels={"app": "ldap"}),
        spec=kubernetes.client.V1PodSpec(containers=[container]),
    )
    spec = kubernetes.client.V1DeploymentSpec(
        selector=kubernetes.client.V1LabelSelector(match_labels={"app": "ldap"}),
        template=template,
    )
    deployment = kubernetes.client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=kubernetes.client.V1ObjectMeta(name="ldap", namespace=model.name),
        spec=spec,
    )
    return kube_apps_client.create_namespaced_deployment(namespace=model.name, body=deployment)


@pytest_asyncio.fixture(scope="module", name="ldap_server_ip")
async def ldap_server_ip_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    ldap_server: kubernetes.client.V1Deployment,
) -> str:
    """The LDAP deployment pod ip.

    Localhost is, by default, added to NO_PROXY by juju, hence the pod ip has to be used.
    """
    spec: kubernetes.client.V1DeploymentSpec = ldap_server.spec
    template: kubernetes.client.V1PodTemplateSpec = spec.template
    metadata: kubernetes.client.V1ObjectMeta = template.metadata
    return await get_pod_ip(model, kube_core_client, metadata.labels["app"])


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda result: not result),
    wait=tenacity.wait_fixed(10),
    stop=tenacity.stop_after_delay(10 * 60),
    retry_error_callback=_raise_retry_timeout,
    before_sleep=_log_retry,
)
def _install_plugins_via_web_api(
    unit_web_client: UnitWebClient, plugins: typing.Iterable[str]
) -> bool:
    """Request plugin installation only when a requested plugin is missing."""
    plugins = tuple(plugins)
    if all(unit_web_client.client.has_plugin(plugin) for plugin in plugins):
        return True
    post_data = {f"plugin.{plugin}.default": "on" for plugin in plugins}
    post_data["dynamic_load"] = ""
    try:
        response = unit_web_client.client.requester.post_url(
            f"{unit_web_client.web}/manage/pluginManager/install", data=post_data
        )
        return response.ok
    except (requests.exceptions.RequestException, urllib3.exceptions.HTTPError):
        logger.exception("Failed to post plugin installations.")
        return False


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda result: not result),
    wait=tenacity.wait_fixed(10),
    stop=tenacity.stop_after_delay(300),
    retry_error_callback=_raise_retry_timeout,
    before_sleep=_log_retry,
)
async def _has_plugin_temp_files(ops_test: OpsTest, unit_name: str) -> bool:
    """Return whether Jenkins still has plugin download temporary files."""
    ret_code, stdout, stderr = await ops_test.juju(
        "exec", "--unit", unit_name, "ls /var/lib/jenkins/plugins"
    )
    assert not ret_code, f"Failed to check for tmp files, {stderr}"
    return "tmp" in stdout


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda result: not result),
    wait=tenacity.wait_fixed(10),
    stop=tenacity.stop_after_delay(300),
    retry_error_callback=_raise_retry_timeout,
    before_sleep=_log_retry,
)
async def _has_plugin_delay_log(ops_test: OpsTest) -> bool:
    """Return whether plugin cleanup was delayed while downloads were active."""
    ret_code, stdout, stderr = await ops_test.juju(
        "debug-log",
        "--replay",
        "--no-tail",
        "--level",
        "WARNING",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"
    return "Plugins being downloaded, waiting until further actions." in stdout


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda result: not result),
    wait=tenacity.wait_fixed(10),
    stop=tenacity.stop_after_delay(300),
    retry_error_callback=_raise_retry_timeout,
    before_sleep=_log_retry,
)
def _all_plugins_active(unit_web_client: UnitWebClient, plugins: typing.Iterable[str]) -> bool:
    """Return whether all requested plugins are active in Jenkins."""
    return all(unit_web_client.client.has_plugin(plugin) for plugin in plugins)


@pytest.mark.usefixtures("app_with_allowed_plugins")
async def test_plugins_remove_delay(
    ops_test: OpsTest,
    update_status_env: typing.Iterable[str],
    unit_web_client: UnitWebClient,
):
    """
    arrange: given a Jenkins with plugins being installed through UI.
    act: when update_status_hook is fired.
    assert: the plugin removal delayed warning is logged until plugin installation is settled.
    """
    _install_plugins_via_web_api(unit_web_client, ALLOWED_PLUGINS)

    await _has_plugin_temp_files(ops_test, unit_web_client.unit.name)
    ret_code, _, stderr = await ops_test.juju(
        "exec",
        "--unit",
        unit_web_client.unit.name,
        "--",
        f"{' '.join(update_status_env)} ./dispatch",
    )
    assert not ret_code, f"Failed to execute update-status-hook, {stderr}"

    await _has_plugin_delay_log(ops_test)
    unit_web_client.client.safe_restart()

    _all_plugins_active(unit_web_client, ALLOWED_PLUGINS)


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
    assert (check_url_content := str(check_url_res.content, encoding="utf-8")) == "<div/>", (
        f"Non-empty error message returned, {check_url_content}"
    )


@pytest.fixture(name="seed_ldap_user")
def seed_ldap_user_fixture(
    model: Model,
    kube_core_client: kubernetes.client.CoreV1Api,
    ldap_settings: LDAPSettings,
    ldap_server: kubernetes.client.V1Deployment,
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
    pods = kube_core_client.list_namespaced_pod(namespace=model.name, label_selector="app=ldap")
    pod_name = pods.items[0].metadata.name
    response = stream(
        kube_core_client.connect_get_namespaced_pod_exec,
        name=pod_name,
        namespace=model.name,
        command=["sh", "-c", " ".join(command)],
        stderr=True,
        stdin=True,
        stdout=True,
    )
    assert "adding new entry" in response


@pytest.mark.usefixtures("app_with_allowed_plugins", "seed_ldap_user")
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
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.client.baseurl}/manage/descriptorByName/hudson.security"
        ".LDAPSecurityRealm/validate",
        json=data,
    )

    assert "User lookup: successful" in str(res.content, encoding="utf-8"), (
        f"User lookup unsuccessful, {res.content}"
    )


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
    assert "Configuration Matrix" in test_page, (
        f"Configuration matrix table not found, {test_page}"
    )


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
        "ssh", "--container", "jenkins-agent-k8s", unit.name, "cat", test_output_path
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

    assert res.status_code == 200, (
        f"Failed to access Blueocean frontend, {str(res.content, encoding='utf-8')}"
    )


@tenacity.retry(
    retry=tenacity.retry_if_result(lambda result: not result),
    wait=tenacity.wait_fixed(10),
    stop=tenacity.stop_after_delay(300),
    retry_error_callback=_raise_retry_timeout,
    before_sleep=_log_retry,
)
async def _has_thinbackup_output(ops_test: OpsTest, unit_name: str, backup_path: str) -> bool:
    """Return whether ThinBackup created a complete backup directory."""
    ret, stdout, stderr = await ops_test.juju(
        "ssh", "--container", "jenkins", unit_name, "ls", backup_path
    )
    logger.info(
        "Run backup path ls result: code: %s stdout: %s, stderr: %s",
        ret,
        stdout,
        stderr,
    )
    return ret == 0 and "FULL" in stdout


async def test_thinbackup_plugin(ops_test: OpsTest, unit_web_client: UnitWebClient):
    """
    arrange: given a Jenkins charm with thinbackup plugin installed and backup configured.
    act: when a backup action is run.
    assert: the backup is made on a configured directory.
    """
    await install_plugins(unit_web_client, ("thinBackup",))
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
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.web}/manage/thinBackup/backupManual"
    )
    res.raise_for_status()

    await _has_thinbackup_output(ops_test, unit_web_client.unit.name, backup_path)


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
