# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "basic_deploy" {
  variables {
    model_uuid = run.setup_tests.model_uuid
    base       = "ubuntu@24.04"
    channel    = "latest/edge"
    # renovate: depName="jenkins-k8s"
    revision = 360
  }

  assert {
    condition     = output.application.name == "jenkins-k8s"
    error_message = "jenkins-k8s application name did not match expected"
  }

  assert {
    condition     = output.provides.value.endpoint == "grafana-dashboard"
    error_message = "jenkins-k8s module should provide 'provides.value' output"
  }

  assert {
    condition     = output.provides.metrics_endpoint.endpoint == "metrics-endpoint"
    error_message = "jenkins-k8s module should provide 'provides.metrics_endpoint' output"
  }

  assert {
    condition     = output.requires.value.endpoint == "agent"
    error_message = "jenkins-k8s module should provide 'requires.value' output"
  }

  assert {
    condition     = output.requires.agent_discovery_ingress.endpoint == "agent-discovery-ingress"
    error_message = "jenkins-k8s module should provide 'requires.agent_discovery_ingress' output"
  }

  assert {
    condition     = output.requires.haproxy_route.endpoint == "haproxy-route"
    error_message = "jenkins-k8s module should provide 'requires.haproxy_route' output"
  }

  assert {
    condition     = output.requires.ingress.endpoint == "ingress"
    error_message = "jenkins-k8s module should provide 'requires.ingress' output"
  }

  assert {
    condition     = output.requires.logging.endpoint == "logging"
    error_message = "jenkins-k8s module should provide 'requires.logging' output"
  }
}
