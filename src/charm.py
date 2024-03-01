#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

import logging
import typing

import ops

import actions
import agent
import auth_proxy
import cos
import ingress
import jenkins
import state
import timerange
from state import (
    JENKINS_SERVICE_NAME,
    CharmConfigInvalidError,
    CharmIllegalNumUnitsError,
    CharmRelationDataInvalidError,
    State,
)

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
        except (CharmConfigInvalidError, CharmIllegalNumUnitsError) as exc:
            self.unit.status = ops.BlockedStatus(exc.msg)
            return
        except CharmRelationDataInvalidError as exc:
            raise RuntimeError("Invalid relation data received.") from exc

        self.actions_observer = actions.Observer(self, self.state)
        self.agent_observer = agent.Observer(self, self.state)
        self.cos_observer = cos.Observer(self)
        self.ingress_observer = ingress.Observer(self)
        self.auth_proxy_observer = auth_proxy.Observer(self, self.ingress_observer.ingress)
        self.framework.observe(
            self.on.jenkins_home_storage_attached, self._on_jenkins_home_storage_attached
        )
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
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
                JENKINS_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "jenkins",
                    "command": f"java -D{jenkins.SYSTEM_PROPERTY_HEADLESS} "
                    f"-D{jenkins.SYSTEM_PROPERTY_LOGGING} "
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

    def calculate_env(self) -> jenkins.Environment:
        """Return a dictionary for Jenkins Pebble layer.

        Returns:
            The dictionary mapping of environment variables for the Jenkins service.
        """
        prefix = "/"
        if self.auth_proxy_observer.has_relation_data():
            prefix = f"/{self.model.name}-{self.model.app.name}"
        return jenkins.Environment(
            JENKINS_HOME=str(state.JENKINS_HOME_PATH), JENKINS_PREFIX=prefix
        )

    def _on_jenkins_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Configure and start Jenkins server.

        Args:
            event: The event fired when pebble is ready.

        Raises:
            TimeoutError: if there was an error waiting for Jenkins service to come up.
            JenkinsBootstrapError: if there was an error installing Jenkins.
            JenkinsError: if there was an error fetching Jenkins version.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            self.unit.status = ops.WaitingStatus("Waiting for container/storage.")
            event.defer()  # Jenkins installation should be retried until preconditions are met.
            return

        self.unit.status = ops.MaintenanceStatus("Installing Jenkins.")
        # First Jenkins server start installs Jenkins server.
        container.add_layer(
            "jenkins",
            self._get_pebble_layer(self.calculate_env()),
            combine=True,
        )
        container.replan()
        try:
            jenkins.wait_ready()
            self.unit.status = ops.MaintenanceStatus("Configuring Jenkins.")
            if self.auth_proxy_observer.has_relation_data():
                jenkins.bootstrap(
                    container, jenkins.AUTH_PROXY_JENKINS_CONFIG, self.state.proxy_config
                )
            else:
                jenkins.bootstrap(
                    container, jenkins.DEFAULT_JENKINS_CONFIG, self.state.proxy_config
                )
            # Second Jenkins server start restarts Jenkins to bypass Wizard setup.
            container.restart(JENKINS_SERVICE_NAME)
            jenkins.wait_ready()
        except TimeoutError as exc:
            logger.error("Timed out waiting for Jenkins, %s", exc)
            raise
        except jenkins.JenkinsBootstrapError as exc:
            logger.error("Error installing plugins, %s", exc)
            raise

        try:
            version = jenkins.get_version()
        except jenkins.JenkinsError as exc:
            logger.error("Failed to get Jenkins version, %s", exc)
            raise

        self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

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
            logger.error("Failed to remove plugins, %s", exc)
            return ops.BlockedStatus("Failed to remove plugins.")
        return ops.ActiveStatus()

    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Handle update status event.

        On Update status:
        1. Remove plugins that are installed but are not allowed by plugins config value.
        2. Update Jenkins patch version if available and is within restart-time-range config value.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            self.unit.status = ops.WaitingStatus("Waiting for container/storage.")
            return

        if self.state.restart_time_range and not timerange.check_now_within_bound_hours(
            self.state.restart_time_range.start, self.state.restart_time_range.end
        ):
            return

        self.unit.status = self._remove_unlisted_plugins(container=container)

    def _on_jenkins_home_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
        """Correctly set permission when storage is attached.

        Args:
            event: The event fired when the storage is attached.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for pebble.")
            # This event should be handled again once the container becomes available.
            event.defer()
            return

        command = [
            "chown",
            "-R",
            f"{jenkins.USER}:{jenkins.GROUP}",
            str(event.storage.location.resolve()),
        ]

        container.exec(
            command,
            timeout=120,
        ).wait()


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
