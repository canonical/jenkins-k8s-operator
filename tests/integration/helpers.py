# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers for Jenkins-k8s-operator charm integration tests."""

import logging
import secrets
import textwrap
import time
import typing
from collections.abc import Callable, Iterable
from enum import Enum
from urllib.parse import urlparse

import jenkinsapi.jenkins
import jubilant
import kubernetes.client
import requests
import tenacity

import jenkins

from .types_ import JujuApplication, UnitWebClient

logger = logging.getLogger(__name__)


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, max=60),
    reraise=True,
    stop=tenacity.stop_after_attempt(5),
)
def install_plugins(
    unit_web_client: UnitWebClient,
    plugins: Iterable[str],
) -> None:
    """Install plugins to Jenkins unit.

    Args:
        unit_web_client: The wrapper around unit, web_address and Jenkins client.
        plugins: Desired plugins to install.
    """
    web, client = unit_web_client.web, unit_web_client.client
    plugins = tuple(plugin for plugin in plugins if not client.has_plugin(plugin))
    if not plugins:
        return

    post_data = {f"plugin.{plugin}.default": "on" for plugin in plugins}
    post_data["dynamic_load"] = ""
    res = client.requester.post_url(f"{web}/manage/pluginManager/install", data=post_data)
    assert res.status_code == 200, "Failed to request plugins install"

    # Block until the UI does not have "Pending" in the download progress column.
    wait_for(
        lambda: "Pending"
        not in str(
            client.requester.post_url(f"{web}/manage/pluginManager/updates/body").content,
            encoding="utf-8",
        ),
        timeout=60 * 10,
    )

    # The library can return 503 while Jenkins restarts, so restart and wait
    # for the authenticated endpoint rather than checking one status code.
    client.safe_restart()
    wait_for(
        lambda: requests.get(web, timeout=10).status_code == 403,
        timeout=60 * 10,
        check_interval=10,
    )


def get_model_unit_addresses(model: jubilant.Juju, app_name: str) -> list[str]:
    """Return addresses for all units of an application."""
    application_status = model.status().apps.get(app_name)
    assert application_status, f"Application status {app_name} not found"

    # Machine-model units populate ``public_address`` while Kubernetes units
    # populate ``address``. Accept both so cross-model tests share this helper.
    return [
        str(unit.address or unit.public_address)
        for unit in application_status.units.values()
        if unit.address or unit.public_address
    ]


def exec_in_container(
    model: jubilant.Juju,
    unit: str,
    container: str,
    command: str,
) -> str:
    """Run a shell command in a named Juju workload container."""
    return model.ssh(unit, command, container=container)


def dispatch_update_status(
    model: jubilant.Juju,
    unit: str,
    environment: Iterable[str],
) -> str:
    """Run update-status through the unit agent's command context."""
    environment_assignments = " ".join(environment)
    command = f"/usr/bin/juju-exec {unit} '{environment_assignments} ./dispatch'"
    return exec_in_container(model, unit, "charm", command)


def short_model_name(model: jubilant.Juju) -> str:
    """Return a model's short name from a Jubilant model specification."""
    model_name = model.model
    assert model_name, "Jubilant model is not connected"
    return model_name.rsplit(":", maxsplit=1)[-1]


def gen_test_job_xml(node_label: str) -> str:
    """Generate a job XML with the target node label."""
    return textwrap.dedent(f"""
        <project>
            <actions/>
            <description/>
            <keepDependencies>false</keepDependencies>
            <properties/>
            <scm class="hudson.scm.NullSCM"/>
            <assignedNode>{node_label}</assignedNode>
            <canRoam>false</canRoam>
            <disabled>false</disabled>
            <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>
            <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>
            <triggers/>
            <concurrentBuild>false</concurrentBuild>
            <builders>
                <hudson.tasks.Shell>
                    <command>echo "hello world"</command>
                    <configuredLocalRules/>
                </hudson.tasks.Shell>
            </builders>
            <publishers/>
            <buildWrappers/>
        </project>
        """)


def assert_job_success(
    client: jenkinsapi.jenkins.Jenkins, agent_name: str, test_target_label: str
) -> None:
    """Assert that a job can be created and run successfully."""
    nodes = client.nodes.iterkeys()
    assert any(agent_name in key for key in nodes), f"Jenkins {agent_name} node not registered."

    job = client.create_job(agent_name, gen_test_job_xml(test_target_label))
    queue_item = job.invoke()
    queue_item.block_until_complete()
    build: jenkinsapi.build.Build = queue_item.get_build()
    assert build.get_status() == "SUCCESS"


def gen_git_test_job_xml(node_label: str) -> str:
    """Generate a git test job XML with the target node label."""
    return textwrap.dedent(f"""
        <project>
            <actions />
            <description></description>
            <keepDependencies>false</keepDependencies>
            <properties />
            <scm class="hudson.plugins.git.GitSCM" plugin="git@5.0.2">
                <configVersion>2</configVersion>
                <userRemoteConfigs>
                    <hudson.plugins.git.UserRemoteConfig>
                        <url>https://github.com/canonical/jenkins-k8s-operator</url>
                    </hudson.plugins.git.UserRemoteConfig>
                </userRemoteConfigs>
                <branches>
                    <hudson.plugins.git.BranchSpec>
                        <name>*/main</name>
                    </hudson.plugins.git.BranchSpec>
                </branches>
                <doGenerateSubmoduleConfigurations>
                    false</doGenerateSubmoduleConfigurations>
                <submoduleCfg class="empty-list" />
                <extensions />
            </scm>
            <assignedNode>{node_label}</assignedNode>
            <canRoam>true</canRoam>
            <disabled>false</disabled>
            <blockBuildWhenDownstreamBuilding>
                false</blockBuildWhenDownstreamBuilding>
            <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>
            <triggers />
            <concurrentBuild>false</concurrentBuild>
            <builders>
                <hudson.tasks.Shell>
                    <command>git checkout main\ngit pull</command>
                    <configuredLocalRules />
                </hudson.tasks.Shell>
            </builders>
            <publishers />
            <buildWrappers />
        </project>
        """)


def get_pod_ip(
    model: jubilant.Juju,
    kube_core_client: kubernetes.client.CoreV1Api,
    app_label: str,
) -> str:
    """Return the ready pod IP for an application label."""

    def get_ready_pod_ip() -> str | None:
        podlist = kube_core_client.list_namespaced_pod(
            namespace=short_model_name(model), label_selector=f"app={app_label}"
        )
        for pod in podlist.items:
            if pod.status is None or pod.status.conditions is None:
                continue
            if any(
                condition.type == "Ready" and condition.status == "True"
                for condition in pod.status.conditions
            ):
                return pod.status.pod_ip
        return None

    return typing.cast(
        str,
        wait_for(get_ready_pod_ip, timeout=300, check_interval=5),
    )


def wait_for(
    func: Callable[[], typing.Any],
    timeout: int = 300,
    check_interval: int = 10,
) -> typing.Any:
    """Wait for a function to return a truthy value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if result := func():
            return result
        time.sleep(check_interval)

    if result := func():
        return result
    raise TimeoutError()


def _wait_for_apps(
    model: jubilant.Juju,
    apps: Iterable[str],
    *,
    wait_for_active: bool,
    timeout: int,
) -> None:
    """Wait for the requested applications to settle in a model."""
    app_list = list(apps)
    if wait_for_active:
        model.wait(
            lambda status: jubilant.all_active(status, *app_list)
            and jubilant.all_agents_idle(status, *app_list),
            error=jubilant.any_error,
            timeout=timeout,
        )
    else:
        model.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=timeout)


def ensure_relation(
    *,
    model: jubilant.Juju,
    application: JujuApplication,
    other_application: JujuApplication,
    relation: str | tuple[str, str] | None = None,
    renew: bool = False,
    apps: Iterable[str] | None = None,
    wait_for_active: bool = True,
    timeout: int = 20 * 60,
    idle_period: int | None = None,
) -> None:
    """Ensure a relation exists and wait for its applications to settle."""
    del idle_period  # Jubilant's status wait uses repeated successful polls.
    if relation is None:
        application_endpoint = other_application_endpoint = "agent"
    elif isinstance(relation, tuple):
        application_endpoint, other_application_endpoint = relation
    else:
        application_endpoint = other_application_endpoint = relation

    app_list = list(apps) if apps is not None else [application.name, other_application.name]
    relation_target = f"{other_application.name}:{other_application_endpoint}"
    relation_source = f"{application.name}:{application_endpoint}"

    if renew:
        try:
            model.remove_relation(relation_source, relation_target)
        except jubilant.CLIError as exc:
            if "not found" not in str(exc).lower() and "no relation" not in str(exc).lower():
                raise
        else:
            _wait_for_apps(
                model,
                app_list,
                wait_for_active=False,
                timeout=timeout,
            )

    try:
        model.integrate(relation_source, relation_target)
    except jubilant.CLIError as exc:
        if "already exists" not in str(exc).lower():
            raise

    _wait_for_apps(model, app_list, wait_for_active=wait_for_active, timeout=timeout)


class AuthMethod(Enum):
    """Authentication method for Jenkins client generation."""

    TOKEN = "token"  # nosec: B105
    PASSWORD = "password"  # nosec: B105


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, max=60),
    reraise=True,
    stop=tenacity.stop_after_attempt(5),
)
def generate_jenkins_client(
    model: jubilant.Juju,
    jenkins_app: JujuApplication,
    address: str,
    method: AuthMethod = AuthMethod.TOKEN,
) -> jenkinsapi.jenkins.Jenkins:
    """Generate a Jenkins client using an API token or admin password."""
    jenkins_unit = jenkins_app.units[0]
    start = time.monotonic()
    current_unit_ips = get_model_unit_addresses(model=model, app_name=jenkins_app.name)
    requested_host = urlparse(address).hostname
    logger.info(
        "phase=generate_client app=%s unit=%s address=%s requested_host=%s resolved_ips=%s method=%s",
        jenkins_app.name,
        jenkins_unit,
        address,
        requested_host,
        current_unit_ips,
        method.value,
    )
    if requested_host and requested_host not in current_unit_ips:
        logger.warning(
            "phase=generate_client app=%s unit=%s stale_address_detected address_host=%s resolved_ips=%s",
            jenkins_app.name,
            jenkins_unit,
            requested_host,
            current_unit_ips,
        )

    if method == AuthMethod.TOKEN:
        secret = model.ssh(
            jenkins_unit,
            f"cat {jenkins.API_TOKEN_PATH}",
            container="jenkins",
        ).strip()
    elif method == AuthMethod.PASSWORD:
        action = model.run(jenkins_unit, "get-admin-password")
        logger.info(
            "phase=generate_client app=%s unit=%s auth_action=%s action_status=%s action_result_keys=%s",
            jenkins_app.name,
            jenkins_unit,
            "get-admin-password",
            action.status,
            sorted(action.results.keys()),
        )
        secret = action.results["password"]
    else:
        raise ValueError(f"Unsupported auth method: {method}")

    try:
        response = requests.get(f"{address}/login", timeout=10)
        logger.info(
            "phase=generate_client app=%s unit=%s login_probe_status=%s elapsed_s=%.2f",
            jenkins_app.name,
            jenkins_unit,
            response.status_code,
            time.monotonic() - start,
        )
    except requests.RequestException as exc:
        logger.warning(
            "phase=generate_client app=%s unit=%s login_probe_error=%s elapsed_s=%.2f",
            jenkins_app.name,
            jenkins_unit,
            repr(exc),
            time.monotonic() - start,
        )

    client = jenkinsapi.jenkins.Jenkins(address, "admin", secret, timeout=60)
    logger.info(
        "phase=generate_client app=%s unit=%s client_created=true elapsed_s=%.2f",
        jenkins_app.name,
        jenkins_unit,
        time.monotonic() - start,
    )
    return client


def generate_unit_web_client_from_application(
    model: jubilant.Juju,
    jenkins_app: JujuApplication,
) -> UnitWebClient:
    """Build a :class:`UnitWebClient` for a Jenkins application."""
    unit_ips = get_model_unit_addresses(model, jenkins_app.name)
    assert unit_ips, f"Unit IP address not found for {jenkins_app.name}"
    address = f"http://{unit_ips[0]}:8080"
    jenkins_client = generate_jenkins_client(model, jenkins_app, address)
    return UnitWebClient(
        model=model,
        unit=jenkins_app.units[0],
        web=address,
        client=jenkins_client,
    )


def get_job_invoked_unit(
    job: jenkins.jenkinsapi.job.Job,
    units: Iterable[str],
) -> str | None:
    """Return the Jenkins unit that ran the latest job."""
    invoked_agent = job.get_last_build().get_slave()
    for unit in units:
        if unit.replace("/", "-") == invoked_agent:
            return unit
    return None


def gen_test_pipeline_with_custom_script_xml(script: str) -> str:
    """Generate a job xml with custom pipeline script.

    Args:
        script: Custom pipeline script.

    Returns:
        The job XML.
    """
    return textwrap.dedent(f"""
        <flow-definition plugin="workflow-job@1385.vb_58b_86ea_fff1">
            <actions/>
            <description></description>
            <keepDependencies>false</keepDependencies>
            <properties/>
            <definition
                class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition"
                plugin="workflow-cps@3837.v305192405b_c0">
                <script>{script}</script>
                <sandbox>true</sandbox>
            </definition>
            <triggers/>
            <disabled>false</disabled>
        </flow-definition>
        """)


def kubernetes_test_pipeline_script() -> str:
    """Generate a test pipeline script using the kubernetes plugin.

    Return:
        The pipeline script
    """
    return textwrap.dedent("""
        podTemplate(yaml: '''
            apiVersion: v1
            kind: Pod
            metadata:
            labels:
                some-label: some-label-value
            spec:
            containers:
            - name: busybox
              image: busybox
              imagePullPolicy: IfNotPresent
              command:
              - sleep
              args:
              - 99d
              tty: true
        ''') {
        node(POD_LABEL) {
            stage('Integration Test') {
            sh '''#!/bin/bash
                hostname
            '''
            }
        }
        }""")


def declarative_pipeline_script() -> str:
    """Generate a declarative pipeline script.

    Return:
        The pipeline script
    """
    return textwrap.dedent("""
        pipeline {
            agent any

            stages {
                stage('Integration Test') {
                    steps {
                        sh'''#!/bin/bash
                            echo "$(hostname) $(date) : Running in $(pwd)"
                        '''
                    }
                }
            }
        }""")


def create_secret_file_credentials(
    unit_web_client: UnitWebClient, kube_config: str
) -> typing.Optional[str]:
    """Use the jenkins client to create a new secretfile credential.

    plain-credentials plugin is required.

    Args:
        unit_web_client: Client for Jenkins's remote access API.
        kube_config: path to the kube_config file.

    Returns:
        The id of the created credential, or None in case of error.
    """
    url = f"{unit_web_client.web}/credentials/store/system/domain/_/createCredentials"
    credentials_id = f"kube-config-{secrets.token_hex(4)}"
    payload = {
        "json": f"""{{
            "": "4",
            "credentials": {{
                "file": "file0",
                "id": "{credentials_id}",
                "description": "Created by API",
                "stapler-class": "org.jenkinsci.plugins.plaincredentials.impl.FileCredentialsImpl",
                "$class": "org.jenkinsci.plugins.plaincredentials.impl.FileCredentialsImpl",
            }},
        }}"""
    }
    headers = {
        "Accept": "*/*",
    }

    with open(kube_config, "rb") as kube_config_file:
        files = [("file0", ("config", kube_config_file, "application/octet-stream"))]
        logger.debug("Creating jenkins credentials, params: %s %s %s", headers, files, payload)
        res = unit_web_client.client.requester.post_url(
            url=url, headers=headers, data=payload, files=files, timeout=30
        )
        logger.debug("Credential created, %s", res.status_code)
        return credentials_id if res.status_code == 200 else None


def create_kubernetes_cloud(
    unit_web_client: UnitWebClient, kube_config_credentials_id: str
) -> typing.Optional[str]:
    """Use the Jenkins client to add a Kubernetes cloud.

    For dynamic agent provisioning through pods.

    Args:
        unit_web_client: Client for Jenkins's remote access API.
        kube_config_credentials_id: credential id stored in jenkins.

    Returns:
        The created kubernetes cloud name or None in case of error.
    """
    kubernetes_test_cloud_name = "kubernetes"

    url = f"{unit_web_client.web}/manage/cloud/doCreate"

    payload = {
        "name": kubernetes_test_cloud_name,
        "cloudDescriptorName": "org.csanchez.jenkins.plugins.kubernetes.KubernetesCloud",
        "json": f"""
        {{
            "name": "{kubernetes_test_cloud_name}",
            "credentialsId": "{kube_config_credentials_id}",
            "jenkinsUrl": "{unit_web_client.web}",
            "type": "org.csanchez.jenkins.plugins.kubernetes.KubernetesCloud",
            "webSocket":true,
            "connectTimeout": "300",
            "Submit": "",
        }}""",
        "webSocket": True,
        "Submit": '""',
    }
    accept_header = (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,"
        "image/webp,"
        "image/apng,"
        "*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    )
    headers = {
        "Accept": accept_header,
    }

    logger.debug("Creating jenkins kubernetes cloud, params: %s %s", headers, payload)
    res = unit_web_client.client.requester.post_url(
        url=url, headers=headers, data=payload, timeout=60 * 5
    )
    logger.debug("Cloud created, status=%s body=%s", res.status_code, res.text)

    return kubernetes_test_cloud_name if res.status_code == 200 else None
