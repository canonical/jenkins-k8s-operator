# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins charm actions."""
import logging

import ops

import jenkins

logger = logging.getLogger(__name__)

JENKINS_HOME_STORAGE_NAME = "jenkins-home"


class Reconciler(ops.Object):
    """Jenkins storage observer.

    Attributes:
        storage_path: the Jenkins home mounted storage path.
    """

    def __init__(self, charm: ops.CharmBase):
        """Initialize the observer.

        Args:
            charm: The Jenkins k8s charm to attach the observer to.
        """
        super().__init__(charm, "storage-observer")

    @property
    def storage_path(self) -> str | None:
        """The Jenkins home mounted storage path."""
        container_meta = self.framework.meta.containers["jenkins"]
        return container_meta.mounts["jenkins-home"].location

    def is_storage_ready(self) -> bool:
        """Check if storage is mounted and ready for operations.

        Returns:
            Whether the Jenkins storage is mounted.
        """
        return JENKINS_HOME_STORAGE_NAME in self.model.storages

    def reconcile_storage(self, *, container: ops.Container) -> None:
        """Reconcile Jenkins home path from storage.

        The Jenkins storage is expected to be mounted and the workload container is expected to be
        up and running.

        Args:
            container: Active Jenkins workload container.
        """
        logger.info("Reconciling storage")

        command = [
            "chown",
            "-R",
            f"{jenkins.USER}:{jenkins.GROUP}",
            str(self.storage_path),
        ]
        container.exec(
            command,
            timeout=120,
        ).wait()
