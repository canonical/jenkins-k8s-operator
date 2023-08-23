#!/usr/bin/env python3

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
import typing

import ops

import agent
import jenkins
import status
import timerange
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
        container = self.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            event.defer()
            return
        credentials = jenkins.get_admin_credentials(container)
        event.set_results({"password": credentials.password})

    def _remove_unlisted_plugins(self, container: ops.Container) -> ops.StatusBase:
        """Remove plugins that are installed but not allowed.

        Args:
            container: The jenkins workload container.

        Returns:
            The unit status of the charm after the operation.
        """
        original_status = self.unit.status.name
        try:
            jenkins.remove_unlisted_plugins(plugins=self.state.plugins, container=container)
        except (jenkins.JenkinsPluginError, jenkins.JenkinsError) as exc:
            logger.error("Failed to remove unlisted plugin, %s", exc)
            return ops.StatusBase.from_name(original_status, "Failed to remove unlisted plugin.")
        except TimeoutError as exc:
            logger.error("Failed to restart jenkins after removing plugin, %s", exc)
            return ops.BlockedStatus("Failed to restart Jenkins after removing plugins")
        return ops.ActiveStatus()

    def _update_jenkins_version(self, container: ops.Container) -> ops.StatusBase:
        """Update Jenkins patch version if available.

        The update will only take place if the current time is within the restart-time-range config
        value.

        Args:
            container: The Jenkins workload container.

        Returns:
            The unit status of the charm after the operation.
        """
        original_status = self.unit.status.name
        self.unit.status = ops.StatusBase.from_name(original_status, "Checking for updates.")
        try:
            if not jenkins.has_updates_for_lts():
                return ops.StatusBase.from_name(original_status, "")
        except jenkins.JenkinsUpdateError as exc:
            logger.error("Failed to get Jenkins updates, %s", exc)
            return ops.StatusBase.from_name(
                original_status, "Failed to get Jenkins patch version."
            )

        self.unit.status = ops.MaintenanceStatus("Updating Jenkins.")
        try:
            updated_version = jenkins.update_jenkins(
                container=container, proxy=self.state.proxy_config
            )
        except jenkins.JenkinsUpdateError as exc:
            logger.error("Failed to fetch required Jenkins update data, %s", exc)
            return ops.StatusBase.from_name(original_status, "Failed to get update data.")
        except jenkins.JenkinsRestartError as exc:
            logger.error("Failed to safely restart Jenkins. %s", exc)
            return ops.BlockedStatus("Update restart failed.")

        self.unit.set_workload_version(updated_version)
        return ops.ActiveStatus()

    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Handle update status event.

        On Update status:
        1. Remove plugins that are installed but are not allowed by plugins config value.
        2. Update Jenkins patch version if available and is within restart-time-range config value.
        """
        container = self.unit.get_container(self.state.jenkins_service_name)
        if not container.can_connect():
            return

        if self.state.restart_time_range and not timerange.check_now_within_bound_hours(
            self.state.restart_time_range.start, self.state.restart_time_range.end
        ):
            return

        self.unit.status = status.get_priority_status(
            (
                self._remove_unlisted_plugins(container=container),
                self._update_jenkins_version(container=container),
            )
        )


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
