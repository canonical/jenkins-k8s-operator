Here is the complete, updated review document. The implementation checklist at the bottom has been expanded so that **every single task** (A.1, A.2, B.1, etc.) has its own individual `- [ ]` checkbox for the agents to tick off as they work through the steps.

***

# PR #379 Review — Improvement & Test-Simplification Plan

**PR:** [canonical/jenkins-k8s-operator#379](https://github.com/canonical/jenkins-k8s-operator/pull/379)
**Branch:** `feature/jcasc-plugin` → `main`
**Epic:** [ISD-5501](https://warthogs.atlassian.net/browse/ISD-5501) (JCasC) · tickets ISD-5874 / ISD-5875
**Reviewer:** claude-opus-4.8
**Status:** COMPLETE — 8 findings (A–H) + race analysis + implementation sequencing. Last updated: 2026-06-25

> This file is the durable deliverable. It is updated section-by-section so the
> review survives context compaction. Each finding is self-contained: a smaller
> model can pick up any single `### Task` block and implement it without re-reading
> the whole PR.

---

## Scope Guardrail (READ FIRST)

This review covers **only code introduced by PR #379** (the cumulative `feature/jcasc-plugin`
branch — stacked PRs #380–382 are merged into it). Confirmed via:

- `git merge-base --is-ancestor main HEAD` → main is a clean ancestor.
- `git show main:src/jenkins.py | grep "def build_jcasc_config|sync_jcasc_config|reload_jcasc|check_jcasc"` → **none exist in main**; all four are new in this PR.

**Explicitly OUT OF SCOPE** (do NOT touch in this PR — pre-existing on `main`):

- `install_default_config` / `install_auth_proxy_config` (`src/jenkins.py`) — added by commit `07fa609` (PR #120), unchanged by `main..HEAD`. Even though JCasC now supersedes the legacy XML security installers, removing them is a separate cleanup PR.
- Any test smell in files NOT touched by `main..HEAD` (the diff touched the unit suite broadly, so most are in-scope — but verify per file before editing).

---

## Files In Play (all paths relative to repo root)

| File | Role in PR #379 |
|------|-----------------|
| `src/jenkins.py` | `build_jcasc_config` (1147–1200), `sync_jcasc_config` (1203–1245), dead `reload_jcasc`/`check_jcasc` (662–702), `JCASC_CONFIG_PATH`, `CONFIGURATION_HASH` env field (111) |
| `src/charm.py` | `_reconcile_pre_startup_configurations` (514–540), `_reconcile_jcasc_config` (542–581), `calculate_env` CONFIGURATION_HASH wiring (~183), reconcile order (212–218) |
| `src/state.py` | `_parse_jcasc_config` (229–242), `_parse_system_properties` (197–212), `ProxyConfig` (253–283), `State.jcasc_config` (306) |
| `src/pebble.py` | `system_properties` → JVM args (33) |
| `charmcraft.yaml` | `jcasc-config` (121–127), `system-properties` (114–120) config options |
| `tests/unit/test_charm_jcasc.py` | charm-level JCasC tests (321 lines) — **contains the bug-locking test** at 64–67 |
| `tests/unit/test_jenkins_jcasc.py` | `build/sync_jcasc_config` tests (296 lines) |
| `tests/unit/test_jenkins_credentials.py`, `test_jenkins_agents.py`, `test_jenkins_plugins.py`, `test_jenkins_readiness.py` | conditional-assertion test smells |

---

## Findings Index

| ID | Severity | Title | Type |
|----|----------|-------|------|
| A  | **High** | `securityRealm: {authorizationStrategy: unsecured}` is malformed JCasC | Correctness bug |
| G  | **Medium** | `jenkins:` with empty body crashes `build_jcasc_config` (TypeError) | Crash / input validation |
| D  | Medium | Removing `jcasc-config` leaves a stale file on disk and skips the restart hash | Edge case / state drift |
| B  | Medium | `reload_jcasc` / `check_jcasc` are dead code | Dead code |
| C  | Medium | `sync_jcasc_config` docstring promises a validate/reload/rollback lifecycle it does not implement | Misleading docs |
| E  | Medium | Unit tests use conditional assertions (`if expected: assert X else: assert Y`) | Test quality |
| F  | Low | `build_jcasc_config` redundant `get` + `setdefault().update()` double-merge | Minor cleanup |
| H  | Low (note) | Copyright header `2025` on new files (should be 2026) | Convention |

> Severity = reviewer's assessment of user impact, not a blocker gate. A/G/D are
> behavioural/crashes; B/C/E/F are maintainability/clarity. See the per-finding detail
> below and the "Implementation Sequencing" section at the end for smaller-model task order.

---

## Finding A — `securityRealm: {authorizationStrategy: unsecured}` is malformed JCasC  **[High]**

### What & where
`src/jenkins.py:1169–1174`, inside `build_jcasc_config`, auth-proxy branch:

```python
if auth_proxy:
    if "securityRealm" in jenkins_section:
        logger.warning("Security realm is managed user provided jcasc-config settings.")
    else:
        logger.warning("Bypassing Jenkins security, security via auth proxy assumed.")
        jenkins_section["securityRealm"] = {"authorizationStrategy": "unsecured"}
```

This serializes to:

```yaml
jenkins:
  securityRealm:
    authorizationStrategy: unsecured   # <-- WRONG: nested under securityRealm
```

### Why it's a bug
In the JCasC schema, `securityRealm` and `authorizationStrategy` are **sibling keys**
under `jenkins:`, not parent/child. Evidence:

1. JCasC plugin docs & community templates always show them as siblings under `jenkins:`
   (verified against plugins.jenkins.io/configuration-as-code and verifa.io getting-started).
2. **This repo's own legacy template** `templates/jenkins-auth-proxy-config.xml` (the XML this
   JCasC block is meant to replace) encodes the auth-proxy posture as two separate elements:
   ```xml
   <useSecurity>false</useSecurity>
   <authorizationStrategy class="hudson.security.AuthorizationStrategy$Unsecured"/>
   <securityRealm class="hudson.security.SecurityRealm$None"/>
   ```
   i.e. authorizationStrategy = Unsecured **and** securityRealm = None — two distinct settings.

The current code drops `authorizationStrategy` to a value-position string inside a
`securityRealm` map. The JCasC `configuration-as-code` plugin will fail to find a configurator
for `securityRealm.authorizationStrategy` and **either abort config loading or silently skip it**,
leaving Jenkins in its default (secured, admin-only) state. In auth-proxy mode that means the
reverse-proxy-authenticated requests can be rejected — the exact opposite of the intended bypass.

### Correct structure
```python
if auth_proxy:
    if "securityRealm" in jenkins_section or "authorizationStrategy" in jenkins_section:
        logger.warning(
            "Jenkins security is managed by user-provided jcasc-config; "
            "auth-proxy bypass not injected."
        )
    else:
        logger.warning("Bypassing Jenkins security, security via auth proxy assumed.")
        jenkins_section["securityRealm"] = "none"
        jenkins_section["authorizationStrategy"] = "unsecured"
```

Producing the correct:
```yaml
jenkins:
  securityRealm: "none"
  authorizationStrategy: "unsecured"
```

> NOTE for implementer: confirm the exact JCasC scalar spellings against the
> `configuration-as-code` plugin version pinned for this charm before finalizing
> (`securityRealm: "none"` and `authorizationStrategy: "unsecured"` are the documented
> short forms, but pin-verify). Do this with a quick `tox -e integration` auth-proxy run
> or the JCasC `/configuration-as-code/check` endpoint against a live unit.

### Task A.1 — fix the structure
- File: `src/jenkins.py`, `build_jcasc_config`, lines ~1169–1174.
- Replace the nested assignment with the two-sibling assignment above.
- Extend the user-managed guard to also detect a user-supplied `authorizationStrategy`
  (today only `securityRealm` is checked, so a user who sets `authorizationStrategy`
  but not `securityRealm` would still get the charm's realm injected at line 1177).

### Task A.2 — fix the test that locks in the bug
- File: `tests/unit/test_charm_jcasc.py`, `test_build_jcasc_config_security_realm_behavior`
  (lines 43–67). The assertion at line 65 currently asserts the **malformed** shape:
  ```python
  assert result["jenkins"]["securityRealm"] == {"authorizationStrategy": "unsecured"}
  ```
  Update it to assert the corrected sibling shape. (This test is ALSO a conditional-assertion
  smell — see Finding E, Task E.1, which folds the fix and the de-smelling together.)

### Task A.3 — add a structural regression test
- New parametrized test asserting that for auth-proxy mode the serialized YAML has
  `authorizationStrategy` as a **sibling** of `securityRealm` (not nested). Assert on the
  dict directly:
  ```python
  assert result["jenkins"]["securityRealm"] == "none"
  assert result["jenkins"]["authorizationStrategy"] == "unsecured"
  ```

### Verification
- `PYTHONPATH=src:lib uv run pytest tests/unit/test_charm_jcasc.py tests/unit/test_jenkins_jcasc.py -v`
- (If feasible) live JCasC validation via `/configuration-as-code/check` in an integration run.

---

## Finding B — `reload_jcasc` / `check_jcasc` are dead code  **[Medium]**

### What & where
`src/jenkins.py:662–676` (`reload_jcasc`) and `src/jenkins.py:678–702` (`check_jcasc`).
Both are methods on the Jenkins API-client class that POST to the live JCasC endpoints:

- `reload_jcasc` → `POST {web_url}/configuration-as-code/reload`
- `check_jcasc`  → `POST {web_url}/configuration-as-code/check` (returns `status == 200`)

### Why it's dead
Whole-repo grep (`grep -rn "reload_jcasc|check_jcasc" --include=*.py`) shows **zero production
callers**. The only references are their own unit tests in
`tests/unit/test_jenkins_jcasc.py:234–296`. The actual config-apply path
(`_reconcile_jcasc_config` → `sync_jcasc_config`) never calls either: it writes the file to disk
and lets a `CONFIGURATION_HASH` env-var change drive a Pebble restart (`src/charm.py:183`,
`216–218`).

This is the residue of an abandoned architecture: the original plan
(`.hermes/plans/jcasc-implementation.md`) said the charm would "validate via the live check
endpoint, and reload Jenkins via the JCasC API." That approach was dropped in favour of
write-to-disk + restart-on-hash, because JCasC is written during
`_reconcile_pre_startup_configurations` **before Jenkins is running** (see Finding C) — so a
live check/reload endpoint does not yet exist at apply time.

### Decision required (pick one — recommend B-remove)
- **B-remove (recommended, in scope):** delete both methods and their four tests. The
  restart-on-hash mechanism is the chosen design and already covers config changes. Dead code
  that LOOKS like a working validate/reload path is a maintenance trap.
- **B-wire (out of scope for #379):** wire `reload_jcasc` into a *post-startup* config-changed
  path so that JCasC edits to an already-running Jenkins reload without a full restart. This is a
  behavioural enhancement, not a review fix — file as a follow-up ticket, do not do it in #379.

### Task B.1 — remove dead methods
- Delete `reload_jcasc` (`src/jenkins.py:662–676`) and `check_jcasc` (`src/jenkins.py:678–702`).
- Remove now-unused imports if they become unused (check `jenkinsapi.custom_exceptions`,
  `requests.exceptions` are still used elsewhere — they are, so leave them).

### Task B.2 — remove their tests
- Delete from `tests/unit/test_jenkins_jcasc.py`:
  - `test_check_jcasc_returns_status_from_endpoint` (234–247)
  - `test_check_jcasc_raises_jenkins_error_on_request_exception` (250–264)
  - `test_reload_jcasc_posts_reload_endpoint` (267–280)
  - `test_reload_jcasc_raises_jenkins_error_on_request_exception` (282–296)

### Verification
- `PYTHONPATH=src:lib uv run pytest tests/unit/test_jenkins_jcasc.py -v`
- `tox run -e lint,static` — confirm no unused-import / vulture complaints reappear.

---

## Finding C — `sync_jcasc_config` docstring promises a lifecycle it does not implement  **[Medium]**

### What & where
`src/jenkins.py:1203–1245`. The docstring (1204–1222) claims:

```
Write JCasC config to disk, validate, and reload. Rollback on failure.

Handles the full JCasC file lifecycle:
1. Pull current config (if any)
2. Short-circuit if unchanged
3. Push desired config
4. Validate via Jenkins API      <-- NOT IMPLEMENTED
5. Reload if valid, rollback if invalid   <-- NOT IMPLEMENTED

Raises:
    JenkinsError: if Jenkins API calls fail (check/reload).   <-- never raised here
```

The body only does steps 1–3: pull current, hash-compare to short-circuit, push. It never
validates, reloads, or rolls back, and never raises `JenkinsError`.

### Why this is the correct behaviour (NOT a bug — do not "fix" by adding validation)
`sync_jcasc_config` runs inside `_reconcile_pre_startup_configurations` (`src/charm.py:514–540`),
which executes **before** the Pebble replan that starts Jenkins (`_reconcile` order:
`src/charm.py:212` writes config → `218` starts Jenkins). At write time:

- There is no running Jenkins, so `POST /configuration-as-code/check` has no server to hit.
- "Rollback" is meaningless: the new config only takes effect on the next boot, which is exactly
  the boot being prepared. Writing the file IS the apply.

So the validate/reload/rollback lifecycle is **architecturally impossible at this call site** and
correctly omitted. The defect is purely the **misleading docstring** (and the dead methods in
Finding B that the docstring still references).

### Task C.1 — correct the docstring to match reality
- File: `src/jenkins.py:1204–1222`. Rewrite to describe what the function actually does and why:

```python
def sync_jcasc_config(container: ops.Container, configuration_yaml: str) -> str:
    """Write the JCasC config file to the workload, short-circuiting if unchanged.

    JCasC is applied at Jenkins startup (the file is read by the configuration-as-code
    plugin when the service boots), so this runs before Jenkins is running. There is no
    live API to validate or reload against at this point; a config change is applied by
    writing the file and letting the changed CONFIGURATION_HASH env var trigger a Pebble
    restart (see charm.calculate_env / _reconcile_pebble).

    Steps:
    1. Pull the current on-disk config (empty string if absent).
    2. Short-circuit and return the existing hash if the content is unchanged.
    3. Push the desired config to disk.

    Args:
        container: The Jenkins workload container.
        configuration_yaml: The full YAML string to write.

    Returns:
        The SHA-256 hash of the configuration written (drives restart-on-change).
    """
```

- Remove the `Raises: JenkinsError` clause (the function does not raise it). NOTE: the caller
  `_reconcile_jcasc_config` (`src/charm.py:577–581`) wraps the call in
  `except jenkins.JenkinsError`. After this change that handler is dead for THIS call but is
  harmless; leave it or tighten to `ops.pebble.Error` in a follow-up. Do not expand scope here.

### Task C.2 — keep the TODO honest
- The in-body TODO (`src/jenkins.py:1230–1231`) about computing the hash via `pebble exec`
  instead of pulling the file is legitimate and can stay. Optionally convert to a tracked ticket
  reference rather than an inline TODO.

### Verification
- Docstring-only + comment change: `tox run -e lint,static` and the existing
  `tests/unit/test_jenkins_jcasc.py` sync tests must still pass.

---

## Finding D — Removing `jcasc-config` leaves a stale file on disk; config is never truly cleared  **[Medium]**

### What & where
`src/charm.py:563–564`, in `_reconcile_jcasc_config`:

```python
if charm_state.jcasc_config is None:
    return ""
```

`charm_state.jcasc_config` is `None` whenever the user-facing `jcasc-config` option is empty
(see `state._parse_jcasc_config`, `src/state.py:229–242`: blank/whitespace → `None`).

### The edge case (config drift on un-set)
Sequence:
1. User sets `jcasc-config` to some YAML → charm writes `${JENKINS_HOME}/jenkins.yaml`
   (`jenkins.JCASC_CONFIG_PATH`, defined `src/jenkins.py:53`) and `CONFIGURATION_HASH=<h1>`.
2. User later clears the option (`juju config jenkins-k8s jcasc-config=""`).
3. `_reconcile_jcasc_config` hits the `None` branch and returns `""` **without removing the
   file**. There is no `container.remove_path` anywhere in `src/` (verified by grep).
4. `calculate_env` sets `CONFIGURATION_HASH=""` (`src/charm.py:183`), which differs from `<h1>`,
   so Pebble replans and **restarts Jenkins**.
5. On restart, `CASC_JENKINS_CONFIG` still points at the on-disk `jenkins.yaml` (env always set,
   `src/charm.py:181`), so Jenkins **re-applies the stale config the user just tried to remove.**

Net effect: clearing `jcasc-config` triggers a restart but does NOT clear the configuration —
the old settings silently persist. This is a state-drift / least-surprise violation introduced
by this PR (the `None → return ""` branch is new).

### Design question for the implementer
What *should* "unset jcasc-config" mean? Two defensible answers — pick and make it explicit:

- **D-clear (recommended):** removing the option should remove the charm-managed JCasC file so
  Jenkins boots with only its built-in defaults + charm-injected admin realm. But note:
  `build_jcasc_config` also injects the admin `securityRealm` and `disabledAdministrativeMonitors`
  even for an otherwise-empty user config. So "cleared" likely should still write the
  charm-managed baseline (admin realm), NOT delete the file outright — otherwise admin login
  breaks. **Therefore the `None` branch should fall through to building config from an empty
  `{}` base, not early-return.**
- **D-keep:** document that JCasC, once set, is sticky and only changes when replaced. (Weaker;
  surprising to operators.)

### Task D.1 — make un-set apply the charm-managed baseline
- File: `src/charm.py`, `_reconcile_jcasc_config` (`542–581`).
- Replace the early `return ""` with building from an empty base so the admin realm and managed
  monitors are still written:
  ```python
  user_config = charm_state.jcasc_config or {}
  desired_config = jenkins.build_jcasc_config(
      user_config,
      charm_state.proxy_config,
      charm_state.auth_proxy_integrated,
  )
  ```
  i.e. drop the `if charm_state.jcasc_config is None: return ""` guard and pass `{}` through.
- Confirm `build_jcasc_config` is safe with `{}` input: it does `config.get("jenkins", {})`
  then `config.setdefault("jenkins", {}).update(...)` (`src/jenkins.py:1166,1199`), so an empty
  dict yields a valid `{"jenkins": {securityRealm..., disabledAdministrativeMonitors...}}`. ✓

### Task D.2 — (only if D-clear-delete is chosen instead) explicit file removal
- If the team decides un-set should delete the file entirely (NOT recommended, breaks admin
  login), add a `container.remove_path(str(jenkins.JCASC_CONFIG_PATH), recursive=False)` guarded
  by existence, and return a sentinel hash. Document the admin-login consequence. **Default to
  D.1, not this.**

### Task D.3 — test the un-set transition
- Parametrized test in `tests/unit/test_charm_jcasc.py` driving `_reconcile_jcasc_config` with
  `jcasc_config=None`:
  - asserts the written YAML still contains the injected admin `securityRealm`,
  - asserts a non-empty hash is returned (so the baseline is deterministic across reconciles and
    an un-set does not thrash the restart hash on every hook).

### Verification
- `PYTHONPATH=src:lib uv run pytest tests/unit/test_charm_jcasc.py -v`
- Manually reason through the hash: with D.1, two consecutive reconciles with `jcasc_config=None`
  must produce the **same** hash (no restart loop). Add an assertion for hash stability.

---

## Finding E — Conditional assertions in unit tests; parametrize values, don't branch  **[Medium]**

### Principle (the user's standing rule)
> Unit tests should have parametrized cases but **must not** contain conditional assertions.
> A test body that does `if <param>: assert A else: assert B` is two tests wearing a trench coat;
> the branch hides which case actually ran and lets a case silently assert nothing.

The PR's restructure (splitting the 1630-line `test_jenkins.py` into focused files) is a big
improvement and is correctly parametrized in most places. The remaining smell is **three distinct
anti-patterns**, catalogued below with exact locations and the mechanical fix for each.

> Scope note: the whole unit suite was restructured by THIS PR (`test_jenkins.py` 1630→~0,
> redistributed into `test_jenkins_*`/`test_charm_*`/`test_agent_*`), so every file below is
> in-scope. Counts from `grep -cE "^\s+if .+:$"` per file.

---

### Pattern E-α — conditional ASSERTION (the real defect)
A branch chooses which `assert` runs. When the condition is False the asserted-value branch is
skipped entirely, so the "success" case may assert **nothing**.

**Offender 1 — `tests/unit/test_charm_jcasc.py:43–67`** (also Finding A.2):
```python
@pytest.mark.parametrize(
    "auth_proxy_integrated, expects_unsecured",
    [pytest.param(True, True, id="..."), pytest.param(False, False, id="...")],
)
def test_build_jcasc_config_security_realm_behavior(auth_proxy_integrated, expects_unsecured):
    result = jenkins.build_jcasc_config(VALID_JCASC_CONFIG, proxy_config=None,
                                        auth_proxy=auth_proxy_integrated)
    if expects_unsecured:
        assert result["jenkins"]["securityRealm"] == {"authorizationStrategy": "unsecured"}  # bug shape!
    else:
        assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "admin"
```
Two different assertion *shapes* per branch — impossible to express as one expected value without
restructuring. **Fix: split into two intention-revealing tests** (they assert genuinely different
things, so this is the rare case where splitting beats parametrizing):
```python
def test_build_jcasc_config_auth_proxy_bypasses_security():
    result = jenkins.build_jcasc_config(VALID_JCASC_CONFIG, proxy_config=None, auth_proxy=True)
    # corrected sibling shape from Finding A
    assert result["jenkins"]["securityRealm"] == "none"
    assert result["jenkins"]["authorizationStrategy"] == "unsecured"

def test_build_jcasc_config_default_injects_admin_realm():
    result = jenkins.build_jcasc_config(VALID_JCASC_CONFIG, proxy_config=None, auth_proxy=False)
    assert result["jenkins"]["securityRealm"]["local"]["users"][0]["id"] == "admin"
```
> Rule of thumb: parametrize when cases differ only in **values**; split when they differ in
> **assertion structure**. This one differs in structure → split. (Folds in Finding A.2/A.3.)

**Offender 2 — `tests/unit/test_jenkins_agents.py:34–52`** (`test_list_agent_nodes`):
```python
if not raise_api_error:
    assert result == [mock_node]
# when raise_api_error is True: NOTHING about result is asserted
```
The error case relies solely on the `pytest.raises` context manager; the success case asserts the
return. They share almost no body. **Fix: split into two tests** — one asserts the raise, one
asserts the value — removing both the `if raise_api_error:` setup branch and the trailing
conditional assertion:
```python
def test_list_agent_nodes_success(container, mock_client):
    mock_node = MagicMock()
    mock_client.get_nodes.return_value = {"node": mock_node}
    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        assert list(_jenkins_instance(container).list_agent_nodes()) == [mock_node]

def test_list_agent_nodes_raises_on_api_error(container, mock_client):
    mock_client.get_nodes.side_effect = jenkinsapi.custom_exceptions.JenkinsAPIException()
    with patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client):
        with pytest.raises(jenkins.JenkinsError):
            list(_jenkins_instance(container).list_agent_nodes())
```

**Offender 3 — `tests/unit/test_jenkins_agents.py:55–75`** (`test_get_node_secret`): identical
shape to Offender 2 (`if not raise_api_error: assert node_secret == expected_secret`). Same fix:
split success/raise.

**Offender 4 — `tests/unit/test_jenkins_agents.py:170–186`** (delete-node path, the
`if not raise_api_error: mock_client.delete_node.assert_called_once_with(...)`): same fix.

### Task E.1 — de-smell `test_charm_jcasc.py` security-realm test
Split `test_build_jcasc_config_security_realm_behavior` into the two tests above, using the
**corrected** Finding-A sibling shape. This single task closes Finding A.2 + A.3 + E-α offender 1.

### Task E.2 — de-smell `test_jenkins_agents.py`
Split the four error/success conditional tests (`test_list_agent_nodes`, `test_get_node_secret`,
the delete-node test, and any sibling using `if not raise_api_error:`) into explicit
`_success` / `_raises_on_api_error` pairs. Removes 4–6 `if`-blocks from this file.

---

### Pattern E-β — conditional SETUP feeding a shared act/assert
Branches only build inputs/mocks; the act + assert are unconditional. Less harmful than E-α, but
the user's rule is "parametrize the values." Prefer moving the varying input INTO `parametrize`
via a factory/value, or use `pytest.param(..., marks=...)`.

**Example — `tests/unit/test_jenkins_readiness.py:159–185`** (`test_is_storage_ready_falsey_cases`):
```python
@pytest.mark.parametrize("case", ["no-container", "cant-connect", "not-mounted"])
def test_is_storage_ready_falsey_cases(case):
    if case == "no-container":
        container = None
    elif case == "cant-connect":
        ...
    else:
        ...
    assert not jenkins.is_storage_ready(container=container)
```
Parametrizing on a **string discriminator** then `if/elif`-ing on it inside the body is just a
`switch` — the parametrization buys nothing. **Fix: parametrize a container factory** so the body
has zero branches:
```python
def _no_container(): return None
def _cant_connect():
    c = MagicMock(ops.Container); c.can_connect.return_value = False; return c
def _not_mounted():
    c = MagicMock(ops.Container); c.pull.return_value = io.StringIO(""); return c

@pytest.mark.parametrize("make_container",
    [_no_container, _cant_connect, _not_mounted],
    ids=["no-container", "cant-connect", "not-mounted"])
def test_is_storage_ready_falsey_cases(make_container):
    assert not jenkins.is_storage_ready(container=make_container())
```

### Task E.3 — parametrize factories instead of string switches
- `tests/unit/test_jenkins_readiness.py` storage-ready falsey cases (above) and the
  `if exception_type is requests.exceptions.JSONDecodeError:` setup at 84–86.
- `tests/unit/test_jenkins_plugins.py:360–369` (`if failure_stage == ...`) — same factory/value
  treatment.
- `tests/unit/test_agent_reconcile.py:124–126` (`if error_stage == "add":`).

---

### Pattern E-γ — conditional context-manager (acceptable, leave or tidy)
```python
expected_ctx = pytest.raises(jenkins.JenkinsError) if raise_api_error else nullcontext()
```
(`test_jenkins_agents.py:38,58,93`; `test_auth_proxy.py:58`). This is a **legitimate** idiom and
NOT a conditional assertion — the assertion (does/doesn't raise) is encoded in the parametrized
context manager. **Recommendation:** where the success branch ALSO has a value to assert (E-α
offenders), split instead; where the test only checks raise-vs-not-raise with no extra value
assertion, the `expected_ctx` idiom is fine — leave it. Do not mass-rewrite γ.

### Helper-extraction note (matches user's test style: helpers for boilerplate)
The repeated
```python
with (patch.object(jenkins.Jenkins, "_get_api_client", return_value=mock_client), expected_ctx):
```
block recurs ~6× in `test_jenkins_agents.py`. After the E-α splits, extract a small helper
(e.g. `_patched_client(mock_client)` returning the `patch.object` CM) to kill the boilerplate,
keeping tests functional (not class-based) and free of section comments per house style.

---

### Finding E summary table (in-scope, this PR)

| File | `if`-blocks | Pattern | Task |
|------|-------------|---------|------|
| `test_charm_jcasc.py` | 1 | E-α | E.1 (folds A.2/A.3) |
| `test_jenkins_agents.py` | 6 | E-α + E-γ | E.2 |
| `test_jenkins_readiness.py` | 2 | E-β | E.3 |
| `test_jenkins_plugins.py` | 5 | E-β / E-γ | E.3 |
| `test_jenkins_credentials.py` | 2 | E-β setup | E.3 (low) |
| `test_agent_reconcile.py` | 2 | E-β | E.3 |
| `test_agent_discovery.py` | 2 | E-β setup (relation list build) | E.3 (low) |
| `test_auth_proxy.py` | 1 | E-γ | leave |

### Verification (all of Finding E)
- `PYTHONPATH=src:lib uv run pytest tests/unit/ -v` — full green.
- After each split, confirm BOTH new tests actually run and assert (no silently-empty case):
  `uv run pytest tests/unit/test_jenkins_agents.py -v` and eyeball the case IDs.
- `tox run -e lint` (functional style, no class wrappers, no section comments).
- Re-grep the smell is gone in touched files:
  `grep -rnE "if .+:\s*$" tests/unit/test_jenkins_agents.py tests/unit/test_charm_jcasc.py`.

---

## Finding F — `build_jcasc_config` redundant `get` + `setdefault().update()` double-merge  **[Low]**

### What & where
`src/jenkins.py:1166` and `:1199`:
```python
jenkins_section: typing.Dict[str, typing.Any] = config.get("jenkins", {})   # 1166
...
config.setdefault("jenkins", {}).update(jenkins_section)                     # 1199
```
When `config` already has a `jenkins` key, `jenkins_section` is the **same object** as
`config["jenkins"]`; every mutation (1174–1197) already lands in `config`. Line 1199 then
`update`s that dict with itself — a no-op. When `config` lacks the key, `jenkins_section` is a
detached `{}` and 1199 is what actually attaches it. So the function relies on object-identity
coincidence and the final `setdefault().update()` exists only to cover the missing-key branch.

### Why fix (clarity, not behaviour)
It reads as if it merges two dicts but mostly self-updates. The cleaner, intention-revealing form
also fixes Finding G's crash in one stroke:
```python
config = copy.deepcopy(jcasc_config)
jenkins_section = config.get("jenkins") or {}   # None-safe (Finding G)
... mutate jenkins_section ...
config["jenkins"] = jenkins_section             # single explicit assignment
return config
```

### Task F.1 — simplify the merge
- File: `src/jenkins.py`, `build_jcasc_config` lines 1166 + 1199.
- Use `config.get("jenkins") or {}` at the top and a single `config["jenkins"] = jenkins_section`
  at the bottom; drop the `setdefault().update()`. Behaviour-preserving for all dict inputs;
  also closes Finding G. Covered by existing `test_jenkins_jcasc.py` build tests + Finding G's new
  test.

---

## Finding G — `jenkins:` with an empty body crashes `build_jcasc_config` (`TypeError`)  **[Medium]**

### What & where (reproduced)
A user-supplied `jcasc-config` of just:
```yaml
jenkins:
```
is **valid YAML** that parses to `{"jenkins": None}`. It passes the only input guard
(`_parse_jcasc_config`, `src/state.py:240` — `isinstance(parsed, dict)` is True because the
*top level* is a dict). Then in `build_jcasc_config`:
```python
jenkins_section = config.get("jenkins", {})   # returns None (key EXISTS with value None)
if "securityRealm" in jenkins_section:        # TypeError: argument of type 'NoneType' is not iterable
```

Reproduced with the repo venv:
```
'jenkins:'  -> parsed={'jenkins': None}  jenkins_section=None
   >>> CRASH at line 1170: argument of type 'NoneType' is not iterable
```
(The `config.get("jenkins", {})` default only applies when the key is ABSENT; here the key is
present with value `None`, so the default is bypassed.)

### Impact
A single empty `jenkins:` line (easy operator mistake, or a partially-commented config) takes the
charm to **error state** on the config-changed hook instead of a clean `BlockedStatus`. The
top-level `isinstance(dict)` validation gives a false sense of safety because it doesn't validate
the value under `jenkins`.

### Task G.1 — None-safe section access (the real fix)
- File: `src/jenkins.py:1166`. Change `config.get("jenkins", {})` →
  `config.get("jenkins") or {}` so a `None` body collapses to `{}`. (Folded into Finding F.1.)

### Task G.2 — validate the value type at parse time (defence in depth, optional)
- File: `src/state.py`, `_parse_jcasc_config` (229–242). After the top-level dict check, if
  `"jenkins" in parsed and parsed["jenkins"] is not None and not isinstance(parsed["jenkins"], dict)`
  raise `CharmConfigInvalidError("jcasc-config 'jenkins' section must be a mapping")`. This turns
  a malformed non-empty `jenkins:` (e.g. `jenkins: "oops"`) into a clean BlockedStatus too. Keep
  empty (`None`) tolerated and normalized by G.1, not rejected — an empty section is a legitimate
  "charm-managed only" request (ties to Finding D).

### Task G.3 — regression tests
- `tests/unit/test_jenkins_jcasc.py`: parametrized `build_jcasc_config` test feeding
  `{"jenkins": None}` and `{}` and `{"jenkins": {}}`, asserting all three produce a valid dict
  with the injected admin `securityRealm` (no exception). Single expected-shape assertion per
  case — no conditional branches.
- `tests/unit/test_state.py`: assert `_parse_jcasc_config` tolerates `"jenkins:\n"` (→ normalized)
  and (if G.2 adopted) rejects `"jenkins: oops"` with `CharmConfigInvalidError`.

### Verification
- `PYTHONPATH=src:lib uv run pytest tests/unit/test_jenkins_jcasc.py tests/unit/test_state.py -v`
- Manual repro before/after:
  `PYTHONPATH=src:lib uv run python -c "import yaml,jenkins; print(jenkins.build_jcasc_config(yaml.safe_load('jenkins:')))"`
  — must NOT raise after the fix.

---

## Finding H — Inconsistent copyright year on newly-added files (`2025` vs `2026`)  **[Low / convention]**

### What & where
This PR adds 12 new test files. Six correctly carry `Copyright 2026`, six carry `Copyright 2025`.
New files created in 2026 must use 2026 (house convention; the user has flagged this exact
2025→2026 slip before, so check the WHOLE PR, not one file).

**Files ADDED by this PR with the wrong year (must become 2026):**
```
tests/unit/test_charm_events.py
tests/unit/test_charm_jcasc.py
tests/unit/test_charm_plugins.py
tests/unit/test_charm_reconcile.py
tests/unit/test_jenkins_credentials.py
tests/unit/test_jenkins_readiness.py
```
(Verified via `git diff main..HEAD --name-status | grep ^A` + header inspection. The other six
added files — `test_agent_discovery/reconcile`, `test_jenkins_agents/bootstrap/jcasc/plugins` —
already say 2026 and are correct.)

> Modified-but-not-added files (e.g. `src/jenkins.py`, `src/charm.py`, `src/state.py`) keep their
> original creation year per the usual "year of creation, not last edit" rule — do NOT bump those.
> This finding is strictly about the six NEW files above.

### Task H.1 — fix the six headers
- For each file above, change the header line `Copyright 2025 Canonical Ltd.` →
  `Copyright 2026 Canonical Ltd.` (match the exact format already used in the 2026 files).
- Re-run the audit to prove zero added-file mismatches remain:
  ```sh
  git diff main..HEAD --name-status -- '*.py' | grep '^A' | while read st f; do
    yr=$(head -2 "$f" | grep -oE '20[0-9]{2}' | head -1); [ "$yr" != 2026 ] && echo "WRONG($yr) $f";
  done   # must print nothing
  ```

### Verification
- `tox run -e lint` (the repo's licence-header check, if enabled, should pass).

---

## Race conditions & concurrency analysis (cross-cutting)

The charm runs in Juju's single-threaded hook model — no in-process threads — so "race" here means
**TOCTOU across hook invocations** and **ordering within `_reconcile`**. Each JCasC touch point:

### R1 — hash-then-restart ordering (NOT a race, by design) — confirmed safe
`_reconcile` (`src/charm.py:186+`) writes the JCasC file (`_reconcile_jcasc_config`) and stores its
hash into `CONFIGURATION_HASH` (`calculate_env`, `:183`) BEFORE the Pebble replan that may restart
Jenkins (`:218`). File-write and hash both precede the replan within the same synchronous hook, so
there is no window where Jenkins restarts against a half-written file. ✓ **Action: none** (noted so
a future editor doesn't "fix" the ordering and break it).

### R2 — concurrent config-changed + pebble-ready hooks — confirmed safe
Juju serialises hooks per unit; two never run concurrently for the same unit. Reconcile-on-every-
event re-converges. The only requirement is **idempotency + hash stability**: identical inputs must
yield an identical hash, else every hook restarts Jenkins. Findings D.3 and G.3 add the
hash-stability assertions that lock this in. ✓ **Action: covered by D.3/G.3 tests.**

### R3 — TOCTOU on the JCasC file (pull-compare-push) — benign, document
`sync_jcasc_config` (`src/jenkins.py:1203+`) pulls current content, hash-compares, pushes. Nothing
else writes that path (only the charm manages `jenkins.yaml`; Jenkins reads it), so the pull→push
window is benign. The in-body TODO about hashing via `pebble exec` is a perf note, not a race. ✓
**Action: none; keep the TODO (Finding C.2).**

### R4 — admin-password availability vs JCasC interpolation — verify (possible ordering gap)
JCasC injects `password: ${JENKINS_ADMIN_PASSWORD}` (`src/jenkins.py:1181`); the env supplies that
var from the Juju secret via `_get_admin_password` (`src/state.py:245–250`). If a reconcile writes
JCasC referencing the admin password **before** the secret exists (first boot), Jenkins could
interpolate an empty password. **Task R4.1:** add a parametrized unit test asserting that when
`_get_admin_password` returns `None`, `_reconcile_jcasc_config` either defers (no write) or the env
still yields a deterministic password — confirm which and document. This is the one concurrency-ish
spot worth an explicit test; everything else is structurally safe.

---

## Implementation Sequencing (for smaller models)

Execute findings in this order. Each step is independently committable, has its OWN inline tests
(never a separate test-only PR), and must pass `tox run -e lint,unit,static,coverage-report`
before moving on. Use `PYTHONPATH=src:lib uv run pytest tests/unit/<file> -v` for fast local loops.

| Step | Finding(s) | Files touched | Why this order |
|------|-----------|---------------|----------------|
| 1 | **A** (correctness) | `src/jenkins.py` (auth-proxy realm), `tests/unit/test_charm_jcasc.py` | Highest impact; security posture. Fix the malformed `securityRealm`/`authorizationStrategy` siblings first. |
| 2 | **G + F** (crash + cleanup) | `src/jenkins.py:1166,1199`; `src/state.py` (opt G.2); `tests/unit/test_jenkins_jcasc.py`, `test_state.py` | G's None-safe access IS F's rewrite — do them together in one edit. Prevents the empty-`jenkins:` crash. |
| 3 | **D** (state drift) | `src/charm.py:563`; `tests/unit/test_charm_jcasc.py` | Depends on F/G being None-safe (passes `{}` through `build_jcasc_config`). |
| 4 | **B** (dead code) | `src/jenkins.py:662–702`; `tests/unit/test_jenkins_jcasc.py:234–296` | Pure deletion; do after B's siblings confirmed unused. No behaviour change. |
| 5 | **C** (docstring) | `src/jenkins.py:1204–1222` | Docs-only; safe anytime, grouped here to land with the jenkins.py changes. |
| 6 | **E** (test quality) | `test_charm_jcasc.py`, `test_jenkins_agents.py`, `test_jenkins_readiness.py`, `test_jenkins_plugins.py`, `test_agent_reconcile.py` | E.1 reuses A's corrected shape, so do A first (step 1) then E. |
| 7 | **R4.1** (concurrency test) | `tests/unit/test_charm_jcasc.py` | Adds the admin-password-None regression test. |
| 8 | **H** (copyright) | 6 new test files | Trivial header bump; last so it doesn't churn diffs mid-review. Can also be folded into whichever step first touches each file. |

### Per-step definition of done
1. Code change is surgical (edit the real source file, never a parallel/fallback file).
2. Inline tests added in the SAME step — parametrized, no conditional assertions (Finding E rules).
3. Run tests BEFORE committing: `tox run -e lint,unit,static,coverage-report` green.
4. If the step touches a stacked downstream PR, propagate immediately (amend → rebase →
   force-push downstream) per the repo's stacked-PR workflow.

### Smaller-model guardrails
- Do NOT expand scope: each task lists exact files + line ranges. If a fix seems to need a file not
  listed, STOP and flag it rather than inventing changes.
- Do NOT add the validate/reload lifecycle (Finding B/C) back in — it was deliberately dropped.
- Verify every claim with a command (grep/pytest), never assume. The crash in G was found by
  actually running `yaml.safe_load('jenkins:')` — reproduce, don't speculate.
- Preserve house test style: functional (not class-based), no section comments, parametrize
  shared-setup cases, helpers for boilerplate.

---

## Review summary comment (paste into PR #379)

> Solid restructure — splitting the 1630-line `test_jenkins.py` into focused modules is a real
> readability win, and the write-to-disk + restart-on-hash JCasC apply model is the right call.
> A few things to address before merge:
>
> **Blocking-ish:**
> - **`securityRealm` shape is malformed** for the auth-proxy bypass case — JCasC expects
>   `securityRealm: "none"` and `authorizationStrategy: "unsecured"` as **siblings**, not nested
>   (`src/jenkins.py`). The unit test encodes the same wrong shape so it passes green against a
>   config Jenkins would reject. (Finding A)
> - **Empty `jenkins:` crashes the charm** — `jenkins.build_jcasc_config` does
>   `'securityRealm' in config.get("jenkins", {})`, but a bare `jenkins:` parses to
>   `{"jenkins": None}` (key present, value None), so the default is bypassed and it raises
>   `TypeError`. One-line None-safe fix. (Finding G)
>
> **Should-fix:**
> - Clearing `jcasc-config` leaves the old `jenkins.yaml` on disk and re-applies it on the
>   restart it triggers — config never actually clears. (Finding D)
> - `reload_jcasc`/`check_jcasc` are dead (no callers); the `sync_jcasc_config` docstring still
>   advertises a validate/reload/rollback lifecycle that was dropped. (Findings B, C)
> - A handful of unit tests use conditional assertions (`if expected: assert X else: assert Y`),
>   which can silently assert nothing on one branch — split or parametrize on values. (Finding E)
>
> **Nits:** redundant `setdefault().update()` self-merge (Finding F); six new test files say
> `Copyright 2025`, should be 2026 (Finding H).
>
> Full per-finding detail with exact line refs, fixes, and tests in the review doc.

---

## Implementation Checklist for Smaller Agents

Execute in the recommended order below. Each step must pass `tox run -e lint,unit,static,coverage-report` before moving on. Check off each individual task as you complete it.

### Step 1: Fix auth-proxy JCasC structure & test smells (Findings A + E.1)
- [x] **Task A.1**: Fix `securityRealm` and `authorizationStrategy` to be siblings under `jenkins:` in `src/jenkins.py:1169-1174`.
- [x] **Task A.2**: Fix the test that locks in the bug in `tests/unit/test_charm_jcasc.py` (assert the corrected sibling shape).
- [x] **Task A.3**: Add a structural regression test asserting `authorizationStrategy` is a sibling of `securityRealm` for auth-proxy mode.
- [x] **Task E.1**: De-smell `test_charm_jcasc.py` security-realm test by splitting it into two intention-revealing tests (folds A.2/A.3).

### Step 2: Fix empty `jenkins:` crash & redundant merge (Findings G + F)
- [x] **Task F.1**: Simplify the `build_jcasc_config` merge in `src/jenkins.py` using `config.get("jenkins") or {}` and a single assignment.
- [x] **Task G.1**: Ensure None-safe section access (folded into F.1).
- [x] **Task G.2** *(optional)*: Add validation in `src/state.py:_parse_jcasc_config` to reject non-dict `jenkins:` values (tolerate `None`).
- [x] **Task G.3**: Add parametrized regression tests in `tests/unit/test_jenkins_jcasc.py` and `tests/unit/test_state.py` for empty/None `jenkins:` handling.

### Step 3: Fix state drift on un-set `jcasc-config` (Finding D)
- [x] **Task D.1**: Update `_reconcile_jcasc_config` in `src/charm.py` to pass `{}` through `build_jcasc_config` when `jcasc_config` is `None`.
- [ ] **Task D.2** *(skip unless D-clear-delete is chosen)*: Explicit file removal if team decides un-set should delete the file entirely.
- [x] **Task D.3**: Add a parametrized test in `tests/unit/test_charm_jcasc.py` asserting the un-set transition writes the admin baseline and returns a stable hash.

### Step 4: Remove dead code (Finding B)
- [x] **Task B.1**: Delete `reload_jcasc` and `check_jcasc` methods from `src/jenkins.py:662-702`.
- [x] **Task B.2**: Delete their four corresponding tests from `tests/unit/test_jenkins_jcasc.py:234-296`.

### Step 5: Correct misleading docstring (Finding C)
- [x] **Task C.1**: Rewrite the docstring for `sync_jcasc_config` in `src/jenkins.py:1204-1222` to accurately describe the write-to-disk + short-circuit behavior.
- [x] **Task C.2**: Review/convert the inline TODO at `src/jenkins.py:1230-1231` to a tracked ticket reference.

### Step 6: De-smell remaining conditional tests (Finding E)
- [x] **Task E.2**: Split 4 conditional error/success tests in `tests/unit/test_jenkins_agents.py` into explicit `_success` / `_raises_on_api_error` pairs.
- [x] **Task E.3**: Parametrize factories instead of string switches in `test_jenkins_readiness.py`, `test_jenkins_plugins.py`, `test_agent_reconcile.py`, etc.

### Step 7: Add concurrency/admin-password test (Race R4)
- [x] **Task R4.1**: Add a parametrized unit test in `tests/unit/test_charm_jcasc.py` asserting behavior when `_get_admin_password` returns `None`.

### Step 8: Fix copyright headers (Finding H)
- [x] **Task H.1**: Update `Copyright 2025` to `Copyright 2026` in the 6 newly added test files.

### Definition of Done (per step)
- [ ] Code change is surgical (edit real source file).
- [ ] Inline tests added in the SAME step (parametrized, no conditional assertions).
- [ ] `tox run -e lint,unit,static,coverage-report` is green.
- [ ] If touching stacked downstream PRs, amend -> rebase -> force-push.
