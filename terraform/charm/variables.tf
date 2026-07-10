# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "jenkins-k8s"
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "latest/stable"
}

variable "config" {
  description = <<-EOT
    Application configuration options for the jenkins-k8s charm. Each attribute
    maps to a charm config option defined in charmcraft.yaml. Unset attributes
    fall back to the charm-provided default.

    Details about available options can be found at
    https://charmhub.io/jenkins-k8s/configurations

    - restart_time_range: Preferred UTC time range in 24 hour format for
      restarting Jenkins (e.g. "03-05"). If empty, restart happens whenever
      Jenkins needs to restart.
    - allowed_plugins: Comma-separated list of allowed plugin short names. If
      empty, any plugin can be installed.
    - system_properties: Comma-separated JVM system properties (key=value,
      without the -D prefix) passed to the Jenkins process at startup.
    - jcasc_config: Jenkins Configuration as Code (JCasC) YAML content. Mutually
      exclusive with jcasc_repository.
    - jcasc_repository: HTTPS URL of a public git repository containing JCasC
      YAML files. Mutually exclusive with jcasc_config.
    - jcasc_repository_token: A Juju user-secret URI granting access to a private
      jcasc_repository. The secret must contain `username` and `token` keys.
    - jcasc_repository_config_path: Path to the directory within
      jcasc_repository containing YAML files. Defaults to "jcasc".
    - jcasc_repository_branch: Git branch to check out when cloning
      jcasc_repository. Defaults to "main".
    - jcasc_environment_secrets: A Juju user-secret URI containing key-value
      pairs to inject as environment variables for JCasC interpolation.
  EOT
  type = object({
    restart_time_range           = optional(string)
    allowed_plugins              = optional(string)
    system_properties            = optional(string)
    jcasc_config                 = optional(string)
    jcasc_repository             = optional(string)
    jcasc_repository_token       = optional(string)
    jcasc_repository_config_path = optional(string)
    jcasc_repository_branch      = optional(string)
    jcasc_environment_secrets    = optional(string)
  })
  default = {}
}

variable "constraints" {
  description = "Juju constraints to apply for this application."
  type        = string
  default     = ""
}

variable "model" {
  description = "Reference to a `juju_model`."
  type        = string
  default     = ""
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
}

variable "base" {
  description = "The operating system on which to deploy"
  type        = string
  default     = "ubuntu@24.04"
}
