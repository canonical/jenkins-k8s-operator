# Reconcile-Centered Jenkins Bootstrap Design

## Summary

Move Jenkins bootstrap entirely into the charm reconcile flow with strict idempotency and explicit completion markers.

Key decisions from design discussion:
- Bootstrap completion semantics: strict (complete only after runtime/API bootstrap succeeds).
- Pre-install phase plugin scope: `REQUIRED_PLUGINS` only (preserve current behavior).
- Upgrade migration behavior: if legacy bootstrap artifacts exist but new sentinel is missing, backfill sentinel and skip re-bootstrap.

## Problem Statement

Bootstrap behavior is currently split between event-specific handling and reconcile, and the in-progress refactor introduced incomplete bootstrap marker plumbing.

Current code (as inspected) shows:
- Reconcile orchestration already calls `_reconcile_bootstrap`.
- `_reconcile_bootstrap` references `_jenkins_bootstrapped` and `_mark_jenkins_bootstrapped`, but helper implementations are not present.
- Logging config installation historically performed by `pebble.replan_jenkins` is at risk of being skipped in the new reconcile path.
- Bootstrap internals in `jenkins.py` currently mix static filesystem prep and runtime/API work in one method.

We need a clear, resilient, and testable bootstrap flow that converges from any event ordering.

## Goals

1. Bootstrap is fully reconcile-driven and idempotent.
2. Strict completion: mark bootstrapped only when runtime/API initialization has succeeded.
3. Pre-start static prep includes required plugin pre-install before first meaningful Jenkins runtime bootstrap.
4. Existing deployments upgrade safely without forced re-bootstrap.
5. Preserve existing behavior where possible (notably plugin scope and update-status plugin cleanup cadence).

## Non-Goals

1. No redesign of update-status plugin removal policy.
2. No broad plugin policy changes (only `REQUIRED_PLUGINS` in pre-install phase, per decision).
3. No unrelated agent/integration behavior changes.
4. No production behavior changes requiring manual migration actions.

## Proposed Architecture

### 1) Two-Phase Bootstrap Model

Split bootstrap into explicit reconcile phases:

- Phase A: pre-start/static convergence
  - Logging config
  - Jenkins config XML selection/install (`auth-proxy` or default)
  - Required plugin pre-install (`REQUIRED_PLUGINS` only)

- Phase B: post-start/runtime convergence
  - Wait for Jenkins service readiness
  - Wizard unlock/version marker handling
  - API token setup
  - Proxy Groovy configuration
  - Restart once for configuration effect
  - Final readiness wait
  - Set workload version
  - Write bootstrap completion sentinel

### 2) Reconcile Order

`_reconcile(event)` should execute in this order:

1. Precondition gate (container/storage)
2. State derivation
3. `_reconcile_storage(container)` for `StorageAttachedEvent` and `UpgradeCharmEvent` only
4. `_reconcile_bootstrap_prestart(container, state)`
   - stop early on failure
5. `_reconcile_pebble(container, state)`
6. `_reconcile_bootstrap_poststart(container, state)`
   - stop early on waiting/failure
7. `_reconcile_agents(state)`
8. `_reconcile_agent_discovery()`
9. `_reconcile_auth_proxy(state)`
10. `_reconcile_plugins(container, state)` only for `UpdateStatusEvent` (unchanged)
11. ActiveStatus

Rationale: static prep must happen before runtime bootstrap and before relying on live API invariants. Storage ownership correction is event-gated to storage attach/upgrade to avoid unnecessary reconcile churn on every event.

## Idempotency and Persistent State

### Bootstrap sentinel

Use explicit charm-owned sentinel under Jenkins home:
- Suggested directory: `${JENKINS_HOME}/.charm/`
- Bootstrap completion marker: `${JENKINS_HOME}/.charm/bootstrap-complete`

`_jenkins_bootstrapped(container)` semantics:
1. If sentinel exists: `True`
2. Else if legacy artifacts exist (token + wizard/version artifacts):
   - backfill sentinel
   - `True`
3. Else: `False`

`_mark_jenkins_bootstrapped(container)` writes marker only after successful post-start/runtime phase completion.

### Required plugin pre-install marker

To avoid re-running plugin manager on every reconcile, persist a marker/fingerprint for required plugin pre-install.

Marker should encode at least:
- sorted `REQUIRED_PLUGINS`
- `JENKINS_PLUGIN_MANAGER_VERSION`

If fingerprint unchanged, skip pre-install.

## Module Responsibilities

### `src/charm.py`

- Orchestration only.
- Adds bootstrap marker helpers and legacy backfill logic.
- Splits bootstrap reconcile into pre-start and post-start methods.
- Owns service restart boundaries and status transitions.

### `src/jenkins.py`

Refactor bootstrap API into explicit phases:

- `prepare_bootstrap_static(container, jenkins_config_file, proxy_config)`
  - install logging config
  - install chosen Jenkins config
  - ensure required plugins pre-installed idempotently

- `complete_bootstrap_runtime(container, proxy_config)`
  - unlock wizard
  - setup API token
  - configure proxy via API/Groovy

Existing `bootstrap(...)` may remain temporarily as compatibility wrapper during transition.

### `src/pebble.py`

- Keep `get_pebble_layer(...)` as desired state renderer.
- Avoid relying on legacy monolithic `replan_jenkins(...)` from charm reconcile path.

## Error and Status Semantics

- Preconditions unmet (container/storage): `WaitingStatus` (unchanged).
- Invalid config/state: `BlockedStatus` (unchanged path via state validation).

Pre-start/static phase failures:
- Config/logging/plugin pre-install hard failures -> `BlockedStatus`
- Reason: typically persistent operator/environment issues; avoid endless retries.

Post-start/runtime phase:
- Jenkins not ready yet / startup race / transient API readiness -> `WaitingStatus` and retry on next reconcile.
- Hard runtime failures (e.g., unrecoverable proxy apply failure) -> `BlockedStatus`.

Strict completion rule:
- Do not write bootstrap-complete sentinel on partial success.

## Migration / Upgrade Behavior

For units already initialized before this design:
- If new sentinel is missing but legacy bootstrap artifacts are present:
  - create sentinel (backfill)
  - skip runtime bootstrap re-execution

This avoids unnecessary restart/bootstrap churn after upgrade.

## Test Plan

### Unit tests

`tests/unit/test_charm.py`
- First bootstrap path: pre-start + post-start ordering and final sentinel write.
- Bootstrapped path: sentinel present => runtime bootstrap skipped.
- Legacy backfill path: sentinel absent + legacy artifacts present => sentinel backfilled; runtime bootstrap skipped.
- Pre-start plugin/config failure => `BlockedStatus`.
- Post-start readiness not reached => `WaitingStatus`.
- Storage reconcile trigger remains event-gated (`StorageAttachedEvent`/`UpgradeCharmEvent`).
- Preserve update-status-only plugin cleanup behavior.

`tests/unit/test_jenkins.py`
- New phase method coverage:
  - static prep operations
  - required plugin marker/fingerprint behavior
  - runtime completion operations

`tests/unit/test_agent.py`
- Align any stale call sites with current `_reconcile_agents(state) -> bool` signature.

### Integration tests

- Fresh deploy converges with one bootstrap completion, actions usable.
- Upgrade-like path with missing new sentinel but legacy artifacts present backfills sentinel and avoids re-bootstrap churn.
- Auth-proxy integrated path uses correct config selection under reconcile bootstrap.

## Risks and Mitigations

1. Risk: regressions from moving responsibilities between `charm.py` and `jenkins.py`.
   - Mitigation: phase-specific unit tests and keeping temporary compatibility wrapper.

2. Risk: plugin pre-install running too often.
   - Mitigation: marker/fingerprint state.

3. Risk: status oscillation between waiting/blocked in partial-failure states.
   - Mitigation: explicit failure-class mapping and strict completion marker semantics.

## Rollout Strategy

1. Add helper methods and marker constants.
2. Introduce phase APIs in `jenkins.py`.
3. Reorder reconcile and wire prestart/poststart methods.
4. Add/adjust tests.
5. Validate with unit then targeted integration.

## Open Follow-ups (non-blocking)

1. Decide whether to fully remove/deprecate legacy `pebble.replan_jenkins` once no longer referenced.
2. Decide if additional plugin fingerprints should include Jenkins core version over time.
3. Consider a dedicated charm action to inspect/reset bootstrap marker state for debugging (future).