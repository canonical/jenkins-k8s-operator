# How to resize the jenkins-home storage volume
The default size of the jenkins-home storage volume for a fresh installation is 1GB. While this works for most scenarios, operators might need to have more storage for installing plugins, storing artifacts, and running builds/checking out SCMs on the built-in node.

A low disk-space on the built-in node will cause the node to go offline, blocking Jenkins from running jobs.

### Create a backup of the current Jenkins charm instance
Follow the `Create a backup` section of [the charm's backup and restore documentation](https://charmhub.io/jenkins-k8s/docs/backup-and-restore-jenkins) to create an archive of the Jenkins data on your host system

### Deploy the new Jenkins charm instance, specifying the size of the storage volume
Create a new application with the `--storage` flag. In this example we'll deploy the charm with a storage of 10GB
```bash
juju deploy jenkins-k8s-new --storage jenkins-home=10GB
```

### Restore the created backup onto the newly created Jenkins charm instance
Follow the `Restore the backup on a new (or existing) charm instance` section of [the charm's backup and restore documentation](https://charmhub.io/jenkins-k8s/docs/backup-and-restore-jenkins) to create an archive of the Jenkins data on your host system. Remember to update the `JENKINS_UNIT` environment variable. For our example we have `JENKINS_UNIT=jenkins-k8s-new/0`