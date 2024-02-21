# How to integrate with IAM

This charm supports integration with the [IAM bundle](https://charmhub.io/iam) via [Oathkeeper](https://charmhub.io/oathkeeper), adding an authentication layer that will front the Jenkins applications. When enabled, the [reverse-proxy-auth-plugin](https://plugins.jenkins.io/reverse-proxy-auth-plugin/) will be installed and configured, blocking unauthorised access to Jenkins.

The steps to enable this mechanism are described below.

## Deploy the IAM bundle

To deploy the IAM bundle, follow [the corresponding section of the tutorial](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial#heading--0001) and configure it with the Identity Provider of your choice, as described in [the documentation](https://charmhub.io/topics/canonical-identity-platform/tutorials/e2e-tutorial#heading--0002).

## Deploy Oathkeeper

Oathkeeper will interface between Jenkins and the IAM bundle. You will need to deploy the charm and issue and configure TLS certificates for in-cluster communication. Note that the [self-signed-certificates charm](https://charmhub.io/self-signed-certificates) is already deployed as part of the IAM bundle.

```
juju deploy oathkeeper --channel edge --trust
juju integrate oathkeeper:certificates self-signed-certificates
```

To leverage proxy authentication, enable traefiks feature and integrate the traefik charm instante with oathkeeper. As earlier, traefik-public is already deployed as part of the bundle.
```
juju config traefik-public enable_experimental_forward_auth=True
juju integrate oathkeeper traefik-public:experimental-forward-auth
```

Finally, integrate Oathkeeper with [Kratos](https://charmhub.io/kratos), the User Management system, also part of the IAM bundle.
```
juju integrate oathkeeper kratos
```

## Configure the Jenkins charm

Jenkins needs to be accessible via the same ingress in which Oathkeeper has been configured for the requests to be redirected, so upon integrating with it and with Oathkeeper itself. Authentication is set up in place.
```
juju integrate jenkins-k8s:ingress traefik-public
juju integrate oathkeeper jenkins-k8s:auth-proxy
```
