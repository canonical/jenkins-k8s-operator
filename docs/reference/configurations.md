# Configurations

See [Configurations](https://charmhub.io/jenkins-k8s/configure).

> Read more about configurations in the Juju docs: [Configuration](https://canonical.com/juju/docs/juju-cli/3.6/reference/configuration/)

## `allowed-plugins`

Controls which plugins may remain installed on Jenkins.

| Value | Effect |
|---|---|
| Not set (default) | No allowlist is enforced; the charm **never removes** user-installed plugins. |
| Empty string (`""`) | Same as not set — no allowlist is enforced; user-installed plugins are left intact. |
| Comma-separated list (e.g. `"git,blueocean"`) | Only the listed plugins (plus required internal plugins) are allowed. Any installed plugin not on the list is **automatically removed** on the next `update-status` hook (or within the configured `restart-time-range`). |

> **Important:** an empty `allowed-plugins` value (`""`) and an unset value are intentionally treated the same way — both disable the allowlist and leave all user-installed plugins untouched. Only a non-empty list activates the cleanup behaviour.