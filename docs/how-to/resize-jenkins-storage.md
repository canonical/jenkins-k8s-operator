# How to resize the jenkins-home storage volume
The default size of the jenkins-home storage volume for a fresh installation is 1GB. While this works for most scenarios, operators might need to have more storage for installing plugins, storing artifacts, and runninng builds/checking out SCMs on the built-in node.

A low disk-space on the built-in node will cause the node to go offline, blocking jenkins from running jobs.

## Create a backup
From [Backing-up/Restoring Jenkins](https://www.jenkins.io/doc/book/system-administration/backing-up/), This script backs up the most essential files as mentioned in the article:
* The `master.key` file.
* Job-related files in the `./jobs`, `./builds` and `./workspace` folders.
* Plugins (`.hpi` and `.jpi` files) in the `./plugins` folder

```bash
echo cat <<EOF > backup.sh
#!/bin/bash
export JENKINS_HOME=/var/lib/jenkins
export JENKINS_BACKUP=/mnt/backup

echo "running backup as \$(whoami) in \$(pwd)"
mkdir -p \$JENKINS_BACKUP
cp \$JENKINS_HOME/secrets/master.key \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/*.xml \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/jobs \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/builds \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/workspace \$JENKINS_BACKUP
mkdir -p \$JENKINS_BACKUP/plugins
cp -r \$JENKINS_HOME/plugins/*.hpi \$JENKINS_BACKUP/plugins
cp -r \$JENKINS_HOME/plugins/*.jpi \$JENKINS_BACKUP/plugins

chown -R 2000:2000 $JENKINS_BACKUP
tar zcvf jenkins_backup.tar.gz --directory=/mnt backup
EOF

chmod +x backup.sh
```
1. Transfer the backup script above to the running unit of the Jenkins-k8s charm and run it
```bash
JENKINS_UNIT=jenkins-k8s/0
juju scp --container jenkins ./backup.sh $JENKINS_UNIT:/backup.sh
juju ssh  --container jenkins $JENKINS_UNIT /backup.sh
```
2. Retrieve the compressed backup file
```bash
JENKINS_UNIT=jenkins-k8s/0
juju scp --container jenkins $JENKINS_UNIT:/jenkins_backup.tar.gz jenkins_backup.tar.gz
```
3. With the data backed-up, we can remove the jenkins-k8s application.
```bash
JENKINS_APP=jenkins-k8s
juju remove-application $JENKINS_APP
```

## Restore the backup on a new charm instance
1. When the application has been deleted, create a new application with the `--storage` flag. In this example we'll deploy the charm with a storage of 10GB
```bash
juju deploy jenkins-k8s --storage jenkins-home=10GB
```
2. Wait for the charm to be ready, then restore the backup on the new unit.
```bash
JENKINS_UNIT=jenkins-k8s/0
juju scp --container jenkins ./jenkins_backup.tar.gz $JENKINS_UNIT:/jenkins_backup.tar.gz
juju ssh --container jenkins $JENKINS_UNIT tar zxvf jenkins_backup.tar.gz
juju ssh --container jenkins $JENKINS_UNIT chown -R 2000:2000 /backup
juju ssh --container jenkins $JENKINS_UNIT cp -R /backup/* /var/lib/jenkins
juju ssh --container jenkins $JENKINS_UNIT rm -rf /backup /jenkins_backup.tar.gz
```
3. Finally restart pebble
```bash
juju ssh --container jenkins $JENKINS_UNIT pebble restart jenkins
```
