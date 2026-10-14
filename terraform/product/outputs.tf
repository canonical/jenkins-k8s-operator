# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "jenkins_agent_k8s_app_name" {
  description = "Name of the the deployed jenkins_agent_k8s application."
  value       = juju_application.jenkins_agent_k8s.name
}

output "jenkins_k8s_app_name" {
  description = "Name of the the deployed jenkins_k8s application."
  value       = module.jenkins_k8s.application.name
}

output "jenkins_k8s_provides" {
  description = "Map of the jenkins-k8s endpoints provided by this product, not yet consumed internally."
  value = {
    grafana_dashboard = module.jenkins_k8s.provides.grafana_dashboard
    metrics_endpoint  = module.jenkins_k8s.provides.metrics_endpoint
  }
}

output "jenkins_k8s_requires" {
  description = "Map of the jenkins-k8s endpoints required by this product, not yet fulfilled internally."
  value = {
    logging = module.jenkins_k8s.requires.logging
  }
}

output "metadata" {
  description = "Metadata of the jenkins-k8s product deployment."
  value = {
    version     = "1.0.0"
    deployed_at = terraform_data.deployed_at.output
    updated_at  = timestamp()
  }
}

output "models" {
  description = "Map of the model key to the model UUID and the components deployed in it."
  value = {
    jenkins = {
      model_uuid = var.model_uuid
      components = {
        jenkins_k8s             = module.jenkins_k8s.application
        jenkins_agent_k8s       = juju_application.jenkins_agent_k8s
        public_ingress          = juju_application.public_ingress
        agent_discovery_ingress = juju_application.agent_discovery_ingress
      }
    }
  }
}

output "public_ingress_app_name" {
  description = "Name of the deployed public_ingress application."
  value       = juju_application.public_ingress.name
}

output "public_ingress_provides" {
  description = "Map of the public_ingress endpoints provided by this product, not yet consumed internally."
  value = {
    grafana_dashboard = "grafana-dashboard"
    metrics_endpoint  = "metrics-endpoint"
  }
}

output "public_ingress_requires" {
  description = "Map of the public_ingress endpoints required by this product, not yet fulfilled internally."
  value = {
    certificates = "certificates"
    logging      = "logging"
  }
}
