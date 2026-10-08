# Configurations

See [Configurations](https://charmhub.io/jenkins-k8s/configure).

> Read more about configurations in the Juju docs: [Configuration](https://canonical.com/juju/docs/juju-cli/3.6/reference/configuration/)

## OpenSSH Proxy Configuration

By default Jenkins uses a built-in Java SSH client. Users may configure Jenkins
to use the OpenSSH client available on the host. To facilitate this in environments
behind a proxy, the client needs to first establish a TCP tunnel.

When Juju proxy variables are set, the charm automatically configures OpenSSH
clients in the Jenkins server container to tunnel through the model proxy:

```bash
juju model-config juju-https-proxy=http://squid.example.com:3128
```

The charm reads `JUJU_CHARM_HTTPS_PROXY`, falling back to `JUJU_CHARM_HTTP_PROXY`.
The selected URL must use `http://` without credentials. TLS connections to the
proxy and proxy authentication are not supported and cause the charm to block.

The charm manages `/etc/ssh/ssh_config.d/00-jenkins-proxy.conf` using the
`netcat-openbsd` helper included in the Jenkins rock. All SSH destinations 
use the proxy regardless of `juju-no-proxy`.