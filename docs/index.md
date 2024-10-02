# Jenkins-k8s Operator

A Juju charm deploying and managing Jenkins on Kubernetes. [Jenkins](https://www.jenkins.io/) is an open source automation server. Jenkins provides hundreds of plugins to support building, deploying and automating any project. It can be integrated with both k8s and machine (VM) agents for use.

This charm simplifies initial deployment and operations of Jenkins on Kubernetes, including integration with Jenkins agent instances, automatic patch updates and more. It allows for deployment on many different Kubernetes platforms, from [MicroK8s](https://microk8s.io/) to [Charmed Kubernetes](https://ubuntu.com/kubernetes) to public cloud Kubernetes offerings.

For DevOps or SRE teams this charm will make operating Jenkins simple and straightforward through Juju's clean interface. It will allow easy deployment into multiple environments for testing of changes, and supports scaling out agents for enterprise deployments.

## In this documentation

| | |
|--|--|
|  [Tutorials](https://charmhub.io/jenkins-k8s/docs/tutorial-getting-started)</br>  Get started - a hands-on introduction to using the charm for new users </br> |  [How-to guides](https://charmhub.io/jenkins-k8s/docs/how-to-configure-restart-time-range) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/jenkins-k8s/docs/reference-actions) </br> Technical information - specifications, APIs, architecture | [Explanation](https://charmhub.io/jenkins-k8s/docs/explanation-agent-deprecated-relation) </br> Concepts - discussion and clarification of key topics  |

## Contributing to this documentation

Documentation is an important part of this project, and we take the same open-source approach to the documentation as 
the code. As such, we welcome community contributions, suggestions and constructive feedback on our documentation. 
Our documentation is hosted on the [Charmhub forum](https://discourse.charmhub.io/) 
to enable easy collaboration. Please use the "Help us improve this documentation" links on each documentation page to 
either directly change something you see that's wrong, ask a question or make a suggestion about a potential change via 
the comments section.

If there's a particular area of documentation that you'd like to see that's missing, please 
[file a bug](https://github.com/canonical/jenkins-k8s-operator/issues).

## Project and community

The Jenkins-k8s Operator is a member of the Ubuntu family. It's an open source project that warmly welcomes community projects, contributions, suggestions, fixes and constructive feedback.

- [Code of conduct](https://ubuntu.com/community/code-of-conduct)
- [Get support](https://discourse.charmhub.io/)
- [Join our online chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
- [Contribute](https://github.com/canonical/jenkins-k8s-operator/blob/94521d904be53c5645881fc43ba0b71ff60b9776/CONTRIBUTING.md)

Thinking about using the Jenkins-k8s Operator for your next project? [Get in touch](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)!

# Contents

1. [Tutorial](tutorial)
   1. [Getting Started](tutorial/getting-started.md)
1. [How to](how-to)
   1. [Backup and restore](how-to/backup-and-restore-jenkins.md)
   1. [Configure installable plugins](how-to/configure-installable-plugins.md)
   1. [Configure Jenkins memory usage](how-to/configure-jenkins-memory-usage.md)
   1. [Configure restart-time-range](how-to/configure-restart-time-range.md)
   1. [Get admin password](how-to/get-admin-password.md)
   1. [Integrate with external agents](how-to/integrate-with-external-agents.md)
   1. [Integrate with IAM](how-to/integrate-with-iam.md)
   1. [Integrate with machine agents](how-to/integrate-with-machine-agents.md)
   1. [Redeploy](how-to/redeploy.md)
   1. [Resize Jenkins storage](how-to/resize-jenkins-storage.md)
   1. [Rotate credentials](how-to/rotate-credentials.md)
1. [Reference](reference)
   1. [Actions](reference/actions.md)
   1. [Configurations](reference/configurations.md)
   1. [Integrations](reference/integrations.md)
1. [Explanation](explanation)
   1. [Agent-deprecated relation](explanation/agent-deprecated-relation.md)
