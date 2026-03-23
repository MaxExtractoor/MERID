## Quick Take
- `make smoke-test` is broken: it fails with `ModuleNotFoundError: httpx`, and the later Makefile rule overrides the original pytest-based smoke target (Makefile:31 vs Makefile:538).
- `pip install -r requirements-test.txt` fails because `codium>=0.1.0` is not published; several pins likely do not support Python 3.12, blocking a clean CI-like setup.
- Coinbase WS ingestion uses fixed 5s reconnect without heartbeat/backoff and silently no-ops when `websockets` is missing, creating latent data gaps.
- The streaming bus monkey-patch forces a hidden global singleton, bypassing per-instance locks/metrics.
- `AgentGrid` startup can leave background tasks running after partial failures; long-lived loops continue without backoff on repeated errors.
- LangGraph swarm path always returns `"mock-123"`, acting as a built-in simulator that can be mistaken for live execution.

## CI & Tests
- Blocker: `make smoke-test` runs `scripts/smoke_test_wiring.py` (due to the duplicate target) and fails immediately on missing `httpx`, so no endpoints are exercised.  
  Repro: `make smoke-test` → import error; `make -p | grep -n "^smoke-test"` shows the later rule winning.
- Blocker: `requirements-test.txt` cannot install because `codium>=0.1.0` has no matching distribution (and some pins appear 3.12-incompatible), preventing full test env setup.  
  Repro: `pip install -r requirements-test.txt` → “No matching distribution found for codium>=0.1.0”.
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
