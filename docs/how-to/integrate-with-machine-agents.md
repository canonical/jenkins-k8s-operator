# How to integrate with machine agents

### Prerequisites

This guide assumes the `jenkins-k8s` charm to already be deployed on a k8s juju model `tutorial`.

To integrate machine (VM) agents, you'll need to have a bootstrapped machine model. Learn about
bootstrapping different clouds
[here](https://documentation.ubuntu.com/juju/3.6/tutorial/#prepare-your-cloud).

Use `juju bootstrap localhost localhost` to bootstrap a `lxd` machine controller with the name
`localhost` for tutorial purposes.

Use `juju add-model tutorial` to add a model named `tutorial`.

<!-- vale Canonical.007-Headings-sentence-case = NO -->
### Deploy Jenkins agents (VM)
<!-- vale Canonical.007-Headings-sentence-case = YES -->

Deploy 3 units of [jenkins agents](https://charmhub.io/jenkins-agent) on the lxd cloud.

```
# Deploy an edge version of the charm until stable version is released.
juju deploy jenkins-agent --channel=latest/edge -n3
```

### Create an offer for cross model relation

To relate charms
[across different models](https://documentation.ubuntu.com/juju/3.6/howto/manage-relations/#add-a-cross-model-relation), a Juju
[`offer`](https://documentation.ubuntu.com/juju/3.6/howto/manage-offers/#integrate-with-an-offer) is
required.

Create an offer of the `jenkins-agent` charm's `agent` relation.

```
juju offer jenkins-agent:agent
```

The output should look similar to the contents below:

```
Application "jenkins-agent" endpoints [agent] available at "admin/tutorial.jenkins-agent"
```

### Relate Jenkins agents through the offer

Switch back to the k8s model where `jenkins-k8s` charm is deployed. An example of the switch
command looks like the following: `juju switch microk8s-localhost:tutorial`.

Relate the agents to the `jenkins-k8s` server charm through the offer.
The syntax of the offer is as follows: `<controller>:<user>/<model>.<charm>`.

```
juju relate jenkins-k8s:agent localhost:admin/tutorial.jenkins-agent
```
