# Design: Fresh State Derivation Refactor

## Problem

The charm currently stores `State` as an instance variable (`self.state`) set during `__init__`, and
re-reads it midway through `_on_config_changed`. Observers (`agent.Observer`, `auth_proxy.Observer`)
receive this state at construction time and hold it as their own `self.state`. When state changes
(e.g., config or relation data updates), observers use a stale snapshot. This is the first step
toward a full reconciliation pattern: ensuring state is always fresh before any action is taken.

## Scope

This refactor covers state derivation and event routing only. The reconcile loop unification (making
all hooks call the same reconcile function) is a separate subsequent step.

## Design

### Principle

`State` is never stored. It is derived fresh at the start of every event handler by a single
`_get_state()` method on the charm, then passed explicitly to any observer method that needs it.

### `charm.py`

- Remove `self.state` assignment from `__init__`. State is no longer an instance variable.
- Remove the early return / blocking logic from `__init__` that was guarding `self.state` (that
  logic moves into `_get_state()`).
- Add `_get_state() -> State | None` method:
  - Calls `State.from_charm(self)`.
  - On `CharmConfigInvalidError` or `CharmIllegalNumUnitsError`: sets `BlockedStatus` and returns
    `None`.
  - On `CharmRelationDataInvalidError`: raises `RuntimeError` (same as current behaviour).
- Every event handler in `charm.py` begins with:
  ```python
  state = self._get_state()
  if state is None:
      return
  ```
- All `framework.observe(...)` calls that currently live inside `agent.Observer.__init__` and
  `auth_proxy.Observer.__init__` move to `charm.py.__init__`. The charm becomes the single place
  where events are wired.

### `agent.Observer`

- `__init__` signature drops the `state: State` parameter; no `self.state` stored.
- All `charm.framework.observe(...)` calls are removed from `__init__`.
- Previously-internal event handler methods (`_on_agent_relation_joined`,
  `_on_agent_relation_departed`, `_on_agent_relation_changed`, `_ingress_on_ready`,
  `_ingress_on_revoked`) either remain as helpers that charm.py calls directly, or are inlined into
  charm.py handlers. Their `state` dependency comes from the caller.
- `reconcile_agents(event, state: State)` receives state explicitly.
- `reconfigure_agent_discovery(event, state: State)` receives state explicitly (even if unused
  today, for consistency).
- `_add_agent_nodes_from_relation` and `_remove_agent_nodes_not_in_relation` receive
  `agent_relation` from the caller (derived from `state.agent_relation_meta`).

### `auth_proxy.Observer`

- `__init__` signature drops the `state: State` parameter; no `self.state` stored.
- All `charm.framework.observe(...)` calls are removed from `__init__`.
- Handler methods (`_on_auth_proxy_relation_joined`, `_auth_proxy_relation_departed`,
  `_ingress_on_ready`, `_ingress_on_revoked`) gain a `state: State` parameter.

### Unaffected Files

- `cos.py` — no `State` dependency; unchanged.
- `storage.py` — no `State` dependency; unchanged.
- `ingress.py` — no `State` dependency; unchanged.
- `pebble.py` — already accepts `state` as a function argument; unchanged.
- `precondition.py` — no `State` dependency; unchanged.
- `state.py` — `State` and `State.from_charm()` are unchanged.

## Error Handling

All state-derivation errors are handled in one place: `_get_state()`.

| Exception | Behaviour |
|---|---|
| `CharmConfigInvalidError` | `BlockedStatus(exc.msg)`, return `None` |
| `CharmIllegalNumUnitsError` | `BlockedStatus(exc.msg)`, return `None` |
| `CharmRelationDataInvalidError` | `raise RuntimeError(...)` |

## Testing

- Existing unit tests for `charm.py` handlers need updating: mock `_get_state()` instead of
  patching `State.from_charm` in `__init__`.
- Observer tests no longer need to pass a `State` to `__init__`; state is passed per-call.
- The `_get_state() -> None` path (blocked state) should be tested for each handler to confirm
  early return.
