# How to upgrade

Upgrade to a new revision of the Jenkins charm using the `juju refresh` command:

```bash
juju refresh jenkins-k8s
```

The upgrade may take several seconds to complete. You can monitor the status of the upgrade using:

```bash
juju status
```

Once the charm is ready, the status will show the new revision number.
