#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Jenkins."""

# pylint: disable=too-many-instance-attributes

import logging
import typing

import ops

import actions
import agent
import auth_proxy
import cos
import ingress
import jenkins
import pebble
import timerange
from state import (
    JENKINS_SERVICE_NAME,
    CharmConfigInvalidError,
    CharmIllegalNumUnitsError,
    CharmRelationDataInvalidError,
    State,
)

AGENT_DISCOVERY_INGRESS_RELATION_NAME = "agent-discovery-ingress"
INGRESS_RELATION_NAME = "ingress"
logger = logging.getLogger(__name__)


class JenkinsK8sOperatorCharm(ops.CharmBase):
    """Charmed Jenkins."""

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

        # Ingress dedicated to agent discovery
        self.agent_discovery_ingress_observer = ingress.Observer(
            self, "agent-discovery-ingress-observer", AGENT_DISCOVERY_INGRESS_RELATION_NAME
        )
        self.ingress_observer = ingress.Observer(self, "ingress-observer", INGRESS_RELATION_NAME)
        self.jenkins = jenkins.Jenkins(self.calculate_env())
        self.actions_observer = actions.Observer(self, self.state, self.jenkins)
        self.agent_observer = agent.Observer(
            self, self.state, self.agent_discovery_ingress_observer, self.jenkins
        )
        self.cos_observer = cos.Observer(self)
        self.auth_proxy_observer = auth_proxy.Observer(
            self, self.ingress_observer.ingress, self.jenkins, self.state
        )
        self.framework.observe(
            self.on.jenkins_home_storage_attached, self._on_jenkins_home_storage_attached
        )
        self.framework.observe(self.on.jenkins_pebble_ready, self._on_jenkins_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._upgrade_charm)

    def calculate_env(self) -> jenkins.Environment:
        """Return a dictionary for Jenkins Pebble layer.

        Returns:
            The dictionary mapping of environment variables for the Jenkins service.
        """
        return jenkins.Environment(
            JENKINS_HOME=str(jenkins.JENKINS_HOME_PATH),
            JENKINS_PREFIX=self.ingress_observer.get_path(),
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
        pebble.replan_jenkins(container, self.jenkins, self.state)
        try:
            version = self.jenkins.version
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
            self.jenkins.remove_unlisted_plugins(plugins=self.state.plugins, container=container)
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
        self.jenkins_set_storage_config(event)

    def _upgrade_charm(self, event: ops.UpgradeCharmEvent) -> None:
        """Correctly set permissions when charm is upgraded.

        Args:
            event: The event fired when the charm is upgraded.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            self.jenkins_set_storage_config(event)
        # Update the agent discovery address.
        # Updating the secret is not required since it's calculated using the agent's node name.
        self.agent_observer.reconfigure_agent_discovery(event)

    def jenkins_set_storage_config(self, event: ops.framework.EventBase) -> None:
        """Correctly set permissions when storage is attached.

        Args:
            event: The event fired when the permission change is needed.
        """
        container = self.unit.get_container(JENKINS_SERVICE_NAME)
        container_meta = self.framework.meta.containers["jenkins"]
        storage_path = container_meta.mounts["jenkins-home"].location
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for pebble.")
            # This event should be handled again once the container becomes available.
            event.defer()
            return

        command = [
            "chown",
            "-R",
            f"{jenkins.USER}:{jenkins.GROUP}",
            str(storage_path),
        ]

        container.exec(
            command,
            timeout=120,
        ).wait()


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(JenkinsK8sOperatorCharm)
