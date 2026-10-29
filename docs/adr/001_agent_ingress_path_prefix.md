---
title: ADR-001 - agent ingress must carry the Jenkins path prefix
author: Yanks Yoon (yangsoo.yoon@canonical.com)
date: 2026/10/28
domain: architecture
replaced-by:
---

# Agent ingress must carry the Jenkins path prefix

Jenkins serves the UI and the agent protocol from one global URL prefix. The
`agent-discovery-ingress` route must expose the same path as the server
`ingress` route and must not strip it.

## Context

The charm exposes two ingress relations that use the `ingress` interface:

- `ingress` serves the Jenkins UI.
- `agent-discovery-ingress` serves agent discovery and the agent connection.

Jenkins starts once with `--prefix=<path>`, and everything it serves moves under
that prefix: the UI, `/jnlpJars/agent.jar`, the per-agent `.jnlp` file, and the
agent WebSocket. The path comes from the server `ingress` URL.

Traefik publishes `/{model}-{app}` in path routing mode and
`{app}.{external_hostname}` in subdomain mode. The agent requirer used to send
`strip_prefix=True`, so Traefik removed the path prefix before forwarding the
request.

```
browser --+                        +-- agent
          |                        |
   traefik:server            traefik:agent
   PathPrefix(/x)            PathPrefix(/x)
   no strip                  strip /x      <-- prefix removed
          |                        |
          +--------> Jenkins <-----+
                     --prefix=/x
                     serves /x/... only
```

That made the first agent request work when Jenkins ran at the root, but Jenkins
builds the agent JNLP from the request it receives:

```
GET  http://agents.example.com/jenkins-jenkins-k8s/computer/a/jenkins-agent.jnlp
JNLP <argument>-url</argument><argument>http://agents.example.com/</argument>
GET  http://agents.example.com/login   -> 404 (no router matches "/")
```

The agent retried and never registered. The same defect affected the previously
allowed combination of a root server ingress with a path-mode agent route, so
the block on non-root server paths was hiding the defect rather than preventing
a separate risk.

## Decision

Jenkins has one prefix, so both routes must agree on it.

1. The agent ingress requirer does not strip the path.
2. The Jenkins prefix is the server `ingress` path, else the
   `agent-discovery-ingress` path, else the root (`""`). The agent route may
   define the prefix when no server ingress is related.
3. `agent-discovery-ingress` is blocked when both relations are ready and their
   paths differ. Pending relation data keeps `WaitingStatus`.
4. The metrics path and the pod-IP agent fallback use the same resolved prefix.
5. `haproxy-route` publishes the resolved prefix as the route path, the same
   contract the `ingress` relation uses. HAProxy forwards `/<prefix>/...`
   unchanged, so a browser route can serve a Jenkins that runs under a prefix.

| Server route | Agent ingress | Result |
|---|---|---|
| `ingress` at root (subdomain) | root (subdomain) | works, Jenkins at the root |
| `ingress` at `/x` (path) | `/x` (path) | works, Jenkins runs `--prefix=/x` |
| not related | `/x` (path) | works, the agent route defines the prefix |
| `ingress` at `/x` | root, or a different path | blocked, one prefix cannot serve both |
| `haproxy-route` | `/x` (path) | works, HAProxy routes and forwards `/x`, Jenkins runs `--prefix=/x` |
| `haproxy-route` | root (subdomain) | works, Jenkins at the root, HAProxy routes the whole host |

The `haproxy-route` rows depend on the provider accepting `paths` from the
`haproxy-route` v2 interface and rendering it as a `path_beg` ACL without a
path rewrite. A browser therefore reaches Jenkins at
`https://<hostname><prefix>`, not at the hostname root.

## Consequences

- Path routing works for a dedicated agent route because both relations publish
  the same `{model}-{app}` path.
- An agent-only path-mode deployment works instead of failing silently.
- Mixed path and subdomain routing is blocked, because it cannot work with one
  prefix.
- The two routes are separate addresses, not a security boundary. The UI route
  still proxies `/jnlpJars/agent.jar` and the agent JNLP. Isolation needs
  network policy or an authenticating proxy in front of the UI route.

## Alternatives considered

**Keep stripping the prefix.** Rejected. It fixes the first request and breaks
the JNLP handshake, which makes the agent retry against a path no route serves.
Stripping only works for applications that generate relative URLs.

**Use a different path for each route.** Rejected. The `ingress` interface always
publishes `{model}-{app}` for the requirer, so both routes always carry the same
path. A distinct path would need the `traefik-route` interface with a custom
rule, and the agent route would still have to serve the prefix that the JNLP
advertises.

**Rewrite the path with `addPrefix` before Jenkins.** Rejected. The JNLP
advertises `http://<host><prefix>/`, so an agent on another path would call the
prefix next, which that route does not serve.

**Keep Jenkins at the root and strip on both routes.** Rejected. Jenkins emits
absolute URLs for redirects and static resources, so the UI breaks behind a
path.
