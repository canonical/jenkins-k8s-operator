# How to upgrade

Upgrade to the latest revision of the Jenkins charm using the `juju refresh` command:

```bash
juju refresh jenkins-k8s
```

The upgrade may take several seconds to complete. You can monitor the status of the upgrade using:

```bash
juju status
```

Once the charm is ready, the status will show the new revision number.

## Repair ownership after upgrading older revisions

Starting with revision 405, normal charm hooks only reconcile the ownership of
the Jenkins home mount point. This avoids long-running hooks on large Jenkins
homes.

When upgrading a deployment from a revision older than 405, run a one-time
recursive repair:

```bash
juju run jenkins-k8s/0 reconcile-storage recursive=true timeout=1800
```

Increase `timeout` if the Jenkins home contains a large number of files or is
backed by slow storage.
