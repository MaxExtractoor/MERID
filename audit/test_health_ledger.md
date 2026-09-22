# MERID Test Health Ledger — 2026-09-22

Baseline command:
`python -m pytest -n 4 -q --tb=line -rf --junitxml=audit/baseline_junit_20260921.xml`

Environment: Python 3.11.9 (`.venv/Scripts`), pytest 9.0.2, Windows, 8 cores.
Collected: 23,205 tests (307s). First run: **1181 failed / 9586 passed /
1083 skipped / 19 errors / 117 warnings** (~11.9k executed; remainder ignored via
`collect_ignore` / markers), 18m42s, INTERNALERROR at worker shutdown
(BrokenPipeError on execnet channel — controller-side, after counts printed).

## Disposition legend
- fixed — product code or test fixed, verified green
- retired — obsolete test deleted; replacement coverage documented
- skipif — narrow conditional skip on a real capability check
- xfail(strict) — known defect, tracked, expiry-bound, still executes
- dep — declared/pinned test dependency added
- warn-filter — narrow warning filter w/ removal trigger

## Clustered failure ledger
(populated from junit run — see baseline_junit_20260921.xml)

| ID | Test/module cluster | Classification | Root cause | Disposition | Verification |
|----|--------------------|----------------|------------|-------------|--------------|

## Skips inventory
13 collection-level module skips (legacy/optional imports) — require
per-module classification.

## Known pollution events observed
- `data/deployment_state.json`: agent modes flipped PAPER<->LIVE by tests.
- `data/risk_kill_switch.json`: rewritten by kill-switch tests.
- `data/gauntlet_verdicts.jsonl`: appended by gauntlet tests.
- `data/kalshi_fills_intent_index.json`: read/written by fill-rate tests
  (fixed via `MERID_FILLS_INTENT_INDEX_PATH` override + tmp_path fixture).
- `data/reconciliation_report.json`: rewritten by reconciler tests
  (fixed via `MERID_RECONCILIATION_REPORT_PATH`).
- `data/risk_kill_switch.json`: **deleted** by a test during run 2
  (restored from HEAD; writer now env-redirected — deleter not yet
  identified, the fingerprint guard will catch a recurrence).
- `logs/full.log`: test logging writes (diagnostic; out of scope for data guard).
- Import-time live Kalshi balance fetch in `merid.settings` — network call
  during test collection; needs isolation guard or lazy init.
- `execution_guard._bg_promo` daemon thread leaks across tests — runs an
  85s gauntlet/promotion report in the background and emits "I/O operation
  on closed file" logging errors at teardown. Pre-existing noise, not a
  test failure; classify as test-isolation defect.

## Fixes landed this pass (pre-ledger)
- portfolio_engine: Decimal money/quantity fields; exact weighted-average
  basis (no floor truncation); canonical centi-contract division (no negative
  floor-div); authoritative `proceeds_cents` preferred for cash; event_id +
  fill_id dedup; JSON-safe serialization via `_json_num`.
- portfolio_event_sources: Decimal parsing of `count_fp`/`price_cents`/
  `fee_cents` (fixes `int("5.00")` crash + sub-cent fee truncation).
- portfolio_event_log: JSON event-data serialization (was Python repr;
  read path couldn't reconstruct dicts); Decimal/datetime-safe default;
  parse-on-read with `ast.literal_eval` fallback for legacy rows.
- loop_15m: exit-guard canonical-position cache failure now fails closed for
  discretionary/unknown exit classes; only operational/emergency fall through
  to intent-contract revalidation.
- market_maker_15m: removed fabricated `side="yes"` default in phase-2
  directional quoting — no clear signal now emits no quote.
- conftest: durable-state env redirects to per-process temp dir +
  session-level `data/` pollution guard (snapshot/diff, fails run).
  Guard fingerprint uses `os.scandir` dir-signature walk (~2.5s over the
  491k-file tree); the earlier `Path.rglob`+`stat` snapshot took ~2h and
  was the actual cause of the second baseline's apparent worker deadlock
  (4 workers × 491k stats), not pytest-timeout.
- conftest redirect map extended: circuit-breaker watermark/halt,
  reconciliation report, fills session metadata, paper ladder state,
  prob-accuracy DB, entry provenance, promotion states, risk state,
  warmup snapshots, run summaries, ingress, kalshi archive, credentials
  path, profile snapshots.
- Hot writers converted to env-overridable paths: trading_circuit_breaker
  (2), reconciliation.py + venue_reconciler (report), fills_ledger
  (session metadata + intent index), paper_ladder, prob_accuracy_tracker,
  entry_provenance, auto_promoter, risk_guard, warmup_data_collector,
  run_summary, ingress_recorder, archiver, agent_grid_15m (shadow
  telemetry → MERID_SHADOW_TELEMETRY_DIR), credential_manager
  (data/credentials → MERID_CREDENTIALS_PATH — real-credential leak into
  test process), startup_validations (fills DB → MERID_FILLS_DB_PATH),
  loop.py (profile snapshots).
- binary_price_space: canonical/crisis/FLB range predicates now parse side
  via `_try_parse_side` and return False for unknown values (were defaulting
  to YES or silently falling into the NO branch).
- loop_15m: candidate side normalized/rejected via `_try_parse_side` before
  side-aware price-range and exit-policy resolution (was `or "yes"`).
- order_router: `_intent_price_side` no longer fabricates "yes" for ambiguous
  side strings (was `action or "buy"` into yes_delta + `except: return "yes"`);
  returns None. Callers fail closed: `_validate_outcome_price_placement`
  rejects with `unknown_price_space`; `_bbo_moved` treats unknown as diverged
  (reprice path); payload-consistency site sets bid/ask None so downstream
  validation rejects.
- ws_bridge/fill_bus: `or 'buy'` fallbacks removed on the fill→position_cache
  path — undetermined action now reaches the position-cache quarantine
  (`POSITION-CACHE-FILL-QUARANTINED` + REST reconciliation) instead of being
  silently recorded as a buy.
- position_cache: `on_fill`/`apply_fill` defaults `action="buy"`→`""`;
  explicit undetermined-direction quarantine + `require_rest_reconciliation`
  before signed-YES math (was a bare ValueError dead-lettered as transient);
  `_derive_proceeds_dollars` raises on undetermined action.
- order_manager/executors: fabricated `or "yes"` outcomes → `""`/`None`
  (honest unknown in tracking/telemetry).
- fill_bus:75: `kalshi:order_filled` payload `(_can_action or "buy")` → `""`
  (event consumers see missing action instead of fabricated buy).
- position_cache rebuild path (~6042): `or 'buy'`/`or 'yes'` → `''` with
  explicit undetermined-direction warning+skip (was silent `continue`).
- position_cache reconstruction/rebuild (4331, 6148): removed dead
  `thesis_side or "yes"` fallbacks — `from_signed_yes_exposure` always
  returns a real side for nonzero exposure; the defaults documented a
  wrong mental model.
- order_router:~17852 decision-ledger `FillEvent`: `_ledger_side`/
  `_ledger_action` now `Optional` and explicitly derived; unresolvable
  direction logs `[LEDGER-DIRECTION-UNKNOWN]` critical and skips the
  fabricated record (fill still recorded in authoritative fills_ledger).
- client.py batch-order wire payload: missing/invalid `action`/`side` now
  skips the order with `[KALSHI_BATCH_ORDER_VALIDATION]` (was `spec.get(
  "action", "buy")` fabricating a live buy on the wire).
- ws_bridge REST-resync fill ingestion (both copies): `action` now
  validated `in ("buy","sell")`; invalid → `[WS-BRIDGE-ACTION-INVALID]`
  discard (side was already fail-closed via `require_consistent_outcome_side`).
- canonical_portfolio_reconciler: `.get("outcome", "yes")` → `or ""` at
  all three sites — unknown exchange outcome yields 0 signed exposure →
  reconciliation divergence flagged instead of fabricated YES.
- ct_execution_adapter: direction validated before pending-order tracking
  and before `submit_signal`/`OrderIntent` construction (was fabricating
  buy/yes upstream of contract validation, and leaving stale pending
  entries that blocked the ticker).
- swarm/execution_subscriber: missing/invalid side/action now raises
  RuntimeError before VenueGate/ExecutionGuard (was `or "yes"`).
- swarm/matrix: return-calculation skips fills with unknown action
  (was `or "buy"` flipping the payout formula).
- incidents/replayer: position seed `p.get("side", "yes")` → `or ""`
  (honest unknown in replay evidence).
- portfolio_event_sources: ORDER_CREATED event `action` default "buy" →
  `None` (honest missing field in the event ledger).
- position_cache: `data/` paths (`kalshi_applied_fill_ids`,
  `kalshi_pending_tp_targets`, `kalshi_order_id_to_client_tag`) now
  env-overridable + redirected in conftest.

### Classified no-change sites
- order_router `RepriceWouldCross` exception fields (`intent.action or "buy"`,
  side guesses at ~7965/7977/8028/8157+): metadata on a rejection path;
  consumer only reads `e.reason`/`e.attempted_price`. OrderIntent contract
  already guarantees action ∈ {buy,sell} before routing.
- order_router:13288 `(intent.action or "buy")` in the order-conversion block:
  pre-parse placeholder; `_build_create_order_request` re-derives side/action
  canonically and raises OrderIdentityError on unresolvable values — the
  placeholder cannot reach the wire.
- client.py:5587 `side = "yes"  # Default for legacy positive positions`:
  Kalshi `position_fp` sign convention — positive signed count with absent
  side field is defined as YES by the exchange format; not a fabricated
  direction. Reviewed, justified.
- loop_15m `can_fill_order_safely(..., side="yes")` probes at ~4224/6382:
  pre-direction asset-readiness liquidity probes (direction not yet chosen);
  coarse gate, noted caveat — probes YES book depth only.
- Signature defaults `side="yes"`/`action="buy"` in maker_taker_policy,
  market_regime, canonical_buckets, kalshi_tools, model, unified_sizing,
  liquidity_fallback, crypto_15m_indicators, trading.get_best_price,
  rebalancer.side_preference, flow.models.whale_action: latent hazards —
  checked call sites pass explicit values on hot paths; left in place to
  avoid churning public signatures, flagged for follow-up hardening.
- 13 collection-level module skips are legacy-module `skip()` calls —
  classification pending per-module review.

## Un-skipped file resolutions

### tests/test_reliability_audit_regressions.py — 73 passed, 1 warning
Removed blanket module `pytestmark` + all unconditional per-test skips
(were hidden behind "unrelated to config migration"). Real fixes landed:
- `merid/settings.py`: added missing `KALSHI_MAX_RETRIES` Field; removed
  duplicate `KALSHI_CIRCUIT_RECOVERY_TIMEOUT` declaration.
- `client.py::_load_kalshi_settings()`: now actually reads `merid.settings`
  (was dead code re-assigning hardcoded literals).
- Stale source-grep tests updated to current implementation (BUG-04 lazy
  settings loader, BUG-06 subscription filter, BUG-07 fake loop `**kwargs`
  + coroutine close, BUG-08 `set_task_context` now in `_tick_body`).
- 2 BUG-02 auth→circuit-breaker tests deleted as obsolete: the contract
  (record auth failure on circuit breaker) was deliberately rejected by a
  documented STARTUP FIX — concurrent agent auth failures at startup would
  open the shared circuit and block all trading.

### tests/kalshi_alignment/test_production_invariants.py — 23 passed, 4 xfailed
Removed unconditional skips hiding 8 stale/failed tests. Fixes: resync tests
drive the current debounce contract (≥3 violations in 30s, patched
`_schedule_duality_resync`); duality fixture corrected (was crossed-book, not
a duality gap); large-spread fixture satisfies YES/NO invariants while
exceeding the current 85¢ threshold; `OrderIntent`s gained
`time_to_expiry_seconds` + `p_selected`; `_check_intent_risk` and
`_get_strategy_policy` patched; `pytest_asyncio.plugin` added to the
test-caller authorization prefixes; market states built entry-ready
(`data_source=WS_LIVE`, `data_quality=GOOD`, `snapshot_complete`,
`live_sequence_confirmed`, `book_health=LIVE`, strike fields) so the tests
reach the gates under test instead of dying at `market_not_entry_ready`.
- `test_order_rejected_when_age_exceeds_sla`: assertion updated to the
  canonical `staleness_slo` rejection (5s SLO in `_prepare_order_for_gate`,
  stricter than the now-unreachable 60s `stale_market_data` check in
  `_route_live`). Invariant preserved and strengthened.

Strict xfails (tracked defects, expiry 2026-10-15):
- AUDIT-2026-09-22-01 — `test_backward_timestamp_logged`,
  `test_negative_age_auto_corrected`: backward/negative market-data
  timestamp critical logging was dropped in the market_state refactor;
  no code path flags negative ages anymore.
- AUDIT-2026-09-22-02 — `test_kill_switch_no_live_data_blocks_orders`:
  SEV-0 no-live-data kill switch disabled via `if False:` at
  order_router.py:11551 ("to reduce trade blocking") — stale
  priority-series data cannot reject orders.
- AUDIT-2026-09-22-03 — `test_kill_switch_too_many_reconnects_blocks_orders`:
  `risk_controller.can_trade()` kill-switch gate (order_router.py:11939)
  only runs inside `_route_live`; MOCK/PAPER routes bypass it entirely.

Remaining warning in file: DeprecationWarning for `_kalshi_fee_cents`
(order_router.py:6066) — deprecated fee helper still called in production;
classify as warn-filter candidate pending replacement.

## Baseline run 2 (2026-09-22, -n 4, timeout=12, JUnit OK)
`335 failed / 5956 passed / 912 skipped / 102 warnings / 32054 errors`,
17m38s, `audit/baseline_junit_20260922.xml` serialized successfully.

**32k-error root cause found + fixed**: `tests/conftest.py` created
`_stdlib_logging.StreamHandler()` with no stream arg at conftest-import time,
binding the collection-phase pytest capture stream. Once closed, every emit
through the shared `utils.logger` stub handlers raised
`ValueError: I/O operation on closed file` — surfacing as setup/teardown
errors on ~32k tests under xdist (serial runs showed it only as teardown
"Logging error" noise). Fixed by binding `sys.__stderr__`. Verified: a 300-test
`-n 2` sample produced 0 errors afterward.

**Import-time live-balance fetch fixed**: `Settings.__init__` called
`_fetch_kalshi_balance()` (real signed REST call with repo credentials)
whenever `MERID_TOTAL_CAPITAL_USD <= 0` — fired during test collection.
Now skips when `MERID_ENV=testing` alongside the existing replay guard.
conftest also force-empties `KALSHI_API_KEY_ID`/`KALSHI_PRIVATE_KEY_PATH`
so any other direct-auth path fails closed on missing credentials.

Note: run-2 counts still reflect the pre-fix harness (errors inflated);
a rerun after the StreamHandler fix is required for the true census.

### tests/test_cognitive_ui.py — class-level strict xfails
AUDIT-2026-09-22-04 — the Sprint-12 cognitive UI was never committed to
this tree: `CognitiveView.tsx`, `useCognitive.ts`, `useRealityDebug.ts`,
`RealityDebugPanel.tsx`, `RegimeTagCloud.tsx`, `HypothesisTimeline.tsx`
have no git history, `constants.ts` defines no COGNITIVE endpoints, and
`web/main.py` never mounts `cognitive_api`. Only orphan backend modules
(`merid/cognitive/*`, `web/api/cognitive_api.py`) exist. All 9 UI-facing
test classes (~246 tests) carry `xfail(strict=True)` — TestBackendAPIs
(tests the existing backend modules) is unmarked and passes. Expiry
2026-10-15: land the UI or delete the classes.

## Baseline run 3 (2026-09-22, -n 4, timeout=120, JUnit OK)
`1917 failed / 14497 passed / 1199 skipped / 250 xfailed / 241 warnings /
10748 errors` in 1h27m, `audit/baseline_junit_20260922c.xml`.

**Dominant error cluster root-caused**: 10,695 of 10,756 errors were
`ValueError: I/O operation on closed file` at setup/teardown. Reproduced
serially: `scripts/go_live_preflight.py:30` executes
`sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)` at IMPORT time on
Windows. Under pytest that discards the capture `EncodedFile`; its GC
closes the shared per-test capture tempfile → every subsequent
`snap()`/`suspend()` in `FDCapture` raises → the entire worker errors out
per-test. One bad import in `tests/test_audit_plan_a.py` poisoned the whole
worker. Fixed: rewrap now guarded by `"pytest" not in sys.modules` (same fix
in `scripts/check_live_readiness.py`). The conftest `StreamHandler` →
`sys.__stderr__` fix from run 2 remains valid but was NOT the cascade cause.

Remaining genuine setup errors (small counts, per-test):
`create_app() got an unexpected keyword argument 'lifespan'` (36),
`merid.reconciliation` missing `kalshi_reconciler` attr (8),
`MarketCandidate` import gone from kalshi_continuous_trader (6),
`merid.event_venues.kalshi.take_profit` module gone (3),
8 worker crashes (execnet 'node down').

## Failure cluster census (from baseline_junit_20260922c.xml)

Top failure signatures (count | signature):

| n | Signature | Likely disposition |
|---|-----------|--------------------|
| 321 | ModuleNotFoundError (removed modules: swarm.consensus_aggregator, trading.paper_trading, flow.risk, signals.*, prediction.*) | obsolete — tests target deleted modules; per-class delete/collect_ignore pending review |
| 163 | FileNotFoundError | missing fixtures/UI files — split: obsolete vs missing-dep |
| ~150 | UI source-grep on never-committed React files (cognitive_ui, loop_orchestration_ui, ui_robustness, sprint41_react_memo, sprint42_displayname) | xfail(strict) AUDIT-2026-09-22-04 — applied |
| 61 | RuntimeError: no current event loop | async-fixture drift — needs pytest-asyncio review |
| 45+43+30+14 | AttributeError clusters | API drift — per-cluster triage pending |
| 51 | test_exit_fill_without_position_fix_2026_07_21 | pending triage |
| 55 | test_capital_ladder | pending triage |
| 35 | test_kalshi_pipeline_invariants | URL/env-derivation contract changed (unknown/unset env → live via deprecated KALSHI_USE_DEMO shim); needs per-test disposition — potential fail-open default |
| 26 | "Endpoint key missing from constants.ts" | same missing-UI family |
| 23 | CachedPosition.__init__ signature drift | stale tests — pending |
| 22 | UnicodeDecodeError 0x90 | binary file read as text — pending |
| 21 | "too many values to unpack (expected 3)" | signature drift — pending |
| 12 | assert 401 == 200 | tests hitting real API without auth — pending (may be env-dependent) |
| 10 | httpx.ConnectError refused | tests requiring live services — skipif candidates |
| 9 | assert_exit_delta kwarg drift | stale tests — pending |

Genuine setup errors remaining after IO fix (~61 total):
create_app(lifespan=) signature (36), reconciliation.kalshi_reconciler attr (8),
MarketCandidate import (6), take_profit module (3), 8 worker crashes.

### conftest stub-completion fix
`utils.logger` stub gained a lazy `__getattr__` delegating unstubbed
attributes (`JsonFormatter`, `SensitiveDataFilter`, `format_price`, …) to
the real `utils/logger.py` loaded under a private module name. Fixes
`test_telemetry.py::TestJsonFormatter::*` import failures without
restoring production log paths (the stub's temp-dir get_logger still
wins).

## Disposition pass 2 — UI source-grep + obsolete-module sweep (2026-09-22)

Applied via audit/apply_dispositions.py + audit/apply_ui_marks.py +
audit/fix_parametrize_positions.py (all three committed under audit/).

- 234 obsolete tests + 18 now-empty classes deleted across 57 files: they
  imported or source-grepped modules deleted in the Phase-1 legacy sweep
  (e.g. merid.swarm.consensus_aggregator, merid.trading.paper_trading,
  merid.prediction.trading_agent, web.api.rewards/betting/quadratic_funding,
  merid.signals.* helpers, merid.flow.risk) or deleted design docs.
  Verified against git history: deletions were deliberate
  ("Phase 1: Safe Module Deletion").
- merid/flow/__init__.py + web/api/flow_api.py: real bug fixed — imported
  `merid.flow.risk` but the module was renamed `flow_risk`; the whole
  merid.flow package was unimportable. Restored tests/test_flow.py (83 pass).
- Missing-file UI tests (fnf on never-committed React targets):
  conditional strict xfail per param via `_ui_params()` /
  `_ui_pair_params()` — `xfail(not target.exists(), strict=True)`, so the
  mark drops off per-param once a file lands.
- Existing-file content violations: per-param or per-test strict xfail.

New tracked defects (all strict xfail, expiry 2026-10-15):

| ID | Defect |
|----|--------|
| AUDIT-2026-09-22-04 | frontend file/feature absent from this tree (never committed) |
| AUDIT-2026-09-22-05 | existing stateless React components not wrapped in React.memo |
| AUDIT-2026-09-22-06 | existing React.memo components missing displayName |
| AUDIT-2026-09-22-07 | hardcoded setTimeout in views instead of DEFAULTS.TIMEOUTS |
| AUDIT-2026-09-22-08 | new view components built but not wired into App/Sidebar/views.ts |
| AUDIT-2026-09-22-11 | existing implementation violates asserted contract (UI + backend) |

Focused UI verification: 24 files -> 357 passed / 461 xfailed /
0 failed / 0 XPASS (was 115 XPASS(strict) from file-level marks).

Remaining unclassified (still failing — not hidden):
- ~200 ImportError "cannot import name" / AttributeError on deleted or
  renamed attrs (merid.prediction.*, web.api.*, merid.reconciliation,
  webhook_client, kalshi_continuous_trader, liquidity_monitor, ...)
  -> same deleted-module sweep, second order.
- test_kalshi_pipeline_invariants env-URL cluster (22): URL derivation
  treats unknown/missing env as live via deprecated KALSHI_USE_DEMO shim —
  fail-open default under review.
- test_prediction_audit_regressions (6): `merid.prediction.risk` attr
  drift — triage pending.

## Durable-state isolation — additional writers redirected

- trading/paper_trading.py: `_PERSIST_FILE` now honors
  MERID_PAPER_POSITIONS_PATH; startup cleanup honors
  MERID_PAPER_LADDER_STATE_PATH. (Was: hardcoded repo data/, deleted
  files at startup — the source of the paper_positions.json pollution.)
- merid/monitoring/rejection_monitor.py: output_dir default now honors
  MERID_REJECTIONS_DIR.
- backup/backup_manager.py: backup_dir default now honors
  MERID_BACKUP_DIR (core/database_backup_manager.py already did).
- tests/conftest.py: added MERID_PAPER_POSITIONS_PATH,
  MERID_REJECTIONS_DIR, MERID_BACKUP_DIR to the redirect map.
- Residual: tests that `patch.dict(os.environ, clear=True)` wipe the
  redirects and can still write repo data/ paths during the cleared
  window — flagged; per-test fix pending identification of writers.

## Disposition pass 3 — ImportError/AttributeError obsolete sweep (2026-09-22)

Applied via audit/apply_deletions2.py (second-order obsolete deletion).

- 113 additional tests deleted across ~35 files: `ImportError: cannot
  import name` / `AttributeError` failures on symbols removed by the same
  deliberate refactors (renamed modules, replaced APIs like the old
  `calculate_kalshi_fee_cents(prob, price)` signature, removed helpers).
- AST-overlap bug found and fixed in both deletion passes: deleting a
  whole class left stale child spans that consumed following classes.
  29 damaged files restored from d87a3776 and dispositions re-applied;
  audit/damage_check_final3.txt verifies 0 remaining damage across 98
  changed test files. audit/restore_orphans.py + parent-class mapping
  distinguishes true collateral from helpers nested inside intended
  deletions.

## Production-code fixes (2026-09-22, third commit batch)

- merid/loop.py: removed dead `self._run_consensus(summary)` call block —
  the method was deleted in 0c135d21 but the call site survived, so the
  legacy loop would crash with AttributeError every consensus interval
  (~120s). Also wrapped `_feature_service()`, `_scanner()`,
  `_signal_store()`, `_drift_detector()` accessor use in
  _refresh_features/_run_arb_scan/_update_cqi with the file's existing
  graceful-degradation pattern — each lazily imports a deleted
  merid.signals.* module and previously raised ModuleNotFoundError inside
  _tick_body. (loop.py is legacy; production path is loop_15m.py, but the
  file is still referenced by health/worker tooling.)
- merid/swarm/__init__.py: removed dead `consensus_aggregator` re-export.
  The package initializer imported a deleted module, which broke
  `import merid.swarm.execution_subscriber` — still used by the live
  order router (event_venues/kalshi/order_router.py). Same defect class
  as the earlier merid.flow init bug.
- web/main.py: wired the existing `swarm_bus_api` router into the compat
  stub alongside the other preserved routers.
- tests/test_sprint_m.py: updated stale consolidated view IDs
  (`calibration-dashboard` -> `calibration`, plus `consensus-calibration`)
  to match the actual React manifest + backend sidebar_config; deleted
  obsolete `TestSocialBroadcasterConsensusEvent` (deleted module).
- tests/test_loop_lag_stress.py: restored `TestLoopLagIntegration` (valid
  loop-liveness contract, wrongly deleted as obsolete) and the lag-skip
  tests with corrected 2000ms threshold expectations (was 500/1000).

## Durable-state isolation — pinned environment + verdict

- tests/conftest.py: `os.environ` replaced with `_PinnedEnviron` — a
  subclass of the interpreter's `_Environ` that re-pins all
  safety-critical MERID_* redirects inside `clear()`. Tests using
  `patch.dict(os.environ, clear=True)` can no longer wipe the durable
  path redirects mid-test; unrelated env manipulation still works.
- Verified: audit/trace_data_writes.py (Python audit hook on
  `open`/`sqlite3.connect`) recorded ZERO writes under repo `data/`
  across collection + execution of focused suites.
- Important environmental finding: the pollution guard's `data/` diff
  was also catching writes from a concurrently-running production
  uvicorn process (web.main_15m_lean:app, :8011) — it mutates the same
  durable files every ~30s. Guard is only meaningful while no live
  process is running; 24 hung zombie pytest processes (2:57–4:20 AM
  leftovers) were also killed. Operator stopped the server for the audit.
