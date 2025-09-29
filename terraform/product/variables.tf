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

variable "public_ingress" {
  type = object({
    app_name = optional(string, "public-traefik-k8s")
    channel  = optional(string, "latest/edge")
    config = optional(map(string), {
      "enable_experimental_forward_auth" : "true",
      "external_hostname" : ""
    })
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@20.04")
  })
}

variable "agent_discovery_ingress" {
  type = object({
    app_name    = optional(string, "agent-discovery-traefik-k8s")
    channel     = optional(string, "latest/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@20.04")
  })
}

variable "oauth2_proxy" {
  type = object({
    app_name    = optional(string, "oauth2-proxy-k8s")
    channel     = optional(string, "latest/edge")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@22.04")
  })
}

variable "httprequest_lego_k8s" {
  type = object({
    app_name = optional(string, "httprequest-lego-k8s")
    channel  = optional(string, "latest/edge")
    config = optional(map(string), {
      "email" : "",
      "httpreq_endpoint" : "",
      "httpreq_http_timeout" : "180",
      "httpreq_password" : "",
      "httpreq_propagation_timeout" : "600"
      "httpreq_username" : ""
    })
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
  })
}

variable "self_signed_ceritificates" {
  type = object({
    app_name    = optional(string, "self-signed-certificates")
    channel     = optional(string, "1/stable")
    config      = optional(map(string), {})
    constraints = optional(string, "")
    revision    = optional(number)
    base        = optional(string, "ubuntu@24.04")
  })
}

variable "use_httprequest_lego_k8s_certificates" {
  type        = bool
  default     = false
  description = <<EOT
  Whether to use httprequest lego k8s to receive ceritificates.
  Uses self-signed-certificates by default otherwise.
  EOT
}
