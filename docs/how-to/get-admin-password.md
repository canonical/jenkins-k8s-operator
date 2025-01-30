# How to get admin password

### Get admin password

To retrieve the password for the admin account, you can run the `get-admin-password` action.

```
juju run jenkins-k8s/0 get-admin-password 
```

The output should look something similar to the contents below:

```
unit-jenkins-k8s-0:
  UnitId: jenkins-k8s/0
  id: "2"
  results:
    password: <password>
  status: completed
  timing:
    completed: <timestamp>
    enqueued: <timestamp>
    started: <timestamp>
```

You can use the password retrieved above to access your Jenkins server UI at
`http://<UNIT_IP>:8080` as the "admin" user.