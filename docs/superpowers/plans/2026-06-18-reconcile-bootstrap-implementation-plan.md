# Reconcile-Centered Jenkins Bootstrap Implementation Plan

> For Hermes: use subagent-driven-development for execution, one task at a time, and enforce strict TDD (RED -> GREEN -> REFACTOR) on each code task.

Goal: Move Jenkins bootstrap fully into reconcile with explicit prestart/poststart phases, strict completion semantics, and idempotent markers.

Architecture:
- `src/charm.py` owns orchestration, phase gating, and bootstrap completion markers.
- `src/jenkins.py` owns phase internals (`prepare_bootstrap_static`, `complete_bootstrap_runtime`) and required-plugin preinstall idempotency.
- `src/pebble.py` remains a layer renderer; old monolithic `replan_jenkins` is not used by reconcile flow.

Tech stack: ops framework, pytest, unittest.mock, uv/tox.

---

## Preconditions and guardrails

- Branch: `chore/reconcile-bootstrap`
- Existing staged/uncommitted files are present (`src/charm.py`, `tests/unit/test_agent.py`, `tests/unit/test_charm.py`, and the design spec). Do not discard them.
- Use test commands through `uv run` or `tox -e unit` so dependencies are available.

Recommended test command patterns:
- Targeted RED/GREEN: `uv run pytest <path>::<test_name> -v`
- File-level regression: `uv run pytest <path> -v`
- Broad unit run before completion: `tox -e unit -- tests/unit/test_charm.py tests/unit/test_jenkins.py tests/unit/test_agent.py`

---

### Task 1: Add failing charm tests for phase split ordering

Objective: Prove reconcile order changes from single bootstrap gate to explicit prestart -> pebble -> poststart.

Files:
- Modify: `tests/unit/test_charm.py`
- Modify: `src/charm.py` (later, GREEN)

Step 1: Write failing tests
- Add a test that patches these methods and records call order:
  - `_reconcile_storage`
  - `_reconcile_bootstrap_prestart`
  - `_reconcile_pebble`
  - `_reconcile_bootstrap_poststart`
  - `_reconcile_agents`
- Assert order is exactly:
  1) storage
  2) bootstrap_prestart
  3) pebble
  4) bootstrap_poststart
  5) agents

Step 2: Run test to verify failure
Run:
`uv run pytest tests/unit/test_charm.py::test_reconcile_orders_bootstrap_prestart_before_pebble_and_poststart_after -v`
Expected: FAIL because `_reconcile_bootstrap_prestart/_poststart` do not exist yet and current order differs.

Step 3: Minimal implementation
- In `src/charm.py`, update `_reconcile(...)` orchestration:
  - replace `_reconcile_bootstrap(...)` call with two gates:
    - `if not self._reconcile_bootstrap_prestart(container, state): return`
    - `self._reconcile_pebble(container, state)`
    - `if not self._reconcile_bootstrap_poststart(container, state): return`
- Keep early-return behavior before agents/auth/plugin cleanup.

Step 4: Re-run test
Run same command; expected PASS.

Step 5: Commit
`git add tests/unit/test_charm.py src/charm.py`
`git commit -m "test(charm): enforce reconcile bootstrap phase order"`

---

### Task 2: Add failing charm tests for strict bootstrap completion marker semantics

Objective: Marker should only be written after successful poststart runtime completion + restart + readiness.

Files:
- Modify: `tests/unit/test_charm.py`
- Modify: `src/charm.py` (later, GREEN)

Step 1: Write failing tests
Add tests:
1) `test_bootstrap_poststart_marks_complete_only_after_restart_and_wait_ready`
- Patch `jenkins.is_jenkins_ready` True.
- Patch `self.jenkins.complete_bootstrap_runtime`, `container.restart`, `self.jenkins.wait_ready`, `_mark_jenkins_bootstrapped`.
- Assert marker call happens after runtime + restart + wait.

2) `test_bootstrap_poststart_does_not_mark_complete_on_runtime_error`
- Make `complete_bootstrap_runtime` raise `jenkins.JenkinsBootstrapError`.
- Assert `_mark_jenkins_bootstrapped` not called.
- Assert `BlockedStatus` (or chosen failure status) is set.

Step 2: Run RED
`uv run pytest tests/unit/test_charm.py -k "poststart_marks_complete or poststart_does_not_mark_complete" -v`
Expected: FAIL.

Step 3: Minimal implementation
- Add `_reconcile_bootstrap_poststart(self, container, state) -> bool`.
- In this method:
  - If already bootstrapped: set workload version and return True.
  - If service not ready: set `WaitingStatus(...)` and return False.
  - Call runtime phase method.
  - Restart service.
  - Wait ready.
  - Mark complete sentinel.
  - Set workload version.
- Do not set complete marker on exceptions.

Step 4: Run GREEN
Run same command; expected PASS.

Step 5: Commit
`git add tests/unit/test_charm.py src/charm.py`
`git commit -m "feat(charm): enforce strict bootstrap completion marker semantics"`

---

### Task 3: Add failing charm tests for sentinel and legacy backfill behavior

Objective: Implement idempotent full-bootstrap detection and migration backfill.

Files:
- Modify: `tests/unit/test_charm.py`
- Modify: `src/charm.py` (later, GREEN)

Step 1: Write failing tests
Add tests for helper semantics:
1) sentinel exists -> `_jenkins_bootstrapped(...)` returns True.
2) sentinel missing + legacy artifacts exist (token + wizard/version) -> backfill marker and return True.
3) neither sentinel nor legacy artifacts -> return False.

Use `container.exists(...)` and `container.push(...)` patching to simulate files.

Step 2: Run RED
`uv run pytest tests/unit/test_charm.py -k "jenkins_bootstrapped or legacy_backfill" -v`
Expected: FAIL (helpers missing).

Step 3: Minimal implementation
In `src/charm.py` add:
- constants for marker paths under `${JENKINS_HOME}/.charm/`.
- `_jenkins_bootstrapped(container) -> bool`
- `_mark_jenkins_bootstrapped(container) -> None`
- optional phase marker helpers for prestart (`_jenkins_bootstrap_prestart_done`, mark/clear) if used by flow.

Backfill logic:
- when sentinel missing and legacy artifacts are present, write sentinel and treat as bootstrapped.

Step 4: Run GREEN
Re-run command from Step 2; expected PASS.

Step 5: Commit
`git add tests/unit/test_charm.py src/charm.py`
`git commit -m "feat(charm): add bootstrap sentinel and legacy backfill detection"`

---

### Task 4: Add failing Jenkins unit tests for static/runtime phase APIs

Objective: Define split APIs in `src/jenkins.py` with coverage before implementation.

Files:
- Modify: `tests/unit/test_jenkins.py`
- Modify: `src/jenkins.py` (later, GREEN)

Step 1: Write failing tests
Add tests:
1) `test_prepare_bootstrap_static_calls_logging_config_config_and_required_plugins`
- patch `install_logging_config`, `_install_configs`, and plugin preinstall path.

2) `test_complete_bootstrap_runtime_calls_unlock_token_proxy`
- patch `_unlock_wizard`, `_setup_user_token`, `_configure_proxy`.

3) `test_bootstrap_wrapper_calls_static_then_runtime`
- preserve compatibility by asserting `bootstrap(...)` delegates in correct order.

Step 2: Run RED
`uv run pytest tests/unit/test_jenkins.py -k "prepare_bootstrap_static or complete_bootstrap_runtime or bootstrap_wrapper" -v`
Expected: FAIL because methods do not exist yet.

Step 3: Minimal implementation
In `src/jenkins.py`:
- add `prepare_bootstrap_static(container, jenkins_config_file, proxy_config=None)`.
- add `complete_bootstrap_runtime(container, proxy_config=None)`.
- update `bootstrap(...)` wrapper to call the two methods and preserve current exception contract.

Step 4: Run GREEN
Re-run command from Step 2; expected PASS.

Step 5: Commit
`git add tests/unit/test_jenkins.py src/jenkins.py`
`git commit -m "feat(jenkins): split bootstrap into static and runtime phases"`

---

### Task 5: Add failing Jenkins unit tests for REQUIRED_PLUGINS preinstall marker/fingerprint

Objective: Prevent repeated plugin-manager runs unless fingerprint/input changed or plugin files absent.

Files:
- Modify: `tests/unit/test_jenkins.py`
- Modify: `src/jenkins.py` (later, GREEN)

Step 1: Write failing tests
Add tests:
1) marker matches + required plugin files present -> skip plugin install.
2) marker missing -> run plugin install and write marker.
3) marker mismatch (plugin manager version or plugin set changed) -> run plugin install and rewrite marker.
4) marker matches but plugin archive missing -> run plugin install.

Step 2: Run RED
`uv run pytest tests/unit/test_jenkins.py -k "required_plugins_preinstall or fingerprint" -v`
Expected: FAIL.

Step 3: Minimal implementation
In `src/jenkins.py`:
- add marker constants under `${JENKINS_HOME}/.charm/`.
- add fingerprint builder (sorted `REQUIRED_PLUGINS` + `JENKINS_PLUGIN_MANAGER_VERSION`).
- add marker read/write helpers.
- make `prepare_bootstrap_static(...)` call `_install_plugins(...)` only when marker check says needed.

Step 4: Run GREEN
Run same command; expected PASS.

Step 5: Commit
`git add tests/unit/test_jenkins.py src/jenkins.py`
`git commit -m "feat(jenkins): add idempotent required-plugins preinstall marker"`

---

### Task 6: Wire charm prestart implementation and status mapping

Objective: Implement prestart phase with deterministic status behavior.

Files:
- Modify: `src/charm.py`
- Modify: `tests/unit/test_charm.py`

Step 1: Write failing tests
Add tests for `_reconcile_bootstrap_prestart`:
- bootstrapped path returns True and does not rerun prestart.
- prestart static failure sets `BlockedStatus` and returns False.
- successful prestart sets/uses prestart-done marker and returns True.

Step 2: Run RED
`uv run pytest tests/unit/test_charm.py -k "bootstrap_prestart" -v`
Expected: FAIL.

Step 3: Minimal implementation
Implement `_reconcile_bootstrap_prestart`:
- choose config file (`AUTH_PROXY_JENKINS_CONFIG` vs `DEFAULT_JENKINS_CONFIG`).
- call `self.jenkins.prepare_bootstrap_static(...)`.
- set `MaintenanceStatus` while preparing.
- map hard prestart errors to `BlockedStatus`.

Step 4: Run GREEN
Re-run Step 2 command; expected PASS.

Step 5: Commit
`git add src/charm.py tests/unit/test_charm.py`
`git commit -m "feat(charm): add bootstrap prestart phase and status mapping"`

---

### Task 7: Wire charm poststart implementation with Waiting vs Blocked semantics

Objective: Finalize poststart behavior and ensure retries for transient readiness.

Files:
- Modify: `src/charm.py`
- Modify: `tests/unit/test_charm.py`

Step 1: Write failing tests
Add tests:
- Jenkins not ready in poststart -> `WaitingStatus`, returns False.
- runtime timeout/readiness race -> `WaitingStatus`, returns False.
- unrecoverable runtime bootstrap error -> `BlockedStatus`, returns False.

Step 2: Run RED
`uv run pytest tests/unit/test_charm.py -k "bootstrap_poststart and (waiting or blocked or timeout)" -v`
Expected: FAIL.

Step 3: Minimal implementation
- complete `_reconcile_bootstrap_poststart` exception handling:
  - transient startup/API readiness failures => Waiting.
  - hard bootstrap failures => Blocked.
- keep strict completion marker behavior from Task 2.

Step 4: Run GREEN
Re-run Step 2 command; expected PASS.

Step 5: Commit
`git add src/charm.py tests/unit/test_charm.py`
`git commit -m "feat(charm): finalize bootstrap poststart transient vs hard failure handling"`

---

### Task 8: Fix stale `_reconcile_agents` call signatures in unit tests

Objective: Keep tests aligned with current method signature `_reconcile_agents(self, state)`.

Files:
- Modify: `tests/unit/test_agent.py`

Step 1: Write failing assertion/update test first
- Add/keep explicit signature assertion (`state` parameter required).
- Update stale callsites passing `event=...` to pass only `state=...`.

Step 2: Run RED
`uv run pytest tests/unit/test_agent.py -k "reconcile_agents" -v`
Expected: FAIL before callsite updates.

Step 3: Minimal implementation
- adjust patched helper signatures and invocations to match method definition.

Step 4: Run GREEN
Re-run command from Step 2; expected PASS.

Step 5: Commit
`git add tests/unit/test_agent.py`
`git commit -m "test(agent): align reconcile_agents tests with state-only signature"`

---

### Task 9: Full targeted verification + docs note update

Objective: Prove refactor with focused unit coverage and update architecture docs if needed.

Files:
- Modify (if architecture wording changed): `docs/reference/charm-architecture.md`

Step 1: Run focused unit suite
`tox -e unit -- tests/unit/test_charm.py tests/unit/test_jenkins.py tests/unit/test_agent.py`
Expected: PASS, coverage report produced.

Step 2: Run high-value integration smoke (if environment available)
`tox -e integration -- tests/integration/test_jenkins.py::test_bootstrap_after_restart -s`
Expected: PASS (or document explicit environment blocker).

Step 3: Update docs (only if needed)
- describe reconcile two-phase bootstrap and marker semantics.

Step 4: Final verification
- `git diff -- src/charm.py src/jenkins.py src/pebble.py tests/unit/test_charm.py tests/unit/test_jenkins.py tests/unit/test_agent.py`
- confirm no unrelated drive-by changes.

Step 5: Final commit
`git add src/charm.py src/jenkins.py tests/unit/test_charm.py tests/unit/test_jenkins.py tests/unit/test_agent.py docs/reference/charm-architecture.md`
`git commit -m "feat: move Jenkins bootstrap to reconcile with idempotent two-phase flow"`

---

## Implementation notes (must-haves)

1) Keep update-status plugin cleanup behavior unchanged:
- `_reconcile_plugins(...)` still only on `UpdateStatusEvent`.

2) Preserve auth-proxy config selection:
- prestart must still choose config file using `state.auth_proxy_integrated`.

3) Avoid production `assert` in new charm runtime paths:
- use explicit conditionals + `BlockedStatus`/`WaitingStatus` mapping.

4) Keep compatibility during transition:
- leave `Jenkins.bootstrap(...)` as wrapper for external/legacy callers.

5) `src/pebble.py::replan_jenkins`:
- no functional expansion required for this refactor; keep as legacy helper unless explicitly cleaned up in a follow-up.

---

## Acceptance checklist

- [ ] Reconcile order is: storage -> bootstrap_prestart -> pebble -> bootstrap_poststart -> agents/auth/plugin-cleanup.
- [ ] Bootstrap complete marker is written only after runtime phase + restart + ready.
- [ ] Legacy artifacts backfill bootstrap marker without forcing re-bootstrap.
- [ ] Required plugin preinstall is idempotent with marker/fingerprint.
- [ ] Unit tests for charm/jenkins/agent all pass.
- [ ] Integration bootstrap smoke passes or blocker is explicitly documented.
- [ ] No behavior regression for update-status plugin cleanup cadence.
