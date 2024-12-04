# How to back up and restore Jenkins
A backup is a snapshot of the Jenkins data (jobs, configurations, secrets, plugins, etc.) at a given point in time. This backup can be used to:
* Restore Jenkins to a previous stable state (during disaster recovery).
* Migrate data to a new Jenkins charm instance.

## Create a backup
1. Create the backup script
From [Backing-up/Restoring Jenkins](https://www.jenkins.io/doc/book/system-administration/backing-up/), This script backs up the most essential files as mentioned in the article:
* The `master.key` file.
* Job-related files in the `./jobs`, `./builds` and `./workspace` folders.
* Plugin-related files (`.hpi` and `.jpi`) in the `./plugins` folder.

```bash
cat <<EOF > backup.sh
#!/bin/bash
export JENKINS_HOME=/var/lib/jenkins
export JENKINS_BACKUP=/mnt/backup

echo "running backup as \$(whoami) in \$(pwd)"
mkdir -p \$JENKINS_BACKUP
cp \$JENKINS_HOME/secrets/master.key \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/jobs \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/builds \$JENKINS_BACKUP
cp -r \$JENKINS_HOME/workspace \$JENKINS_BACKUP
mkdir -p \$JENKINS_BACKUP/plugins
cp -r \$JENKINS_HOME/plugins/*.hpi \$JENKINS_BACKUP/plugins
cp -r \$JENKINS_HOME/plugins/*.jpi \$JENKINS_BACKUP/plugins

chown -R 2000:2000 \$JENKINS_BACKUP
tar zcvf jenkins_backup.tar.gz --directory=/mnt backup
EOF

chmod +x backup.sh
```
2. Transfer the backup script above to the running unit of the Jenkins-k8s charm and run it
```bash
JENKINS_UNIT=jenkins-k8s/0
juju scp --container jenkins ./backup.sh $JENKINS_UNIT:/backup.sh
juju ssh  --container jenkins $JENKINS_UNIT /backup.sh
```
3. Retrieve the compressed backup file
```bash
JENKINS_UNIT=jenkins-k8s/0
juju scp --container jenkins $JENKINS_UNIT:/jenkins_backup.tar.gz jenkins_backup.tar.gz
```
You now have the compressed Jenkins data on your host system.

## Restore the backup on a new (or existing) charm instance
1. Restore the backup on the Jenkins charm unit.
```bash
JENKINS_UNIT=jenkins-k8s/0
juju scp --container jenkins ./jenkins_backup.tar.gz $JENKINS_UNIT:/jenkins_backup.tar.gz
juju ssh --container jenkins $JENKINS_UNIT tar zxvf jenkins_backup.tar.gz
juju ssh --container jenkins $JENKINS_UNIT chown -R jenkins:jenkins /backup
juju ssh --container jenkins $JENKINS_UNIT cp -avR /backup/* /var/lib/jenkins
juju ssh --container jenkins $JENKINS_UNIT rm -rf /backup /jenkins_backup.tar.gz
```
2. Restart Pebble for the changes to take effect.
```bash
juju ssh --container jenkins $JENKINS_UNIT pebble restart jenkins
```
