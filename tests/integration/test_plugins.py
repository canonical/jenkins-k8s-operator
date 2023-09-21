# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for jenkins-k8s-operator charm."""

import typing

import pytest
from pytest_operator.plugin import OpsTest

from .constants import ALLOWED_PLUGINS, INSTALLED_PLUGINS, REMOVED_PLUGINS
from .helpers import gen_git_test_job_xml, install_plugins
from .types_ import TestLDAPSettings, UnitWebClient


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
    await install_plugins(
        ops_test, unit_web_client.unit, unit_web_client.client, INSTALLED_PLUGINS
    )

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


@pytest.mark.usefixtures("app_k8s_agent_related")
async def test_git_plugin_k8s_agent(ops_test: OpsTest, unit_web_client: UnitWebClient):
    """
    arrange: given a jenkins charm with git plugin installed.
    act: when a job is dispatched with a git workflow.
    assert: job completes successfully.
    """
    await install_plugins(
        ops_test, unit_web_client.unit, unit_web_client.client, INSTALLED_PLUGINS
    )

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
    ops_test: OpsTest,
    unit_web_client: UnitWebClient,
    ldap_server_ip: str,
    ldap_settings: TestLDAPSettings,
):
    """
    arrange: given an ldap server with user setup and ldap plugin installed on Jenkins server.
    act: when ldap plugin is configured and the user is queried.
    assert: the user is authenticated successfully.
    """
    await install_plugins(ops_test, unit_web_client.unit, unit_web_client.client, ("ldap",))

    # This is same as: Manage Jenkins > Configure Global Security > Authentication >
    # Security Realm > LDAP > Test LDAP Settings.
    data = {
        "securityRealm": {
            "configurations": {
                "server": f"ldap://{ldap_server_ip}:{ldap_settings.CONTAINER_PORT}",
                "rootDN": "dc=example,dc=org",  # default example server settings.
                "inhibitInferRootDN": False,
                "userSearchBase": "",
                "userSearch": "uid={0}",
                "groupSearchBase": "",
                "groupSearchFilter": "",
                "groupMembershipStrategy": {
                    "value": "1",
                    "filter": "",
                    "stapler-class": "jenkins.security.plugins.ldap.FromGroupSearchLDAPGroupMembershipStrategy",
                    "$class": "jenkins.security.plugins.ldap.FromGroupSearchLDAPGroupMembershipStrategy",
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
        "testUser": ldap_settings.USER_NAME,
        "testPassword": ldap_settings.USER_PASSWORD,
    }
    res = unit_web_client.client.requester.post_url(
        f"{unit_web_client.client.baseurl}/manage/descriptorByName/hudson.security.LDAPSecurityRealm/validate",
        json=data,
    )

    assert "User lookup: successful" in str(
        res.content, encoding="utf-8"
    ), f"User lookup unsuccessful, {res.content}"
