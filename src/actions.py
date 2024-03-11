# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Jenkins charm actions."""

import ops

import jenkins
from state import JENKINS_SERVICE_NAME, State


class Observer(ops.Object):
    """Jenkins-k8s charm actions observer."""

    def __init__(self, charm: ops.CharmBase, state: State, jenkins_instance: jenkins.Jenkins):
        """Initialize the observer and register actions handlers.

        Args:
            charm: The parent charm to attach the observer to.
            state: The Jenkins charm state.
            jenkins_instance: The Jenkins wrapper.
        """
        super().__init__(charm, "actions-observer")
        self.charm = charm
        self.state = state
        self.jenkins = jenkins_instance

        charm.framework.observe(charm.on.get_admin_password_action, self.on_get_admin_password)
        charm.framework.observe(
            charm.on.rotate_credentials_action,
            self.on_rotate_credentials,
        )

    def on_get_admin_password(self, event: ops.ActionEvent) -> None:
        """Handle get-admin-password event.

        Args:
            event: The event fired from get-admin-password action.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            event.fail("Service not yet ready.")
            return
        credentials = jenkins.get_admin_credentials(container)
        event.set_results({"password": credentials.password_or_token})

    def on_rotate_credentials(self, event: ops.ActionEvent) -> None:
        """Invalidate all sessions and reset admin account password.

        Args:
            event: The rotate credentials event.
        """
        container = self.charm.unit.get_container(JENKINS_SERVICE_NAME)
        if not jenkins.is_storage_ready(container):
            event.fail("Service not yet ready.")
            return
        try:
            password = self.jenkins.rotate_credentials(container)
        except jenkins.JenkinsError:
            event.fail("Error invalidating user sessions. See logs.")
            return
        event.set_results({"password": password})
