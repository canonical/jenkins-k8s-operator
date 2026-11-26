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
| `jenkins.proxy` | When a Juju model proxy is configured | Merged, see below |

## Proxy precedence

When the Juju model has a proxy configured (`juju model-config
juju-http-proxy=...` and `juju-https-proxy=...`), the charm applies it to
Jenkins through the JCasC `jenkins.proxy` block. The charm merges its values
into any user-provided proxy block instead of replacing it:

- `name` and `port` always come from the Juju model proxy.
- `userName` and `secretPassword` come from the model proxy URL when the
  URL contains credentials (`http://user:password@host:port`). Otherwise the
  user-provided `userName` and `secretPassword` are kept.
- All other keys of the user proxy block (`noProxyHost`, `testUrl`, ...) are
  preserved.
- The charm never writes empty credentials.
Jenkins' JCasC `jenkins.proxy` block uses the `secretPassword` attribute
for the proxy password.

For example, with the model proxy
`http://alice:s3cret@proxy.example.com:3128` and the following user JCasC:

```yaml
jenkins:
  proxy:
    noProxyHost: localhost
    userName: myuser
    secretPassword: mypass
```

the rendered JCasC becomes:

```yaml
jenkins:
  proxy:
    noProxyHost: localhost
    userName: alice
    secretPassword: s3cret
    name: proxy.example.com
    port: "3128"
```

## Related configuration

The `ssh-proxy-address` option routes OpenSSH agent connections through a
proxy. It is independent of the Juju model proxy and does not support
credentials. See [Configurations](configurations.md).
