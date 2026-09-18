# How to integrate with external agent charms

We consider any agent charm to be `external` when they don't have layer 3 connectivity with the `jenkins-k8s` charm. To integrate with those agent charms, we'll leverage the `jenkins-k8s` charm's `agent-discovery-ingress` integration.

The `agent-discovery-ingress` integration can be used with any charm that supports the `:ingress` interface. One example is the [traefik-k8s](https://charmhub.io/traefik-k8s) charm.
```bash
juju integrate jenkins-k8s:agent-discovery-ingress traefik-k8s:ingress
```

Agents considered `external` have to be integrated using a cross-model integration. To integrate with such agent, simply integrate with the ingress provider charm as mentioned above and then integrate with the agent charm's offer endpoint.
```bash
juju integrate jenkins-k8s:agent-discovery-ingress traefik-k8s:ingress
juju integrate jenkins-k8s:agent <offer-endpoint>
```

## Route selection

The `agent-discovery-ingress` relation is independent from the Jenkins server
`ingress` relation. When both are related, the dedicated agent URL is preferred.
If only `ingress` is related, it is used as the agent fallback and the charm
warns that the route may be protected. A pending ingress endpoint puts the charm
in `WaitingStatus` instead of publishing a pod address.

The `haproxy-route` relation is a server/browser route and is never used as an
agent endpoint. If agents are related, direct HAProxy routing requires either a
dedicated `agent-discovery-ingress` route or a server `ingress` fallback. A
related `haproxy-route` also requires `external-hostname`. A non-root server
ingress path cannot be combined with `haproxy-route`; the charm enters
`BlockedStatus` rather than exposing a mismatched Jenkins prefix.

## Networking considerations
The charm assumes that:
1. There are connectivity between the Juju controller of the `jenkins-k8s` charm and the Juju controller of the agent charm trying to connect with the `jenkins-k8s` charm.
2. The agent can resolve the ingress host name provided by the `jenkins-k8s` charm and the resulting IP address is reachable, and there are firewall rules in place to allow HTTP traffic.
3. In case a reverse proxy is present, it is also expected that the HTTP connection coming from the agent charm is allowed to be upgraded into a WebSocket connection. The reverse proxy should also be configured with a suitable idle timeout for WebSocket connections to avoid intermittent agent disconnection.

## Preserve manually managed nodes

A Jenkins node can be managed outside Juju, including through the Jenkins UI, REST API, or
external automation. These nodes do not need to be configured through JCasC or Git.

Declare their names in the `external-agent-nodes` charm configuration so relation reconciliation
can detect name collisions and preserve them:

```bash
juju config jenkins-k8s external-agent-nodes="toronto-switch-backup,baremetal-ppc64el-1"
```

This configuration is an ownership declaration only. The charm does not create, configure, or
delete the listed nodes. Labels, executors, launch settings, workspace paths, and credentials
remain managed by the external system.

Relation-managed agent nodes are cleaned up when their relation departs. During reconciliation,
any Jenkins node that is not present in a current agent relation is also removed unless its name is
listed in `external-agent-nodes`. Ensure every externally managed node is listed before enabling
this configuration, otherwise it will be treated as unmanaged and removed.
