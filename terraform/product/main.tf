# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

data "juju_model" "jenkins_k8s" {
  name = var.model
}

module "jenkins_k8s" {
  source      = "../charm"
  app_name    = var.jenkins_k8s.app_name
  channel     = var.jenkins_k8s.channel
  config      = var.jenkins_k8s.config
  constraints = var.jenkins_k8s.constraints
  model       = var.model
  revision    = var.jenkins_k8s.revision
  base        = var.jenkins_k8s.base
}

module "jenkins_agent_k8s" {
  source      = "git::https://github.com/canonical/jenkins-agent-k8s-operator//terraform/charm"
  app_name    = var.jenkins_agent_k8s.app_name
  channel     = var.jenkins_agent_k8s.channel
  config      = var.jenkins_agent_k8s.config
  constraints = var.jenkins_agent_k8s.constraints
  model       = var.model
  revision    = var.jenkins_agent_k8s.revision
  base        = var.jenkins_agent_k8s.base
  units       = var.jenkins_agent_k8s.units
}

resource "juju_integration" "jenkins_k8s_jenkins_agent_k8s_agent" {
  model = var.model

  application {
    name     = module.jenkins_k8s.app_name
    endpoint = module.jenkins_k8s.requires.agent
  }

  application {
    name     = module.jenkins_agent_k8s.app_name
    endpoint = module.jenkins_agent_k8s.provides.agent
  }
}
