# MERID Production Audit — 2026-11-07

Scope: recurring `RECONCILIATION_DIVERGENCE` live-entry halts after restart — a trade executes post-preflight, then the next window is halted, requiring manual restart. Evidence: `data/live_runtime_state.json` transition history, `logs/server_console_20261106_191005.err.log` (halted run pid 7064), `data/kalshi_fills.db`, `merid/event_venues/kalshi/fills_ledger.py`, `fills_poller.py`, `position_cache.py`, `merid/observability/live_runtime_state.py`, `merid/governance/trading_circuit_breaker.py`, git history (`f945e199`, `c1203d6a`, `c54567d1`), Kalshi/alpaca/nautilus reconciliation references.

## Executive summary

**Two independent bugs, both now fixed:**

1. **Average-cost replay bug (halt trigger).** `_compute_position_from_fill_ids` blended *every* fill's execution price into the position's average — including exit fills. A partial exit therefore dragged the residual position's reported average toward the exit price. Kalshi (and `position_cache`, and `_update_position_with_fill`) keep the remaining contracts at their entry basis. On 2026-11-07 the ledger reported avg **75c** where Kalshi reported **69c** for the same 1 NO contract → `price_diff_cents=6 > 1` → `degraded` → `RECONCILIATION_DIVERGENCE` halt every 60 s until the market settled. Introduced by `f945e199`; the correct semantics existed in `c1203d6a` and in `position_cache._recompute_position_from_fills` but were never ported to the ledger replay.

2. **Auto-recovery dead-end (why every such halt needed a manual restart).** The fills poller's recovery path transitioned `LIVE_ENTRIES_HALTED → RECOVERY_RUNNING` unconditionally, then called `complete_runtime_recovery` with hardcoded-`True` evidence and a raw `_http_fill_watermark` read. That circuit-breaker attribute only exists after an *unmatched* fill initializes it — in a healthy session it is never set → `fill_watermark_missing` → recovery refused → machine parked in `RECOVERY_RUNNING` **permanently**, because the retry guard only matches `state == "LIVE_ENTRIES_HALTED"`. Confirmed in prod log: `19:30:52 recovery refused — incomplete evidence: ['fill_watermark_missing']`, then ~18 min parked until operator restart. The 2026-11-05 fix repaired the WS/book recovery paths (`ws_bridge.py`, `market_state.py`) with probed evidence + pre-screen + bounce-back; the reconciliation path — the most common halt source — was left on the old broken pattern.

## Timeline (UTC; local log stamps are UTC-5)

- **00:10:58** restart → run `20261107001058_7064_701071e5` → preflight → `LIVE_ENTRIES_ENABLED`.
- **~00:1x** entry fill: `yes/sell` 4.00 @ YES31/NO69 on `KXXRP15M-26NOV061930-30` → long 4 NO @69c (`client_order_id=merid_2cd3d9…`).
- **~00:2x** partial exit: `yes/buy` 3.00 @ YES16/NO84 → sell 3 NO @84c (`client_order_id=exit_c014…`) → 1 NO remains.
- **00:22:50** first halt — transient quantity race `signed position mismatch: exchange=-100:cache=0` (exchange position visible ~1.7 s before HTTP fill ingestion; bounded ingest+refetch recheck absorbed it next cycle — this part worked).
- **00:23:50 → 00:29:52** every reconcile cycle: ledger avg **75c** vs Kalshi **69c**, qty identical (100 cc NO) → `contract_divergence` → halt re-asserted each minute.
- **19:30:52 local (00:30:52 UTC)** market settles → positions flat → reconcile passes → `LIVE_ENTRIES_HALTED → RECOVERY_RUNNING` (`reconciliation_recovery_evaluation`) → `complete_runtime_recovery` refuses: `['fill_watermark_missing']`.
- **00:30:52 → 00:48:59** machine sits in `RECOVERY_RUNNING` — entries blocked, no retry possible — until operator restart (run `20261107004859_5896_9eca16a6` → preflight → enabled).

## Root cause detail — avg-price replay

`_compute_position_from_fill_ids` (fills_ledger.py ~4199) computed, for every fill:

```
total_cost = abs_exposure * avg_price + count * fill_price
avg = total_cost // (abs_exposure + count)
```

For the exit fill (3 NO @84c against 4 NO @69c): `(400*69 + 300*84) // 700 = 75`. The denominator treats the reduction as an addition. Kalshi's `market_exposure`-style basis and `position_cache._recompute_position_from_fills` (lines ~4928-4959, "a partial exit must not drag avg_price_cents toward its own execution price") both implement the correct model: **sells release `qty × avg` of basis; the remainder keeps its average**.

## Fixes applied

**`merid/event_venues/kalshi/fills_ledger.py`** — `_compute_position_from_fill_ids` now classifies each fill before mutating exposure:
- open/add (same signed direction, or from flat): weighted-average blend of held-side leg price;
- pure reduction (`|fill| < |position|`, opposite direction): exposure applies, `avg_price_cents` unchanged, **no leg price required** (a reduce fill without prices still updates quantity);
- flip (`|fill| > |position|`, opposite direction): residual re-anchors to the flip fill's price in the *new* side's space;
- exact close → position gone.

Held-side price is only required when the fill moves cost basis. `episode_opener_fill_id` (exit-authorization generation id) semantics preserved.

**`merid/event_venues/kalshi/fills_poller.py`** — auto-recovery rewritten to the canonical pattern already used by `ws_bridge._maybe_resume_live_entries_after_reconnect` / `market_state._maybe_recover_session_book_untrusted`:
- probe via `collect_runtime_recovery_evidence(resolved_failure=True, fill_watermark_at_halt=…)` — real subsystem evidence incl. the fills-ledger watermark fallback, never hardcoded `True`;
- pre-screen with `runtime_recovery_evidence_missing` — incomplete evidence → log + stay `LIVE_ENTRIES_HALTED`, retry next 60 s cycle;
- only then `RECOVERY_RUNNING → complete_runtime_recovery`; on refusal transition **back** to `LIVE_ENTRIES_HALTED` with the original reason/codes so the `RECONCILIATION_DIVERGENCE` matcher keeps working.
- `_halt_for_reconciliation` now captures `_halted_fill_watermark` with the same ledger fallback (circuit-breaker watermark is unset until an unmatched fill occurs).

**`merid/observability/live_runtime_state.py`** — `collect_runtime_recovery_evidence` ledger-watermark fallback now normalizes naive `created_time` to UTC before `max()`; a single naive timestamp previously made `max()` raise `TypeError` → watermark `None` → permanent `fill_watermark_missing`.

**`tests/event_venues/kalshi/test_fills_ledger.py`** — new `TestLedgerAvgPriceAccounting` (4 tests): exact incident replay (4 NO @69 entry / 3 NO @84 exit → 1 NO @69c), add-after-partial blend-on-remainder, flip re-anchor, reduce-without-leg-price.

## Verification

- Incident replay through real `on_fill` → `compute_position_from_fills`: **avg 69c** (was 75c). All 4 new tests **pass** under pytest.
- Related suite (`TestFillsLedgerPositionCalculation`, `TestCounterpartyFormAccounting`, `TestFillsLedgerIdempotency`, `TestLedgerAvgPriceAccounting`): **17 passed**; 1 pre-existing failure deselected — `test_promoted_provisional_row_deleted_from_db` expects a DB delete the code intentionally replaced with "retained superseded mirrors (no DB delete)" — unrelated drift in the ignored file.
- `tests/test_runtime_recovery_evidence.py`: **4 passed** — recovery state-machine contract intact.
- Note: `test_fills_ledger.py` is `--ignore`d in `pytest.ini` ("hang-prone"); `tests/conftest.py` collection wedges on this host — verified via `--noconftest` + explicit env isolation instead.

## Residual risks / notes

- **Deploy requires restart** — the running process (pid 5896) still has both bugs. Any partial exit can re-trigger the avg-price divergence; any reconciliation halt still dead-ends until restart. Recommend restart at the next convenient window; `auto_execution_mode: 1` auto-resumes after preflight.
- `fresh_reconciliation` evidence reads `_last_reconcile_time` (last *successful* cycle): after a >5 min halt the first passing cycle pre-screens incomplete → stays halted one extra 60 s cycle, then recovers. Effectively requires two consecutive clean reconciles — acceptable, arguably stronger.
- Transient exchange-ahead-of-ledger races (the 00:22:50 `cache=0` halt and the 11-03 355 ms incident) are absorbed by the bounded ingest+refetch recheck when they resolve within the window; with the recovery fix, ones that do halt now auto-recover instead of parking.
- Web research aligned with the fix: exchange/OMS practice is weighted-average cost basis where sells release `qty × avg` (Alpaca documented method, Kalshi `market_exposure`), idempotent fill ingestion keyed on venue trade id (already present), grace windows before declaring cache-vs-venue divergence (Nautilus position-discrepancy activity stamps ≈ the existing bounded recheck), and deterministic restart recovery = replay durable log + fetch outage-window fills at preflight (already the startup contract).
