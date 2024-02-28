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

# Networking considerations
The charm assumes that:
1. There are connectivity between the juju controller of the `jenkins-k8s` charm and the juju controller of the agent charm trying to connect with the `jenkins-k8s` charm.
2. The agent can resolve the ingress hostname provided by the `jenkins-k8s` charm and the resulting IP address is reachable, and there are firewall rules in place to allow HTTP traffic.
3. In case a reverse proxy is present, it is also expected that the HTTP connection coming from the agent charm is allowed to be upgraded into a Websocket connection.
