# MERID Agent Notes

## Canonical data model

- **Quantity**: integer centi-contracts (`quantity_cc = int(Decimal(count_fp) * 100)`). Fractional fills such as `0.49` are represented as `49` centi-contracts and are never rounded to whole contracts.
- **Price**: `Decimal` dollars, validated against the market's `price_ranges` and tick size. `price_cents` may be used as a lossy display/legacy field, but the canonical cost basis is `Decimal`.
- **Exposure**: signed-YES centi-contracts (`yes_exposure_cc`). Positive is long YES, negative is long NO.
- **Fill identity**: immutable `fill_id`. A fill is the atomic unit of state mutation.
- **Order identity**: `intent_id` (internal), `client_order_id` (wire), `order_id` (venue). All three map to a single order record.

## Non-negotiable invariants

- **One fill ID mutates state exactly once.** Router immediate-fill handling, WebSocket fills, and HTTP pollers must all call the same durable `apply_fill_once(fill_id, ...)` path. Duplicate `fill_id`s are a no-op with `duplicate_fill_id` telemetry.
- **Exchange/cache/ledger exposure must match per ticker.** Any divergence sets `reconciliation_halted` and blocks new entry routing. Exits remain enabled so the agent can close to zero.
- **Unknown fills are quarantined; never inferred as entries.** A fill with no `client_order_id`, `order_id`, or recorded `OrderIntent` is stored as `UNMATCHED_FILL`. It must not create a position, attach TP/SL, add monitor state, consume or release risk, or update PnL.
- **Reduce-only fills cannot increase absolute exposure.** A `reduce_only` or `entry_or_exit == "exit"` fill may reduce or flatten exposure, but it can never create a new position in the opposite outcome.
- **Exit routing remains enabled during entry halt.** Fail-closed reconciliation blocks entries, not exits.
- **Event positions are not market positions.** `market_positions.position_fp` is the signed, per-market exposure. `event_positions` are aggregate event-level data and must not be used as a substitute for per-market exposure.

## Fill application invariants

- `fill_id` is the global immutable idempotency key.
- A fill may mutate the ledger, cache, risk, allocator, monitor, and session accounting exactly once.
- Router immediate-fill handling and HTTP/WebSocket pollers must call the same durable `apply_fill_once(fill_id, ...)` path.
- A duplicate fill is a no-op with `duplicate_fill_id` telemetry.
- An unresolved fill is quarantined as `UNMATCHED_FILL`; it must not create a position, attach TP/SL, add monitor state, consume/release risk, or update PnL.
- `reduce_only`, `entry_or_exit`, `order_id`, and `client_order_id` are immutable order metadata. They are resolved before any cache mutation.
- A reduce-only fill can reduce or flatten exposure only. It can never create a new position in the opposite outcome.

## OrderResult semantics

For V2, Kalshi's create-order response separates `fill_count` and `remaining_count` for IOC, and `remaining_count` for GTC resters. `OrderResult` must therefore expose:

```python
request_completed: bool      # HTTP response received and parseable
has_execution: bool          # at least one fill confirmed
executed_quantity_cc: int    # filled quantity in centi-contracts
remaining_quantity_cc: int   # remaining open quantity in centi-contracts
is_resting: bool             # confirmed GTC order is live on the book
requires_recovery: bool      # submission state unknown; do not retry blindly
```

Recommended mapping:

| Result | Request completed | Has execution | Risk effect |
|---|---:|---:|---|
| `filled_live` | Yes | Yes | Apply filled exposure |
| `partial_live` | Yes | Yes | Apply filled exposure, resolve remainder |
| `unfilled_ioc` | Yes | No | Release reservation, no trade |
| `resting` | Yes | No | Retain confirmed-open reservation |
| `rejected` | Yes | No | Release reservation |
| `submission_unknown` | No/unknown | Unknown | Retain reservation until lookup |
| `duplicate_unknown` | Unknown | Unknown | Lookup before retry |

## Required verification

After changing order-router, port, ledger conversion, exposure-reconciliation, or binary_price_space code, run at least:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_router_ioc_tif_reconciliation.py tests\kalshi_alignment\test_order_router.py tests\event_venues\kalshi\test_port_ledger_adapter.py tests\event_venues\kalshi\test_kalshi_p0_partial_fill_reconciliation.py tests\event_venues\kalshi\test_kalshi_p0_maker_taker_simulator.py tests\event_venues\kalshi\test_kalshi_p0_exit_order_simulator.py tests\test_loop_15m_bugfixes.py tests\test_loop_15m_decimal_fix_2026_07_29.py tests\test_exit_canonicalization_and_policy_2026_08_07.py tests\test_canonical_exposure_reconciliation.py tests\test_fills_ledger_v2_side_action_fix.py tests\test_fills_ledger_v2_fractional_replay.py tests\position_management\test_position_monitor_cleanup_exit.py tests\position_management\test_position_monitor.py tests\position_management\test_position_monitor_exit_audit.py tests\position_management\test_spread_stop_provenance.py tests\event_venues\kalshi\test_execution_risk_firewall.py tests\event_venues\kalshi\test_kalshi_order_manager.py tests\test_direct_venue_submission_guard.py tests\test_production_startup_validation.py tests\test_trade_decision_release_gates.py tests\test_cf_rti_adapter.py tests\test_cf_rti_e2e.py -v
```

For firewall enforcement smoke in production, set `MERID_EXIT_FIREWALL_OBSERVE_ONLY=false` and `MERID_REQUIRE_EXIT_PARENTAGE=1` and watch for `firewall:` rejection reasons. In observe-only/canary mode, set `MERID_EXIT_FIREWALL_OBSERVE_ONLY=true`.

## Explicit environment model (2026-08-18)

- `tests/conftest.py` sets `MERID_ENV=testing`, `MERID_EXIT_FIREWALL_OBSERVE_ONLY=true`, `MERID_REQUIRE_EXIT_PARENTAGE=0`, and clears direct-execution bypass flags before any merid imports. Do not rely on `PYTEST_CURRENT_TEST` to alter production behavior.
- `merid/settings.py` loads `.env` with `override=False` so `os.environ` always wins over the repo `.env`. Test config cannot inherit `MERID_ENV=prod` from `.env`.
- `merid/startup_validations.validate_production_startup()` hard-fails production startup if `PYTEST_CURRENT_TEST`, `DEBUG_ALLOW_MANUAL_ORDERS`, `ALLOW_DIRECT_EXECUTION`, `MERID_ALLOW_CT_SCRIPT_BYPASS`, `MERID_EXIT_FIREWALL_OBSERVE_ONLY=true`, `MERID_CIRCUIT_BREAKER_DISABLED=true`, or any legacy exchange credential is present; or if `MERID_REQUIRE_EXIT_PARENTAGE` is not set to `1`; or if `KALSHI_ENV` conflicts with the canonical `MERID_KALSHI_ENV`. It is called from `web/main_15m_lean.py` before any venue connection or worker.
- `start_15m.ps1` enforces the same variables in live mode, derives `KALSHI_ENV` from `MERID_KALSHI_ENV`, strips legacy exchange credentials, and loads `.env.production` (or another `-EnvFile`) as the production config source.

## Open issues

- `tests/test_kalshi_client.py` (`TestOrderOperations` and `TestPagination`) now pass. Raw `VenueOrder` objects in manual/test mode receive an auto-generated `client_order_id` if none is supplied, and event positions are explicitly excluded from `get_positions_result` market-position output (per the "Event positions are not market positions" invariant).

## CF Benchmarks RTI adapter (2026-08-19)

- The canonical settlement price authority is `merid.data.cf_rti_adapter.CfbRtiObservation`.
- `get_live_rti(asset)` is the only interface that can produce `settlement_reference="cfb_rti_live"`.  It returns `None` for all failure modes and never falls back to a public spot price.
- Health gates enforced: source identity, asset/symbol mapping, value sanity, freshness (`MERID_MAX_CFB_RTI_AGE_MS`), stream liveness, ordering (timestamp and sequence), subscription integrity, and target linkage.
- Rejection reasons are precise: `cfb_rti_unavailable`, `cfb_rti_stale`, `cfb_rti_symbol_mismatch`, `cfb_rti_nonmonotonic`, `cfb_rti_invalid_value`, `cfb_rti_subscription_unconfirmed`, `source_not_cf_benchmarks`.
- The adapter must be enabled with `MERID_CFB_RTI_ADAPTER=true`.  In the default `false` state it returns `None` and logs `cfb_rti_adapter_not_live`.
- `merid/prediction/agent_grid_15m.py` resolves the settlement input through the adapter and records the honest `settlement_reference`.  Downstream `trade_decision.py` only marks `confidence_valid=true` for `cfb_rti_live`.
- `merid/prediction/trade_decision.py` blocks all entries inside `MERID_FINAL_MINUTE_CUTOFF_S` (default 60s) with `no_trade_reason=final_minute_entry_disabled`.
- Shadow-mode telemetry is persisted to `data/shadow/cfb_rti/` for every candidate (enabled by `MERID_CFB_RTI_SHADOW_TELEMETRY=1`, default on).  Files include the raw RTI frame, normalized observation, probabilities, edge, confidence, and rejection reason.
- Tests: `tests/test_cf_rti_adapter.py` and `tests/test_trade_decision_release_gates.py::test_rejects_final_minute`.
- For live canary: run `MERID_CFB_RTI_ADAPTER=true MERID_PM_TRADING_MODE=paper MERID_ALLOW_LIVE_TRADES=false` and validate the shadow telemetry for several complete market cycles before allowing the first capped live entry.

For firewall enforcement smoke in production, set `MERID_EXIT_FIREWALL_OBSERVE_ONLY=false` and `MERID_REQUIRE_EXIT_PARENTAGE=1` and watch for `firewall:` rejection reasons. In observe-only/canary mode, set `MERID_EXIT_FIREWALL_OBSERVE_ONLY=true`.

Also run the new fractional/replay tests in `tests/test_fills_ledger_v2_fractional_replay.py`:

- Fractional fills (`0.49`, `0.50`, `0.51`, `0.99`, `1.00`, `1.55`) preserve exact centi-contract exposure and fees.
- Two fills totaling one contract remain two ledger records with separate `fill_id`s.
- Router fill followed by identical HTTP fill causes exactly one cache/risk/monitor mutation.
- Exit `SELL_YES` on long YES reaches zero and cannot construct long NO.
- `BUY_NO` and `SELL_YES` both produce `-q` signed-YES exposure.
- `market_positions.position_fp=-1.55` normalizes to `-155` signed-YES centi-contracts.
- Sub-cent price payloads remain valid and preserve exact cost basis.
- Unknown fill metadata produces `UNMATCHED_FILL`, never a `NEW` position.
- Cache rebuild from immutable applied fills matches current exchange signed position to the centi-contract.

## Bracket safety

- `_submit_resting_bracket` must skip non-open markets.
- `status=unknown` must not proceed as harmless; emit `BRACKET_UNAVAILABLE_MONITOR_REQUIRED` if bracket placement cannot be confirmed.
- A startup replay must never submit brackets.
- A fresh live entry with unknown market state must not create unprotected risk.

## Rollback / recovery policy

Never use `PositionCache.reset()` as a rollback action. If anomalous fill or position counts are observed:

1. Disable new entries immediately.
2. Keep exit/reduce-only routing enabled.
3. Snapshot local ledger, cache, order gate, and risk reservations.
4. Fetch exchange open orders, current market positions, fills, and where needed historical positions/fills.
5. Rebuild a new cache projection from immutable persisted ledger events.
6. Compare exchange, ledger, cache, and pending orders in centi-contract units.
7. Quarantine mismatches; do not delete them.
8. Resume entries only after all active-ticker mismatches are resolved.

## Spread-stop and provenance invariants (2026-08-11)

- A stop-loss exit is only allowed when the trust chain is complete:
  `ORIGINAL_PERSISTED` risk state → `risk_params_schema_version >= 2` →
  fill linkage (`client_order_id`, `entry_intent_id`, or `entry_fill_id`) →
  `entry_book_capture_quality == "AT_FILL"` → `MIN_STOP_ARM_SECONDS` elapsed.
- Any missing link fails closed: the position is preserved and an alert is logged.
- A `POST_FILL` or later quote can never be recorded as the entry executable book
  for spread-only / adverse-move invariants.
- The `Position` dataclass downgrades `original_persisted` to `unknown` if no
  linkage is present and clears any inherited stop-loss.
- Profit exits (`TAKE_PROFIT`, `TRAIL`, `DYNAMIC_TAKE_PROFIT`, `EXTREME_PROFIT`)
  must use the executable own-side bid and must be at least
  `entry_fill_price_cents + TAKE_PROFIT_MIN_PROFIT_CENTS`.
- Fallback take-profit is only set from a trusted `entry_fill_price_cents` and
  only if the computed target clears the round-trip fee buffer.

## Order identity and circuit-breaker invariants (2026-08-11)

- Every outbound order must carry an identity chain: `client_order_id`,
  `intent_id`, `run_id`, `process_id`, `reason`.  The router rejects any order
  missing one of these before the API call.
- Exit orders must link to their parent entry via `parent_entry_fill_id`.  Set
  `MERID_REQUIRE_EXIT_PARENTAGE=1` to enforce this once every exit path is wired.
- `TradingCircuitBreaker` is a process-wide fail-closed emergency halt.
- A WebSocket fill that cannot be linked to a known or recently-submitted intent
  trips the breaker after a pending-intent grace lookup.
- An HTTP fill trips the breaker only if it is strictly newer than the persisted
  per-source watermark (`data/trading_circuit_breaker_http_watermark.json`).
  Backfills and CSV exports older than the watermark are quarantined and logged,
  but never halt trading.
- Before halting, the breaker looks up the fill against durable intent indices
  and the `fills_ledger` pending-order registry (`lookback_seconds=30`), so
  order-submission / fill-arrival races do not self-halt a healthy deployment.
- `is_manual_emergency_close` is not sufficient to bypass a halt.  It must also
  carry `approval_token` matching `MERID_MANUAL_EMERGENCY_TOKEN`.
- `audit_open_orders` is two-phase: first build a cancellation set from a fully
  paginated open-order snapshot and a consistent intent-registry snapshot; then
  re-fetch open orders and cancel only those still open and still untracked.
- Deploy the breaker in `MERID_CIRCUIT_BREAKER_OBSERVE_ONLY=1` mode first to
  validate watermarks and intent matching before enabling enforcement.
- Do not run in production with `MERID_CIRCUIT_BREAKER_DISABLED=1`.

## Release gate

- [x] All `OrderResult.success` consumers switched to `request_completed` / `has_execution` / `executed_quantity_cc` / `remaining_quantity_cc`.
- [x] `port_ledger_adapter` no longer rounds fractional contracts or canonicalizes cent-rounded prices.
- [x] `venue_client_port.get_fills()` groups split pieces by unique `fill_id` and returns one `Fill` per unique `fill_id`.
- [x] `KalshiFill` carries `quantity_cc` (centi-contracts) and `price_dollars` as `Decimal`.
- [x] `binary_price_space.yes_delta()` and `to_signed_yes_exposure()` operate on centi-contracts.
- [x] `position_cache.on_fill()` and `sync_from_rest()` reconcile in `quantity_cc`/`yes_exposure_cc`.
- [x] Replay tests verify that an exit fill followed by HTTP/WebSocket replay leaves zero position and zero monitor registrations.
- [x] No submitted stop exit has `risk_params_state != ORIGINAL_PERSISTED`, `risk_params_schema_version < 2`, or `entry_book_capture_quality != AT_FILL`.
- [x] Stop exit records capture raw YES bid/ask, derived NO bid/ask, and the executable liquidation price via the `ExitPriceSnapshot` path.
- [x] No live order is routed with missing `client_order_id`, `intent_id`, `run_id`, `process_id`, or `reason`.
- [x] `TradingCircuitBreaker` is not disabled (`MERID_CIRCUIT_BREAKER_DISABLED` unset) in production.
- [ ] `MERID_CIRCUIT_BREAKER_OBSERVE_ONLY=1` has been run in paper/canary and the watermark and pending-intent lookup are verified.
- [x] `MERID_MANUAL_EMERGENCY_TOKEN` is set and stored outside the codebase (User environment).
- [ ] `audit_open_orders(cancel_untracked=True)` has been run and zero untracked resting orders remain.
- [ ] Canary run in paper mode shows zero `unfilled_ioc` trades, zero malformed ledger dicts, and zero fractional-contract rounding.

## Incident links

- `docs/incidents/2026-08-09-fill-replay.md`
- `docs/incidents/2026-08-09-cross-leg-exposure.md`

## V2 fixed-point, replay, and rollback invariants (2026-08-09)

### Fixed-point quantity model

- `KalshiFill.count_fp` is an exact `Decimal` in whole contracts. It is never rounded to an integer.
- `KalshiFill.quantity_cc` is the canonical integer centi-contracts (`count_fp * 100`).
- `port_ledger_adapter` converts `Fill.size` / `Position.size` `Decimal` to `quantity_cc` without rounding; `contracts` is a display-only floor value.
- `fills_ledger._parse_fill` preserves fractional `count_fp` from V2 `count_fp` and computes `quantity_cc` exactly.
- `compute_position_from_fills` and `position_cache.on_fill` / `apply_fill` use `quantity_cc` for exposure, cost basis, and PnL.
- `CachedPosition.quantity_cc` is the canonical position size. `CachedPosition.contracts` is display-only (`quantity_cc // 100`).

### Replay safety

- `fill_id` is the global, immutable idempotency key. `KalshiPositionCache._applied_fill_ids` and the durable `KalshiFillsLedger` both gate duplicate application.
- A replayed HTTP-poller exit with the same `fill_id` as a prior WS exit is a no-op and cannot re-open a closed position.
- An exit fill is authoritative only when correlated to an `OrderIntent` with `entry_or_exit == "exit"` or `reduce_only == True`; otherwise it is `UNMATCHED_FILL`.
- `recompute_position_from_ledger` replays `KalshiFill.quantity_cc` in timestamp order and reconstructs `CachedPosition.quantity_cc` exactly.

### Position monitor cleanup and exit invariants

- `PositionMonitor.remove_position` removes the active position **before** attempting capacity/risk/monitor cleanup. A bookkeeping failure never resurrects or retains an active position.
- All notional math in `PositionMonitor` uses `Decimal`; `record_position_closure` and `record_order_execution` in `kalshi_crypto_15m_risk_envelope` defensively cast to `float` so a rogue `Decimal` can never raise a `TypeError`.
- If capacity/risk/monitor cleanup fails, a `CLEANUP_PENDING` work item is queued and retried via `PositionMonitor.retry_cleanup`.
- `PositionMonitor.add_position` rejects strip/series-only keys (e.g. `KXBTC15M`). Positions and exits must be keyed by a full market ticker (`KXBTC15M-26AUG100000-00`).
- Exit in-flight state is a state machine (`SUBMITTED` → `SUBMISSION_UNKNOWN` → `RECONCILED`). A 15.15s timeout does **not** silently clear the in-flight record; it transitions to `SUBMISSION_UNKNOWN` and blocks duplicate exits until `port`/`exchange` reconciliation confirms the order state or the position is flat.

### Rollback plan

1. Revert to the last known-good commit if anomalous fill/position counts, phantom positions, or PnL drift are observed.
2. Restart the process with `PositionCache.reset()` / `KalshiPositionCache().clear()` so the cache is rebuilt from the durable fills ledger and REST snapshot.
3. Do not manually cancel or place orders until the three-way exposure reconciliation (exchange / ledger / cache) reports `matched` for all active tickers.
4. If a specific ticker is `reconciliation_halted`, allow only reduce-only exits until the mismatch is resolved.

## Canonical order-intent contract (2026-08-10)

- Every order submitted to `route_order()` / `route_order_async()` is normalized through `merid.event_venues.kalshi.order_intent_contract.normalize_order()`.
- `CanonicalOrderIntent` is an immutable, signed-YES, centi-contract contract: `market_ticker`, `contract`, `action`, `purpose`, `qty_cc`, `limit_cents`, `strategy_signal`, `expected_position_before`, `expected_position_after`, `expected_realized_pnl_cents`, `reason`.
- Exits fetch a fresh exchange position snapshot before validation; entries use the reconciled position cache.
- Hard-rejection invariants: `qty > 0`, `10 <= limit <= 75` for entries (canonical entry range, symmetric YES/NO), `1 <= limit <= 99` for exits/reduce-only orders, `expected_position_before == exchange_position`, no position flips, no over-close, `sell` may not create a negative YES position unless `allow_short=True`, and predicted adverse PnL may not exceed `MERID_MAX_ADVERSE_PNL_CENTS`.
- Decisions are persisted to `logs/order_decisions.jsonl`.

## Live runtime hardening (2026-08-11)

- `Position.__post_init__` sets a fallback take-profit only from a trusted
  `entry_fill_price_cents` and only if the target clears `TAKE_PROFIT_MIN_PROFIT_CENTS`.
  It never derives a take-profit from a REST-reconstructed or fallback average price.
- `position_cache.sync_from_rest()` is the single cache-mutation surface for REST snapshots.
  `fills_ledger.reconcile_with_kalshi_positions()` is purely diagnostic and never calls
  `cache.sync_from_rest()`.  Duplicate snapshots are dropped via per-source idempotency on
  `rest_timestamp`.
- REST-synced positions with unknown risk provenance are added to `PositionMonitor` for
  PnL/reconciliation tracking but carry no invented TP/SL.  Only schema-2 `ORIGINAL_PERSISTED`
  positions with an entry linkage restore their original stop-loss or take-profit.
- Negative `position_fp` values from Kalshi REST are a normal representation for long NO
  exposure and are logged at `INFO`, not `WARNING`.
- `MERID_SINGLE_USER_OPERATOR=1` is treated as an auth bypass and is hard-blocked when any
  live trading latch is set (`TRADING_ENABLED`, `MERID_PM_LIVE_ENABLED`, `MERID_ALLOW_LIVE_TRADES`,
  `MERID_PM_TRADING_MODE=live`).  Live runs must use `MERID_OPERATOR_TOKEN` and set
  `MERID_SINGLE_USER_OPERATOR=0`.
- `MERID_PM_PROFILE=production` is required for live Kalshi crypto 15m runs alongside
  `MERID_PROFILE=kalshi_crypto_15m_v2`.  `MERID_PM_PROFILE=baseline` skips production wiring
  and data-guard validation and must not be used for live trading.
- `MERID_KALSHI_WS_CLIENT=ws` is required for live production runs; the `websocket_service`
  trade channel is a stub and is rejected by startup validation when live.

## Protective-exit gating and entry idempotency (2026-08-16)

- Stop-loss exits go through the audited `StopCandidate` path in
  `merid/event_venues/kalshi/stop_candidate.py`.  Submission is gated by
  `MERID_ENABLE_STOP_CANDIDATE_SUBMISSION=true` (default off) and read dynamically via
  `stop_submission_enabled()`.  `MERID_STOP_SUBMISSION_KILL=1` is an emergency kill
  switch that overrides both the enable flag and `force=True`.
- A stop candidate that fires but is not submitted emits a `CRITICAL`
  `[ALERT][STOP-CANDIDATE-NOT-SUBMITTED]` record.  Treat any occurrence in live as SEV-1.
- Entries are fail-closed: `validate_canonical_intent` rejects `purpose="open"` with
  `PROTECTIVE_EXIT_DISABLED` whenever `protective_exits_enabled()` is False.  Exits are
  never blocked by this gate.  `MERID_ALLOW_UNPROTECTED_ENTRIES=1` is an explicit ops
  override and must not be set in production.
- Entries are also rejected with `entry_with_open_position` when the exchange/cache
  position for the ticker is non-zero (one open inventory unit per ticker).
- Per-(ticker, side, window) entry idempotency: a second accepted entry for the same
  key within `MERID_ENTRY_IDEMPOTENCY_TTL_SECONDS` (default 900) is rejected as
  `duplicate_entry`; resubmitting the same `client_order_id` qualifies as cancel/replace.
  Disable only via `MERID_ENTRY_IDEMPOTENCY_ENABLED=0`.
- Stop exits use bounded liquidation: limit = best executable bid minus
  `MERID_STOP_MAX_SLIPPAGE_CENTS` (default 3, floor 1c).  A stale trigger price can never
  sweep the book below that cap.  Submissions record trigger price, reference bid,
  submitted price, fill price, and realized slippage.
- Fee accounting: `fee_dollars_to_cents()` in `fills_ledger.py` is the only
  dollars→cents conversion (Decimal, ROUND_HALF_UP).  Never use `int(fee * 100)`.
  Kalshi V2 `fee_cost`/`fee_paid` are dollars; only the legacy `fee` key may be cents.
- Legacy tests run with `MERID_ALLOW_UNPROTECTED_ENTRIES=1` and
  `MERID_ENTRY_IDEMPOTENCY_ENABLED=0` via an autouse fixture in `tests/conftest.py`;
  the guard tests in `tests/event_venues/kalshi/test_stop_entry_fee_guards_2026_08_16.py`
  manage these env vars themselves.

## TradingCircuitBreaker halt gating and release (2026-08-11)

### Halt gating

When `TradingCircuitBreaker.halted` is `True`, `Kalshi15mLoop._run_agent_grid_with_timeout`
short-circuits before `agent_grid.run_cycle` is invoked. It emits one clear log line per
cycle and runs `agent_grid.sync_from_rest(tick)` to keep exchange reconciliation alive, then
returns an empty candidate list. This stops signal generation, sizing, allocation, and entry
execution. `PositionMonitor` and other background tasks remain alive; their autonomous exit
orders are rejected by `order_router.is_order_allowed` unless they carry `is_manual_emergency_close`
and a valid `MERID_MANUAL_EMERGENCY_TOKEN`.

The loop state also surfaces the halt reason via `no_trade_reason` in `_run_one_cycle`:
`TRADING_CIRCUIT_BREAKER_HALT:<reason>`.

### Controlled release

A halt must NEVER be cleared by calling `TradingCircuitBreaker.resume()` directly from
application code. The only supported release path is the logged administrative action
`TradingCircuitBreaker.admin_release(operator, run_id, approval_token, *, force=False, ...)`.

Required before release (unless `force=True`):

1. Kalshi open positions are zero (position cache / `get_balance`).
2. Kalshi open orders are zero and no untracked resting orders remain (`audit_open_orders(cancel_untracked=False)`).
3. No unresolved `UNMATCHED_FILL` events in the last 30 minutes (`fills_ledger.get_fills`).
4. The persisted HTTP watermark (`data/trading_circuit_breaker_http_watermark.json`) has
   advanced past the triggering fill timestamp.
5. A fresh `run_id`, non-empty `operator` id, and a valid release token
   (`MERID_BREAKER_RELEASE_TOKEN`, or `MERID_MANUAL_EMERGENCY_TOKEN` as fallback).

The method writes a `risk.trading_halt_released` event to `data/risk_audit_chain.jsonl`, then
calls `resume()`. The return value contains `released`, `ok`, and a list of every safety check.

### 2026-08-11 incident root cause

At 2026-08-11 22:38:34 UTC the system placed a BUY_YES order for `KXBTC15M-26AUG112145-45`
(`client_order_id=client_e2f7b5f653244b10`, `order_id=6ce07d03-b277-4828-bbcf-e7aefc74734d`).
The order filled immediately. Approximately 5 seconds later the HTTP fill poller ingested the
same fill from Kalshi's `/portfolio/fills` endpoint. The HTTP payload did not echo the
`client_order_id`, and the fills_ledger order-id index had not been durably updated by the
time the circuit breaker's pending-intent grace lookup ran. The breaker therefore treated a
live, newer-than-watermark HTTP fill as unmatched and halted.

Classification: `lost_intent` (not `other_writer`, `parser_defect`, or `historical_false_positive`).
The order was a legitimate MERID order. The failure was correlation/intent-linkage timing:
the fill's `order_id` was present but the ledger's lookup did not resolve it before the halt.

Reconciliation record: `data/reconciliation_record_6edd27fc.json`.
Incident doc: `docs/incidents/2026-08-11-unmatched-fill-halt.md`.

## 2026-08-12 REST avg-price and model-exit provenance fixes

### NO-position price normalization from Kalshi REST

- Kalshi reports `avg_price_cents` and `market_exposure_dollars`/`position_fp` in YES-side
  space for all positions. `position_cache.sync_from_rest()` now converts these values to
  the position's own side space: for a long NO position,
  `canonical_avg = 100 - raw_yes_avg`.
- New REST positions infer their canonical `thesis_side` from the signed `position_fp`
  before the price conversion, because `pos["side"]` is always `"yes"` from Kalshi's
  YES-side perspective.
- The resulting `CachedPosition.side`/`outcome_side` are canonical (not REST diagnostic),
  so `_yes_exposure()`, `notional_usd`, and `Position` conversion all use the correct side.
- For existing positions, `sync_from_rest()` uses `dataclasses.replace()` to update size and
  price while preserving the original entry fill/intent linkage and risk-parameter provenance.

### Model-invalidation loss exit provenance gate

- `ExitPolicy.evaluate_edge_decay()` now returns `MODEL_INVALIDATION_LOSS_EXIT` only when
  the position has trusted provenance:
  - `risk_params_state == ORIGINAL_PERSISTED`
  - `risk_params_schema_version >= 2`
  - at least one of `entry_fill_id`, `entry_order_id`, `client_order_id`, or `entry_intent_id`
  - `entry_book_capture_quality == "AT_FILL"`
  - `entry_signal_id`, `entry_model_probability`, and `entry_edge` are all present
  - `fill_source` is not in `{rest_sync, replay, historical, manual, unknown}`
- Without this chain, an edge-decay/loss exit is held and logged at `WARNING` with
  `[EXIT-POLICY-PROVENANCE]`. This prevents REST/replay-reconstructed positions from
  realizing a model-invalidation loss on a stale or inverted price.

### Verification commands

```powershell
.\.venv\Scripts\python.exe data\emergency_query_kalshi.py
.\.venv\Scripts\python.exe -m pytest tests\event_venues\kalshi\test_position_cache_health.py::TestRestPriceNormalization -v
.\.venv\Scripts\python.exe -m pytest tests\position_management\test_exit_policy.py::TestExitPolicyModelInvalidationProvenance -v
.\.venv\Scripts\python.exe -m pytest tests\position_management\test_position_monitor.py tests\position_management\test_position_monitor_exit_audit.py tests\position_management\test_spread_stop_provenance.py tests\test_exit_canonicalization_and_policy_2026_08_07.py -v
```

## KalshiFill canonical/execution field split (2026-08-12)

`KalshiFill` now stores the exchange's raw execution report in `side` and `action`, and the MERID canonical position effect in `canonical_position_side`, `canonical_position_action`, and `canonical_yes_delta_cc`.  Raw exchange audit fields are `execution_outcome_side`, `execution_action`, and `execution_price_cents`.  Downstream consumers of position/exposure/PnL must use the `canonical_position_*` fields; `side`/`action` are for audit and DB round-trip only.

The live `FILL-CANONICALIZATION` log emits every fill with raw + canonical fields and a parity check between `cache_signed_yes_after` and the last known `exchange_signed_yes_after`.  A `FAIL` sets `reconciliation_halted` for the ticker and blocks new entries.

### Deployment/reset procedure after this change

Do **not** simply restart and preserve an old `CachedPosition`.  When rolling this change to an existing deployment:

1. Fetch authoritative Kalshi positions and open orders.
2. Clear/rebuild only local derived state: position cache, monitor state, allocator exposure map, and fill-derived position projections.
3. Rehydrate from the canonical ledger plus a fresh exchange REST snapshot.
4. Verify every live ticker against exchange signed exposure.
5. Resume entries only after three-way reconciliation (exchange/ledger/cache) reports `matched` for all active tickers.

## Canonicalization invariants and migration (2026-08-13)

### Separation of raw execution and canonical position fields

- `KalshiFill.side` / `KalshiFill.action` are the raw exchange-reported contract side and direction. They are not a source of truth for position effect; they are audit fields.
- `KalshiFill.canonical_position_side` and `KalshiFill.canonical_position_action` are the raw exchange execution facts (`execution_outcome_side`, `execution_action`) exactly as the exchange reported them. The position effect is derived from those facts by `binary_price_space.yes_delta()` and recorded in `canonical_yes_delta_cc`.
- **Intent may not override execution.** `OrderIntent.side` is used only for correlation, comparison, and `side_conflict` alerting. If the exchange outcome side differs from the intent contract side, a `FILL-SIDE-CONFLICT` is logged.  When the exchange-reported exposure direction (signed-YES delta) also diverges from the intent, the fill is quarantined as `UNTRUSTED_SIDE_CONFLICT` instead of being applied.
- `KalshiFill.price_cents` returns the leg price for `canonical_position_side` (`yes_price_dollars * 100` for YES, `no_price_dollars * 100` for NO). The position cache converts cross-leg fills to the resulting-side cost basis.
- `KalshiFill.execution_outcome_side`, `execution_action`, and `execution_price_cents` are persisted for audit and per-fill parity checks.

### Ledger schema versioning and migration

- `KalshiFill.ledger_schema_version` / `canonicalization_version` track provenance:
  - `1` — pre-canonical rows (no canonical fields, no state).
  - `2` — canonical fields backfilled from raw execution facts; `canonicalization_state == TRUSTED_BACKFILLED_V1`.
  - `3` — execution-derived canonical fields created by current `fills_ledger._parse_fill` with explicit `canonicalization_state` and strict legacy rules.
- Only two states are trusted for live position math:
  - `TRUSTED_LIVE_V1` — a new fill whose canonical position effect was derived directly from exchange execution facts by `_parse_fill`.
  - `TRUSTED_BACKFILLED_V1` — a legacy row whose canonical fields were backfilled deterministically from raw `side`/`action`.
- `canonicalization_state == None` is never trusted. It is treated as `UNTRUSTED_RAW` and the fill is quarantined. This prevents unpatched producers, partial deployments, or stale persisted data from mutating live positions.
- `KalshiFillsLedger._init_sqlite()` and `_init_postgres()` migrate legacy tables by adding missing core, audit, and canonical columns, then run a deterministic backfill.
- A legacy row with usable `side` and `action` is backfilled to `ledger_schema_version=2`, `canonicalization_version=1`, `canonicalization_state=TRUSTED_BACKFILLED_V1`.
- A legacy row missing `side` and/or `action` is marked `canonicalization_state=UNTRUSTED_LEGACY`, `unmatched=True`, and must not be used to construct live positions.
- `load_from_db()` re-derives canonical fields only when `canonicalization_state` is `None`, `UNTRUSTED_LEGACY`, or `UNTRUSTED_RAW`, or when the canonical side/action are absent. A `TRUSTED_BACKFILLED_V1` row is loaded as-is and is not re-derived.

### Verification

After changing `fills_ledger`, `position_cache`, `binary_price_space`, or the canonical fill model, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fills_ledger_v2_side_action_fix.py tests\test_fills_ledger_v2_fractional_replay.py tests\test_canonical_exposure_reconciliation.py tests\event_venues\kalshi\test_kalshi_side_inversion_fix.py tests\event_venues\kalshi\test_fills_ledger_canonicalization.py -v
```

This suite covers:
- Exchange execution side wins over intent (`side_conflict` logged, not applied).
- Direct canonicalization of all four order forms and both execution sides.
- Legacy DB backfill and `UNTRUSTED_LEGACY` quarantine.
- Canonical `yes_delta_cc` for fractional and whole-contract fills.
- Position-cache cross-leg equivalence and idempotency.

## PostgreSQL required mode (soak)

- `.env.shadow` sets `MERID_POSTGRES_REQUIRED=true` for paper/shadow soaks.
- `merid.startup_validations.validate_postgres_liveness()` is called by `validate_production_startup()` and performs a synchronous `asyncpg.connect` probe when the flag is set.
- `merid/event_venues/kalshi/fills_ledger.py` and `merid/event_venues/kalshi/portfolio_event_log.py` raise `RuntimeError` on PostgreSQL pool failure when `MERID_POSTGRES_REQUIRED=true` instead of silently falling back to SQLite.
- The preflight script `data/shadow/artifacts/preflight_startup_path.py` demonstrates the P1.0.x startup gates and confirms RTI observations for all five enabled assets before any trading loop runs.

### UNTRUSTED_LEGACY quarantine and migration gate

- A fill with `canonicalization_state` that is `None`, `UNTRUSTED_LEGACY`, or `UNTRUSTED_RAW` is retained for audit only. It must never construct, alter, close, or reverse a live position.
- `KalshiFillsLedger.compute_position_from_fills()` and `KalshiPositionCache.on_fill()` explicitly skip `None`, `UNTRUSTED_LEGACY`, and `UNTRUSTED_RAW` fills. A `None` state is normalized to `UNTRUSTED_RAW` and triggers `require_rest_reconciliation()`.
- `KalshiFillsLedger.on_fill()` also quarantines any fill whose `canonicalization_state` is not explicitly `TRUSTED_LIVE_V1` or `TRUSTED_BACKFILLED_V1`.
- `load_from_db()` records a migration summary:
  - `legacy_rows_total`
  - `trusted_backfilled_rows`
  - `untrusted_legacy_rows`
  - `rows_excluded_from_live_replay`
  - `canonicalization_failures`
  - `untrusted_legacy_tickers`
- For every untrusted ticker, `position_cache.require_rest_reconciliation(ticker)` is called and the ticker is added to `fills_ledger.get_untrusted_legacy_tickers()`.
- Before re-enabling live entries, verify:
  - `exchange positions == cache positions == monitor positions`
  - `exchange signed YES exposure == ledger signed YES exposure`
  - all open exchange orders map to known intents
  - `untrusted_legacy_rows` contribute zero live exposure

### Live rollout

After a fresh exchange REST snapshot and cache rebuild:

1. Run the canonicalization verification suite and the full regression suite.
2. Start with one-contract live entries only.
3. For the first resumed fill, require the following to be logged and to match:
   - raw fill execution fields (`execution_outcome_side`, `execution_action`, `execution_price_cents`)
   - canonical position fields (`canonical_position_side`, `canonical_position_action`, `canonical_leg_price_cents`)
   - cache signed-YES delta after application
   - fresh REST signed-YES position
   - parity = `PASS`
   - monitor side/basis matches cache
   - allocator exposure matches cache
4. Do not scale, change EV/fee/slippage, or disable `MERID_CIRCUIT_BREAKER_OBSERVE_ONLY` until the first real fill survives the complete `fill → ledger → cache → monitor → REST reconciliation` loop.

### Clean-environment verification

To guarantee verification is reproducible and not an artifact of the current `.venv`:

```powershell
py -m venv .venv-clean
.\.venv-clean\Scripts\python.exe -m pip install --upgrade pip
.\.venv-clean\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-clean\Scripts\python.exe -m pytest tests\test_order_router_ioc_tif_reconciliation.py tests\kalshi_alignment\test_order_router.py tests\event_venues\kalshi\test_port_ledger_adapter.py tests\event_venues\kalshi\test_kalshi_p0_partial_fill_reconciliation.py tests\event_venues\kalshi\test_kalshi_p0_maker_taker_simulator.py tests\event_venues\kalshi\test_kalshi_p0_exit_order_simulator.py tests\test_loop_15m_bugfixes.py tests\test_loop_15m_decimal_fix_2026_07_29.py tests\test_exit_canonicalization_and_policy_2026_08_07.py tests\test_canonical_exposure_reconciliation.py tests\test_fills_ledger_v2_side_action_fix.py tests\test_fills_ledger_v2_fractional_replay.py tests\position_management\test_position_monitor_cleanup_exit.py tests\position_management\test_position_monitor.py tests\position_management\test_position_monitor_exit_audit.py tests\position_management\test_spread_stop_provenance.py
```

### Final release gate

Do not resume normal live entries until all are true:

- [ ] No `canonicalization_state=None` fill can mutate live position state.
- [ ] No `UNTRUSTED_*` fill can mutate live position state.
- [ ] Every new fill has explicit `canonicalization_state` (`TRUSTED_LIVE_V1`) and `canonicalization_version=1`.
- [ ] Untrusted ticker requires fresh exchange REST reconciliation.
- [ ] `test_kalshi_side_inversion_fix.py`: 9 passed.
- [ ] Canonicalization suite: 85 passed.
- [ ] Required suite: 354 passed.
- [ ] Clean Python 3.11 environment installs successfully.
- [ ] Clean environment passes the required suite.

## FILL-SIDE-CONFLICT hardening (2026-08-16)

A side *label* mismatch (`execution_outcome_side != intent_target_side`) is now
handled by exposure comparison, not by blindly trusting the exchange label.

- `fills_ledger._parse_fill` computes both the agent-intent signed-YES exposure
  (`intent_yes_delta_cc`) and the exchange-reported signed-YES exposure
  (`execution_yes_delta_cc`).
- If the exchange `outcome_side` differs from the intent target side but the
  signed-YES exposure matches (e.g. SELL_YES for a BUY_NO), the fill is treated
  as the V2 counterparty form.  `side_conflict` is logged and `side_conflict=True`
  is recorded, but the fill is still trusted and applied using the exchange's
  canonical fields.
- If the exposure direction also diverges (e.g. BUY_YES reported for a BUY_NO
  intent), the fill is quarantined as `UNTRUSTED_SIDE_CONFLICT`.  Its
  `canonical_position_side`, `canonical_position_action`,
  `canonical_leg_price_cents`, and `canonical_yes_delta_cc` are all set to
  `None`, and the fill must not be applied to a live position.
- `position_cache.on_fill` rejects `UNTRUSTED_SIDE_CONFLICT` and other
  `UNTRUSTED_*` canonicalization states; it does not create, alter, or close a
  position for such a fill.
- `ingest_ws_fill` stores quarantined fills in the durable ledger and returns
  `True`, but it does not call `position_cache.on_fill` for them.  The ledger
  retains the raw exchange fields and the intent audit fields for later
  reconciliation.
- Quarantine reason is recorded in `KalshiFill.unmatched_reason` and the CRITICAL
  log `[FILL-SIDE-CONFLICT-QUARANTINE]` is emitted for observability.

This closes the live BTC incident where an intent targeting NO was reported by
Kalshi as a YES-side fill; the exposure-inverted report is now caught before it
mutates local positions.

## CF-RTI shadow soak (2026-08-19)

- Candidate and order telemetry is written to `data/shadow/cfb_rti/` when
  `MERID_CFB_RTI_SHADOW_TELEMETRY=1`. Tests set this to `0` in
  `tests/conftest.py` to avoid disk writes.
- Candidate records use `schema_version=1` and include RTI provenance,
  probability, confidence, edge breakdown, book values, and selected side.
- Order records use `record_type="order"` and capture `kalshi_side`,
  `v2_book_side`, fill counts, price, latency, and terminal status.
- `scripts/shadow_report.py` is the durable control plane. Run it in strict
  mode after each versioned shadow segment:

  ```powershell
  python scripts/shadow_report.py `
    --input data/shadow/cfb_rti `
    --output data/shadow/reports `
    --run-id <run_id> `
    --strict `
    --format both
  ```

- `docs/runbooks/shadow-soak.md` contains the full operational procedure.
- Targeted verification after shadow-report changes:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests\test_shadow_report.py tests\test_cf_rti_e2e.py tests\prediction -q
  .\.venv\Scripts\python.exe -m pytest tests\kalshi_alignment\test_order_router.py tests\test_loop_15m_bugfixes.py tests\test_loop_15m_decimal_fix_2026_07_29.py tests\test_cf_rti_e2e.py tests\test_shadow_report.py -q
  ```

- Full verification: `pytest -m kalshi_15m` and the `AGENTS.md` required suite
  both pass after the client-order-id, market-state schema, and position-cache
  rounding fixes.
- Startup fail-closed for shadow soak: `validate_live_trading_safety()` in
  `merid/startup_validations.py` raises `StartupValidationError` if
  `MERID_CFB_RTI_SHADOW_TELEMETRY=1` and either `MERID_ALLOW_LIVE_TRADES=true`
  or `MERID_PM_TRADING_MODE` is not `paper`.

## Kalshi CF-RTI WebSocket primary source (2026-08-19)

- `merid/data/kalshi_cf_rti_ws.py` implements an authenticated Kalshi
  WebSocket client for the `cfbenchmarks_value` channel.
- `merid/data/cf_rti_adapter.py` uses it as the primary settlement-reference
  source when `MERID_CFB_RTI_SOURCE=kalshi_ws` (set in `.env.shadow`).
- Valid index IDs are discovered with `indexlist` at connection time; the
  client subscribes to the canonical BTC, ETH, SOL, XRP, and DOGE RTI symbols.
- Direct CF Benchmarks REST remains an optional fallback:
  - `MERID_CFB_RTI_SOURCE=direct` forces the direct REST key.
  - `MERID_CFB_RTI_SOURCE=both` tries the Kalshi WebSocket first, then falls
    back to `MERID_CFB_RTI_API_KEY` / `CFB_API_KEY`.
- In `MERID_ENV=testing` with no explicit source, the adapter defaults to
  `direct` so unit tests that mock `httpx.Client` do not attempt a live
  WebSocket connection.
- `web/main_15m_lean.py` starts the stream during its P1.0.3 startup phase.

## PostgreSQL verification (2026-08-19)

- The durable fills ledger in `merid/event_venues/kalshi/fills_ledger.py` uses
  `asyncpg` when `POSTGRES_PASSWORD` is set and falls back to SQLite otherwise.
- The PostgreSQL service is reachable on the configured host/port.
- Initialize or update the schema before a soak with:

  ```powershell
  .\.venv\Scripts\python.exe scripts\init_postgres_schema.py
  ```

- Runbooks and env files should keep `POSTGRES_*` values aligned with the
  running service.

## Kalshi CF-RTI WebSocket protocol notes (2026-08-19)

- Primary endpoint for the ``cfbenchmarks_value`` channel is the dedicated
  Trade API WebSocket: `wss://external-api-ws.kalshi.com/trade-api/ws/v2`.
- Auth uses the same RSA-PSS signed headers as order placement.
- Initial subscribe should use `index_ids: ["all"]` so the server emits all
  available CF Benchmarks indices immediately.
- `update_subscription` with `action: "indexlist"` returns the authoritative
  index ID list (e.g. `BRTI`, `ETHUSD_RTI`, `SOLUSD_RTI`, `XRPUSD_RTI`,
  `DOGEUSD_RTI`).  It does not stop the feed.
- Each ``cfbenchmarks_value`` frame has `msg.index_id`, `msg.received_at`
  (Kalshi receive, ms), `msg.data` (raw CF Benchmarks JSON as a string), and
  `msg.avg_60s_data`.  The raw JSON contains `time` (ms), `id`, and `value`.
- `merid.data.kalshi_cf_rti_ws` parses the raw string and forwards a
  `KalshiCfRtiFrame` to the adapter, which uses `time` as the source
  timestamp and `value` as the RTI price.

## Exit-guardrail and test environment notes (2026-08-20)

- New loop-15m exit guardrail env vars:
  - `MERID_EXIT_MIN_PROFIT_CENTS` (default 5) enforces a minimum net-profit
    floor on every non-stop, non-emergency exit.
  - `MERID_EXIT_MAX_QUOTE_AGE_MS` (default 10000) and
    `MERID_EXIT_MAX_QUOTE_AGE_NEAR_EXPIRY_MS` (default 15000) tier quote
    freshness by time-to-expiry to reduce stale-quote rejections near
    settlement.
- `TAKE_PROFIT_MIN_PROFIT_CENTS` is now configurable via
  `MERID_TAKE_PROFIT_MIN_PROFIT_CENTS` and defaults to 5c.
- `ExitReason.TRAIL` priority was raised above `ExitReason.EDGE_DECAY` so
  active trailing stops are not pre-empted by edge-decay signals.
- `PositionMonitor` profit-exit invariants now cover `EDGE_DECAY` and other
  discretionary exit reasons, while `TRAIL` remains a stop-class reason.
- The required regression test command must run with `MERID_MAX_SLIPPAGE_CENTS=5`
  (or rely on `tests/conftest.py` which now pins it).  A repo `.env` value of
  15 will otherwise fail the order-router price-adjustment tests.

## Edge-gate tuning environment variables (2026-08-20)

- `MERID_TRADE_DECISION_MIN_P_SELECTED` (default `0.5`): the minimum
  model probability a side must exceed to be tradable.  Values below `0.5`
  allow cost-basis (positive-EV) trades on the less-likely side; `0.5`
  preserves the release-gate invariants and the cost-basis-override tests.
- `MERID_MODEL_UNCERTAINTY` and `MERID_MODEL_UNCERTAINTY_<ASSET>` (default
  `0.05`): uncertainty reserve added to the model-risk term.  Lowering this
  makes cheap contracts viable for BTC/ETH/SOL/DOGE when their believed side
  already clears the p-threshold.
- `MERID_MIN_NET_EDGE` and `MERID_MIN_NET_EDGE_<ASSET>` (default `0.03`): the
  net edge threshold passed to `compute_trade_decision`.
- `MERID_ANNUALIZED_VOL_<ASSET>` (defaults: BTC `0.60`, ETH `0.80`,
  SOL `1.00`, XRP `1.00`, DOGE `1.20`): per-asset annualized volatility used
  in the normal CDF probability model.

Shadow-mode telemetry in `data/shadow/cfb_rti/` records every candidate's
`p_yes`, `p_no`, `net_edge_yes`, `net_edge_no`, and `rejection_reason`, which
is the canonical source for diagnosing why one asset trades and another does
not.  A quick replay of those files is in `tmp/replay_shadow.py`.

## Hybrid model audit and containment (2026-08-26)

### Production-safe containment toggles

- `MERID_HYBRID_BACHELIER_ONLY=1` or `MERID_HYBRID_DISABLE_ALL_DELTAS=1`
  disables every indicator/velocity/MACD/RSI/OBI/regime/FVG delta.  The live
  decision uses the Bachelier baseline probability, but the model-
  decomposition log still records the deltas for diagnosis.
- `MERID_SHADOW_BACHELIER_ONLY=1` computes a parallel Bachelier-only decision
  alongside the live hybrid decision and writes it to the model-decomposition
  ledger.  The shadow is fully logged but never executed.
- `MERID_MODEL_DECOMPOSITION_TELEMETRY=0` disables the new ledger.  The
  default path is `data/logs/hybrid_model_decomposition.jsonl`.
- `MERID_MODEL_CONTAINMENT_SIZE_SCALE` (default `1.0`): scales every live
  position down to a minimum of one contract (100 cc).  Set to `0.0` to force
  one-contract sizing; `0.25` for quarter-size canary.
- `MERID_BACHELIER_ONLY_SIZE_SCALE` (default `0.0` when
  `MERID_HYBRID_BACHELIER_ONLY` is active, otherwise `1.0`): extra size
  reduction when the live signal is the Bachelier baseline only.

### Audit artifacts

- `merid.prediction.hybrid_audit` generates the three canonical ledgers:
  `expiry_alpha_entries.csv`, `intracontract_exit_trades.csv`, and
  `decision_to_settlement_audit.csv`.
- `data/logs/hybrid_model_decomposition.jsonl` joins the raw model inputs,
  each delta, the pre-clip and final probability, the live decision, and the
  Bachelier-only decision per evaluation.  Settlement jobs can join on
  `decision_id` to compute each component's directional contribution.
- `tests/test_hybrid_delta_sign_correlation.py` asserts that synthetic
  component contributions are positive and reports the held-to-expiry win
  rate from `reports/last_24h_fills_with_pairing_and_settlement_*.csv`.
  Set `MERID_HELD_EXPIRY_MIN_WIN_RATE` to enforce a threshold; set
  `MERID_HYBRID_SIGN_CORRELATION_ASSERT=1` for future out-of-sample
  component validation.
