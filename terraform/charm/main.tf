# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  # Map the typed config object attributes onto their charmcraft.yaml option
  # names, then drop any attribute left unset so the charm-provided default
  # applies instead of overriding it with an empty value.
  config = {
    for key, value in {
      "restart-time-range"           = var.config.restart_time_range
      "allowed-plugins"              = var.config.allowed_plugins
      "system-properties"            = var.config.system_properties
      "jcasc-config"                 = var.config.jcasc_config
      "jcasc-repository"             = var.config.jcasc_repository
      "jcasc-repository-token"       = var.config.jcasc_repository_token
      "jcasc-repository-config-path" = var.config.jcasc_repository_config_path
      "jcasc-repository-branch"      = var.config.jcasc_repository_branch
      "jcasc-environment-secrets"    = var.config.jcasc_environment_secrets
    } : key => value if value != null
  }
}

resource "juju_application" "jenkins_k8s" {
  name  = var.app_name
  model = var.model

  charm {
    name     = "jenkins-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  config      = local.config
  constraints = var.constraints
  units       = 1
}
