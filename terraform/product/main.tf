# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  jenkins_k8s_channel       = coalesce(var.jenkins_k8s.channel, "latest/${var.risk}")
  jenkins_agent_k8s_channel = coalesce(var.jenkins_agent_k8s.channel, "latest/${var.risk}")
}

module "jenkins_k8s" {
  source      = "../charm"
  app_name    = var.jenkins_k8s.app_name
  channel     = local.jenkins_k8s_channel
  config      = var.jenkins_k8s.config
  constraints = var.jenkins_k8s.constraints
  model_uuid  = var.model_uuid
  revision    = var.jenkins_k8s.revision
  base        = var.jenkins_k8s.base
  units       = var.jenkins_k8s.units
}

# jenkins-agent-k8s-operator's own terraform/charm module (pinned at rev55,
# the latest available tag at migration time) has not migrated to CC008 and
# still declares the juju_application `model` argument that was replaced by
# `model_uuid` in juju/juju provider 1.0.0 (required by this module's own
# terraform.tf per CC008). Composing that module here would therefore break
# at plan time for any provider version this module can declare. Deploy the
# jenkins-agent-k8s charm directly instead of through that module; see the
# final report for this deviation.
resource "juju_application" "jenkins_agent_k8s" {
  name       = var.jenkins_agent_k8s.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "jenkins-agent-k8s"
    channel  = local.jenkins_agent_k8s_channel
    revision = var.jenkins_agent_k8s.revision
    base     = var.jenkins_agent_k8s.base
  }

  config      = var.jenkins_agent_k8s.config
  constraints = var.jenkins_agent_k8s.constraints
  units       = var.jenkins_agent_k8s.units
}

resource "null_resource" "wait_for_jenkins_up" {
  provisioner "local-exec" {
    command = "juju wait-for application ${module.jenkins_k8s.application.name}"
  }
}

resource "juju_application" "public_ingress" {
  name       = var.public_ingress.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "traefik-k8s"
    channel  = var.public_ingress.channel
    revision = var.public_ingress.revision
    base     = var.public_ingress.base
  }

  config      = var.public_ingress.config
  constraints = var.public_ingress.constraints
  units       = 1

  trust = true
}

resource "juju_integration" "jenkins_k8s_public_ingress" {
  model_uuid = var.model_uuid

  depends_on = [null_resource.wait_for_jenkins_up]

  application {
    name     = module.jenkins_k8s.requires.ingress.name
    endpoint = module.jenkins_k8s.requires.ingress.endpoint
  }

  application {
    name     = juju_application.public_ingress.name
    endpoint = "ingress"
  }
}

resource "juju_application" "agent_discovery_ingress" {
  name       = var.agent_discovery_ingress.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "traefik-k8s"
    channel  = var.agent_discovery_ingress.channel
    revision = var.agent_discovery_ingress.revision
    base     = var.agent_discovery_ingress.base
  }

  config      = var.agent_discovery_ingress.config
  constraints = var.agent_discovery_ingress.constraints
  units       = 1

  trust = true
}

resource "juju_integration" "jenkins_k8s_agent_discovery_ingress" {
  model_uuid = var.model_uuid

  depends_on = [null_resource.wait_for_jenkins_up]

  application {
    name     = module.jenkins_k8s.requires.agent_discovery_ingress.name
    endpoint = module.jenkins_k8s.requires.agent_discovery_ingress.endpoint
  }
  application {
    name     = juju_application.agent_discovery_ingress.name
    endpoint = "ingress"
  }
}

resource "juju_integration" "jenkins_k8s_jenkins_agent_k8s_agent" {
  model_uuid = var.model_uuid

  depends_on = [null_resource.wait_for_jenkins_up]

  application {
    name     = module.jenkins_k8s.requires.agent.name
    endpoint = module.jenkins_k8s.requires.agent.endpoint
  }

  application {
    name     = juju_application.jenkins_agent_k8s.name
    endpoint = "agent"
  }
}

resource "terraform_data" "deployed_at" {
  input = timestamp()

  lifecycle {
    ignore_changes = [input]
  }
}
