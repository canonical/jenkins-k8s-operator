# JCasC (Jenkins Configuration as Code) Implementation Plan

**Epic:** [ISD-5501](https://warthogs.atlassian.net/browse/ISD-5501)
**Repo:** `canonical/jenkins-k8s-operator`
**Branch base:** `main` (after PR #374 merges)

---

## Overview

Add the `configuration-as-code` Jenkins plugin as a default plugin and expose a `jcasc-config` charm config option. JCasC is always active. The charm writes merged YAML (user config + charm-managed sections) to the workload, validates via the live check endpoint, and reloads Jenkins via the JCasC API.

---

## Design Decisions (Resolved)

| Decision | Answer |
|----------|--------|
| Auth proxy | Always via JCasC. Charm merges its auth_proxy config. Block if user supplies `securityRealm` while auth_proxy integrated |
| Conflict detection | Top-level key (e.g. `securityRealm`, `credentials`) |
| Validation | Live `/configuration-as-code/check` endpoint |
| Plugin version | Pinned, baked into rockcraft.yaml |
| Empty config | Block the charm — config must not be empty |
| Reconcile frequency | Every event (inside `_reconcile`) |
| Plugin management | Separate from JCasC (`allowed-plugins` unchanged) |
| Default config | Non-empty YAML baseline — fresh deploy works OOTB |
| Admin credentials | Charm injects admin credentials section if user config omits it |
| Secrets | Admin password via Juju secret → `JENKINS_ADMIN_PASSWORD` env var → `${JENKINS_ADMIN_PASSWORD}` in JCasC |
| JCasC plugin installs | Not supported upstream — plugins managed separately |
| Secret rotation | Later (ISD-5875) |
| User secrets mapping | Later (ISD-5874) |

---

## Default JCasC Configuration

The `jcasc-config` charm config option has this default value:

```yaml
jenkins:
  systemMessage: "Managed by jenkins-k8s charm via JCasC\n"
  numExecutors: 0
  securityRealm:
    local:
      allowsSignup: false
      users:
        - id: "admin"
          password: "${JENKINS_ADMIN_PASSWORD}"
  authorizationStrategy:
    loggedInUsersCanDoAnything:
      allowAnonymousRead: false
  crumbIssuer:
    standard:
      excludeClientIPFromCrumb: true
  remotingSecurity:
    enabled: true
```

---

## Charm-Managed Sections (Auto-Injected)

### Admin credentials (always injected if missing)

If user-provided JCasC config does NOT contain `jenkins.securityRealm` with admin user config, the charm injects:

```yaml
jenkins:
  securityRealm:
    local:
      allowsSignup: false
      users:
        - id: "admin"
          password: "${JENKINS_ADMIN_PASSWORD}"
```

### Auth proxy (injected when relation is active)

When `auth_proxy` relation is integrated, the charm injects:

```yaml
jenkins:
  securityRealm:
    oic:
      clientId: "${AUTH_PROXY_CLIENT_ID}"
      clientSecret: "${AUTH_PROXY_CLIENT_SECRET}"
      # ... remaining OIDC config from auth_proxy relation data
```

**Conflict rule:** If user-provided config contains `securityRealm` at the top level under `jenkins` AND auth_proxy is integrated → `BlockedStatus("JCasC conflict: 'securityRealm' is managed by auth_proxy relation, remove from jcasc-config")`.

---

## Implementation Tasks

### Task 1: Add `configuration-as-code` plugin to rockcraft.yaml

**Files:** `rockcraft.yaml`

- Pin `configuration-as-code` plugin to latest stable version (check [plugins.jenkins.io](https://plugins.jenkins.io/configuration-as-code/))
- Add plugin .hpi to the rock image at build time under `/usr/share/jenkins/ref/plugins/`
- Verify plugin is loaded on Jenkins startup

### Task 2: Add `jcasc-config` charm config option

**Files:** `charmcraft.yaml`

```yaml
config:
  options:
    jcasc-config:
      type: string
      description: |
        Jenkins Configuration as Code (JCasC) YAML content. This is the declarative
        way to manage Jenkins configuration (security, clouds, credentials, views, etc.).
        The charm auto-injects admin credentials if not provided, and auth proxy config
        when the relation is active. Must not be empty.
        See https://www.jenkins.io/projects/jcasc/ for schema reference.
      default: |
        jenkins:
          systemMessage: "Managed by jenkins-k8s charm via JCasC\n"
          numExecutors: 0
          securityRealm:
            local:
              allowsSignup: false
              users:
                - id: "admin"
                  password: "${JENKINS_ADMIN_PASSWORD}"
          authorizationStrategy:
            loggedInUsersCanDoAnything:
              allowAnonymousRead: false
          crumbIssuer:
            standard:
              excludeClientIPFromCrumb: true
          remotingSecurity:
            enabled: true
```

### Task 3: Add `CASC_JENKINS_CONFIG` to Pebble layer environment

**Files:** `src/charm.py` (in `calculate_env()`)

Add to the environment dict:

```python
"CASC_JENKINS_CONFIG": "/var/lib/jenkins/jenkins.yaml",
"JENKINS_ADMIN_PASSWORD": self._get_admin_password(),
```

The admin password is read from the Juju secret the charm already creates.

### Task 4: Add JCasC state to `state.py`

**Files:** `src/state.py`

Add a `JcascConfig` dataclass or property to `State`:

```python
@property
def jcasc_config(self) -> str:
    """Raw JCasC YAML from charm config."""
    return self._charm_config.get("jcasc-config", "")
```

### Task 5: Implement `_reconcile_jcasc()` in charm.py

**Files:** `src/charm.py`

```python
def _reconcile_jcasc(self, container: ops.Container, state: State) -> None:
    """Reconcile JCasC configuration."""
    raw_config = state.jcasc_config

    # 1. Block if empty
    if not raw_config.strip():
        self.unit.status = ops.BlockedStatus(
            "jcasc-config must not be empty"
        )
        return

    # 2. Parse YAML
    try:
        user_config = yaml.safe_load(raw_config)
    except yaml.YAMLError as e:
        self.unit.status = ops.BlockedStatus(
            f"Invalid JCasC YAML: {e}"
        )
        return

    # 3. Conflict check (top-level keys)
    charm_managed_keys = set()
    if state.auth_proxy_integrated:
        charm_managed_keys.add("securityRealm")

    jenkins_section = user_config.get("jenkins", {})
    conflicts = charm_managed_keys & set(jenkins_section.keys())
    if conflicts:
        self.unit.status = ops.BlockedStatus(
            f"JCasC conflict: {conflicts} managed by charm, remove from jcasc-config"
        )
        logger.warning("JCasC conflicts with charm-managed keys: %s", conflicts)
        return

    # 4. Inject admin credentials if missing
    if "securityRealm" not in jenkins_section:
        jenkins_section["securityRealm"] = {
            "local": {
                "allowsSignup": False,
                "users": [{"id": "admin", "password": "${JENKINS_ADMIN_PASSWORD}"}],
            }
        }
        user_config.setdefault("jenkins", {}).update(jenkins_section)

    # 5. Inject auth proxy config if relation active
    if state.auth_proxy_integrated:
        jenkins_section["securityRealm"] = self._build_auth_proxy_realm(state)
        user_config["jenkins"] = jenkins_section

    # 6. Write if changed
    desired_yaml = yaml.dump(user_config, default_flow_style=False)
    jcasc_path = "/var/lib/jenkins/jenkins.yaml"
    try:
        current = container.pull(jcasc_path).read()
    except (ops.pebble.PathError, FileNotFoundError):
        current = ""

    if current != desired_yaml:
        container.push(jcasc_path, desired_yaml)
        # 7. Validate via live check endpoint
        if not self.jenkins.check_jcasc():
            self.unit.status = ops.BlockedStatus(
                "JCasC validation failed — check juju debug-log for details"
            )
            # Rollback
            if current:
                container.push(jcasc_path, current)
                self.jenkins.reload_jcasc()
            return
        # 8. Apply
        self.jenkins.reload_jcasc()
```

Place in reconcile loop after `_reconcile_pebble` (Jenkins must be running):

```python
self._reconcile_pebble(container, state)
self._reconcile_jcasc(container, state)  # NEW
self._reconcile_agents(event, state)
self._reconcile_agent_discovery()
self._reconcile_auth_proxy(event, state)
```

### Task 6: Add JCasC methods to `jenkins.py`

**Files:** `src/jenkins.py`

```python
def reload_jcasc(self) -> None:
    """Reload JCasC configuration without restarting Jenkins."""
    self._client.requester.post_url(
        f"{self.url}/configuration-as-code/reload"
    )

def check_jcasc(self) -> bool:
    """Validate JCasC config via the check endpoint.

    Returns:
        True if config is valid, False otherwise.
    """
    try:
        response = self._client.requester.post_url(
            f"{self.url}/configuration-as-code/check"
        )
        return response.status_code == 200
    except Exception as e:
        logger.error("JCasC validation failed: %s", e)
        return False
```

### Task 7: Inject admin password env var from Juju secret

**Files:** `src/charm.py`

In `calculate_env()` or the Pebble layer builder, read the admin password from the Juju secret and add it as an environment variable:

```python
def _get_admin_password(self) -> str:
    """Get admin password from Juju secret."""
    secret = self.model.get_secret(label="admin-password")
    content = secret.get_content()
    return content["password"]
```

Add to Pebble env:

```python
"JENKINS_ADMIN_PASSWORD": self._get_admin_password(),
```

### Task 8: Remove XML template config application from bootstrap

**Files:** `src/pebble.py`, `src/jenkins.py`

Since JCasC is now the source of truth:
- Remove `_install_configs()` call from `bootstrap()` — config.xml is no longer written by the charm
- Keep `wait_ready()` and the initial restart for wizard bypass
- The `DEFAULT_JENKINS_CONFIG` and `AUTH_PROXY_JENKINS_CONFIG` XML templates can be deprecated (remove in follow-up)

**Note:** bootstrap still needs to:
1. Start Jenkins
2. Wait for ready
3. Install logging config
4. JCasC auto-applies from `CASC_JENKINS_CONFIG` env var on startup

### Task 9: Auth proxy JCasC builder

**Files:** `src/charm.py` (new method)

```python
def _build_auth_proxy_realm(self, state: State) -> dict:
    """Build JCasC securityRealm for auth proxy (OIDC)."""
    return {
        "oic": {
            "clientId": "${AUTH_PROXY_CLIENT_ID}",
            "clientSecret": "${AUTH_PROXY_CLIENT_SECRET}",
            "authorizationServerUrl": state.auth_proxy_config.authorization_url,
            "tokenServerUrl": state.auth_proxy_config.token_url,
            "userInfoServerUrl": state.auth_proxy_config.userinfo_url,
            # ... additional OIDC parameters from relation data
        }
    }
```

Also inject auth proxy env vars into Pebble layer when relation is active.

### Task 10: Unit tests

**Files:** `tests/unit/test_jcasc.py` (new), updates to existing test files

- Test `_reconcile_jcasc` with valid config → writes file, reloads
- Test empty config → BlockedStatus
- Test invalid YAML → BlockedStatus
- Test conflict detection (user provides `securityRealm` + auth_proxy active) → BlockedStatus
- Test admin credentials injection when missing from user config
- Test auth proxy injection when relation active
- Test no-op when config unchanged
- Test validation failure → rollback + BlockedStatus
- Test `check_jcasc()` and `reload_jcasc()` methods

### Task 11: Integration tests

**Files:** `tests/integration/test_jcasc.py` (new)

- Deploy with default config → Jenkins configured correctly
- Change `jcasc-config` → Jenkins picks up new config
- Set config with `securityRealm` + integrate auth_proxy → charm blocks
- Set invalid YAML → charm blocks
- Set empty config → charm blocks
- Verify admin password works after fresh deploy

---

## Dependency Order

```
Task 1 (rockcraft) ─────────┐
Task 2 (charmcraft config) ──┤
Task 3 (pebble env) ─────────┤── can be done in parallel
Task 4 (state.py) ────────────┤
Task 7 (admin secret env) ────┘
         │
         ▼
Task 8 (remove XML templates from bootstrap)
         │
         ▼
Task 5 (reconcile_jcasc) ←── Task 6 (jenkins.py methods)
         │                         │
         ▼                         ▼
Task 9 (auth proxy builder)
         │
         ▼
Task 10 (unit tests)
         │
         ▼
Task 11 (integration tests)
```

---

## Future Work (Separate Tickets)

- **ISD-5874:** Generalized Juju secrets → env var mapping for user-defined secrets
- **ISD-5875:** Admin password secret rotation support
- Remove deprecated XML config templates entirely
- Consider migrating `allowed-plugins` to a `plugins.yaml` mechanism baked into the rock

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| JCasC check endpoint not available during startup | Only call check after `wait_ready()` confirms Jenkins is up |
| Plugin not loaded on first boot (race) | Bake into rock image, not runtime install |
| Existing deployments have no `jcasc-config` set | Default value in charmcraft.yaml ensures non-empty config on upgrade |
| Auth proxy relation data changes mid-reconcile | Reconcile runs on every event — next event picks up new state |
| JCasC reload fails silently | Check HTTP response, log errors, set appropriate status |

---

## Related Tickets

- [[ISD-5501]] — Epic: Jenkins JCasC
- [[ISD-5874]] — Secrets mapping (Juju secrets → env vars for JCasC interpolation)
- [[ISD-5875]] — Admin password secret rotation
