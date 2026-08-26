# How to set up OIDC authentication via HAProxy SPOE

This guide fronts Jenkins with HAProxy and enforces OIDC login at the edge
using HAProxy's SPOE `haproxy-spoe-auth` charm. Jenkins keeps its own security
realm; HAProxy guards browser access to the configured hostname. No identity
headers are passed to Jenkins — this is edge access control only.

## Deployment graph

    jenkins-k8s ──haproxy-route──> haproxy ──spoe-auth──> haproxy-spoe-auth ──oauth──> <OIDC provider>

Machine agents must not go through SPOE because they cannot perform browser
OIDC. Keep agents on the dedicated `agent-discovery-ingress` relation. For the
PS7 topology, connect that relation to `ingress-configurator`, then connect
`ingress-configurator:gateway-route` to `gateway-api-integrator`. The server
hostname and agent hostname must be distinct. Removing `agent-discovery-ingress`
restores the legacy fallback path; keep it related while Gateway API is being repaired.

## Prerequisites

- An OIDC provider. For testing, a lightweight containerized provider (Dex, Keycloak,
  or a mock OIDC server) is sufficient — the full Canonical Identity Platform
  (Kratos/Hydra) is NOT required.
- The `oauth-external-idp-integrator` charm to bridge that provider onto the
  `oauth` interface that `haproxy-spoe-auth` requires.

## Steps

1. Configure `external-hostname` on Jenkins to the protected server hostname
   (e.g. `jenkins.example.com`) and relate Jenkins to HAProxy:

       juju config jenkins-k8s external-hostname=jenkins.example.com
       juju integrate jenkins-k8s:haproxy-route haproxy

   Configure a distinct agent hostname on ingress-configurator and connect the
   agent route through Gateway API:

       juju config ingress-configurator hostname=jenkins-agent.example.com
       juju integrate jenkins-k8s:agent-discovery-ingress ingress-configurator:ingress
       juju integrate ingress-configurator:gateway-route gateway-api-integrator:gateway-route

2. Register an OIDC client at your provider for that hostname. Set the redirect
   URI to the value expected by `haproxy-spoe-auth` for `jenkins.example.com`
   (the charm builds it from its `hostname` config). Record the client_id and
   client_secret. Treat the secret as sensitive — never commit it.

3. Deploy and configure the integrator to point at your provider:

       juju deploy oauth-external-idp-integrator
       juju config oauth-external-idp-integrator \
         client_id=<CLIENT_ID> \
         client_secret=<CLIENT_SECRET> \
         issuer_url=<ISSUER_URL>

   (Set `authorization_endpoint`, `token_endpoint`, `jwks_endpoint`,
   `userinfo_endpoint`, and `scope` too if your provider does not expose a
   standard discovery document.)

4. Deploy `haproxy-spoe-auth`, set its `hostname` to the SAME value as Jenkins'
   `external-hostname`, and wire the chain:

       juju deploy haproxy-spoe-auth
       juju config haproxy-spoe-auth hostname=jenkins.example.com
       juju integrate haproxy-spoe-auth:oauth oauth-external-idp-integrator
       juju integrate haproxy:spoe-auth haproxy-spoe-auth

5. Browse to `https://jenkins.example.com`. HAProxy redirects unauthenticated
   users to the OIDC provider; after login they reach Jenkins' own login realm.

## Notes

- The protected `hostname` value is the join key: it must be identical across
  Jenkins' `external-hostname` config, the `haproxy-spoe-auth` `hostname` config,
  and the OIDC client's registered redirect URI.
- The Gateway API agent hostname must be distinct from the protected server
  hostname. Do not connect the agent route to the HAProxy SPOE hostname.
- Any credentials shown here are placeholders; substitute your own and keep
  secrets out of version control.
