<!-- vale Canonical.007-Headings-sentence-case = NO -->
# Jenkins-k8s Terraform module
<!-- vale Canonical.007-Headings-sentence-case = YES -->

This folder contains a base [Terraform](https://developer.hashicorp.com/terraform) module for the
Jenkins-k8s charm.

The module uses the 
[Terraform Juju provider](https://registry.terraform.io/providers/juju/juju/latest/docs) to model 
the charm deployment onto any Kubernetes environment managed by [Juju](http://juju.is/).

## Module structure

- **main.tf** - Defines the Juju application to be deployed.
- **variables.tf** - Allows customization of the deployment. Also models the charm configuration, 
  except for exposing the deployment options (Juju model UUID, channel or application name).
- **outputs.tf** - Integrates the module with other Terraform modules, primarily
  by defining potential integration endpoints (charm integrations), but also by exposing
  the deployed Juju application.
- **terraform.tf** - Defines the Terraform provider version.

## Using `jenkins-k8s` base module in higher level modules

If you want to use `jenkins-k8s` base module as part of your Terraform module, import it
like shown below:

```text
data "juju_model" "my_model" {
  name = "my-model"
}

module "jenkins-k8s" {
  source = "git::https://github.com/canonical/jenkins-k8s-operator//terraform/charm?ref=tf-1.0.0"

  model_uuid = data.juju_model.my_model.uuid

  # Charm configuration options (all optional; unset options keep charm defaults).
  # The config map keys match the charm configuration option names in charmcraft.yaml.
  # config = {
  #   "allowed-plugins"      = "git,kubernetes,ldap"
  #   "system-properties"    = "jenkins.model.Jenkins.crumbIssuerProxyCompatibility=true"
  #   "jcasc-repository"     = "https://github.com/my-org/my-jcasc"
  #   "external-agent-nodes" = "external-agent-0,external-agent-1"
  # }
}
```

The `jcasc-repository-token` and `jcasc-environment-secrets` options take a Juju
user-secret URI. See
[the configurations tab](https://charmhub.io/jenkins-k8s/configurations) for
option semantics and defaults.

Create integrations, for instance:

```text
resource "juju_integration" "jenkins-k8s-agent-agent-v0" {
  model_uuid = data.juju_model.my_model.uuid
  application {
    name     = module.jenkins-k8s.requires.agent.name
    endpoint = module.jenkins-k8s.requires.agent.endpoint
  }
  application {
    name     = "jenkins-agent-k8s"
    endpoint = "agent"
  }
}
```

The complete list of available integrations can be found [in the Integrations tab][jenkins-k8s-integrations].

[Terraform]: https://www.terraform.io/
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://juju.is
[jenkins-k8s-integrations]: https://charmhub.io/jenkins-k8s/integrations

<!-- BEGIN_TF_DOCS -->
<!-- END_TF_DOCS -->
