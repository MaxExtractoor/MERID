# Expectancy & Loss-Containment Audit — Kalshi 15m Scalp Stack
**Date:** 2026-10-08 · **Assets:** BTC / ETH / SOL / XRP / DOGE (KX*15M series)
**Data window:** fills 2026-09-14 → 2026-10-08 · evals 2026-09-21 → 2026-10-08
**Sources:** `data/kalshi_fills.db` (venue rows only, `live_router_*` excluded),
`logs/settlement_outcomes.jsonl`, `logs/exit_evaluations.jsonl`,
`logs/entry_markouts.jsonl`, `data/kalshi_order_attempts.db` (attempt ledger)
**Reconstruction:** `scripts/_audit_expectancy_21_recon_v1.py` (v1) —
venue-fills-only, deduplicated by stable fill identity, centi-contract exact,
mutually exclusive episode cohorts, additive P&L. **All numbers below come
from this single reconstruction unless marked otherwise.**

---

## 1. Verdict

**The scalping edge looks real in the cohort where exits actually fill — but
that is a selected cohort, not an unbiased estimate of the strategy.** The
dominant defect is that exits rarely reach the venue at all.

Venue-reconciled, episode-level, all fees included (recon v1, mutually
exclusive cohorts; counts and P&L sum exactly to totals):

| Cohort | n | win-rate | net | PF | definition |
|---|---|---|---|---|---|
| `flat_with_exit` | 151 | 68.2% | **+$15.250** | 2.777 | position flat via a filled exit order |
| `flat_no_exit` | 12 | — | +$0.426 | — | flat with no exit fill (entry reversal/settlement flat) |
| `resid_exit_filled` | 2 | — | +$2.759 | — | partial exit filled, remainder settled |
| `resid_attempted` | 34 | — | **−$6.986** | — | ≥1 exit attempt, none filled |
| `resid_no_attempt` | 116 | — | **−$21.178** | — | zero exit attempts; rode to settlement |
| **TOTAL** | **315** | 51.7% | **−$9.730** | 0.823 | |

`E = wG − (1−w)L` overall = **−$0.031/episode**. Worst daily drawdown
**$11.30** (09-25 → 10-02). Fees $2.99 vs gross −$6.74 — fees are not the
primary leak.

**Selected-cohort caveat (explicit):** `flat_with_exit` (+$15.25, PF 2.78) is
the set of episodes where the exit machinery happened to work — liquidity was
available, an attempt survived the submit path, and the trigger fired. It is
**not** evidence that every episode would earn that expectancy if exits were
fixed; episodes that never reached an exit may differ systematically (thinner
books, worse entries, later in window). Treat it as an upper-bound diagnostic,
not a realizable backtest.

**Answer to the core question:** yes — the system sells small upside (median
win $0.20) while retaining large downside (median settlement-tail loss
$0.42–0.64, tail max ≈ $0.84/contract). The cause is **exit reliability**:
signals almost never convert to fills.

1. **The EV gate almost never said "sell"** — and, worse, `position_monitor`
   subjected *operational* exits to the same discretionary veto via a private
   reason list + hardcoded `canonical_reason="value_switch_exit"`. **Fixed
   this session** (§5); 14,864 evals → `SELL_SIGNALLED` only 3.8%,
   `HOLD_DATA_INSUFFICIENT` dominated by `vol_source=none`.
2. **Approved exits still didn't fill.** 1,080 durable attempts: 391 stalled
   `INTENT_PERSISTED` (388 legacy JSON-migrated + 3 genuine dispatch stalls),
   461 superseded-after-terminal re-arms, 191 `duplicate:concurrent_in_flight`
   mislabeled `SUBMISSION_UNKNOWN`, 61 `route_timeout:25s`, 50 canceled,
   45 exchange rejects, 30 not-accepted-confirmed. **Lifecycle repairs landed
   this session** (§5). 116 of 152 residual episodes **never produced an exit
   attempt**.
3. **Fractional positions were structurally unexitable** via the
   stop-candidate path (`qty_cc % 100 != 0` → reject) and mock/paper
   partial fills drew whole contracts only. *Fixed.*

**Counterfactual (diagnostic, not a backtest):** on the 117 residual episodes
with evaluator data, selling at the first *evaluated* executable bid would
have lost −$7.08 instead of −$24.98 (≈ +$17.90 better). Assumes top-of-book
fillability, ignores queue position/depth/latency — flagged, not claimed as
realizable.

---

## 1b. Reconciliation of previously reported headline numbers

Several intermediate analyses produced conflicting figures; recon v1 resolves
each. All are definitional differences between intermediate cuts, now made
explicit:

| Earlier figure | Resolved value (recon v1) | Explanation |
|---|---|---|
| "163 exit-filled + 150 no-exit = 313 of 315" | 315 = 151 + 12 + 2 + 34 + 116 | The old cut conflated cohorts. The missing 2 are `resid_exit_filled` (partial exits whose remainder settled) and `flat_no_exit` (12) was folded into "no-exit" incorrectly. |
| Exit-filled net "+$15.68" vs "+$17.31" | `flat_with_exit` = **+$15.250** (n=151); exit-fill-*present* cohort (flat+partial) = **+$18.009** (n=153, PF 3.098) | The two numbers used different dedup/cohort bases pre-recon. v1 canonical: flat-with-exit +$15.25. |
| Exit-filled PF "2.77" vs "3.03" | flat-with-exit PF **2.777**; exit-fill-present PF **3.098** | Same cohort-definition difference. |
| Residual net "−$25.41 / −$24.98 / −$28.16 / −$27.74" | all-residual **−$25.405** (n=152); resid-with-zero-exit-fill **−$28.164** (n=150); counterfactual-eligible subset **−$24.983** (n=117) | Four different subsets of the residual cohort. |
| "52% residual" | **48.3%** = 152/315 | Earlier figure used a partial denominator. |
| "99/1,080 attempts filled" | attempts (durable rows) = 1,080; order submissions = 680 `SUBMITTING` events; venue fills = 99; closed-flat episodes = 151 | Attempt ≠ order ≠ fill ≠ closed episode — each stage leaks. |

**Data-quality exclusions:** 24 synthetic `live_router_*` rows excluded from
venue economics; dedup by stable fill identity (`trade_id`/`fill_id`);
130 fills fractional (0.18–1.55 contracts) preserved in centi-contracts;
0 unresolved fills after canonical view.

---

## 2. Venue reconciliation & data integrity

- **518 unique venue fills** (of 542 in-scope rows; 24 synthetic `live_router_*`
  rows excluded), **315 position episodes**. Quantities kept exact in
  centi-contracts — 130 fills fractional, 44 fractional episodes.
- **Fees reconcile exactly**: every taker fill matches `0.07·C·P(1−P)` within
  rounding; all 214 maker fills carry `fee=0`. Maker share ≈ 41%.
- **Ledger double-count defect** — complement-form exits persisted a synthetic
  `order_router` row alongside the authoritative venue row; raw consumers
  (`kill_switches.py`, `sentiment_risk.py`, `position_cache` cross-validation)
  double-counted. **Fixed this session**: `fills_ledger.get_canonical_fills()`
  is now the single authoritative view (authoritative vs quarantined
  partitions); all three consumers migrated; superseded/provisional mirrors
  excluded; `post_position_fp` is captured and mismatches quarantined.
- New entries are now **blocked while unresolved router fills are stale**
  (fail-closed at the `order_intent_contract` entry-only layer — exits
  unaffected).

## 3. Expectancy by asset (venue-reconciled)

| Asset | n | w | G | L | net | PF | resid n | resid net | flat net |
|---|---|---|---|---|---|---|---|---|---|
| BTC  | 89 | .494 | .239 | .361 | **−5.71** | .648 | 45 | **−12.47** | +6.75 |
| ETH  | 68 | .574 | .350 | .336 | +3.93 | 1.404 | 34 | −0.50 | +4.43 |
| SOL  | 45 | .356 | .241 | .282 | **−4.32** | .471 | 20 | −4.50 | +0.18 |
| XRP  | 74 | .541 | .261 | .460 | **−5.17** | .669 | 33 | **−7.16** | +1.99 |
| DOGE | 39 | .615 | .287 | .357 | +1.54 | 1.287 | 20 | −0.78 | +2.31 |

Every asset's flat cohort is non-negative; all red ink lives in the resid
cohort. BTC resid is worst (w=.20, PF=.197). XRP resid has the fattest tail.
SOL's flat cohort is weakest (PF 1.09) with the only negative 60s entry
markouts (mean −6.6c, n=21 — indicative, not proven).

**Tail concentration**: top-5 losses = $4.10 = 7.4% of $55.12 total losses;
top-10 = 14.5%. All 10 largest losses are ~1-contract episodes with **zero
exit fills** that settled against the position. Max residual capital at risk:
$141.20.

**Taker vs maker entries**: taker-entry net −$10.55 (PF .520) vs maker-entry
+$0.82 (PF 1.03) — paying the spread on entry roughly doubles the losing tail.

## 4. The exit veto chain (as audited; several links now repaired)

For a **discretionary** exit (`stop_loss`, `value_switch_exit`) the candidate
must survive, in order:

1. `stop_candidate.py:1394` — `discretionary_trigger_observe_only` if the EV
   gate is off (off Sep 21–23; **on** since 09-23).
2. `loop_15m.py:2923` — `discretionary_exit_observe_only` reject when gate
   off; `ev_gate_<decision>` reject unless `SELL_SIGNALLED`.
3. `settlement_aligned_exit.py` evaluator — blocks on missing provenance,
   stale/incoherent book, RTI ineligible, **`uncalibrated_model_inputs`
   (`vol_source=none` — dominant)**, `insufficient_bid_depth`, near-expiry
   (<60s), `min_consecutive=3` breaches.
4. ~~`position_monitor._loss_exit_ev_justified` EV-vetoing OPERATIONAL
   reasons (`edge_decay`/`time_exit`/`model_invalidation`) via a private
   reason list + hardcoded `canonical_reason="value_switch_exit"`~~ —
   **fixed**: the monitor now consults the shared taxonomy
   (`classify_exit_reason`/`classify_trigger_reason`), passes the candidate's
   real canonical reason, treats `BYPASS_OPERATIONAL`/`BYPASS_EMERGENCY` as
   allowed, fails closed on UNKNOWN, and applies a degraded-inputs deadline
   (`MERID_EXIT_DEGRADED_DEADLINE_S`, default 300s) so a discretionary hold
   caused *only* by missing model inputs cannot erase a risk deadline.
   `HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED` remains an honored terminal.
5. Router/dispatch layer — **`duplicate:concurrent_in_flight` no longer
   regresses a healthy attempt to SUBMISSION_UNKNOWN**; exceptions between
   obligation creation and dispatch record a real stall reason instead of
   wedging at INTENT_PERSISTED.
6. ~~`stop_candidate` fractional rejection~~ — fixed.
7. `limit_not_executable` rejections on urgent exits (price selection
   needs route-specific handling — see §6).

## 5. Defects fixed in this release (exit-reliability + accounting repair)

| Area | Defect | Fix | Tests |
|---|---|---|---|
| Canonical accounting | Raw `get_fills()` fed synthetic/superseded rows to P&L, position cross-checks, and risk consumers | `get_canonical_fills()` authoritative/quarantined view; `kill_switches`, `sentiment_risk`, `position_cache` migrated; entry gate blocks on stale unresolved fills | `test_canonical_fills_view.py` 8/8 |
| Fractional quantity | `qty_cc % 100` rejections; `int(Decimal)` flooring in router fill accounting; `contracts` payload fields zeroed sub-contract fills; paper partial fills drew whole contracts | centi-contract precision end-to-end | `test_fractional_*.py` + `test_stop_candidate_degraded_exit.py` 36+19 |
| Exit-policy authority | Monitor EV-vetoed OPERATIONAL exits via private reason list + forced `value_switch_exit` | Shared taxonomy is sole classifier; real reason passed; BYPASS honored; degraded deadline added; near-settlement terminal respected | `test_exit_policy_shared_taxonomy.py` 25/25 |
| Durable obligation | 391 INTENT_PERSISTED stalls (388 legacy-migrated + 3 dispatch); `duplicate` mislabeled SUBMISSION_UNKNOWN; exceptions pre-dispatch silently stalled; RESTING remainder re-armed into a duplicate order | `INTENT_PERSISTED→TERMINAL_UNFILLED` edge + stall-reason sweep (`unsubmitted_age_limit:{worker_not_dispatched,migrated_legacy,obligation_orphaned_position_gone}`); duplicate keeps in-flight untouched; dispatch exceptions record `submit_dispatch_error`; RESTING orders keep remainder ownership; reconcile restores live orders to SUBMITTED | `test_exit_obligation_lifecycle.py` 13/13 |
| Fill schema | `post_position_fp` not captured | captured + quarantined on mismatch | covered by canonical-view suite |

## 6. Remaining open items

1. **`vol_source` provenance**: the EWMA realized-vol tracker →
   `annualized_vol_source` chain exists (`realized_vol.py`,
   `_resolve_annualized_vol`, `agent_grid_15m` publishes to
   `market_state`), but evals still show `vol_source=none` — verify the
   state object the evaluator reads carries the published field at eval
   time. The degraded deadline now bounds the damage; do **not** fabricate
   a vol constant.
2. **Partial liquidation at the evaluator**: `require_sufficient_bid_depth`
   still demands full-position depth at top bid — a `min(qty, depth)`
   partial-exit path is needed. The submit path itself now handles partial
   fills exactly (RESTING remainder ownership fixed).
3. **116 `resid_no_attempt` episodes** — monitor coverage gap: positions
   that never produced even an obligation. Needs position-detection audit
   (the obligation layer cannot help positions it never sees).
4. **TP overpay floor**: `bid < fair + exit_cost` vetoes profitable TP —
   the "sufficient net profit" vs "sell-vs-hold" vs "mandatory close"
   distinction is defined but the TP floor still conflates them.
5. **Urgent-exit price selection**: `limit_not_executable` on urgent closes
   needs route-specific semantics (marketable IOC + remainder management)
   vs resting-profit-target semantics.
6. **`min_consecutive=3`** persistence on a 15-min instrument — review once
   exits actually submit.

## 7. Replay status / honest limits

- The counterfactual first-bid replay (§1) is **diagnostic only** —
  top-of-book fillability assumed, no depth/queue model.
- Full chronological multi-policy replay still requires quote-depth history;
  `visible_bid_depth` on eval rows is the only sparse source.
- The 10-01+ window is no longer an untouched holdout — it was inspected and
  influenced these fixes. Use it as a **historical regression** period;
  reserve post-fix data for prospective validation.

## 8. Recommended order (reconciled to the repair plan)

1. ~~Canonical venue accounting everywhere~~ **done** (§5).
2. ~~Fractional preservation~~ **done**.
3. ~~Single exit-policy authority + degraded deadline~~ **done**.
4. ~~Durable obligation lifecycle / stall reasons~~ **done**.
5. Position-detection audit for `resid_no_attempt` (§6.3).
6. Partial-liquidation sizing at the evaluator (§6.2).
7. Re-measure on post-fix data; **only then** revisit sizing (3-contract
   max is a cap, not a target), TP sizing, thresholds, or frequency.
