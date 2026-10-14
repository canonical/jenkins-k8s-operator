# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variables {
  model_uuid = "00000000-0000-0000-0000-000000000002"
}

mock_provider "juju" {
  mock_resource "juju_application" {
    defaults = {
      id = "mock-application"
    }
  }
}

run "default_product_contract" {
  command = plan

  assert {
    condition     = module.jenkins_k8s.application.charm[0].channel == "latest/stable"
    error_message = "jenkins-k8s must default to the latest/stable channel when risk is stable."
  }

  assert {
    condition     = juju_application.jenkins_agent_k8s.name == "jenkins-agent-k8s"
    error_message = "jenkins-agent-k8s app name did not match"
  }

  assert {
    condition     = juju_application.jenkins_agent_k8s.charm[0].channel == "latest/stable"
    error_message = "jenkins-agent-k8s must default to the latest/stable channel when risk is stable."
  }

  assert {
    condition     = output.metadata.version == "1.0.0"
    error_message = "metadata.version did not match"
  }

  assert {
    condition     = output.models.jenkins.model_uuid == var.model_uuid
    error_message = "models.jenkins.model_uuid did not match"
  }
}

run "risk_edge_derives_default_channel" {
  command = plan

  variables {
    risk = "edge"
  }

  assert {
    condition     = module.jenkins_k8s.application.charm[0].channel == "latest/edge"
    error_message = "jenkins-k8s must derive latest/edge from risk=edge"
  }

  assert {
    condition     = juju_application.jenkins_agent_k8s.charm[0].channel == "latest/edge"
    error_message = "jenkins-agent-k8s must derive latest/edge from risk=edge"
  }
}

run "explicit_channel_overrides_risk" {
  command = plan

  variables {
    risk = "edge"
    jenkins_k8s = {
      channel = "2/stable"
    }
    jenkins_agent_k8s = {
      channel = "2/stable"
    }
  }

  assert {
    condition     = module.jenkins_k8s.application.charm[0].channel == "2/stable"
    error_message = "an explicit jenkins_k8s.channel must take precedence over risk"
  }

  assert {
    condition     = juju_application.jenkins_agent_k8s.charm[0].channel == "2/stable"
    error_message = "an explicit jenkins_agent_k8s.channel must take precedence over risk"
  }
}

run "reject_invalid_risk" {
  command = plan

  variables {
    risk = "beta"
  }

  expect_failures = [var.risk]
}
