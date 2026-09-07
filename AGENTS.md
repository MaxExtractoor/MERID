```yaml
---
auto_execution_mode: 1
description: MERID/Kalshi 15m live-trading engineering, safety, and controlled-release contract
---
```

# MERID Agent Notes

You are a senior Python engineer reviewing, modifying, debugging, validating, or operating the MERID Kalshi crypto 15-minute trading system.

Live trading is permitted **only** through the controlled-release gates in this contract. Your highest priority remains execution correctness, exposure integrity, reconciliation safety, and the ability to reduce or close risk during failures.

Do not make changes that weaken these rules. Do not enable live routing merely because `auto_execution_mode: 1` is set. That flag authorizes the system to *attempt controlled live enablement*; it does not override any safety gate, reconciliation halt, circuit breaker, environment check, model-validation requirement, or operator approval requirement.

## Live-trading authorization

`auto_execution_mode: 1` means the system may submit live orders only when every required gate below is true for the current process, run, ticker, and decision.

A live order may be routed only if all of the following hold:

- The runtime profile is explicitly production/live.
- Kalshi credentials are present, valid, authenticated, and unambiguous.
- Venue configuration is explicitly live and cannot resolve to demo, sandbox, paper, shadow, simulation, replay, or mock routing.
- An authenticated operator has completed the logged live-enable release procedure for the current `run_id`.
- The process has a fresh, non-reused `run_id` and a unique `process_id`.
- The circuit breaker is not halted and has not been bypassed.
- Reconciliation has passed for the relevant ticker and portfolio scope.
- No active critical golden-record, bankroll, fill, order, or settlement discrepancy remains unresolved.
- Required WebSocket subscriptions are healthy and current.
- REST recovery, position synchronization, and open-order reconciliation have completed successfully.
- Protective exit capability is available and independently validated.
- The trade decision passes all risk, provenance, freshness, market-state, model-validation, and entry-policy gates.
- The order router confirms it is using the canonical live Kalshi implementation, not a test, stub, direct-execution bypass, or paper adapter.
- The process has not detected testing flags, debug/manual-order flags, unsafe environment overrides, credential conflicts, or disabled safety controls.
- The live model release criteria in **Probability calibration and live model release** are satisfied.

If any gate is false, unknown, stale, unavailable, or inconsistent:

- Block new entries.
- Preserve reduce-only exits and cancellation/flatten capability.
- Emit a structured reason code and operator-visible telemetry.
- Do not silently downgrade the failure to paper execution while claiming live readiness.
- Do not retry unknown submissions without recovery.

## Canonical data model

- Quantities are integer centi-contracts:

  ```python
  quantity_cc = int(Decimal(count_fp) * 100)
  ```

  Never round fractional contract fills to whole contracts.

- Prices and cost basis use `Decimal` dollars. `price_cents` is display/legacy only and must not become the canonical source of price or PnL math.

- Exposure is signed YES centi-contracts (`yes_exposure_cc`):
  - Positive = long YES.
  - Negative = long NO.

- `fill_id` is immutable and globally idempotent.

- Each order must preserve the identity chain:

  ```text
  intent_id → client_order_id → order_id
  ```

- Market positions are per-market positions. Do not substitute aggregate `event_positions` for `market_positions.position_fp`.

## Non-negotiable fill rules

1. One `fill_id` may mutate ledger, cache, risk, allocator, monitor, and session accounting exactly once.

2. Router immediate fills, WebSocket fills, and HTTP-poller fills must use the same durable `apply_fill_once(fill_id, ...)` path.

3. Duplicate fill IDs are no-ops and must emit `duplicate_fill_id` telemetry.

4. A fill that cannot be correlated to a known intent/order is persisted as `UNMATCHED_FILL` and quarantined. It must not create or alter a position, attach TP/SL, update monitor state, consume/release risk, or update PnL.

5. Only fills with `canonicalization_state` equal to `TRUSTED_LIVE_V1` or `TRUSTED_BACKFILLED_V1` may mutate live position state.

6. A `reduce_only` or exit fill can reduce or flatten exposure only. It must never increase absolute exposure or reverse a position into the opposite leg.

7. Raw exchange execution facts win over order intent for audit and exposure calculation. Intent is used for correlation and conflict detection only.

8. A side-label mismatch is acceptable only when the exchange-reported signed-YES delta equals the intended signed-YES delta. Otherwise quarantine it as `UNTRUSTED_SIDE_CONFLICT`.

9. A live submission acknowledgement is not evidence of execution. Only a trusted exchange execution record may produce a position mutation.

10. A fill observed through more than one source must preserve the same immutable exchange identity and must be deduplicated before any downstream state mutation.

## Reconciliation and failure policy

- Exchange, ledger, cache, monitor, allocator, and pending-order exposure must agree per active ticker in centi-contract units.

- Any unexplained exposure divergence sets `reconciliation_halted` and blocks new entries for that ticker.

- An entry halt must never disable reduce-only exits. Preserve the ability to flatten exposure.

- Never use an in-place cache reset as a rollback shortcut or as a way to hide an inconsistency.

- For recovery:
  1. Freeze new entries.
  2. Retain exits, cancellation, and flatten capability.
  3. Snapshot durable state.
  4. Fetch authoritative exchange positions, open orders, and fills.
  5. Build a new derived cache projection from immutable ledger events plus REST.
  6. Compare exchange, ledger, cache, monitor, allocator, and pending-order state.
  7. Quarantine discrepancies.
  8. Resume entries only after reconciliation passes and a logged release gate approves the ticker.

- Unknown submission outcomes must retain risk reservations and require order lookup/recovery before retry. Never blindly retry an order after timeout, transport failure, or ambiguous create-order response.

- Reconciliation success must be timestamped. A stale successful reconciliation cannot authorize a new live entry after the configured freshness window expires.

- A successful reconciliation at startup is necessary but not sufficient for entry authorization. The system must also remain synchronized during live operation.

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
- `submission_unknown` or `duplicate_unknown`: retain reservation and recover by lookup before any retry.

Do not use a generic `OrderResult.success` field where these state-specific properties are required.

For live trading, an order result must also carry sufficient correlation data to support recovery:

```python
intent_id: str
client_order_id: str
order_id: str | None
venue: str
ticker: str
observed_at: datetime
```

If `order_id` is absent after a timed-out, ambiguous, or duplicate response, the client order ID and intent ID remain mandatory recovery keys.

## Entry and exit safety

- Every outbound order requires:
  - `client_order_id`
  - `intent_id`
  - `run_id`
  - `process_id`
  - `reason`

- Exit orders must include `parent_entry_fill_id` when exit-parentage enforcement is enabled.

- New live entries must be blocked when:
  - Reconciliation is halted or stale.
  - Protective exits are unavailable, unarmed, unvalidated, or unsupported for the position.
  - An exchange/cache position already exists for the ticker.
  - An unresolved open order or unknown submission outcome exists for the ticker.
  - Final-minute entry restrictions apply.
  - The circuit breaker is halted.
  - Risk, provenance, freshness, market-state, or venue validation fails.
  - The live operator release is missing, expired, invalid, or belongs to another run.
  - WebSocket health, fill watermark progress, or REST synchronization is stale.
  - Critical golden-record or bankroll drift findings are unresolved.
  - The active model or calibration artifact is not explicitly approved for live use.
  - The decision uses a disabled hybrid signal, an unvalidated RTI source, a stale settlement reference, or a data path with degraded provenance.

- Exits must use fresh executable own-side prices.

- Profit exits must meet the configured net-profit floor after fees.

- Stop-loss or model-invalidation exits require trusted entry provenance, fill/order linkage, trusted at-fill book capture, and the required arming interval. If provenance is incomplete, fail closed and alert.

- A startup replay, REST reconstruction, or unknown market state must never create an unprotected live entry or submit speculative brackets.

- If an entry fill occurs but protective exit installation cannot be confirmed, immediately:
  1. Freeze further entries for the ticker and process.
  2. Retain the risk reservation.
  3. Reconcile the exchange order and position state.
  4. Attempt only safe reduce-only protection or flattening actions.
  5. Escalate through circuit-breaker and operator telemetry according to configured severity.

## Live release procedure

Live order routing must remain disabled at process start until the controlled-release procedure succeeds. `auto_execution_mode: 1` does not eliminate this requirement.

The administrative live-enable path must:

1. Create a fresh `run_id` and record the authenticated operator identity.
2. Verify production profile and live Kalshi venue configuration.
3. Verify no testing, mock, simulation, direct-routing bypass, manual-order debug, or shadow/paper routing flag is enabled.
4. Verify credential validity, credential uniqueness, account identity, and intended venue environment.
5. Verify the required Kalshi WebSocket implementation is connected, subscribed, receiving messages, and advancing its trusted fill watermark.
6. Fetch authoritative exchange balances, positions, open orders, and recent fills.
7. Rebuild derived state from immutable ledger events and authoritative REST data.
8. Verify per-ticker signed exposure agreement across exchange, ledger, cache, monitor, allocator, and pending reservations.
9. Confirm no unresolved `UNMATCHED_FILL`, `UNTRUSTED_SIDE_CONFLICT`, missing-order, overfill, settlement mismatch, or critical bankroll discrepancy remains within the configured lookback period.
10. Confirm all active positions and resting orders are either reconciled and protected or are explicitly quarantined under the expired-market rules.
11. Confirm reduce-only exit routing, cancellation, and flatten capability are enabled and pass a non-mutating health validation.
12. Confirm all live model-release requirements are satisfied.
13. Require a valid approval token that is bound to the current `run_id`, environment, account, and expiration time.
14. Persist an immutable, auditable release record before allowing the first entry.
15. Enable entries only after all gates pass.

The release record must include at least:

```python
run_id: str
process_id: str
operator_id: str
approval_token_id: str
approved_at: datetime
expires_at: datetime
environment: str
venue_environment: str
kalshi_account_id: str
fill_watermark: str | int
reconciliation_snapshot_id: str
model_release_id: str
safety_gate_results: dict[str, bool]
```

The system must automatically return to entry-halted status when:

- The approval token expires.
- The process restarts.
- A critical reconciliation discrepancy occurs.
- The circuit breaker trips.
- WebSocket/fill-watermark health becomes stale.
- Credentials, account identity, or venue environment change.
- The model release becomes invalidated, revoked, or stale.
- A required safety control becomes disabled or unavailable.

A new live-enable release is required after any such event.

## Circuit breaker rules

- The circuit breaker is process-wide and fail-closed for entries.

- Do not clear a halt through direct `resume()` calls from application code.

- Release only through the logged administrative release path with:
  - A valid approval token.
  - A fresh run ID.
  - No unsafe open positions or orders.
  - No recent unresolved unmatched fills.
  - A verified or advanced fill watermark.
  - A successful reconciliation snapshot.
  - Confirmed production environment integrity.
  - Confirmed live model-release validity.

- Backfills and historical fills older than the durable source watermark are quarantined/logged, not treated as evidence of another writer.

- Before declaring a fill unmatched, perform durable intent/order lookup and a bounded pending-intent grace lookup to account for submission/fill races.

- A circuit-breaker release may restore entry eligibility only. It must not overwrite, erase, or reinterpret prior ledger, order, reconciliation, or quarantine records.

## Environment and production rules

- Test configuration must be explicit and must not inherit production behavior.

- Environment variables override repository `.env` values.

- Production startup must fail closed if testing flags, direct-execution bypasses, debug/manual-order flags, credential conflicts, disabled safety controls, or incompatible venue environment settings are present.

- Live trading requires:
  - Production profile.
  - Explicit `auto_execution_mode: 1`.
  - Authenticated operator controls.
  - A valid unexpired live-enable release for the current run.
  - The required Kalshi WebSocket implementation.
  - Authenticated live Kalshi credentials.
  - Verified live venue/account identity.
  - All required safety gates.
  - An approved production model release.

- Paper/shadow telemetry modes must not permit live order routing.

- The system must fail closed if configuration is contradictory, including combinations such as:
  - Live routing plus paper/shadow mode.
  - Production profile plus sandbox/demo venue.
  - `auto_execution_mode: 1` plus test, mock, replay, or simulation adapters.
  - Live routing plus direct execution bypass.
  - Live routing plus disabled exit firewall or disabled reconciliation.
  - Live routing plus missing or stale operator approval.
  - Live routing plus unapproved hybrid model features.

- Do not add insecure bypasses, silent fallbacks, permissive defaults, or environment-dependent production behavior without explicit fail-closed validation and test coverage.

- No environment variable, CLI option, config-file value, feature flag, or application-code branch may bypass the live-release gates, circuit breaker, trusted-fill requirements, exit firewall, reconciliation halt, or model-release constraints.

## CF Benchmarks RTI rules

- `CfbRtiObservation` is the canonical settlement-price authority.

- `get_live_rti(asset)` is the only path that may return `settlement_reference="cfb_rti_live"`.

- RTI data must fail closed on source mismatch, symbol mismatch, invalid value, stale data, stream failure, ordering regression, subscription failure, or target-linkage failure.

- Never silently substitute public spot data for an unavailable RTI settlement reference.

- Entries using the RTI-based settlement path require valid RTI provenance and confidence validation.

- Loss, staleness, ordering regression, or provenance failure in RTI must block affected new entries immediately while preserving exits.

## Probability calibration and live model release

The Kalshi 15-minute crypto binary tail showed a near-zero realized win rate in 7-day trade data for 0–19c held-side positions. Buying cheap YES in that bucket is structurally negative expected value under the observed data.

The canonical fee formula is:

```python
fee_cents = ceil(rate * C * P * (1 - P) * 100)
```

Cheap-tail taker fees can represent a large percentage of premium. Edge thresholds must use the full expected cost stack, including exchange fees, expected spread/slippage, and any applicable execution costs. Do not use a generic 1c-per-contract fee approximation for live eligibility.

- `trade_decision.py` tail calibration must apply unconditionally whenever the held-side price is below `MERID_TAIL_CALIBRATION_PRICE_FLOOR`.
- Do not gate tail calibration on `p_selected > 0.5`.
- The prior `p_selected > 0.5` gate allowed low-confidence YES positions in the 0–29c tail to execute using a miscalibrated hybrid model.
- Hybrid Bachelier-plus-delta signals, including velocity, MACD, RSI, OBI, FVG, and regime features, remain disabled for live execution until they pass the required out-of-sample validation and are included in an explicit approved model release.
- Bachelier-only with TWAP-appropriate volatility is the permitted default live baseline unless a separately approved model-release artifact explicitly authorizes another model.

A live model release requires all of the following:

- At least two weeks of paper/shadow decisions evaluated on a hold-out test set.
- Brier score and reliability-diagram review over the hold-out period.
- Probability of Backtest Overfitting, measured with CSCV, below 0.30.
- Deflated Sharpe Ratio above 0.95.
- Walk-forward efficiency, OOS/IS, above 0.30.
- Positive mean net edge by price bucket after the corrected full fee model.
- A documented, pre-registered parameter set with no further tuning during the validation window.
- A model version, data cutoff, feature manifest, calibration artifact hashes, and approval identity persisted in the model-release record.
- No unresolved evidence that realized calibration gaps exceed 0.10 in any price bucket for two consecutive days.

The existing 7-day `data/probability_tail_calibration.json` was fit using YES-held data only; its NO curve was a `1 - p_yes` dual. It is not sufficient authority for live NO-tail trading.

Before enabling NO-held tail entries:

1. Refit a true NO curve from NO-held fill/settlement records using `scripts/refit_no_tail_curve_from_audit.py`.
2. Preserve the generated artifact and its source-data manifest for audit.
3. Run a hold-out paper/shadow window of at least five days and at least 200 NO-held trades.
4. Require Brier score less than or equal to 0.20.
5. Require reliability gaps within ±0.10 in each evaluated bucket.
6. Promote the output to `data/probability_tail_calibration.json` only through a logged model-release approval.

Until that approval exists, block live NO-tail entries rather than inferring a NO calibration curve from YES data.

## Change and review expectations

When reviewing or modifying code:

1. Read the relevant implementation, its direct callers, models/contracts, configuration resolution, live-routing boundary, and targeted tests before reaching a conclusion. Do not report speculative issues.

2. Prioritize correctness of fills, signed exposure, fixed-point quantity/price math, idempotency, reconciliation, order state transitions, live-release gating, and exit safety.

3. Treat WebSocket/HTTP replay, duplicate fills, partial fills, unknown order outcomes, counterparty-equivalent side forms, REST rebuilds, process restarts, stale live-release tokens, and live/paper environment conflicts as mandatory edge cases.

4. Preserve `Decimal` and centi-contract arithmetic end to end. Do not introduce float-based financial calculation or lossy rounding.

5. For every defect found, provide:
  - Severity.
  - Exact code location.
  - Execution path.
  - Violated MERID invariant.
  - Concrete impact.
  - Minimal safe fix.
  - Required regression test.

6. Report pre-existing defects only when directly confirmed by the code path being examined and materially affecting correctness, live-trading safety, or financial exposure.

7. Do not alter behavior solely to make tests pass. Update tests only when a valid contract change is intentional, documented, and safe.

8. Any change that enables or affects live routing must include explicit negative tests demonstrating that a missing approval token, stale reconciliation, broken WebSocket, paper mode, unsafe environment flag, stale model release, or circuit-breaker halt blocks entries while preserving exits.

## Required verification

After touching order routing, ledger conversion, fill application, cache, reconciliation, binary price-space logic, position monitoring, exit policy, production startup validation, live-release gates, model release, or CF-RTI integration:

1. Run focused tests first.
2. Run the required Kalshi 15-minute regression suite.
3. Run live-routing gate tests that exercise both authorization and denial conditions.
4. Verify a no-order dry health check against the authenticated live account before operator release.
5. Do not submit a live order solely as a connectivity test.

After changing order-router, port, ledger conversion, exposure-reconciliation, binary_price_space, production startup, or live-routing release code, run at least:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_router_ioc_tif_reconciliation.py tests\kalshi_alignment\test_order_router.py tests\event_venues\kalshi\test_port_ledger_adapter.py tests\event_venues\kalshi\test_kalshi_p0_partial_fill_reconciliation.py tests\event_venues\kalshi\test_kalshi_p0_maker_taker_simulator.py tests\event_venues\kalshi\test_kalshi_p0_exit_order_simulator.py tests\test_loop_15m_bugfixes.py tests\test_loop_15m_decimal_fix_2026_07_29.py tests\test_exit_canonicalization_and_policy_2026_08_07.py tests\test_canonical_exposure_reconciliation.py tests\test_fills_ledger_v2_side_action_fix.py tests\test_fills_ledger_v2_fractional_replay.py tests\position_management\test_position_monitor_cleanup_exit.py tests\position_management\test_position_monitor.py tests\position_management\test_position_monitor_exit_audit.py tests\test_spread_stop_provenance.py tests\event_venues\kalshi\test_execution_risk_firewall.py tests\event_venues\kalshi\test_kalshi_order_manager.py tests\test_direct_venue_submission_guard.py tests\test_production_startup_validation.py tests\test_trade_decision_release_gates.py tests\test_cf_rti_adapter.py tests\test_cf_rti_e2e.py tests\test_ws_rest_divergence_guard.py -v
```

Add and run focused tests covering:

- `auto_execution_mode: 1` without a valid live-release record blocks all entry routes.
- A valid release record enables only canonical live Kalshi routing.
- Live routing is rejected in paper, shadow, test, mock, replay, simulation, sandbox, or demo modes.
- A stale or expired live-release token blocks new entries.
- A process restart invalidates prior live authorization until a fresh release occurs.
- Reconciliation, WebSocket health, REST freshness, or fill-watermark regression immediately halts new entries.
- Circuit-breaker halt prevents entries even when `auto_execution_mode: 1`.
- Reduce-only exits remain available during all entry halts.
- A missing protective-exit capability blocks an entry.
- Unknown submission outcomes retain reservations and do not trigger blind retries.
- Fractional fills preserve exact centi-contract exposure and fees.
- Duplicate HTTP/WebSocket/router delivery produces one state mutation only.
- Unknown or untrusted fills remain quarantined.
- Reduce-only exits cannot reverse exposure.
- REST/cache/ledger/exchange signed exposure matches per ticker.
- Partial IOC/GTC behavior retains or releases reservations correctly.
- Exit and protective-order provenance gates fail closed.
- Production startup rejects unsafe environment combinations.
- Shadow/paper modes cannot submit live orders.
- Live NO-tail entries are blocked until a separately validated NO calibration release exists.
- Hybrid features cannot become live-eligible without an approved validation artifact.

For firewall enforcement smoke in production, set:

```powershell
$env:MERID_EXIT_FIREWALL_OBSERVE_ONLY = "false"
$env:MERID_REQUIRE_EXIT_PARENTAGE = "1"
```

Watch for `firewall:` rejection reasons. In observe-only/canary mode, set:

```powershell
$env:MERID_EXIT_FIREWALL_OBSERVE_ONLY = "true"
```

Observe-only mode must never be treated as sufficient authority for unrestricted live entry routing. The live-release record must explicitly record whether the exit firewall is enforcing or observing, and the configured policy must decide whether observe-only blocks entries.

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
- Live routing cannot occur without a current, authenticated, auditable live-release record.
- Model-release, tail-calibration, and RTI provenance failures block affected live entries.

## Reviewer prompt

Before reporting a trading-system finding, evaluate it against the MERID safety contract.

Flag any change that could violate:

- Fill idempotency.
- Signed-YES exposure correctness.
- Centi-contract precision.
- Trusted-fill canonicalization.
- Reconciliation fail-closed behavior.
- Reduce-only exit safety.
- Protective-exit provenance.
- Order identity.
- Circuit-breaker controls.
- Production environment gating.
- Live-release authorization.
- Model-release or calibration gating.
- RTI provenance and freshness requirements.

For each finding, explicitly name the violated MERID invariant and explain the concrete execution sequence that causes the failure.

## 2026-08-28 tuning and quarantine notes

- A stale `closed`/`resolved=False` exchange position, such as `KXETH15M-26AUG280800-00`, must not keep `portfolio_authoritative=false` and block new entries indefinitely.

- The quarantine path is:
  - `position_cache._is_expired_ticker` returns `True` for quarantined tickers.
  - `KalshiPositionCache.quarantine_ticker()` removes a closed-but-not-settled position from `_positions`, clears `reconciliation_halted`, and releases the `GlobalSlotAllocator` slot.
  - `position_cache.sync_from_rest` quarantines any non-zero position whose market is expired/closed but not yet settled.
  - `canonical_portfolio_reconciler.build_snapshot` filters expired positions from exchange, ledger, and cache before exposure and reconciliation.
  - `KalshiFillsLedger.compute_net_positions` skips quarantined/expired markets.

- Restart is required for those changes to take effect. On startup, `KXETH15M-26AUG280800-00` must be quarantined, the slot released, and `allow_new_entries` may return `True` only after all active tickers reconcile and the full live-release procedure succeeds.

## Golden-record and bankroll alerts

The golden-record audit classifies divergences by severity:

- **Critical**: page/Slack immediately and halt new entries if unresolved:
  - `side_mismatch`
  - `action_mismatch`
  - `qty_mismatch`
  - `overfill`
  - `missing_order`
  - `unmatched_fill`
  - `settlement_mismatch`
  - `missing_settlement_for_settled_market`
  - `missing_pnl`

- **Warning**: review the same day:
  - `rejected_without_reason`

- **Price slippage**: emit `price_slippage_Nc` when economic fill price is worse than intended price by more than `MERID_GOLDEN_RECORD_SLIPPAGE_THRESHOLD_CENTS`, default 2c. Slippage is a warning by default and must be reviewed for execution-quality issues.

The bankroll/equity reconciler uses:

- `MERID_BANKROLL_DRIFT_WARNING_PCT` / `MERID_BANKROLL_DRIFT_WARNING_USD`, default 0.5% / $1.00.
- `MERID_BANKROLL_DRIFT_CRITICAL_PCT` / `MERID_BANKROLL_DRIFT_CRITICAL_USD`, default 1.0% / $5.00.

Any critical bankroll record requires immediate manual reconciliation and circuit-breaker review. Warning records require end-of-day review. A critical unresolved record blocks new live entries.

## Audit plan

### C. Fill and settlement triage

1. Investigate every `unmatched_fill` and `missing_order` within 24 hours. Confirm the fill is quarantined, did not mutate exposure, and trace the parent `client_order_id` and `order_id` from exchange fills.

2. Add settlement provenance. Each `record_settlement` row must capture the `entry_intent_id`, `fill_id`, and `avg_price_cents` from the closed position.

3. Cross-check `settlement_outcomes.jsonl` against the fact table:
   - Every settled market with a MERID position must have a settlement row.
   - Every settlement row with non-zero PnL must trace to an order and fill.

4. Add an `unexplained_settlement_pnl` flag for records that have settlement PnL but no linked order/fill after the settlement-only noise filter.

5. Treat unresolved critical audit outcomes as live-entry release blockers.

### D. Model drift and skip classification

1. Join `golden_records.db` with `logs/decision_telemetry.jsonl` by `decision_id`/`decision_trace_id` to obtain `p_selected` and held side.

2. For each price bucket—0–19c, 20–39c, 40–59c, 60–79c, and 80–99c—compute:
   - Brier score.
   - Reliability-diagram gaps.
   - Realized win rate.
   - Mean net edge after fees and execution cost.

3. Compare realized win rate with `p_selected`. Flag a bucket as miscalibrated when the gap exceeds 0.10 for two consecutive days.

4. Classify skipped or abandoned signals:
   - `selected` → no order.
   - `ordered` → rejected/unfilled.
   - `filled` → not settled.

5. Correlate skip rate with market width, time of day, model edge, and asset.

6. Promote or refit `data/probability_tail_calibration.json` only after the hold-out paper/shadow window passes the live model-release thresholds above.

7. A detected calibration breach, invalid model artifact, or unexplained deterioration in post-fee edge must halt affected live entries pending review and a new approved release.