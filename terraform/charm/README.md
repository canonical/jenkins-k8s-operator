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
  except for exposing the deployment options (Juju model name, channel or application name).
- **outputs.tf** - Integrates the module with other Terraform modules, primarily
  by defining potential integration endpoints (charm integrations), but also by exposing
  the Juju application name.
- **versions.tf** - Defines the Terraform provider version.

## Using `jenkins-k8s` base module in higher level modules

If you want to use `jenkins-k8s` base module as part of your Terraform module, import it
like shown below:

```text
data "juju_model" "my_model" {
  name = var.model
}

module "jenkins-k8s" {
  source = "git::https://github.com/canonical/jenkins-k8s-operator//terraform"

  model = juju_model.my_model.name

  # Charm configuration options (all optional; unset options keep charm defaults).
  # config = {
  #   allowed_plugins   = "git,kubernetes,ldap"
  #   system_properties = "jenkins.model.Jenkins.crumbIssuerProxyCompatibility=true"
  #   jcasc_repository  = "https://github.com/my-org/my-jcasc"
  #   external_agent_nodes = "external-agent-0,external-agent-1"
  # }
}
```

The `config` variable is a typed object whose attributes map directly to the
charm configuration options in `charmcraft.yaml`:

| Terraform attribute            | Charm config option            |
| ------------------------------ | ------------------------------ |
| `restart_time_range`           | `restart-time-range`           |
| `allowed_plugins`              | `allowed-plugins`              |
| `system_properties`            | `system-properties`            |
| `jcasc_config`                 | `jcasc-config`                 |
| `jcasc_repository`             | `jcasc-repository`             |
| `jcasc_repository_token`       | `jcasc-repository-token`       |
| `jcasc_repository_config_path` | `jcasc-repository-config-path` |
| `jcasc_repository_branch`      | `jcasc-repository-branch`      |
| `jcasc_environment_secrets`    | `jcasc-environment-secrets`    |
| `external_agent_nodes`         | `external-agent-nodes`         |

The `jcasc_repository_token` and `jcasc_environment_secrets` options take a Juju
user-secret URI. See
[the configurations tab](https://charmhub.io/jenkins-k8s/configurations) for
option semantics and defaults.

Create integrations, for instance:

```text
resource "juju_integration" "jenkins-k8s-agent-agent-v0" {
  model = juju_model.my_model.name
  application {
    name     = module.jenkins_k8s.app_name
    endpoint = module.jenkins_k8s.requires.jenkins_agent_v0
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
