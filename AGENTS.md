

```yaml
---
auto_execution_mode: 1
description: MERID/Kalshi 15m automatic live-trading startup and execution contract
live_startup_policy: auto_enable_after_preflight
live_entry_authorization: durable_operator_config
---
```

# MERID Agent Notes

You are a senior Python engineer reviewing, modifying, debugging, validating, or operating the MERID Kalshi crypto 15-minute trading system.

`auto_execution_mode: 1` is an explicit durable operator instruction to enable live Kalshi trading at the next production server restart. On every production startup, the system must perform the required startup preflight automatically. If preflight passes, it must transition to `LIVE_ENTRIES_ENABLED` and begin executing eligible trade decisions without requiring a separate approval token, manual release action, dashboard click, CLI command, or per-run operator confirmation.

This durable authorization applies only to the configured production process and authenticated live Kalshi account. It does not override reconciliation, circuit-breaker, trusted-fill, exit-protection, production-environment, venue-identity, model-release, or risk gates.

The system must never submit an entry merely because it restarted. It may execute the **next eligible strategy decision** after successful preflight and normal entry gating.

## Automatic live startup

When all of the following are true:

```yaml
auto_execution_mode: 1
runtime_profile: production
venue_environment: live
```

the next server restart must automatically execute the live startup sequence below.

### Required startup sequence

1. Generate a fresh `run_id` and unique `process_id`.

2. Load configuration with environment variables taking precedence over repository `.env` values.

3. Fail startup closed if any configuration identifies test, mock, replay, simulator, sandbox, demo, shadow, paper, direct-execution bypass, debug-order, or manual-order behavior.

4. Authenticate against the configured Kalshi live account and verify:
   - Credentials are present and valid.
   - Account identity matches the configured intended live account.
   - The venue is Kalshi live production, not demo or sandbox.
   - The canonical live Kalshi order router is installed and selected.
   - No test adapter, stub adapter, paper adapter, or mock adapter can receive an entry order.

5. Start the required Kalshi WebSocket implementation and verify:
   - Required market-data subscriptions are active.
   - Order and fill subscriptions are active.
   - The connection is receiving current messages.
   - The trusted fill watermark is available and advancing.
   - Subscription, ordering, symbol, and provenance checks pass.

6. Fetch authoritative exchange state through REST:
   - Account balance and buying power, **per exchange shard** (`balance_breakdown`).
   - Open orders.
   - Current market positions.
   - Recent fills.
   - Required market metadata and market-state information, including each market's `exchange_index`.

6a. Ensure trading-shard collateral. Kalshi collateralizes orders on the exchange shard that hosts the market (crypto 15m markets: shard 2 since 2026-08-24). Cash on shard 0 cannot back a shard-2 order; the exchange rejects it with `insufficient_balance`. Preflight must:
   - Resolve the trading shard from market metadata (`MERID_KALSHI_TRADING_SHARD` may pin it).
   - If the trading shard holds less than `min(MERID_FIXED_EXPOSURE_CAP_USD, total cash)`, move idle cash from other shards with an intra-account transfer (`POST /portfolio/intra_exchange_instance_transfer`). This is a collateral relocation inside the same account, never a withdrawal, and is governed by `MERID_AUTO_FUND_TRADING_SHARD` (default on).
   - Fail closed (`trading_shard_collateral` FAIL) if the trading shard still cannot back the minimum order of one centi-contract (0.01) plus fee (`MERID_MIN_TRADING_SHARD_COLLATERAL_CENTS`, default 1c). Use Kalshi's exact `balance_dollars` / `balance_breakdown` strings, not the truncated integer `balance`, for all cash comparisons.
   - Sizing uses the trading-shard cash (not total equity) as spendable bankroll and reserves the exact parabolic taker fee; fractional counts are rounded **down** to the centi-contract grid.
   - Kalshi charges `rate * C * P * (1 - P)` rounded **up to $0.0001** (0.01c), verified against live V2 fill records (1 contract @47c -> $0.0175; @1.1c -> $0.0008). It is **not** ceil'd to a whole cent. Live sizing, the shard-collateral gate, and the round-trip net-of-cost gate must use `kalshi_fee_cents_exact`; the whole-cent integer helpers are conservative upper bounds only and reject every sub-1-contract order if used as gates. Spread cost is per contract and must be scaled by the fractional count.
   - The loop re-checks every 60s and the order router rejects locally with `insufficient_shard_balance:...` instead of submitting an order the exchange will refuse.

7. Recover all uncertain submission outcomes by `client_order_id`, `intent_id`, and exchange order lookup before considering entries enabled.

8. Build a fresh derived state projection from immutable ledger events plus authoritative exchange REST state. Do not reset caches in place as a rollback shortcut.

9. Reconcile, per active ticker and in signed YES centi-contracts:
   - Exchange positions.
   - Durable fills ledger.
   - Position cache.
   - Position monitor.
   - Global slot allocator.
   - Pending-order and risk-reservation exposure.

10. Quarantine expired or closed-but-unsettled positions under the existing expired-ticker policy. Do not let a quarantined, expired market block active-ticker reconciliation or new entries.

11. Verify all active positions and resting orders are reconciled, protected, or safely quarantined.

12. Verify reduce-only exits, order cancellation, and flatten capability are configured and available. This is a non-mutating readiness validation; do not place a live connectivity-test order.

13. Verify no critical unresolved condition is present:
   - `side_mismatch`
   - `action_mismatch`
   - `qty_mismatch`
   - `overfill`
   - `missing_order`
   - `unmatched_fill`
   - `settlement_mismatch`
   - `missing_settlement_for_settled_market`
   - `missing_pnl`
   - Critical bankroll drift
   - Unresolved unknown submission
   - Broken trusted fill watermark
   - Reconciliation divergence
   - Untrusted side conflict
   - Missing protective-exit capability
   - Trading-shard collateral below the one-contract minimum

14. Verify the live model configuration is approved:
   - Use Bachelier-only with TWAP-appropriate volatility unless another model has a documented approved release.
   - Disable hybrid Bachelier-plus-delta signals—velocity, MACD, RSI, OBI, FVG, and regime—unless explicitly validated and approved.
   - Apply held-side tail calibration unconditionally below `MERID_TAIL_CALIBRATION_PRICE_FLOOR`.
   - Block NO-tail entries until a validated NO-held calibration artifact is approved.
   - Require the corrected full fee and execution-cost model for every entry decision.

15. If every preflight step succeeds, persist an immutable startup release record and set:

```python
live_runtime_state = "LIVE_ENTRIES_ENABLED"
entry_halted = False
```

16. Begin evaluating normal strategy decisions. Route a live order only when the individual decision passes all entry gates.

17. Emit structured telemetry:

```text
live_startup_preflight_passed
live_entries_enabled
run_id
process_id
kalshi_account_id
venue_environment=live
reconciliation_snapshot_id
fill_watermark
model_release_id
```

### Preflight failure behavior

If any startup preflight condition fails:

```python
live_runtime_state = "LIVE_ENTRIES_HALTED"
entry_halted = True
```

The system must:

- Block every new entry.
- Preserve cancellation, reduce-only exits, stop-loss handling, and flatten capability.
- Retain risk reservations for unknown submission outcomes.
- Emit the exact structured denial reason.
- Persist a durable preflight failure record.
- Retry only the specific safe recovery/synchronization action required to resolve the failure.
- Never silently switch to paper execution, simulation, or mock routing while reporting live readiness.
- Never blindly retry a potentially accepted exchange order.

The next restart may retry automatic preflight. It may enable entries only after all preflight checks pass.

## Live-entry authorization

A new entry is authorized when all of the following are true:

```python
auto_execution_mode == 1
runtime_profile == "production"
venue_environment == "live"
live_runtime_state == "LIVE_ENTRIES_ENABLED"
not circuit_breaker.is_halted
not reconciliation_halted_for_ticker
startup_preflight_is_current
kalshi_websocket_is_healthy
trusted_fill_watermark_is_current
rest_sync_is_current
canonical_live_router_is_active
protective_exit_capability_is_available
model_release_is_valid
```

The individual trade decision must additionally pass:

- Market is active and eligible.
- Fresh executable own-side price is available.
- Market state and settlement-reference provenance are valid.
- Risk limits, bankroll limits, slot limits, and pending-order exposure limits pass.
- No existing exchange/cache position exists for the ticker.
- No resting entry order, unresolved order, or unknown submission outcome exists for the ticker.
- Final-minute restrictions pass.
- Entry has a unique `intent_id` and `client_order_id`.
- The order includes `run_id`, `process_id`, and a structured `reason`.
- Full net edge after corrected fees, spread, expected slippage, and execution costs passes the configured threshold.
- Tail calibration is valid for the held side and price bucket.
- Required RTI provenance is valid if the settlement path uses CF Benchmarks RTI.
- The market's exchange shard holds at least `limit_price + fee` per contract of cash.

The live system must not submit entries outside this canonical decision path.

### Execution mode: full live, no canary lanes

Production runs one decision path: the core Bachelier/TWAP lane with the held-price floor, π* premium, and executable-cost EV gate. The exploration overlays (`MERID_CHEAP_TAIL_CANARY_*`, `MERID_CANARY_4C_LCB`, `MERID_LIVE_CANARY`) are **off** and must stay off unless a documented, approved experiment re-enables one. Order size is bounded by the account (`MERID_MAX_CONTRACTS_PER_ORDER`, `MERID_FIXED_EXPOSURE_CAP_USD`), not by a canary flag; raise both together as the bankroll grows. A low account balance is not a reason to halt entries — the system must size to what the trading shard can collateralize and otherwise trade normally.

`MERID_OBSERVE_ONLY` is an operator emergency read-only switch. `start_15m.ps1` derives its default from `auto_execution_mode` (1 → `0`); it must never silently default to read-only while this contract says auto-execute.

## Runtime halt and recovery

Automatic live startup authorization remains valid only while runtime safety remains healthy. Immediately set:

```python
live_runtime_state = "LIVE_ENTRIES_HALTED"
entry_halted = True
```

when any of the following occurs:

- The circuit breaker trips.
- Reconciliation divergence occurs.
- Trusted fill watermark stops advancing or regresses.
- Required WebSocket subscriptions fail, become stale, or lose required provenance.
- REST state becomes stale.
- A critical golden-record discrepancy occurs.
- Critical bankroll drift occurs.
- An unmatched or untrusted fill is detected.
- A submission outcome is unknown and requires recovery.
- The configured account or venue identity changes.
- The selected order router is no longer the canonical live Kalshi router.
- Protective exits, cancellation, or flatten capability become unavailable.
- A required environment safety control is disabled.
- The active model release, tail calibration, or RTI provenance becomes invalid.

During an entry halt:

- Do not submit new entries.
- Continue consuming exchange fills through `apply_fill_once(fill_id, ...)`.
- Preserve trusted live position state.
- Preserve risk reservations until confirmed release or recovery.
- Continue reduce-only exits, protective handling, cancellation, and flattening.
- Reconcile authoritative REST and WebSocket state.
- Quarantine untrusted discrepancies without mutating position state.

Entries may automatically resume after a runtime halt only when:

1. The specific failure has been resolved.
2. A new reconciliation snapshot passes.
3. The trusted fill watermark is current and non-regressing.
4. No critical audit discrepancy remains unresolved.
5. Required exits and live routing remain available.
6. The process remains in production/live mode with `auto_execution_mode: 1`.
7. A durable `live_runtime_recovery_passed` event is persisted.

Do not call a direct application-level `resume()` method to bypass these conditions.

## Environment and routing rules

Production startup with `auto_execution_mode: 1` must fail closed if any of the following are true:

- `paper`, `shadow`, `simulation`, `replay`, `mock`, `test`, `demo`, or `sandbox` routing is enabled.
- A direct venue submission bypass is enabled.
- A debug/manual-order feature is enabled.
- Credentials are missing, conflicting, invalid, or attached to an unexpected account.
- The configured Kalshi endpoint is not live production.
- Reconciliation, trusted-fill canonicalization, exit firewall, or protective-exit controls are disabled.
- The active router is not the canonical live Kalshi router.
- The selected model is not approved for live use.
- The NO-tail calibration artifact is missing or unapproved while NO-tail entries are enabled.

The system must log the resolved runtime configuration at startup, excluding secret values, including:

```text
runtime_profile
auto_execution_mode
venue_environment
router_implementation
kalshi_account_id
paper_mode
shadow_mode
simulation_mode
replay_mode
exit_firewall_mode
require_exit_parentage
model_release_id
tail_calibration_artifact_hash
trading_shard
shard_balances
auto_fund_trading_shard
```

## Preserved non-negotiable safeguards

All existing rules in this contract remain mandatory, including:

- Exact integer centi-contract quantities.
- `Decimal` price, fee, cost-basis, and PnL arithmetic.
- Signed YES exposure accounting.
- Global immutable `fill_id` idempotency.
- The `intent_id → client_order_id → order_id` identity chain.
- Durable `apply_fill_once(fill_id, ...)` handling across router, WebSocket, and REST sources.
- Quarantine of unmatched and untrusted fills.
- Trusted-fill canonicalization before live-position mutation.
- Raw exchange execution facts as the authoritative exposure source.
- Reduce-only exits that cannot expand or reverse exposure.
- Per-ticker reconciliation against exchange, ledger, cache, monitor, allocator, and pending-order exposure.
- Retention of risk reservations for unknown submission outcomes.
- Protective-exit provenance and fail-closed requirements.
- CF Benchmarks RTI source, freshness, symbol, ordering, and provenance gates.
- Circuit-breaker fail-closed behavior.
- Automatic preservation of exits whenever entries are halted.
- Live-router provisional fills must be promoted (not duplicated) when the
  authoritative exchange fill arrives. The promoted record keeps the user's
  canonical side/action from the originating intent, but overwrites the
  yes/no leg prices, fee, execution audit fields, and cash proceeds with the
  exchange's authoritative values. The canonical leg price and signed
  proceeds are recomputed from the authoritative legs and the user's outcome
  side so counterparty-form fills cannot flip position cost basis.
- Realized PnL is computed from authoritative signed cash proceeds where
  available, not from leg-price conversions, so cross-leg and
  counterparty-equivalent fills produce the correct PnL.

## Coding directive

Implement the next-restart live switch as a **startup state machine**, not as a broad bypass or a simple boolean checked inside the order router.

Required state transitions:

```text
STARTING
  → PREFLIGHT_RUNNING
  → LIVE_ENTRIES_ENABLED
```

or, on any failed condition:

```text
STARTING
  → PREFLIGHT_RUNNING
  → LIVE_ENTRIES_HALTED
```

For a post-startup safety failure:

```text
LIVE_ENTRIES_ENABLED
  → LIVE_ENTRIES_HALTED
  → RECOVERY_RUNNING
  → LIVE_ENTRIES_ENABLED
```

The final transition back to `LIVE_ENTRIES_ENABLED` requires a successful fresh reconciliation and durable recovery event. It must not occur from an in-memory boolean reset, a direct router call, or an uncoupled `resume()` path.

`auto_execution_mode: 1` must cause the next restart to run this state machine automatically and execute the next eligible live trading decision after `LIVE_ENTRIES_ENABLED` is reached.
## Settlement-aligned exit gate (2026-09)

All discretionary exits are observe-only until `MERID_ENABLE_EV_EXIT_GATE` is
enabled in the resolved live config. A discretionary exit is any reason whose
economic justification is "the model or price says sell" — including
`stop_loss`, `trailing_stop`/`trail`/`ratchet_trim`, `loss_cut*`,
`take_profit`/`ratchet_floor`/`scale_out`, `signal_reversal`/`edge_decay`,
`model_invalidation`, and non-mechanical `time_exit` (`time_stop`,
`adaptive_timing`).

Operational exits (`reconciliation`, `manual`, market closed/cancellation,
documented mechanical closeouts) and emergency exits (`expiry_liquidation`,
hard risk) remain live with their existing mechanical checks. Unknown reasons
fail closed.

The final authority for a discretionary exit is the settlement-aligned
sell-vs-hold comparison in
`merid/event_venues/kalshi/settlement_aligned_exit.py`, enforced at
`loop_15m._run_exit_price_guard` and at `stop_candidate.maybe_submit_stop_candidate`:

```text
NetSellValue          = executable same-side bid - exit fee - slippage
ConservativeHoldValue = calibrated held-side settlement probability
                        - uncertainty reserve - residual hold risk
exit allowed          <=> NetSellValue > ConservativeHoldValue + switch_margin
                        for >= MERID_EXIT_EV_MIN_CONSECUTIVE observations
```

Entry price is sunk and never enters the decision. Required inputs: a fresh
sequence-confirmed executable bid for the held side (never the ask, a mid, or
a synthetic opposite-side conversion) with enough visible depth for the order,
a fresh sequence-confirmed execution-eligible CF Benchmarks RTI/model
observation, calibrated model inputs (a default/fallback volatility source or
missing calibration artifact is a hard blocker), and complete entry
provenance. Missing or stale data yields `HOLD_DATA_INSUFFICIENT` — never a
sell.

Evaluator statuses are explicit: `SELL_SIGNALLED` (economics + persistence
cleared), `HOLD_SELL_VALUE_INFERIOR`, `HOLD_PERSISTENCE_NOT_MET`,
`HOLD_DATA_INSUFFICIENT`, `HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED` (inside the
final RTI averaging window, default 60s — a dedicated settlement-phase
evaluator is required there; ordinary spot/velocity model value is not an
adequate proxy), `HOLD_OUTSIDE_CANARY_SCOPE` (sell signalled but outside the
configured canary envelope), `BYPASS_OPERATIONAL`, `BYPASS_EMERGENCY`, and
`BLOCK_UNKNOWN_REASON`. Only `SELL_SIGNALLED` may authorize a live
discretionary order, and only while the gate is enabled;
`MERID_EV_EXIT_GATE_KILL=1` restores observe-only immediately (read live on
every evaluation — no restart required).

The persistence counter is keyed by (market_pk, position_id, held_side,
policy_version, canonical reason, model vol/calibration version). Any context
change, data-validity failure, non-breach, zero quantity, exit attempt start,
or exit fill resets it — a stale signal can never combine with a later
unrelated one.

Every evaluation, exit fill, and settlement is recorded so each real exit can
be replayed against the hold-to-settlement counterfactual, keyed by the
canonical full market ticker (`exit_evaluations.jsonl`,
`exit_counterfactuals.jsonl`). Startup emits a machine-readable `EV-EXIT-GATE`
policy line; whenever the legacy path would have submitted a discretionary
exit, an `EXIT-LEGACY-INVERSION-AUDIT` record logs the trigger price versus
the canonical held-side bid and the EV verdict (critical severity on price
divergence or EV disagreement). Each evaluation records `asset`,
`visible_bid_depth`, `fee_model_version`, `fee_order_type_assumption`,
`p_held_raw_cents`/`p_held_calibrated_cents`, `rti_phase`, `model_vol_source`,
and `model_calibration_version`; the guard annotates evaluations with the
legacy verdict (`legacy_outcome` record lines) so replay can join the legacy
comparison population by `evaluation_id`.

### Shadow-validation phase (current)

The gate is OFF. The live campaign runs normal trading across BTC, ETH, SOL,
XRP, and DOGE with all discretionary exits shadowed. Per 15-minute window the
loop emits `EV-EXIT-SHADOW-SUMMARY` per asset and `EV-EXIT-SHADOW-GLOBAL`
(positions evaluated, legacy triggers, EV sell/hold/data-insufficient/
near-settlement/uncalibrated counts, side mismatches, legacy-EV disagreements,
median RTI/book age, median bid depth, attempts in flight, unmatched fills).
`scripts/ev_exit_shadow_report.py` joins `exit_evaluations.jsonl` to
`exit_counterfactuals.jsonl` by canonical `market_pk` and prints the promotion
table segmented by asset/side/reason/price bucket/RTI phase: realized vs
counterfactual hold P&L, exit opportunity cost, win rate, Brier/ECE, data-age
medians, and invalid-data rate. A high `HOLD_DATA_INSUFFICIENT` rate means the
inputs are not ready — it is not evidence the gate is too strict. Under pytest
the singleton registry never writes to `logs/`; `MERID_EV_EXIT_LOG_DIR`
overrides the directory, `MERID_EV_EXIT_DISABLE_PERSIST` disables writes.

### Canary scope (parsed now, OFF by default)

When the gate is later enabled with `MERID_DISCRETIONARY_EXIT_MODE=ev_gated_canary`,
a `SELL_SIGNALLED` decision must additionally satisfy the canary envelope or it
becomes `HOLD_OUTSIDE_CANARY_SCOPE`: `MERID_EV_EXIT_CANARY_ASSETS` (e.g. `BTC`),
`MERID_EV_EXIT_CANARY_SIDES` (e.g. `YES`), `MERID_EV_EXIT_CANARY_REASONS`
(first live reason: `value_switch_exit` — the evaluator's own decision, not a
trailing-stop or take-profit trigger), `MERID_EV_EXIT_MAX_CONTRACTS` (default 1),
`MERID_EV_EXIT_MAX_ORDERS_PER_WINDOW` (default 1, counted per canonical market
key at authorization), `MERID_EV_EXIT_MIN_SECONDS_TO_EXPIRY` (120) /
`MERID_EV_EXIT_MAX_SECONDS_TO_EXPIRY` (600). `MERID_EV_EXIT_REQUIRE_*` flags
(`FRESH_RTI`, `SEQUENCE_CONFIRMED_BOOK`, `ENTRY_PROVENANCE`,
`SUFFICIENT_BID_DEPTH`, `CALIBRATED_MODEL`) default to the strict posture.
Do not widen the envelope without a replay report showing clean behavior.
