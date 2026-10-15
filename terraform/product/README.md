<!-- vale Canonical.007-Headings-sentence-case = NO -->
# Jenkins-k8s Terraform module
<!-- vale Canonical.007-Headings-sentence-case = YES -->

This folder contains a product [Terraform](https://developer.hashicorp.com/terraform) module for the
Jenkins-k8s solution.

The module uses the 
[Terraform Juju provider](https://registry.terraform.io/providers/juju/juju/latest/docs) to model 
the charm deployment onto any Kubernetes environment managed by [Juju](https://canonical.com/juju).

## Module structure

- **main.tf** - Defines the Juju applications to be deployed.
- **variables.tf** - Allows customization of the deployment. Also models the charm configuration, 
  except for exposing the deployment options (Juju model UUID, channel or application name).
- **outputs.tf** - Integrates the module with other Terraform modules, primarily
  by defining potential integration endpoints (charm integrations), but also by exposing
  the deployed applications and the models/metadata of this product.
- **terraform.tf** - Defines the Terraform provider version.

## Using jenkins-k8s product module in higher level modules

If you want to use `jenkins-k8s` product module as part of your Terraform module, import it
like shown below:

```text
data "juju_model" "my_model" {
  name = "my-model"
}

module "jenkins_k8s" {
  source = "git::https://github.com/canonical/jenkins-k8s-operator//terraform/product?ref=tf-1.0.0"

  model_uuid = data.juju_model.my_model.uuid
  # (Customize configuration variables here if needed)
}
```

Create integrations, for instance:

```text
resource "juju_integration" "jenkins_k8s_jenkins_agent_k8s_agent" {
  model_uuid = data.juju_model.my_model.uuid
  application {
    name     = module.jenkins_k8s.jenkins_k8s_requires.logging.name
    endpoint = module.jenkins_k8s.jenkins_k8s_requires.logging.endpoint
  }
  application {
    name     = "loki-k8s"
    endpoint = "logging"
  }
}
```

The complete list of available integrations can be found [in the Integrations tab][github-runner-integrations].

[Terraform]: https://www.terraform.io/
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://canonical.com/juju
[github-runner-integrations]: https://charmhub.io/jenkins-k8s/integrations

<!-- vale off -->
<!-- BEGIN_TF_DOCS -->
<!-- END_TF_DOCS -->
<!-- vale on -->
