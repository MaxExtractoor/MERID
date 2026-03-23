## Quick Take
- `make smoke-test` is consolidated to the wiring check, installs its deps, and now exits cleanly with a friendly message when the API base is down.
- `requirements-test.txt` installs cleanly after removing the missing `codium` dependency; Python 3.11 is the supported baseline.
- Coinbase WS feed now pings/heartbeats with jittered backoff, fails fast when `websockets` is missing, and exposes health.
- Streaming bus uses instance-scoped semantics with per-channel drop metrics instead of a hidden singleton monkey-patch.
- `AgentGrid` startup rolls back on failure; long-lived loops back off instead of tight-looping; reconciliation can be toggled via env.
- LangGraph swarm explicitly labels the mock path (`"mock-123"`) vs live mode, reducing confusion.

## Status
- Smoke test target consolidated; `make smoke-test` now installs `requirements-smoke.txt` (httpx) and exits cleanly with a friendly message if the API base is unreachable.
- `requirements-test.txt` no longer references missing `codium`; Python 3.11 noted as supported and `pyre-check` gated for <3.12.
- Coinbase WS feed now uses heartbeat/read timeouts, jittered backoff, fail-fast on missing dependency, and surfaces health.
- Streaming bus restores instance semantics with per-channel drop metrics; isolation is covered by tests.
- AgentGrid startup rolls back on failure, loops use capped backoff, and reconciliation is env-toggleable.
- LangGraph swarm explicitly labels mock vs live modes; tests assert mock identifiers.

## CI & Tests
- `make smoke-test` is now a single target that installs `requirements-smoke.txt` and runs the wiring check; when the API is down it emits a clear reachability message instead of a stack trace.  
  Repro: `make smoke-test` (with API stopped) → friendly reachability warning and non-zero exit; with API running → endpoint report.
- `requirements-test.txt` installs after removing `codium`; `pyre-check` is gated to Python <3.12 and Python 3.11 is the expected baseline.  
  Repro: `pip install -r requirements-test.txt` succeeds on Python 3.11.
- CI run 23456411810 ended `action_required` with zero jobs executed—likely awaiting manual approval before scheduling.

## Subsystem Findings

### Data Ingestion — Resilience 6/10
- Fixed-interval reconnect, no heartbeat (Design Risk): `merid/signals/ws_price_feed.py` reconnects every 5s on error, no ping/heartbeat or jittered backoff; half-open stalls can freeze prices while appearing connected. Suggest adding ping/pong or read timeouts plus jittered backoff and a surfaced health flag.
- Silent no-op when dependency missing (Bug/Observability Gap): If `websockets` is absent, `connect()` only warns and returns; feed stays inactive with no strong health signal. Suggest failing fast or surfacing an explicit unhealthy state.
- Swallowed ingestion errors (Observability Gap): `_on_price_update` catches broad exceptions and only warns; prolonged parse/ingest failures won’t trip alerts. Suggest counters + circuit breaker to mark feed unhealthy after repeated errors.

### Messaging / Streaming Bus — Resilience 4/10
- Monkey-patched instance methods to global singleton (Bug/Egg): `core/streaming_bus.py` overwrites `StreamingBus.subscribe/unsubscribe/get_event` with lambdas that route to global helpers, bypassing instance locks/metrics and breaking per-instance isolation; ghost subscribers can persist. Suggest removing or reworking the monkey patch and restoring instance-scoped metrics/backpressure accounting.

### Swarm Orchestration — Resilience 6/10
- Partial-start leak risk (Design Risk): `merid/prediction/agent_grid.py` sets `_running=True` before dependencies fully start; early failures skip cleanup, leaving tasks (volume/reconciliation) armed. Suggest try/finally rollback and scheduling tasks only after all deps succeed.
- Loop resilience/backoff gap (Observability Gap): `_volume_poll_loop` and `_reconciliation_loop` log and continue on exceptions without backoff or escalation; repeated failures can tight-loop CPU and still report running. Suggest exponential backoff and health degradation after N failures.

### UI / API & Smoke Tests — Resilience 5/10
- Duplicate Makefile target overrides canonical smoke (Bug): Later `smoke-test` rule (Makefile:538) shadows the earlier pytest smoke (Makefile:31); current path just runs the wiring script and fails on missing deps. Suggest picking one canonical target and documenting preconditions.
- Wiring script brittleness (Design Risk): `scripts/smoke_test_wiring.py` assumes API at `localhost:8000`, lacks retry/backoff, and depends on `httpx` not installed by default. Suggest reachability precheck, optional skip when API is down, and bundling `httpx` in minimal smoke deps.

## Eggs & Oddities
- Hidden singleton bus: the monkey patch enforces a global bus even for new instances—could be abused as a global event tap but likely accidental.
- Built-in LangGraph simulator: `core/swarm_langgraph.py` returns a fixed `"mock-123"` execution result, useful for demos/shadow tests but misleading if not clearly labeled as mock.
- Auto-reconciliation under the radar: AgentGrid reconciliation loop auto-fixes discrepancies without operator confirmation, potentially mutating state while the system appears paused.

## Suggested Next Steps
1) Fix and clarify smoke tests: choose the canonical target; remove the duplicate Makefile rule or rename; ensure deps (`httpx`) are available and preconditions are documented.  
2) Unblock test env: drop/replace `codium>=0.1.0` (or document internal source) and align pins with a supported Python version.  
3) Restore healthy streaming bus semantics: remove the global monkey patch; keep instance locks/metrics and per-channel drop counts.  
4) Harden Coinbase WS ingestion: add heartbeat/read-timeout plus jittered backoff; fail fast on missing `websockets`; surface feed health to UI/alerts.  
5) Strengthen swarm lifecycle: wrap `AgentGrid.start` in try/finally for rollback; add backoff/alerting in long-lived loops and degrade health after repeated failures.
