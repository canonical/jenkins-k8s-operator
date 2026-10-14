# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variables {
  app_name   = "jenkins-k8s"
  base       = "ubuntu@24.04"
  channel    = "latest/edge"
  config     = {}
  model_uuid = "00000000-0000-0000-0000-000000000001"
  revision   = 10
  units      = 1
}

mock_provider "juju" {
  mock_resource "juju_application" {
    defaults = {
      id = "jenkins-k8s"
    }
  }
}

run "deploys_application" {
  command = plan

  assert {
    condition     = output.application.name == "jenkins-k8s"
    error_message = "application name did not match"
  }

  assert {
    condition     = output.application.model_uuid == var.model_uuid
    error_message = "application model_uuid did not match"
  }

  assert {
    condition     = output.application.charm[0].name == "jenkins-k8s"
    error_message = "application charm name did not match"
  }

  assert {
    condition     = output.provides["metrics_endpoint"].kind == "endpoint"
    error_message = "metrics_endpoint kind did not match"
  }

  assert {
    condition     = output.provides["metrics_endpoint"].name == "jenkins-k8s"
    error_message = "metrics_endpoint name did not match"
  }

  assert {
    condition     = output.provides["metrics_endpoint"].endpoint == "metrics-endpoint"
    error_message = "metrics_endpoint endpoint did not match"
  }

  assert {
    condition     = output.provides["grafana_dashboard"].endpoint == "grafana-dashboard"
    error_message = "grafana_dashboard endpoint did not match"
  }

  assert {
    condition     = output.requires.agent.endpoint == "agent"
    error_message = "agent endpoint did not match"
  }

  assert {
    condition     = output.requires.ingress.endpoint == "ingress"
    error_message = "ingress endpoint did not match"
  }

  assert {
    condition     = output.requires.agent_discovery_ingress.endpoint == "agent-discovery-ingress"
    error_message = "agent_discovery_ingress endpoint did not match"
  }

  assert {
    condition     = output.requires.haproxy_route.endpoint == "haproxy-route"
    error_message = "haproxy_route endpoint did not match"
  }

  assert {
    condition     = output.requires.logging.endpoint == "logging"
    error_message = "logging endpoint did not match"
  }
}
