# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "jenkins_k8s" {
  name  = var.app_name
  model = var.model

  charm {
    name     = "jenkins-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  config      = var.config
  constraints = var.constraints
  units       = 1
}
