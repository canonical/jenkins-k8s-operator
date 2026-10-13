# Configurations

See [Configurations](https://charmhub.io/jenkins-k8s/configure).

> Read more about configurations in the Juju docs: [Configuration](https://canonical.com/juju/docs/juju-cli/3.6/reference/configuration/)

## OpenSSH Proxy Configuration

By default Jenkins uses a built-in Java SSH client. Users may configure Jenkins
to use the OpenSSH client included in the Jenkins server container. To route
those SSH connections through an HTTP proxy, set the experimental
`ssh-proxy-address` charm configuration:

```bash
juju config jenkins-k8s ssh-proxy-address=squid.example.com:3128
```

The value must be a `HOST:PORT` address without a URI scheme or credentials.
The feature is disabled when the value is empty. It is independent of the Juju
model proxy settings, which continue to control Jenkins and plugin network
traffic.

The charm manages `/etc/ssh/ssh_config.d/00-jenkins-proxy.conf` using the
`netcat-openbsd` helper included in the Jenkins rock. All SSH destinations use
the configured proxy when the feature is enabled. Proxy TLS and proxy
authentication are not supported. Disable `ssh-proxy-address` when the proxy
requires either.

Changing this setting does not restart Jenkins. OpenSSH reads this configuration
when each new SSH process starts, and the managed file is outside the Pebble
service plan. Existing SSH processes keep their current connection settings; new
processes use the updated proxy configuration.

### Security

The charm contacts the proxy with a plain HTTP `CONNECT` request that carries no
authentication. Use an internal or otherwise trusted proxy, and do not expose it
to the public internet. The proxy can see which SSH destination is contacted and
can drop or delay connections, but it cannot read or change the SSH session:
OpenSSH encrypts and authenticates the session end to end between the Jenkins
container and the SSH server.

Keep OpenSSH host key verification enabled. Host key verification is what stops
a hostile proxy or network from redirecting a connection to a different SSH
server. Use the `ssh-known-hosts` configuration to provide the host keys of the
servers that Jenkins connects to.

## OpenSSH Known Hosts Configuration

To let the Jenkins container verify the host keys of the SSH servers it connects
to, provide them with the experimental `ssh-known-hosts` charm configuration:

```bash
juju config jenkins-k8s ssh-known-hosts="git.example.com ssh-ed25519 AAAA..."
```

Provide one entry per line, in `known_hosts` format. Use `HOST` to cover the
default port 22, or `[HOST]:PORT` for a server that listens on another port.
Comment lines are ignored. Hashed entries and the `@cert-authority` and
`@revoked` markers are accepted. Malformed entries block the charm.

The charm writes the entries to `/etc/ssh/jenkins_known_hosts` and points
`GlobalKnownHostsFile` at that file from
`/etc/ssh/ssh_config.d/00-jenkins-known-hosts.conf`. The file applies to every
user in the container and is managed by the charm, so manual edits are removed on
the next reconcile. Hosts that are not listed keep the OpenSSH default behaviour,
which rejects unknown host keys in non-interactive sessions. Leaving the
configuration empty removes both files.

This setting is independent of `ssh-proxy-address`, and like it, it only affects
processes that use the OpenSSH client, such as job steps that run `ssh`, `git`
over SSH, or `rsync`. Jenkins plugins that use their own SSH implementation keep
their own host key settings. Changing the setting does not restart Jenkins,
because OpenSSH reads it for each new process.

Pin the servers that Jenkins connects to instead of disabling host key
verification.
