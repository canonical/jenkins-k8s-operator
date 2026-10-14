# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "agent_discovery_ingress" {
  description = "Deployment options for the agent-discovery traefik-k8s ingress charm."
  type = object({
    app_name    = optional(string, "agent-discovery-traefik-k8s")
    channel     = optional(string, "latest/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@20.04")
  })
  default = {}
}

variable "jenkins_agent_k8s" {
  description = "Deployment options for the jenkins-agent-k8s charm."
  type = object({
    app_name    = optional(string, "jenkins-agent-k8s")
    channel     = optional(string)
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 3)
  })
  default = {}
}

variable "jenkins_k8s" {
  description = "Deployment options for the jenkins-k8s charm."
  type = object({
    app_name    = optional(string, "jenkins-k8s")
    channel     = optional(string)
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 1)
  })
  default = {}
}

variable "model_uuid" {
  description = "UUID of the Juju model to deploy the jenkins-k8s solution to."
  type        = string
  nullable    = false
}

variable "public_ingress" {
  description = "Deployment options for the public traefik-k8s ingress charm."
  type = object({
    app_name = optional(string, "public-traefik-k8s")
    channel  = optional(string, "latest/edge")
    config = optional(map(string), {
      "external_hostname" : ""
    })
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@20.04")
  })
  default = {}
}

variable "risk" {
  description = <<-EOT
    Default channel risk used for the bundled jenkins-k8s and jenkins-agent-k8s
    charms when their own `channel` field is left unset; the resolved channel
    is "latest/<risk>". Does not affect the public-traefik-k8s or
    agent-discovery-traefik-k8s ingress charms, whose channels are pinned
    independently of this solution's risk level.
  EOT
  type        = string
  default     = "stable"
  nullable    = false

  validation {
    condition     = contains(["stable", "edge"], var.risk)
    error_message = "risk must be one of: stable, edge."
  }
}
