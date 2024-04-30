# How to redeploy Jenkins

We consider a redeployment is the process where the old charm instance is removed and data is migrated to a new charm instance.

As Jenkins does not use any persistent storage or database, redeploying the charm consists of 3 steps:

1. Create the new Jenkins charm instance
```bash
juju deploy jenkins-k8s jenkins-k8s-new
```
2. Migrate Jenkins data
See the `Migrate Jenkins data` section below.
3. Remove the old Jenkins charm instance
```bash
juju remove-application jenkins-k8s
```

### Migrate Jenkins data
Follow the instructions in [the charm's documentation for resizing storage](https://charmhub.io/jenkins-k8s/docs/how-to-resize-jenkins-storage) to migrate the data to the new Jenkins charm instance.