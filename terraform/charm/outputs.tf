# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Full juju_application object for the deployed jenkins-k8s application."
  value       = juju_application.jenkins_k8s
}

output "provides" {
  description = "Map of the provided integration endpoints."
  value = {
    grafana_dashboard = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "grafana-dashboard"
    }
    metrics_endpoint = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "metrics-endpoint"
    }
  }
}

output "requires" {
  description = "Map of the required integration endpoints."
  value = {
    agent = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "agent"
    }
    agent_discovery_ingress = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "agent-discovery-ingress"
    }
    haproxy_route = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "haproxy-route"
    }
    ingress = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "ingress"
    }
    logging = {
      kind     = "endpoint"
      name     = juju_application.jenkins_k8s.name
      endpoint = "logging"
    }
  }
}
