# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model" {
  description = "Reference to the Juju model to deploy the jenkins-k8s and jenkins-agent-k8s operators."
  type        = string
}

variable "jenkins_agent_k8s" {
  type = object({
    app_name    = optional(string, "jenkins-agent-k8s")
    channel     = optional(string, "latest/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
    units       = optional(number, 3)
  })
}

variable "jenkins_k8s" {
  type = object({
    app_name    = optional(string, "jenkins-k8s")
    channel     = optional(string, "latest/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
  })
}
