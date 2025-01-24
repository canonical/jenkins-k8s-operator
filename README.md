# jenkins-k8s-operator

[![CharmHub Badge](https://charmhub.io/jenkins-k8s/badge.svg)](https://charmhub.io/jenkins-k8s)
[![Publish to edge](https://github.com/canonical/jenkins-k8s-operator/actions/workflows/publish_charm.yaml/badge.svg)](https://github.com/canonical/jenkins-k8s-operator/actions/workflows/publish_charm.yaml)
[![Promote charm](https://github.com/canonical/jenkins-k8s-operator/actions/workflows/promote_charm.yaml/badge.svg)](https://github.com/canonical/jenkins-k8s-operator/actions/workflows/promote_charm.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

A [Juju](https://juju.is/) [charm](https://juju.is/docs/olm/charmed-operators)
deploying and managing [Jenkins](https://jenkins.io/) on Kubernetes. Jenkins is an open source
automation server, providing plugins to support building, deploying and automating any project.

Jenkins is an extendable continuous integration server that monitors executions of repeated jobs. 
The focus of Jenkins is the building/testing of software projects continuously, and monitoring
executions of externally-run jobs. More information at http://jenkins-ci.org/.

This charm provides the Jenkins server service, and when paired with the
jenkins agent provides an easy way to deploy Jenkins.

For DevOps and SRE teams, this charm will make operating Jenkins simple and straightforward
through Juju's clean interface. Allowing both kubernetes and machine agent relations, it supports
multiple environments for automation.

For information about how to deploy, integrate, and manage this charm, see the Official [jenkins-k8s charm Documentation](https://charmhub.io/jenkins-k8s/docs).

## Get started

To begin, refer to the [tutorial](https://charmhub.io/jenkins-k8s/docs/tutorial-getting-started) for step-by-step instructions.

### Basic operations

#### Expose jenkins-k8s through ingress

See the [Expose jenkins-k8s through ingress](https://charmhub.io/jenkins-k8s/docs/tutorial-getting-started#expose-jenkins-k8s-through-ingress) section in the jenkins-k8s-operator documentation.

#### Integrate with the jenkins-agent and the jenkins-agent-k8s charm

See the [deploy and integrate k8s agents](https://charmhub.io/jenkins-k8s/docs/tutorial-getting-started#deploy-and-integrate-k8s-agents) section and the [deploy and integrate machine agents](https://charmhub.io/jenkins-k8s/docs/tutorial-getting-started#deploy-and-integrate-machine-agents-optional) section in the jenkins-k8s-operator documentation.

#### Use agent-discovery-ingress integration to integrate with "external" agents

See the [how to integrate with external agents](https://charmhub.io/jenkins-k8s/docs/how-to-integrate-with-external-agents) section in the jenkins-k8s-operator documentation.

## Learn more

- [Read more](https://charmhub.io/jenkins-k8s/docs)
- [Official Webpage](https://www.jenkins.io/)
- [Troubleshooting](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

## Project and community

The Jenkins-agent-k8s Operator is a member of the Ubuntu family. It's an open source project that warmly welcomes community projects, contributions, suggestions, fixes and constructive feedback.

* [Issues](https://github.com/canonical/jenkins-k8s-operator/issues) <!--Link to GitHub issues (if applicable)-->
* [Contributing](https://github.com/canonical/jenkins-k8s-operator/blob/main/CONTRIBUTING.md) <!--Link to any contribution guides--> 
- [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

