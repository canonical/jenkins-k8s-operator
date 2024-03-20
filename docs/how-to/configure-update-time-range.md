# How to configure update-time-range

### Configure update-time-range

Use the `update-time-range` configuration to set the time interval when `jenkins-k8s` automatically
applies the latest patches for the current [LTS](https://www.jenkins.io/download/lts/) version.
The minimum time interval is 1 hour. Time range is applied each day of the week.

```
juju config jenkins-k8s update-time-range=<desired-time-range>

# desired-time-range example: 22-03 to allow patching from 10PM-03AM UTC.
```

Assuming the installed Jenkins LTS version to be 2.387, the output of `juju status` should look
similar to the following before the update:

```
Model               Controller          Cloud/Region        Version  SLA          Timestamp
jenkins-tutorial    microk8s-localhost  microk8s/localhost  2.9.43   unsupported  <timestamp>

App                Version  Status      Scale  Charm              Channel      Rev  Address         Exposed  Message
jenkins-k8s        2.387  active          1  jenkins-k8s        latest/edge     0   <ip-address>    no

Unit            Workload  Agent  Address       Ports  Message
jenkins-k8s/0*  active    idle   <ip-address>
```

After the update:

```
Model               Controller          Cloud/Region        Version  SLA          Timestamp
jenkins-tutorial    microk8s-localhost  microk8s/localhost  2.9.43   unsupported  <timestamp>

App                Version  Status      Scale  Charm              Channel      Rev  Address         Exposed  Message
jenkins-k8s        2.387.3  active          1  jenkins-k8s        latest/edge  0    <ip-address>    no

Unit            Workload  Agent  Address       Ports  Message
jenkins-k8s/0*  active    idle   <ip-address>
```

Note the difference in patch version under the `Version` column of the application status.

You can verify that the patch has been applied by signing into the Jenkins UI and checking the
version number at the bottom right corner of the footer.