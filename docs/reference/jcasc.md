# JCasC configuration

Jenkins Configuration as Code (JCasC) manages Jenkins through declarative
YAML. The charm exposes it through two configuration options:

- `jcasc-config`: inline JCasC YAML.
- `jcasc-repository`: JCasC YAML fetched from a git repository. The options
  `jcasc-repository-token` and `jcasc-repository-config-path` configure
  authentication and the repository path to read.

The two options are mutually exclusive. Setting both blocks the charm.

## Charm-managed sections

The charm merges the user-provided JCasC YAML with sections it manages
itself. Charm-managed values take precedence over the same keys in the user
configuration.

| Section | When the charm sets it | Precedence |
|---|---|---|
| `jenkins.securityRealm` | Only when the user configuration has no `securityRealm` | User configuration wins if present |
| `jenkins.disabledAdministrativeMonitors` | Always | The charm always wins |
| `jenkins.proxy` | When a Juju model proxy is configured | The model proxy owns the block, see below |

## Proxy precedence

When the Juju model has a proxy configured (`juju model-config
juju-http-proxy=...` and `juju-https-proxy=...`), the charm owns the whole
JCasC `jenkins.proxy` block. When both settings are set, the charm uses
`juju-https-proxy` and falls back to `juju-http-proxy` only when the HTTPS
setting is absent, so place the proxy credentials on `juju-https-proxy`. The block is built from the model proxy only;
user JCasC proxy configuration is never mixed in:

- `name` and `port` always come from the Juju model proxy.
- `userName` and `secretPassword` come from the model proxy URL when the URL
  contains credentials (`http://user:password@host:port`). Otherwise no
  credential keys are written.
- The charm never writes empty credentials.

When no model proxy is configured, the user JCasC `jenkins.proxy` block
passes through untouched.

For example, with the model proxy
`http://alice:s3cret@proxy.example.com:3128`, the rendered JCasC proxy block
becomes:

```yaml
jenkins:
  proxy:
    userName: alice
    secretPassword: s3cret
    name: proxy.example.com
    port: "3128"
```

Configure the proxy entirely through the Juju model, or entirely through
JCasC (by not setting a model proxy). A configured model proxy takes
precedence over the user JCasC proxy block.

## Related configuration

The `ssh-proxy-address` option routes OpenSSH agent connections through a
proxy. It is independent of the Juju model proxy and does not support
credentials. See [Configurations](configurations.md).
