# How to integrate with machine agents

### Prerequisites

This guide assumes the `jenkins-k8s` charm to already be deployed on a k8s juju model `tutorial`.

To integrate machine (VM) agents, you'll need to have a bootstrapped machine model. Learn about
bootstrapping different clouds
[here](https://juju.is/docs/olm/get-started-with-juju#heading--prepare-your-cloud).

Use `juju bootstrap localhost localhost` to bootstrap a `lxd` machine controller with the name
`localhost` for tutorial purposes.

Use `juju add-model tutorial` to add a model named `tutorial`.

### Deploy Jenkins agents (VM)

Deploy 3 units of [jenkins agents](https://charmhub.io/jenkins-agent) on the lxd cloud.

```
# Deploy an edge version of the charm until stable version is released.
juju deploy jenkins-agent --channel=latest/edge -n3
```

### Create an offer for Cross Model Relation

To relate charms
[across different models](https://juju.is/docs/juju/manage-cross-model-integrations), a juju
[`offer`](https://juju.is/docs/juju/manage-cross-model-integrations#heading--create-an-offer) is
required.

Create an offer of the `jenkins-agent` charm's `agent` relation.

```
juju offer jenkins-agent:agent
```

The output should look similar to the contents below:

```
Application "jenkins-agent" endpoints [agent] available at "admin/tutorial.jenkins-agent"
```

### (Optional) configure external URL for agent discovery and configure websocket
If you are deploying your jenkins-k8s charm on environments other than microk8s,
there is a high chance that the cross-model relation will not work unless you set the
`remoting-external-url` configuration value. This is because by default the charm sends its
kubernetes pod IP through the relation to the agent(s) to be used to initialize connection.
This IP is usually internal to the Kubernetes cluster and thus not accessible for the machine
agents on the machine cloud.

There are multiple ways in which this is possible, below is one of the possible methods to
enable agent discovery using a Kubernetes NodePort service.

Create the kubernetes NodePort service
```
$ cat <<'EOF' | kubectl create -f -
apiVersion: v1
kind: Service
metadata:
  labels:
    app.kubernetes.io/name: jenkins-k8s
  name: jenkins-k8s-nodeport
spec:
  ports:
  - port: 8080
    protocol: TCP
    targetPort: 8080
  selector:
    app.kubernetes.io/name: jenkins-k8s
  type: NodePort
status:
  loadBalancer: {}
EOF
```

Configure remoting-external-url with `http://<node-ip>:<node-port>`:
```
juju config jenkins-k8s remoting-external-url=http://<node-ip>:<node-port>
```

Enable websocket, this will allow the agent to use WebSocket rather than JNLP which requires TCP port 50000 to be opened:
```
juju config jenkins-k8s remoting-enable-websocket=true
```

### Relate Jenkins agents through the offer

Switch back to the k8s model where `jenkins-k8s` charm is deployed. An example of the switch
command looks like the following: `juju switch microk8s-localhost:tutorial`.

Relate the agents to the `jenkins-k8s` server charm through the offer.
The syntax of the offer is as follows: `<controller>:<user>/<model>.<charm>`.

```
juju relate jenkins-k8s:agent localhost:admin/tutorial.jenkins-agent
```
