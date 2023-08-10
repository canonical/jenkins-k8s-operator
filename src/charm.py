#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
import typing

import ops

import agent
import jenkins
from state import CharmConfigInvalidError, CharmRelationDataInvalidError, State

if typing.TYPE_CHECKING:
    from ops.pebble import LayerDict  # pragma: no cover


logger = logging.getLogger(__name__)


class JenkinsK8sOperatorCharm(ops.CharmBase):
    """Charm Jenkins."""

    def __init__(self, *args: typing.Any):
        """Initialize the charm and register event handlers.

        Args:
            args: Arguments to initialize the charm base.

        Raises:
            RuntimeError: if invalid state value was encountered from relation.
        """
        super().__init__(*args)
        try:
            self.state = State.from_charm(self)
        except CharmConfigInvalidError as exc:
            self.unit.status = ops.BlockedStatus(exc.msg)
            return
        except CharmRelationDataInvalidError as exc:
            raise RuntimeError("Invalid relation data received.") from exc

        self.agent_observer = agent.Observer(self, self.state)
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)
        self.framework.observe(self.on.update_status, self._on_update_status)

    @property
    def _jenkins_container(self) -> ops.Container:
        """The Jenkins workload container."""
        return self.unit.get_container(self.state.jenkins_service_name)

    def _get_pebble_layer(self, jenkins_env: jenkins.Environment) -> ops.pebble.Layer:
        """Return a dictionary representing a Pebble layer.

        Args:
            jenkins_env: Map of Jenkins environment variables.

        Returns:
            The pebble layer defining Jenkins service layer.
        """
        layer: LayerDict = {
            "summary": "jenkins layer",
            "description": "pebble config layer for jenkins",
            "services": {
                self.state.jenkins_service_name: {
                    "override": "replace",
                    "summary": "jenkins",
                    "command": f"java -D{jenkins.SYSTEM_PROPERTY_HEADLESS} "
                    f"-jar {jenkins.EXECUTABLES_PATH}/jenkins.war",
                    "startup": "enabled",
                    # TypedDict and Dict[str,str] are not compatible.
                    "environment": typing.cast(typing.Dict[str, str], jenkins_env),
                    "user": jenkins.USER,
                    "group": jenkins.GROUP,
                },
            },
            "checks": {
                "online": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": jenkins.LOGIN_URL},
                    "period": "30s",
                    "threshold": 5,
                }
            },
        }
        return ops.pebble.Layer(layer)

    def _on_jenkins_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure and start Jenkins server.

        Args:
            event: The event fired when pebble is ready.
        """
        container = event.workload
        if not container or not container.can_connect():
            event.defer()
            return

        self.unit.status = ops.MaintenanceStatus("Installing Jenkins.")
        # First Jenkins server start installs Jenkins server.
        container.add_layer(
            "jenkins",
            self._get_pebble_layer(jenkins.calculate_env()),
            combine=True,
        )
        container.replan()
        try:
            jenkins.wait_ready()
            self.unit.status = ops.MaintenanceStatus("Configuring Jenkins.")
            jenkins.bootstrap(container, self.state.proxy_config)
            # Second Jenkins server start restarts Jenkins to bypass Wizard setup.
            container.restart(self.state.jenkins_service_name)
            jenkins.wait_ready()
        except TimeoutError as exc:
            logger.error("Timed out waiting for Jenkins, %s", exc)
            self.unit.status = ops.BlockedStatus("Timed out waiting for Jenkins.")
            return
        except jenkins.JenkinsBootstrapError as exc:
            logger.error("Error installing plugins, %s", exc)
            self.unit.status = ops.BlockedStatus("Error installling plugins.")
            return

        try:
            version = jenkins.get_version()
        except jenkins.JenkinsError as exc:
            logger.error("Failed to get Jenkins version, %s", exc)
            self.unit.status = ops.BlockedStatus("Failed to get Jenkins version.")
            return

        self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    def _on_get_admin_password(self, event: ops.ActionEvent) -> None:
        """Handle get-admin-password event.

        Args:
            event: The event fired from get-admin-password action.
        """
        if not self._jenkins_container.can_connect():
            event.defer()
            return
        credentials = jenkins.get_admin_credentials(self._jenkins_container)
        event.set_results({"password": credentials.password})

    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Handle update status event.

        On Update status:
        1. Update Jenkins patch LTS version if available.
        2. Update apt packages if available.
        """
        container = self.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            return

        err_info = ""
        try:
            jenkins.remove_unlisted_plugins(plugins=self.state.plugins, container=container)
        except (jenkins.JenkinsPluginError, jenkins.JenkinsError) as exc:
            logger.error("Failed to remove unlisted plugin, %s", exc)
            err_info = "Failed to remove unlisted plugin."

        if self.state.update_time_range and not self.state.update_time_range.check_now():
            return

        self.unit.status = ops.ActiveStatus("Checking for updates.")
        try:
            latest_patch_version = jenkins.get_updatable_version(proxy=self.state.proxy_config)
        except jenkins.JenkinsUpdateError as exc:
            logger.error("Failed to get Jenkins updates, %s", exc)
            self.unit.status = ops.ActiveStatus("Failed to get Jenkins patch version.")
            return

        if not latest_patch_version:
            self.unit.status = ops.ActiveStatus()
            return

        self.unit.status = ops.MaintenanceStatus("Updating Jenkins.")
        try:
            jenkins.download_stable_war(container, latest_patch_version)
        except jenkins.JenkinsNetworkError as exc:
            logger.error("Failed to download Jenkins war. %s", exc)
            self.unit.status = ops.ActiveStatus("Failed to download executable.")
            return
        try:
            jenkins.safe_restart(container)
            jenkins.wait_ready()
        except (jenkins.JenkinsError, TimeoutError) as exc:
            logger.error("Failed to safely restart Jenkins. %s", exc)
            self.unit.status = ops.BlockedStatus("Update restart failed.")
            return

        self.unit.set_workload_version(latest_patch_version)
        self.unit.status = ops.ActiveStatus(err_info)


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
