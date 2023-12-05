# Jenkins-k8s Operator

A Juju charm deploying and managing Jenkins on Kubernetes. [Jenkins](https://www.jenkins.io/) is an open source automation server. Jenkins provides hundreds of plugins to support building, deploying and automating any project. It can be integrated with both k8s and machine (VM) agents for use.

This charm simplifies initial deployment and "day N" operations of Jenkins on Kubernetes, including integration with Jenkins agent instances, automatic patch updates and more. It allows for deployment on many different Kubernetes platforms, from [MicroK8s](https://microk8s.io/) to [Charmed Kubernetes](https://ubuntu.com/kubernetes) to public cloud Kubernetes offerings.

As such, the charm makes it easy for those looking to take control of their own automation management system whilst keeping operations simple, and gives them the freedom to deploy on the Kubernetes platform of their choice.

For DevOps or SRE teams this charm will make operating Jenkins simple and straightforward through Juju's clean interface. It will allow easy deployment into multiple environments for testing of changes, and supports scaling out agents for enterprise deployments.

## Project and community

The Jenkins-k8s Operator is a member of the Ubuntu family. It's an open source project that warmly welcomes community projects, contributions, suggestions, fixes and constructive feedback.

- [Code of conduct](https://ubuntu.com/community/code-of-conduct)
- [Get support](https://discourse.charmhub.io/)
- [Join our online chat](https://chat.charmhub.io/charmhub/channels/charm-dev)
- [Contribute](Contribute)

Thinking about using the Jenkins-k8s Operator for your next project? [Get in touch](https://chat.charmhub.io/charmhub/channels/charm-dev)!

# Contents

1. [Tutorial](tutorial)
  1. [Getting Started](tutorial/getting-started.md)
1. [How to](how-to)
  1. [Configure update-time-range](how-to/configure-update-time-range.md)
  1. [Get admin password](how-to/get-admin-password.md)
  1. [How to integrate with machine agents](how-to/integrate-with-machine-agents.md)
1. [Reference](reference)
  1. [Actions](reference/actions.md)
  1. [Configurations](reference/configurations.md)
  1. [Integrations](reference/integrations.md)
1. [Explanation](explanation)
  1. [Agent-deprecated relation](explanation/agent-deprecated-relation.md)