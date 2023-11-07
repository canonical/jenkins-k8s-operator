# How to rotate credentials

### Rotate credentials

To rotate credentials for the admin account and invalidate all logged in user sessions, you can run
the `rotate-credentials` action.

```
juju run-action jenkins-k8s/0 rotate-credentials --wait
```

The output should look something similar to the contents below:

```
unit-jenkins-k8s-0:
  UnitId: jenkins-k8s/0
  id: "1"
  results:
    password: <password>
  status: completed
  timing:
    completed: <timestamp>
    enqueued: <timestamp>
    started: <timestamp>
```

You can use the newly generated password above to access your Jenkins server UI at
`http://<UNIT_IP>:8080` as the "admin" user.
