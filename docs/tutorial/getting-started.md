# Getting Started

## What you'll do

- Deploy the [jenkins-k8s charm](https://charmhub.io/jenkins-k8s)
- [Deploy and integrate agents](#deploy-and-relate-agents)
- [Get admin password](#get-admin-password)

The jenkins-k8s charm helps deploy a Jenkins automation server application with ease and
also helps operate the charm. This
tutorial will walk you through each step of deployment to get a basic Jenkins deployment.

### Prerequisites

To deploy jenkins-k8s charm, you will need a juju bootstrapped with any kubernetes controller.
To see how to bootstrap your juju installation with microk8s, please refer to the documentation
on microk8s [installation](https://juju.is/docs/olm/microk8s).

### Setting up the tutorial model

To easily clean up the resources and to separate your workload from the contents of this tutorial,
it is recommended to set up a new model with the following command.

```
juju add-model jenkins-tutorial
```

### Deploy the jenkins-k8s charm

Start off by deploying the jenkins-k8s charm. By default it will deploy the latest stable release
of the jenkins-k8s charm.

```
juju deploy jenkins-k8s --channel=latest/edge
```

The Jenkins application can only have a single server unit. Adding more units through `--num-units`
parameter will cause the application to misbehave.

### Deploy and integrate agents

By default, jenkins-k8s server application is installed with 0 executors for security purposes.
A functional Jenkins application requires additional Jenkins agents to be integrated.

The following commands deploy 3 units of the jenkins-agent-k8s charm and integrate them with the
jenkins-k8s charm.

```
juju deploy jenkins-agent-k8s --channel=latest/edge --num-units=3

# 'agent' relation name is required since jenkins-k8s charm provides multiple compatible
# interfaces with jenkins-agent-k8s charm.
juju relate jenkins-k8s:agent jenkins-agent-k8s:agent
```

### Get admin credentials

You can access the Jenkins server application UI by accessing the IP of a jenkins-k8s unit. To
start managing Jenkins server as an administrator, you need to get the password for the admin
account.

By running the `get-admin-password` action on a jenkins-k8s unit, juju will read and fetch the
admin credentials setup for you. You can use the following command below.

```
juju run-action jenkins-k8s/0 get-admin-password --wait
```

The result should look something similar to the contents below:

```
unit-jenkins-k8s-0:
  UnitId: jenkins-k8s/0
  id: "2"
  results:
    password: <password>
  status: completed
  timing:
    completed: <timestamp>
    enqueued: <timestamp>
    started: <timestamp>
```

You can now access your Jenkins server UI at `http://<UNIT_IP>:8080` and login using username
"admin" and password from the action above.

### Cleaning up the environment

Congratulations! You have successfully finished the jennkins-k8s tutorial. You can now remove the
model environment that you’ve created using the following command.

```
juju destroy model jenkins-tutorial -y --release-storage
```
