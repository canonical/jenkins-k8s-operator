# Deploy the jenkins-k8s charm for the first time

## What you'll do

- Deploy the [jenkins-k8s charm](https://charmhub.io/jenkins-k8s)
- Access the UI
- Deploy and integrate agents

The jenkins-k8s charm helps deploy a Jenkins automation server application with ease and
also helps operate the charm. This
tutorial will walk through each step of deployment to get a basic Jenkins server deployment.

### Requirements

- A machine with amd64 architecture.
- Juju 3 installed.
- Juju MicroK8s controller created and active named `microk8s`. [MetalLB addon](https://microk8s.io/docs/addon-metallb) should be enabled for traefik-k8s to work.
- LXD controller created and active named `lxd` (optional).
- All the requirements can be met using the [Multipass charm-dev blueprint](https://juju.is/docs/juju/set-up--tear-down-your-test-environment#heading--set-up---tear-down-automatically). Use the Multipass VM shell to run all commands in this tutorial.

For more information about how to install Juju, see [Get started with Juju](https://juju.is/docs/olm/get-started-with-juju).

### Set up the tutorial model

To easily clean up the resources and to separate your workload from the contents of this tutorial,
set up a new Juju model in the `microk8s` controller with the following command.

```
juju switch microk8s
juju add-model jenkins-tutorial
```

### Deploy the jenkins-k8s charm

Start off by deploying the jenkins-k8s charm. By default it will deploy the latest stable release
of the jenkins-k8s charm.

```
juju deploy jenkins-k8s --channel=latest/edge
```

Wait for the charm to be active:
```
juju wait-for application jenkins-k8s
```

The Jenkins application can only have a single server unit. Adding more units through `--num-units`
parameter will cause the application to misbehave.


### Expose jenkins-k8s through ingress

Deploy traefik-k8s charm and integrate it with the jenkins-k8s charm:
```
juju deploy traefik-k8s --channel=latest/edge --trust
juju integrate jenkins-k8s:ingress traefik-k8s
```

You can check the status with:
```
juju status --relations
```

After a few minutes, the deployment will be finished and all the units should be in 
the active status.

Run the following command to get the URL to connect to Jenkins:
```
juju run traefik-k8s/0 show-proxied-endpoints --format=yaml
```

The output will be something similar to:
```
Running operation 1 with 1 task
  - task 2 on unit-traefik-k8s-0

Waiting for task 2...
traefik-k8s/0: 
  id: "2"
  results: 
    proxied-endpoints: '{"traefik-k8s": {"url": "http://10.12.97.102"}, "jenkins-k8s":
      {"url": "http://10.12.97.102/jenkins-tutorial-jenkins-k8s"}}'
    return-code: 0
  status: completed
  timing: 
    completed: 2024-09-27 15:09:36 +0200 CEST
    enqueued: 2024-09-27 15:09:35 +0200 CEST
    started: 2024-09-27 15:09:35 +0200 CEST
  unit: traefik-k8s/0
```

In this case, the URL to use in your browser will be `http://10.12.97.102/jenkins-tutorial-jenkins-k8s`. In
your case it will probably be a different IP address.

By running the `get-admin-password` action on the jenkins-k8s unit, Juju will read and fetch the
admin credentials setup for you. You can use the following command below.

```
juju run jenkins-k8s/0 get-admin-password 
```

The output should look something similar to the contents below:

```
Running operation 3 with 1 task
  - task 4 on unit-jenkins-k8s-0

Waiting for task 4...
password: e67a44447d37423887e278bc8c694f95
```

You can now access your Jenkins server UI at the previous URL, and login using username "admin" and password from the action above.

You may need to wait for up to five minutes for the URL to work correctly.

### Deploy and integrate k8s agents

By default, jenkins-k8s server application is installed with 0 executors for security purposes.
A functional Jenkins application requires additional Jenkins agents to be integrated.

The following commands deploy 3 units of the jenkins-agent-k8s charm and integrate them with the
jenkins-k8s charm.

```
juju deploy jenkins-agent-k8s --channel=latest/edge --num-units=3

# 'agent' relation name is required since jenkins-k8s charm provides multiple compatible
# interfaces with jenkins-agent-k8s charm.
juju integrate jenkins-k8s:agent jenkins-agent-k8s:agent
```

You can check the status with:
```
juju status --relations
```

After the units are active, the output to the previous command should be similar to:
```
Model             Controller  Cloud/Region        Version  SLA          Timestamp
jenkins-tutorial  microk8s    microk8s/localhost  3.5.3    unsupported  10:27:59+02:00

App                Version  Status  Scale  Charm              Channel      Rev  Address         Exposed  Message
jenkins-agent-k8s           active      3  jenkins-agent-k8s  latest/edge   27  10.152.183.108  no       
jenkins-k8s        2.462.2  active      1  jenkins-k8s        latest/edge  125  10.152.183.178  no       
traefik-k8s        2.11.0   active      1  traefik-k8s        latest/edge  211  10.152.183.40   no       Serving at 10.12.97.102

Unit                  Workload  Agent  Address      Ports  Message
jenkins-agent-k8s/0   active    idle   10.1.32.148         
jenkins-agent-k8s/1   active    idle   10.1.32.153         
jenkins-agent-k8s/2*  active    idle   10.1.32.152         
jenkins-k8s/0*        active    idle   10.1.32.132         
traefik-k8s/0*        active    idle   10.1.32.147         Serving at 10.12.97.102

Integration provider     Requirer             Interface         Type     Message
jenkins-agent-k8s:agent  jenkins-k8s:agent    jenkins_agent_v0  regular  
traefik-k8s:ingress      jenkins-k8s:ingress  ingress           regular  
traefik-k8s:peers        traefik-k8s:peers    traefik_peers     peer     
```

After a few minutes you should be able to see the jenkins agent K8s model as a new build executor
in the Jenkins UI.


### Deploy and integrate machine agents (optional)

For this section you need a machine model named `lxd`. If you are using the Multipass, the `charm-dev` blueprint
will automatically set up the machine model for you.

The first requirement is to create the offer, so the jenkins-k8s agent endpoint is available
for cross-model integrations.

```
juju offer jenkins-k8s:agent
```

Once the offer is created, we can create the new model, deploy the machine jenkins-agent charm
and integrate it with jenkins-k8s with:
```
juju add-model --controller=lxd jenkins-tutorial
juju deploy --model lxd:jenkins-tutorial jenkins-agent --channel=latest/edge
juju integrate --model lxd:jenkins-tutorial jenkins-agent:agent microk8s:admin/jenkins-tutorial.jenkins-k8s
```

You can check the status of the lxd model with:
```
juju status --model lxd:jenkins-tutorial --relations
```

After a few minutes you should be able to see the jenkins agent machine model as a new build executor
in the Jenkins UI.


### Cleaning up the environment

Congratulations! You have successfully finished the jennkins-k8s tutorial. You can now remove the
model environments that you’ve created using the following commands.


```
juju destroy-model lxd:jenkins-tutorial --destroy-storage
```

```
juju destroy-model jenkins-tutorial --destroy-storage
```

