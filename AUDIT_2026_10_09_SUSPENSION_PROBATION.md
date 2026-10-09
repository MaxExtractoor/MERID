# Suspension / Probation Frontier — BTC · ETH · SOL · XRP · DOGE

**Date:** 2026-10-09 · **Scope:** 15-minute production surface, all five assets,
YES/NO sides, maker/taker routes, both lane authorities (current-build
provisional + threshold-cell) plus the directional throttle.
**Companion:** `AUDIT_2026_10_09_EVIDENCE_POLICY.md` (verdicts, n_eff formula,
missing-artifact policy).

Live state measured from `data/current_build_provisional_lane.json`,
`data/threshold_cell_lane.json`, `data/directional_throttle.json` and the
post-restart verdict stream in `logs/rejected_candidates.jsonl`.

---

## 1. Headline findings

| Metric | Value |
|---|---|
| cbp cells tracked | 40 |
| cbp cells SUSPENDED | **31** (77.5%) |
| cbp cells OBSERVATION | 9 (admit normally) |
| threshold cells tracked | 6 — 5 SUSPENDED, 1 PROBATION |
| throttle suspensions live | 1 (`eth:yes`, ~0.5h TTL at measure time) |
| Suspensions that are **execution-class** | **20 of 31** cbp + 4 of 5 tc |
| Suspensions that are **economic-class** | 11 cbp + 0 tc |
| Integrity suspensions | 0 live (none recorded) |
| Otherwise-qualified evals blocked post-restart | ~453 across both lanes |

**The dominant restriction cause is not losing trades.** 13 of 31 cbp
suspensions are `consecutive_router_rejects=2 (post-only cross/stale
revalidation)` — a router-mechanics defect, not realized P&L. Every one of
them predates the router repair. Under the pre-fix code they were permanent
and indistinguishable from economic failure; under the repaired code they
classify `execution`, release to PROBATION after 6 h, and probe at 1
submission/day under a positive-EV gate.

## 2. What was repaired before this report (all committed)

| Defect | Fix |
|---|---|
| No recovery path — 31/40 cells permanently off | `maybe_recover_cell` lazy release → PROBATION → OBSERVATION, class-gated timing |
| Router rejects conflated with losses | `_classify_suspension_reason` stamps `suspension_class` on every record; rejects never write outcome/loss rows |
| `_suspend_cell(cell_id=…)` arg-order bug at 9 call sites | Fixed — reason and class now land in correct fields |
| Armed `router_consecutive_rejects` counter surviving release → instant re-suspension | Counter zeroed in `maybe_recover_cell` |
| `post_only_order_became_taker` classified `integrity` (never recovers) | Reclassified `execution` — mechanical route breach, probe-verified recovery |
| Probation strikes missing in cbp lane | One-strike re-suspend + `probation_triggered` cooldown (6h exec / 24h econ) |
| Stale `on_probation` flag on re-suspension | Cleared on strike |
| Missing evidence artifact → silent production admit | Fail-closed synthetic decisions + stale artifacts forced escape-only |
| `n_eff ≥ 50` toxic-cell block unreachable | Severity-compensated mid tier added (see §7) |

Recovery knobs (env-tunable): exec suspend ≥6h → econ ≥24h → PROBATION;
probation = 1 submission/day/cell, candidate must clear `max(0, bound)`
conservative EV; 2 clean observations → OBSERVATION; 1 strike → re-suspend
with cooldown. Integrity = manual reset only.

## 3. Full cell inventory

### 3a. Current-build provisional lane (40 cells)

Class = repaired classifier applied to recorded reason. Age = hours since
suspension at measure time. QBLK = otherwise-qualified evals blocked
post-restart (price-derived, ~half of evals; see §6 caveat).

**BTC** (bound +2.0¢ NO / +2.5¢ YES):

| Cell | State | Class | Trigger | Age h | QBLK |
|---|---|---|---|---|---|
| no_40_50_t300_600 | SUSPENDED | econ | first_trade_pnl −42.0¢ | 194 | 10 |
| no_50_60_t300_600 | SUSPENDED | exec | router_rejects×2 | 4 | 0 |
| no_60_70_t120_300 | SUSPENDED | exec | router_rejects×2 | 78 | 3 |
| no_60_70_t300_600 | SUSPENDED | econ | roll3 mean pnl −30.3¢ | 55 | 0 |
| no_70_80_t120_300 | SUSPENDED | econ | roll3 mean pnl −5.3¢ | 4 | 0 |
| no_70_80_t300_600 | SUSPENDED | exec | router_rejects×2 | 100 | 6 |
| **no_80_90_t120_300** | **OBSERVATION** | — | first_fill (fresh) | — | 26* |
| **no_80_90_t300_600** | **OBSERVATION** | — | first_fill (fresh) | — | 0 |
| yes_70_80_t300_600 | SUSPENDED | exec | router_rejects×2 | 51 | 0 |
| yes_80_90_t300_600 | SUSPENDED | exec | router_rejects×2 | 51 | 0 |

**ETH** (+2.0¢ NO / −4.0¢ YES floor):

| Cell | State | Class | Trigger | Age h | QBLK |
|---|---|---|---|---|---|
| no_20_30_t300_600 | SUSPENDED | exec | router_rejects×2 | 146 | 24 |
| no_50_60_t300_600 | SUSPENDED | exec | router_rejects×2 | 56 | 0 |
| no_60_70_t300_600 | SUSPENDED | econ | first_trade_pnl −58.0¢ | 172 | 0 |
| no_70_80_t120_300 | OBSERVATION | — | first_fill | — | 0 |
| no_70_80_t300_600 | SUSPENDED | exec | router_rejects×2 | 27 | 0 |
| no_80_90_t120_300 | SUSPENDED | exec | first_fill_markout −25.5¢ | 102 | 0 |
| no_80_90_t300_600 | OBSERVATION | — | first_fill | — | 0 |
| yes_20_30_t300_600 | SUSPENDED | econ | first_trade_pnl −25.0¢ | 122 | 6 |
| yes_30_40_t300_600 | OBSERVATION | — | first_fill | — | 9* |
| yes_40_50_t300_600 | OBSERVATION | — | first_fill | — | 33* |
| yes_60_70_t300_600 | SUSPENDED | exec | first_fill_markout −6.5¢ | 6 | **92** |
| yes_70_80_t300_600 | SUSPENDED | econ | first_trade_pnl −69.0¢ | 167 | 57 |
| yes_80_90_t300_600 | OBSERVATION | — | first_fill | — | 49* |

**SOL** (+2.5¢ NO / −4.0¢ YES):

| Cell | State | Class | Trigger | Age h | QBLK |
|---|---|---|---|---|---|
| no_20_30_t300_600 | SUSPENDED | exec | first_fill_markout −4.5¢ | 18 | 2 |
| no_80_90_t120_300 | SUSPENDED | exec | router_rejects×2 | 36 | 0 |
| no_80_90_t300_600 | SUSPENDED | econ | first_trade_pnl −81.0¢ | 57 | 0 |
| yes_20_30_t300_600 | SUSPENDED | econ | first_trade_pnl −27.0¢ | 55 | 38 |
| yes_30_40_t120_300 | SUSPENDED | econ | first_trade_pnl −31.0¢ | 165 | 9 |
| yes_30_40_t300_600 | SUSPENDED | exec | first_fill_markout −7.5¢ | 150 | 0 |

**XRP** (+2.5¢ NO / −4.0¢ YES):

| Cell | State | Class | Trigger | Age h | QBLK |
|---|---|---|---|---|---|
| no_50_60_t300_600 | SUSPENDED | econ | roll3 mean pnl −18.7¢ | 56 | 9 |
| **no_60_70_t120_300** | SUSPENDED | exec | router_rejects×2 | 58 | 0 |
| **no_60_70_t300_600** | SUSPENDED | econ | first_trade_pnl −54.0¢ | 194 | 6 |
| no_70_80_t300_600 | SUSPENDED | exec | roll3 neg markouts 2/3 | 77 | 0 |
| yes_70_80_t300_600 | SUSPENDED | exec | first_fill_markout −5.5¢ | 52 | 40 |
| yes_80_90_t120_300 | OBSERVATION | — | first_fill | — | 0 |
| yes_80_90_t300_600 | SUSPENDED | exec | router_rejects×2 | 162 | 44 |

**DOGE** (+2.5¢ NO):

| Cell | State | Class | Trigger | Age h | QBLK |
|---|---|---|---|---|---|
| no_50_60_t300_600 | SUSPENDED | exec | roll3 median markout −6.5¢ | 35 | 3 |
| no_60_70_t120_300 | SUSPENDED | exec | router_rejects×2 | 57 | 0 |
| no_60_70_t300_600 | SUSPENDED | exec | router_rejects×2 | 182 | 0 |

### 3b. Threshold-cell lane (6 cells — measurement lane, own caps)

| Cell | State | Class | Trigger | Age h | QBLK |
|---|---|---|---|---|---|
| doge_no_70_90_t120_600 | SUSPENDED | exec | router_reject_rate 50% (6 att) | 57 | 0 |
| eth_no_50_60_t120_300 | SUSPENDED | exec | router_rejects×2 | 76 | 3 |
| eth_no_60_70_t120_300 | SUSPENDED | exec | router_rejects×2 | 75 | 0 |
| sol_no_30_60_t120_600 | SUSPENDED | exec | first_fill_markout −26.5¢ (probation strike, ct=1) | 81 | 19 |
| sol_no_60_80_t120_600 | SUSPENDED | exec | probation strike: router_reject | 6 | 7 |
| xrp_no_80_90_t120_600 | **PROBATION** | exec | canary_release (post-only verified) | 82 | 0 |

### 3c. Directional throttle (side-scoped, TTL)

| Key | Status | Trigger | Remaining |
|---|---|---|---|
| eth:yes suspension | ACTIVE→expired | catastrophic: cbp_eth_yes_60_70 markout | ~0.5h at measure |
| eth:no, xrp:yes | expired records | 2-consecutive-losses / catastrophic | do not block |
| cautions (btc:yes, eth:yes, sol:yes, yes) | expired | post-release loss | margin-only anyway |

## 4. Per-asset frontier

### BTC — frontier

| Cohort | State | Original cause | Relevance | Blocked | Decision | Evidence required |
|---|---|---|---|---|---|---|
| NO 40–50 (late) | SUSP | econ: first fill −42¢ | **Relevant** — real loss | 10 | **Retain** econ class; probe at +2¢ after 24h | 2 clean probe outcomes |
| NO 50–60 (late) | SUSP | exec: router mechanics | **Stale** — predates repair | 0 | **Reactivate** via probation at next candidate | post-only probe fill |
| NO 60–70 (both TTE) | SUSP | exec + econ | Mixed | 3 | **Probe** t120_300 (exec); retain t300_600 econ watch | probe outcomes |
| NO 70–80 (both) | SUSP | exec + econ | Mixed | 6 | same split | same |
| **NO 80–90 (both)** | **OBS** | none — fresh cells | Current | 26* | **Probe** — Experiment B (cap exception env-gated) | fresh cons-EV ≥ +2.0¢ at live ask |
| YES 70–80 / 80–90 (late) | SUSP | exec: router mechanics | Stale | 0 | Reactivate via probation | probe fills |

### ETH — frontier (largest blocked volume)

| Cohort | State | Cause | Relevance | Blocked | Decision | Evidence |
|---|---|---|---|---|---|---|
| NO 20–30 | SUSP | exec | Stale | 24 | Reactivate via probation | probe fills |
| NO 50–60, 60–70 | SUSP | exec + econ(−58¢) | −58¢ loss relevant | 0 | Probe t300 exec; retain econ | probe outcomes |
| NO 70–80 | OBS/SUSP | exec t300 | Stale | 0 | Probe | probe fills |
| NO 80–90 | OBS + SUSP | exec markout −25.5¢ | Borderline | 0 | Probe t120; retain watch | probe outcomes |
| YES 20–30 | SUSP | econ −25¢ | Relevant | 6 | Retain; floor-lane only | fresh outcomes |
| YES 30–50 | OBS | none | Current | 42* | Active — monitor | — |
| YES 60–70 | SUSP | exec markout −6.5¢ | **92 blocked — highest** | 92 | **Probe** (exec class; throttle now expired) | 2 clean probes |
| YES 70–80 | SUSP | econ −69¢ | Relevant | 57 | Retain econ | fresh outcomes |
| YES 80–90 | OBS | none | Current | 49* | Active — monitor | — |

### SOL — frontier

| Cohort | State | Cause | Relevance | Blocked | Decision | Evidence |
|---|---|---|---|---|---|---|
| NO 20–30 | SUSP | exec markout | Borderline | 2 | Probe | probe outcomes |
| NO 30–60 / 60–80 (tc lane) | SUSP | exec markout −26.5¢ / probation strike | Relevant — markout severe | 19+7 | Shadow until tc probes pass | clean probe outcomes |
| NO 80–90 | SUSP | exec + econ −81¢ | −81¢ relevant | 0 | Retain econ t300; probe t120 | fresh outcomes |
| YES 20–30 | SUSP | econ −27¢ | Relevant | 38 | Retain; floor-lane | fresh outcomes |
| YES 30–40 | SUSP | econ −31¢ + markout | Relevant | 9 | Retain econ | fresh outcomes |

### XRP — frontier

| Cohort | State | Cause | Relevance | Blocked | Decision | Evidence |
|---|---|---|---|---|---|---|
| NO 50–60 | SUSP | econ roll3 −18.7¢ | Relevant | 9 | Retain econ | fresh outcomes |
| **NO 60–70** | SUSP | **exec** t120_300 + econ t300_600 (−54¢) | Mixed | 6 | **Probe t120_300 — Experiment A**; retain t300 econ | fresh cons-EV ≥ +2.0¢, probe outcomes |
| NO 70–80 | SUSP | exec markouts | Borderline | 0 | Probe | probe outcomes |
| YES 70–80 | SUSP | exec markout −5.5¢ | Borderline | 40 | Probe (exec class) | probe outcomes |
| YES 80–90 | OBS + SUSP | exec t300 | Mixed | 44 | Probe | probe outcomes |
| YES floor (−4¢) | active policy | — | Working as designed | — | **Retain unchanged** | — |

### DOGE — frontier (sparsest evidence)

| Cohort | State | Cause | Relevance | Blocked | Decision | Evidence |
|---|---|---|---|---|---|---|
| NO 50–60 | SUSP | exec median markout −6.5¢ | Borderline | 3 | Probe | probe outcomes |
| NO 60–70 | SUSP | exec router×2 | Stale | 0 | Reactivate via probation | probe fills |
| NO 70–90 (tc) | SUSP | exec reject-rate 50% (n=6) | Thin sample | 0 | **Probe** — n=6 is not statistical proof | more attempts |

DOGE note: with ~15 markets/48h, probation completion (2 clean obs) is
reachable but slow — no fill requirement blocks it, which is correct.

## 5. Deadlock audit (directive §4)

| Deadlock | Status |
|---|---|
| Probation needs fills but blocks submissions | **Fixed** — PROBATION admits 1/day at positive EV |
| Recovery needs 50 obs, unreachable | **Fixed** — release is time+class gated; probe outcomes counted, not n_eff |
| Each rejected eval restarts timer | **OK** — `since_ts` fixed at transition; evals don't reset |
| New market inherits old order lock | OK — cell-keyed; `decision_cell_map` is per-decision |
| No opportunities → reads as failed probation | **OK** — no fail timer; cell stays PROBATION until clean obs or strike |
| Repaired exec path needs profit to clear | **Fixed** — exec release is 6h+time; only *submission* needs +EV |

## 6. Blocked-opportunity accounting — caveat

`executable_price_cents` records only the *selected* side's ask; the other
side's price is derived as `100 − ask` (~half of evals). 5,447/8,300 evals
didn't match a cell domain. `QBLK` = evals reaching econPASS/explAUTH inside
the cell domain that were not submitted — conservative for OBS cells (they
may fail downstream caps). Frontier sizes are directional, not exact counts.

## 7. n_eff reachability — final answer

Formula (from artifact builder): per market, rows are decay-weighted
(`exp(−ln2·age/H)`), normalized so the market contributes its newest row's
decay weight. `n_eff` = Σ over distinct markets of that weight — **a
market-normalized decay-weighted market count, not Kish ESS**.

Measured ceiling (48h artifact, 171 markets, 45 populated cells):

| Halflife | Max cell n_eff | Cells ≥8 | Cells ≥50 | Σ n_eff |
|---|---|---|---|---|
| 7d | 12.67 | 3 | **0** | ~120 |
| 21d | 13.26 | 3 | **0** | ~127 |

Aggregate per asset/side also <50 (max ~23.5). **n_eff ≥ 50 is structurally
unreachable in the current window** — the level was a policy reserve, not a
live evidence level. Fix applied per spec: a severity-compensated mid tier —
hard-block now reachable at `n_eff ≥ 8` *only* when demonstrated LCB-EV ≤
−10¢ (vs −5¢ at the unreachable tier), while the n_eff≥50 tier remains as
the full-toxicity standard. Immediate severe-loss tripwires already live in
the per-cell suspension triggers; insufficient-evidence controls size via
the bounded lanes rather than pretending to prove safety.

## 8. Experiment configurations (ready, not promoted)

**Experiment A — XRP NO 60–69¢** (evidence restriction bypass):
Bypass `SOFT_PENALTY_INSUFFICIENT` only for `cbp_xrp_no_60_70_t120_300`.
Delivered by the repair itself: the cell's suspension is execution-class
(router rejects), 58h ≫ 6h window → first qualified candidate (cons-EV ≥
+2.5¢ at live ask) releases it to PROBATION — 1 submission/day, one strike
re-suspends. The t300_600 sibling stays suspended (economic class, −54¢
first trade) — the experiment does not touch it. `AUTHORIZED:current_build_
provisional` verdicts remain exploration authorization.

**Experiment B — BTC NO 80–89¢** (cap exception):
`MERID_PRICE_CAP_EXCEPT_BTC_NO=1` (default 0) lifts `entry_price_cap_block`
per-candidate only when: asset=BTC, side=NO, 75 < ask ≤ 89.99, cons-EV ≥
+2.0¢ at the fresh executable price, no side-throttle block. Cells are
OBSERVATION and admit normally — the cap was the binding gate (26
otherwise-qualified evals in t120_300 post-restart). Downstream cbp caps,
post-only routing, and lane state checks unchanged. Per-candidate: no band
promotion.

## 9. Regression coverage (18/18 passing)

`tests/test_suspension_recovery.py` — exec/econ/integrity release timing,
probation completion, strike re-suspension, restart state preservation,
lane-authority separation, reject≠loss bookkeeping, missing-artifact
fail-closed, stale→escape-only, duplicate-settlement idempotency.

## 10. Recommendations

- **Reactivate via probation:** all 13 router-reject cbp cells + 2 tc
  router cells (stale, repaired cause).
- **Probe:** markout-suspended cells (exec class) — notably ETH YES 60–70
  (92 blocked), XRP YES 70–80 (40), SOL NO 30–60 tc (19).
- **Retain (economic):** 11 first-trade/rolling-PnL cells — real losses,
  keep 24h class recovery; biggest: SOL NO 80–90 (−81¢), ETH YES 70–80
  (−69¢), XRP NO 60–70 t300_600 (−54¢), ETH NO 60–70 (−58¢).
- **Defer:** n_eff≥50 tier stays as reserve; revisit threshold only with a
  longer evidence window, not a lower bar.
- **Keep:** XRP YES −4¢ floor unchanged; directional-throttle semantics
  (TTL, asset-scope, margin cautions) already correct.
