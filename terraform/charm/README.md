<!-- vale Canonical.007-Headings-sentence-case = NO -->
# Jenkins-k8s Terraform module
<!-- vale Canonical.007-Headings-sentence-case = YES -->

This folder contains a base [Terraform](https://developer.hashicorp.com/terraform) module for the
Jenkins-k8s charm.

The module uses the 
[Terraform Juju provider](https://registry.terraform.io/providers/juju/juju/latest/docs) to model 
the charm deployment onto any Kubernetes environment managed by [Juju](https://canonical.com/juju).

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
[Juju]: https://canonical.com/juju
[jenkins-k8s-integrations]: https://charmhub.io/jenkins-k8s/integrations

<!-- vale off -->
<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.12 |
| <a name="requirement_juju"></a> [juju](#requirement\_juju) | ~> 2.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_juju"></a> [juju](#provider\_juju) | ~> 2.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [juju_application.jenkins_k8s](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | resource |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_app_name"></a> [app\_name](#input\_app\_name) | Name of the application in the Juju model. | `string` | `"jenkins-k8s"` | no |
| <a name="input_base"></a> [base](#input\_base) | The operating system on which to deploy. E.g. ubuntu@24.04. If null, the charm's default base is used. | `string` | `null` | no |
| <a name="input_channel"></a> [channel](#input\_channel) | The channel to use when deploying a charm. | `string` | `"latest/stable"` | no |
| <a name="input_config"></a> [config](#input\_config) | Application configuration options for the jenkins-k8s charm, keyed by the<br/>charm config option name as defined in charmcraft.yaml. Unset keys fall<br/>back to the charm-provided default.<br/><br/>Details about available options can be found at<br/>https://charmhub.io/jenkins-k8s/configurations<br/><br/>- restart-time-range: Preferred UTC time range in 24 hour format for<br/>  restarting Jenkins (e.g. "03-05"). If empty, restart happens whenever<br/>  Jenkins needs to restart.<br/>- allowed-plugins: Comma-separated list of allowed plugin short names. If<br/>  empty, any plugin can be installed.<br/>- system-properties: Comma-separated JVM system properties (key=value,<br/>  without the -D prefix) passed to the Jenkins process at startup.<br/>- jcasc-config: Jenkins Configuration as Code (JCasC) YAML content. Mutually<br/>  exclusive with jcasc-repository.<br/>- jcasc-repository: HTTPS URL of a public git repository containing JCasC<br/>  YAML files. Mutually exclusive with jcasc-config.<br/>- jcasc-repository-token: A Juju user-secret URI granting access to a private<br/>  jcasc-repository. The secret must contain `username` and `token` keys.<br/>- jcasc-repository-config-path: Path to the directory within<br/>  jcasc-repository containing YAML files. Defaults to "jcasc".<br/>- jcasc-repository-branch: Git branch to check out when cloning<br/>  jcasc-repository. Defaults to "main".<br/>- jcasc-environment-secrets: A Juju user-secret URI containing key-value<br/>  pairs to inject as environment variables for JCasC interpolation.<br/>- external-agent-nodes: Comma-separated names of Jenkins nodes managed outside<br/>  Juju and preserved during agent relation reconciliation. | `map(string)` | `{}` | no |
| <a name="input_constraints"></a> [constraints](#input\_constraints) | Juju constraints to apply for this application. | `string` | `null` | no |
| <a name="input_endpoint_bindings"></a> [endpoint\_bindings](#input\_endpoint\_bindings) | Map for endpoint bindings. | <pre>set(object({<br/>    endpoint = optional(string)<br/>    space    = string<br/>  }))</pre> | `[]` | no |
| <a name="input_expose"></a> [expose](#input\_expose) | The expose block, restricting access to the application by CIDRs, endpoints or spaces. Defaults to exposed with no restrictions; pass `expose = null` to keep the application unexposed. | <pre>object({<br/>    cidrs     = optional(string)<br/>    endpoints = optional(string)<br/>    spaces    = optional(string)<br/>  })</pre> | `{}` | no |
| <a name="input_model_uuid"></a> [model\_uuid](#input\_model\_uuid) | UUID of the Juju model where the application will be deployed. | `string` | n/a | yes |
| <a name="input_resources"></a> [resources](#input\_resources) | Resources to use with the application, keyed by resource name (e.g. jenkins-image). | `map(string)` | `{}` | no |
| <a name="input_revision"></a> [revision](#input\_revision) | Revision number of the charm | `number` | `null` | no |
| <a name="input_storage_directives"></a> [storage\_directives](#input\_storage\_directives) | Map of storage used by the application, keyed by storage name (e.g. jenkins-home). | `map(string)` | `{}` | no |
| <a name="input_units"></a> [units](#input\_units) | Unit count/scale. | `number` | `1` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_application"></a> [application](#output\_application) | Full juju\_application object for the deployed jenkins-k8s application. |
| <a name="output_provides"></a> [provides](#output\_provides) | Map of the provided integration endpoints. |
| <a name="output_requires"></a> [requires](#output\_requires) | Map of the required integration endpoints. |
<!-- END_TF_DOCS -->
<!-- vale on -->
