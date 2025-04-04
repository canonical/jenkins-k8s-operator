# How to configure installable plugins

### Configure `plugins`

Use the `plugins` configuration to allow plugins to be installed on Jenkins.
The configuration is a comma-separated list of allowed plugin short names. If empty, any plugin can be installed.
Plugins installed by the user and the plugins' dependencies will be removed automatically if they are not on
the list. Included plugins are not automatically installed.

```
juju config jenkins-k8s plugins=<allowed-plugins-csv>

# plugins example: `git, azure-cli, aws-credentials` will allow git, azure and aws-credentials
plugins to be installed.
```

The plugins are cleaned up at `update-status` hook trigger. If the `restart-time-range`
configuration option is provided, the plugins are cleaned up during the defined time range.

On trigger it will:

1. Delete any installed plugins not defined on the list and their dependencies.
2. Set a system message on Jenkins indicating which user installed plugins have been deleted.