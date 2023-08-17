# How to configure installable plugins

### Configure `plugins`

Use the `plugins` configuration to allow a list of plugins to be installed on Jenkins. It is a list
of allowed plugin short names separated by commas. Leaving this empty will allow any
plugins to be installed. Plugins are not automatically installed but can be installed by the
user. Plugins not on the list but installed by the user will be removed automatically,
including its dependencies. The plugins are cleaned up at `update-status` hook trigger. If the
`restart-time-range` configuration option is provided, the plugins are cleaned up during the
defined time range.

On trigger it will:

1. Delete any plugins and its dependencies that are installed but is not defined on the list.
2. Set a system message on Jenkins indicating which user installed plugins have been deleted.

```
juju config jenkins-k8s plugins=<allowed-plugins-csv>

# plugins example: `git, azure-cli, aws-credentials` will allow git, azure and aws-credentials
plugins to be installed.
```
