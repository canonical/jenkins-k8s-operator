# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name of the application in the Juju model."
  type        = string
  default     = "jenkins-k8s"
  nullable    = false
}

variable "base" {
  description = "The operating system on which to deploy. E.g. ubuntu@24.04. If null, the charm's default base is used."
  type        = string
  default     = null
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "latest/stable"
  nullable    = false
}

variable "config" {
  description = <<-EOT
    Application configuration options for the jenkins-k8s charm, keyed by the
    charm config option name as defined in charmcraft.yaml. Unset keys fall
    back to the charm-provided default.

    Details about available options can be found at
    https://charmhub.io/jenkins-k8s/configurations

    - restart-time-range: Preferred UTC time range in 24 hour format for
      restarting Jenkins (e.g. "03-05"). If empty, restart happens whenever
      Jenkins needs to restart.
    - allowed-plugins: Comma-separated list of allowed plugin short names. If
      empty, any plugin can be installed.
    - system-properties: Comma-separated JVM system properties (key=value,
      without the -D prefix) passed to the Jenkins process at startup.
    - jcasc-config: Jenkins Configuration as Code (JCasC) YAML content. Mutually
      exclusive with jcasc-repository.
    - jcasc-repository: HTTPS URL of a public git repository containing JCasC
      YAML files. Mutually exclusive with jcasc-config.
    - jcasc-repository-token: A Juju user-secret URI granting access to a private
      jcasc-repository. The secret must contain `username` and `token` keys.
    - jcasc-repository-config-path: Path to the directory within
      jcasc-repository containing YAML files. Defaults to "jcasc".
    - jcasc-repository-branch: Git branch to check out when cloning
      jcasc-repository. Defaults to "main".
    - jcasc-environment-secrets: A Juju user-secret URI containing key-value
      pairs to inject as environment variables for JCasC interpolation.
    - external-agent-nodes: Comma-separated names of Jenkins nodes managed outside
      Juju and preserved during agent relation reconciliation.
  EOT
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Juju constraints to apply for this application."
  type        = string
  default     = null
}

variable "endpoint_bindings" {
  description = "Map for endpoint bindings."
  type = set(object({
    endpoint = optional(string)
    space    = string
  }))
  default = []
}

variable "expose" {
  description = "The expose block, restricting access to the application by CIDRs, endpoints or spaces. Defaults to exposed with no restrictions; pass `expose = null` to keep the application unexposed."
  type = object({
    cidrs     = optional(string)
    endpoints = optional(string)
    spaces    = optional(string)
  })
  default  = {}
  nullable = true
}

variable "model_uuid" {
  description = "UUID of the Juju model where the application will be deployed."
  type        = string
  nullable    = false
}

variable "resources" {
  description = "Resources to use with the application, keyed by resource name (e.g. jenkins-image)."
  type        = map(string)
  default     = {}
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
}

variable "storage_directives" {
  description = "Map of storage used by the application, keyed by storage name (e.g. jenkins-home)."
  type        = map(string)
  default     = {}
}

variable "units" {
  description = "Unit count/scale."
  type        = number
  default     = 1
}
