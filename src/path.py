# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Paths used by Jenkins."""

from pathlib import Path

JENKINS_HOME = Path("/var/lib/jenkins")
# Path to initial admin password file
INITIAL_PASSWORD = JENKINS_HOME / Path("secrets/initialAdminPassword")
# Path to last executed jenkins version file, required to override wizard installation
LAST_EXEC = JENKINS_HOME / Path("jenkins.install.InstallUtil.lastExecVersion")
# Path to jenkins version file, required to override wizard installation
UPDATE_VERSION = JENKINS_HOME / Path("jenkins.install.UpgradeWizard.state")
