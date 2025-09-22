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
