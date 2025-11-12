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

resource "null_resource" "wait_for_jenkins_up" {
  provisioner "local-exec" {
    command = "juju wait-for application ${module.jenkins_k8s.app_name}"
  }
}


resource "juju_application" "public_ingress" {
  name  = var.public_ingress.app_name
  model = var.model

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
  model = var.model

  depends_on = [null_resource.wait_for_jenkins_up]

  application {
    name     = module.jenkins_k8s.app_name
    endpoint = module.jenkins_k8s.requires.ingress
  }

  application {
    name     = juju_application.public_ingress.name
    endpoint = "ingress"
  }
}

resource "juju_application" "agent_discovery_ingress" {
  name  = var.agent_discovery_ingress.app_name
  model = var.model

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
  model = var.model

  depends_on = [null_resource.wait_for_jenkins_up]

  application {
    name     = module.jenkins_k8s.app_name
    endpoint = module.jenkins_k8s.requires.agent_discovery_ingress
  }
  application {
    name     = juju_application.agent_discovery_ingress.name
    endpoint = "ingress"
  }
}

resource "juju_application" "oauth2_proxy_k8s" {
  name  = var.oauth2_proxy.app_name
  model = var.model

  charm {
    name     = "oauth2-proxy-k8s"
    channel  = var.oauth2_proxy.channel
    revision = var.oauth2_proxy.revision
    base     = var.oauth2_proxy.base
  }

  config      = var.oauth2_proxy.config
  constraints = var.oauth2_proxy.constraints
  units       = 1
}

resource "juju_integration" "jenkins_k8s_oauth2_proxy_k8s" {
  model = var.model

  depends_on = [null_resource.wait_for_jenkins_up]

  application {
    name     = module.jenkins_k8s.app_name
    endpoint = module.jenkins_k8s.requires.auth_proxy
  }
  application {
    name     = juju_application.oauth2_proxy_k8s.name
    endpoint = "auth-proxy"
  }
}

resource "juju_integration" "public_ingress_oauth2_proxy_k8s" {
  model = var.model
  application {
    name     = juju_application.public_ingress.name
    endpoint = "ingress"
  }
  application {
    name     = juju_application.oauth2_proxy_k8s.name
    endpoint = "ingress"
  }
}

resource "juju_integration" "jenkins_k8s_jenkins_agent_k8s_agent" {
  model = var.model

  depends_on = [null_resource.wait_for_jenkins_up, null_resource.wait_for_certs_settle]

  application {
    name     = module.jenkins_k8s.app_name
    endpoint = module.jenkins_k8s.requires.agent
  }

  application {
    name     = module.jenkins_agent_k8s.app_name
    endpoint = module.jenkins_agent_k8s.provides.agent
  }
}
