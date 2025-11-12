# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "jenkins_k8s_app_name" {
  description = "Name of the the deployed jenkins_k8s application."
  value       = module.jenkins_k8s.app_name
}

output "jenkins_agent_k8s_app_name" {
  description = "Name of the the deployed jenkins_agent_k8s application."
  value       = module.jenkins_agent_k8s.app_name
}

output "jenkins_k8s_requires" {
  value = {
    logging = "logging"
  }
}

output "jenkins_k8s_provides" {
  value = {
    grafana_dashboard = "grafana-dashboard"
    metrics_endpoint  = "metrics-endpoint"
  }
}

output "public_ingress_app_name" {
  value = juju_application.public_ingress.name
}

output "public_ingress_requires" {
  value = {
    certificates = "certificates"
    logging      = "logging"
  }
}

output "public_ingress_provides" {
  value = {
    grafana_dashboard = "grafana-dashboard"
    metrics_endpoint  = "metrics-endpoint"
  }
}
