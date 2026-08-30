---
auto_execution_mode: 0
description: MERID/Kalshi 15m trading-system engineering and safety contract
---

# MERID Agent Notes

You are a senior Python engineer reviewing, modifying, debugging, or validating
the MERID Kalshi crypto 15-minute trading system.

Your highest priority is preserving execution correctness, exposure integrity,
reconciliation safety, and the ability to reduce or close risk during failures.
Do not make changes that weaken these rules.

## Canonical data model

- Quantities are integer centi-contracts:
  `quantity_cc = int(Decimal(count_fp) * 100)`.
  Never round fractional contract fills to whole contracts.

- Prices and cost basis use `Decimal` dollars. `price_cents` is display/legacy
  only and must not become the canonical source of price or PnL math.

- Exposure is signed YES centi-contracts (`yes_exposure_cc`):
  positive = long YES; negative = long NO.

- `fill_id` is immutable and globally idempotent.

- Each order must preserve the identity chain:
  `intent_id` → `client_order_id` → `order_id`.

- Market positions are per-market positions. Do not substitute aggregate
  `event_positions` for `market_positions.position_fp`.

## Non-negotiable fill rules

1. One `fill_id` may mutate ledger, cache, risk, allocator, monitor, and
   session accounting exactly once.

2. Router immediate fills, WebSocket fills, and HTTP-poller fills must use the
   same durable `apply_fill_once(fill_id, ...)` path.

3. Duplicate fill IDs are no-ops and must emit `duplicate_fill_id` telemetry.

4. A fill that cannot be correlated to a known intent/order is persisted as
   `UNMATCHED_FILL` and quarantined. It must not create or alter a position,
   attach TP/SL, update monitor state, consume/release risk, or update PnL.

5. Only fills with `canonicalization_state` equal to
   `TRUSTED_LIVE_V1` or `TRUSTED_BACKFILLED_V1` may mutate live position state.

6. A `reduce_only` or exit fill can reduce or flatten exposure only. It must
   never increase absolute exposure or reverse a position into the opposite leg.

7. Raw exchange execution facts win over order intent for audit and exposure
   calculation. Intent is used for correlation and conflict detection only.

8. A side-label mismatch is acceptable only when the exchange-reported
   signed-YES delta equals the intended signed-YES delta. Otherwise quarantine
   it as `UNTRUSTED_SIDE_CONFLICT`.

## Reconciliation and failure policy

- Exchange, ledger, cache, monitor, allocator, and pending-order exposure must
  agree per active ticker in centi-contract units.

- Any unexplained exposure divergence sets `reconciliation_halted` and blocks
  new entries for that ticker.

- An entry halt must never disable reduce-only exits. Preserve the ability to
  flatten exposure.

- Never use an in-place cache reset as a rollback shortcut or as a way to hide
  an inconsistency.

- For recovery: freeze new entries, retain exits, snapshot durable state,
  fetch authoritative exchange positions/open orders/fills, build a new derived
  cache projection from immutable ledger events plus REST, compare all sources,
  quarantine discrepancies, then resume entries only after reconciliation passes.

- Unknown submission outcomes must retain risk reservations and require order
  lookup/recovery before retry. Never blindly retry an order after timeout,
  transport failure, or ambiguous create-order response.

## Order-result contract

Order results must distinguish request completion from execution:

```python
request_completed: bool
has_execution: bool
executed_quantity_cc: int
remaining_quantity_cc: int
is_resting: bool
requires_recovery: bool
```

Interpretation:

- `filled_live`: apply the confirmed filled quantity.
- `partial_live`: apply the confirmed fill and resolve the remainder.
- `unfilled_ioc`: release reservation; no position mutation.
- `resting`: retain confirmed-open reservation.
- `rejected`: release reservation.
- `submission_unknown` or `duplicate_unknown`: retain reservation and recover
  by lookup before any retry.

Do not use a generic `OrderResult.success` field where these state-specific
properties are required.

## Entry and exit safety

- Every outbound order requires:
  `client_order_id`, `intent_id`, `run_id`, `process_id`, and `reason`.

- Exit orders must include `parent_entry_fill_id` when exit-parentage
  enforcement is enabled.

- New entries must be blocked when:
  - reconciliation is halted;
  - protective exits are unavailable;
  - an exchange/cache position already exists for the ticker;
  - final-minute entry restrictions apply;
  - the circuit breaker is halted;
  - risk, provenance, freshness, or market-state validation fails.

- Exits must use fresh executable own-side prices.

- Profit exits must meet the configured net-profit floor after fees.

- Stop-loss or model-invalidation exits require trusted entry provenance,
  fill/order linkage, trusted at-fill book capture, and the required arming
  interval. If provenance is incomplete, fail closed and alert.

- A startup replay, REST reconstruction, or unknown market state must never
  create an unprotected live entry or submit speculative brackets.

## Circuit breaker rules

- The circuit breaker is process-wide and fail-closed for entries.

- Do not clear a halt through direct `resume()` calls from application code.

- Release only through the logged administrative release path with a valid
  approval token, a fresh run ID, no unsafe open positions/orders, no recent
  unresolved unmatched fills, and a verified/advanced fill watermark.

- Backfills and historical fills older than the durable source watermark are
  quarantined/logged, not treated as evidence of another writer.

- Before declaring a fill unmatched, perform durable intent/order lookup and a
  bounded pending-intent grace lookup to account for submission/fill races.

## Environment and production rules

- Test configuration must be explicit and must not inherit production behavior.

- Environment variables override repository `.env` values.

- Production startup must fail closed if testing flags, direct-execution
  bypasses, debug/manual-order flags, credential conflicts, disabled safety
  controls, or incompatible venue environment settings are present.

- Live trading requires production profile, authenticated operator controls,
  the required Kalshi WebSocket implementation, and all required safety gates.

- Paper/shadow telemetry modes must not permit live order routing.

- Do not add insecure bypasses, silent fallbacks, permissive defaults, or
  environment-dependent production behavior without an explicit fail-closed
  validation and test coverage.

## CF Benchmarks RTI rules

- `CfbRtiObservation` is the canonical settlement-price authority.

- `get_live_rti(asset)` is the only path that may return
  `settlement_reference="cfb_rti_live"`.

- RTI data must fail closed on source mismatch, symbol mismatch, invalid value,
  stale data, stream failure, ordering regression, subscription failure, or
  target-linkage failure.

- Never silently substitute public spot data for an unavailable RTI settlement
  reference.

- Entries using the RTI-based settlement path require valid RTI provenance and
  confidence validation.

## Change and review expectations

When reviewing or modifying code:

1. Read the relevant implementation, its direct callers, models/contracts, and
   targeted tests before reaching a conclusion. Do not report speculative issues.

2. Prioritize correctness of fills, signed exposure, fixed-point quantity/price
   math, idempotency, reconciliation, order state transitions, and exit safety.

3. Treat WebSocket/HTTP replay, duplicate fills, partial fills, unknown order
   outcomes, counterparty-equivalent side forms, and REST rebuilds as mandatory
   edge cases.

4. Preserve `Decimal` and centi-contract arithmetic end to end. Do not
   introduce float-based financial calculation or lossy rounding.

5. For every defect found, provide severity, exact code location, execution
   path, violated invariant, concrete impact, and a minimal safe fix.

6. Report pre-existing defects only when they are directly confirmed by the
   code path being examined and materially affect correctness or safety.

7. Do not alter behavior solely to make tests pass. Update tests when a valid
   contract change is intentional, documented, and safe.

## Required verification

After touching order routing, ledger conversion, fill application, cache,
reconciliation, binary price-space logic, position monitoring, exit policy,
or CF-RTI integration, run the relevant focused tests first, followed by the
project's required Kalshi 15m regression suite.

After changing order-router, port, ledger conversion, exposure-reconciliation, or
binary_price_space code, run at least:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_router_ioc_tif_reconciliation.py tests\kalshi_alignment\test_order_router.py tests\event_venues\kalshi\test_port_ledger_adapter.py tests\event_venues\kalshi\test_kalshi_p0_partial_fill_reconciliation.py tests\event_venues\kalshi\test_kalshi_p0_maker_taker_simulator.py tests\event_venues\kalshi\test_kalshi_p0_exit_order_simulator.py tests\test_loop_15m_bugfixes.py tests\test_loop_15m_decimal_fix_2026_07_29.py tests\test_exit_canonicalization_and_policy_2026_08_07.py tests\test_canonical_exposure_reconciliation.py tests\test_fills_ledger_v2_side_action_fix.py tests\test_fills_ledger_v2_fractional_replay.py tests\position_management\test_position_monitor_cleanup_exit.py tests\position_management\test_position_monitor.py tests\position_management\test_position_monitor_exit_audit.py tests\position_management\test_spread_stop_provenance.py tests\event_venues\kalshi\test_execution_risk_firewall.py tests\event_venues\kalshi\test_kalshi_order_manager.py tests\test_direct_venue_submission_guard.py tests\test_production_startup_validation.py tests\test_trade_decision_release_gates.py tests\test_cf_rti_adapter.py tests\test_cf_rti_e2e.py tests\test_ws_rest_divergence_guard.py -v
```

For firewall enforcement smoke in production, set
`MERID_EXIT_FIREWALL_OBSERVE_ONLY=false` and `MERID_REQUIRE_EXIT_PARENTAGE=1` and
watch for `firewall:` rejection reasons. In observe-only/canary mode, set
`MERID_EXIT_FIREWALL_OBSERVE_ONLY=true`.

At minimum, verify:

- Fractional fills preserve exact centi-contract exposure and fees.
- Duplicate HTTP/WebSocket/router delivery produces one state mutation only.
- Unknown or untrusted fills remain quarantined.
- Reduce-only exits cannot reverse exposure.
- REST/cache/ledger/exchange signed exposure matches per ticker.
- Partial IOC/GTC behavior retains or releases reservations correctly.
- Exit and protective-order provenance gates fail closed.
- Circuit-breaker halt and administrative release paths behave correctly.
- Production startup rejects unsafe environment combinations.
- Shadow/paper modes cannot submit live orders.

## Reviewer prompt

Before reporting a trading-system finding, evaluate it against the MERID safety
contract. Flag any change that could violate fill idempotency, signed-YES
exposure correctness, centi-contract precision, trusted-fill canonicalization,
reconciliation fail-closed behavior, reduce-only exit safety, protective-exit
provenance, order identity, circuit-breaker controls, or production environment
gating.

## 2026-08-28 tuning / stuck-position quarantine notes

- A stale `closed`/`resolved=False` exchange position (e.g. `KXETH15M-26AUG280800-00`) must not keep `portfolio_authoritative=false` and block new entries indefinitely.
- Implemented quarantine path:
  - `position_cache._is_expired_ticker` now returns `True` for quarantined tickers.
  - `KalshiPositionCache.quarantine_ticker()` removes a closed-but-not-settled position from `_positions`, clears `reconciliation_halted`, and releases the `GlobalSlotAllocator` slot.
  - `position_cache.sync_from_rest` quarantines any non-zero position whose market is expired/closed but not yet settled.
  - `canonical_portfolio_reconciler.build_snapshot` filters expired positions from exchange/ledger/cache before exposure and reconciliation.
  - `KalshiFillsLedger.compute_net_positions` also skips quarantined/expired markets.
- Restart is required for these changes to take effect.  On startup the KXETH15M-26AUG280800-00 position will be quarantined, the slot released, and `allow_new_entries` can return to `True` once all active tickers reconcile.

For each such finding, explicitly name the violated MERID invariant and explain
the concrete execution sequence that causes the failure.

## 2026-08-28 probability calibration / tail-risk notes

- The Kalshi 15m crypto binary tail (0-19c held) showed a near-zero realized win
  rate in 7-day trade data.  Buying cheap YES in that bucket is structurally -EV.
- The canonical fee formula `fee_cents = ceil(rate * C * P * (1-P) * 100)` makes
  cheap-tail taker fees large as a percentage of premium (e.g. ~6% at 17c,
  ~10% at 10c).  Edge thresholds must be evaluated against the full cost stack,
  not just the raw 1c per-contract fee.
- `trade_decision.py` tail calibration must apply unconditionally whenever the
  held-side price is below `MERID_TAIL_CALIBRATION_PRICE_FLOOR`, not only when
  the raw model probability is > 0.5.  The previous `p_selected > 0.5` gate let
  low-confidence YES trades in the 0-29c tail execute on a miscalibrated hybrid
  model.
- Hybrid Bachelier+delta signals (velocity, MACD, RSI, OBI, FVG, regime) are not
  validated out-of-sample and should be disabled until the model passes a
  Brier/reliability/PBO audit.  Bachelier-only with TWAP-appropriate vol is the
  only defensible live baseline.
- Live re-enablement should require, at minimum:
  - 2+ weeks of paper/shadow decisions with Brier score and reliability diagram
    on a hold-out test set;
  - Probability of Backtest Overfitting (PBO) < 0.30 via CSCV;
  - Deflated Sharpe Ratio (DSR) > 0.95;
  - Walk-forward efficiency (OOS/IS) > 0.30;
  - Positive mean net edge per price bucket after the corrected fee model; and
  - A documented, pre-registered parameter set with no further tuning.
- The 7-day `data/probability_tail_calibration.json` was fit on YES-held data
  only; the NO curve was a `1 - p_yes` dual.  A real NO curve must be refit from
  NO-held fill/settlement records using `scripts/refit_no_tail_curve_from_audit.py`.
  Promote the output to `data/probability_tail_calibration.json` only after a
  hold-out paper/shadow window (>= 5 days, >= 200 NO-held trades) shows Brier
  <= 0.20 and reliability gaps within +/- 0.10 per bucket.
