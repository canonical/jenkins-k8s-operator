# Agent-deprecated relation

The agent-deprecated relation is a remains of the jenkins-k8s charm to provide backwards
compatibility with the existing [jenkins charm](https://charmhub.io/jenkins). The deprecated
relation should not be used as it provides an unstable relation implementation that could result in
some agents not registering successfully.