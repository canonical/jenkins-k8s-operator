# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.jenkins_k8s.name
}

output "requires" {
  value = {
    agent                   = "agent"
    ingress                 = "ingress"
    agent_discovery_ingress = "agent-discovery-ingress"
    auth_proxy              = "auth-proxy"
    logging                 = "loki_push_api"
  }
}

output "provides" {
  value = {
    metrics_endpoint  = "prometheus_scrape"
    grafana_dashboard = "grafana_dashboard"
  }
}
