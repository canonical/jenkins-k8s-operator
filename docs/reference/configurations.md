# Configurations

See [Configurations](https://charmhub.io/jenkins-k8s/configure).

> Read more about configurations in the Juju docs: [Configuration](https://canonical.com/juju/docs/juju-cli/3.6/reference/configuration/)

## OpenSSH Proxy Configuration

By default Jenkins uses a built-in Java SSH client. Users may configure Jenkins
to use the OpenSSH client included in the Jenkins server container. To route
those SSH connections through an HTTP proxy, set the optional
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
