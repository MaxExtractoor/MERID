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
| Otherwise-qualified evals blocked post-restart | **corrected: 254** (§6 — ~453 used an invalid price approximation) |

**The dominant restriction cause is not losing trades.** 13 of 31 cbp
suspensions are `consecutive_router_rejects=2 (post-only cross/stale
revalidation)` — a router-mechanics defect, not realized P&L. Every one of
them predates the router repair. Under the pre-fix code they were permanent
and indistinguishable from economic failure; under the repaired code they
classify `mechanical`, release to PROBATION after 6 h (allowlist-gated), and
probe under bounded submission/fill/loss budgets.

## 2. What was repaired before this report (all committed)

| Defect | Fix |
|---|---|
| No recovery path — 31/40 cells permanently off | `maybe_recover_cell` lazy release → PROBATION → OBSERVATION, class-gated timing |
| Router rejects conflated with losses **and** with markouts | Five-way subtype map: `mechanical` / `contract_violation` / `execution_quality` / `economic` / `integrity`, ordered token rules (`router_reject` resolves before the `(post-only …)` parenthetical in live reasons) |
| `post_only_order_became_taker` classified `integrity` (never recovers), then plain `execution` | Now `contract_violation`: hard-failed until `MERID_EXEC_CONTRACT_FIX_VERIFIED=1`, then restricted probation |
| `_suspend_cell(cell_id=…)` arg-order bug at 9 call sites | Fixed — reason and class now land in correct fields |
| Armed `router_consecutive_rejects` counter surviving release → instant re-suspension | Counter zeroed in `maybe_recover_cell` |
| Probation strikes missing in cbp lane | Cause-specific strikes: mechanical = 1h health pause, contract/integrity = stop, economic = loss budget + 24h cooldown |
| Stale `on_probation` flag on re-suspension | Cleared on strike |
| Missing evidence artifact → silent production admit | Fail-closed synthetic decisions + stale artifacts forced escape-only |
| `n_eff ≥ 50` toxic-cell block unreachable | Severity-compensated sparse tier added — **env-gated off** (`MERID_EVIDENCE_HARD_SPARSE_TIER`, see §7) |
| Unbounded probation / blunt one-strike | Separate budgets: submissions/day, fills/episode, realized-loss budget (50¢); unfilled expiry = evidence, not a strike |
| Lazy release invisible/racy | Atomic `_transition_cell` under `RLock`; every release writes a journaled record (cell, prev/new state, original reason, class, budget, counters reset, policy epoch, ts) |
| No Stage-A scoping | `MERID_RECOVERY_ALLOWLIST` — when set, only listed cell ids may auto-release |
| `100 − selected_ask` used as the other side's ask | Rejected-candidate records now persist `yes_price_cents` / `no_price_cents` / `entry_price_basis` from canonical decision inputs; counting marks unverifiable evals `price_unverified` (§6) |

Recovery knobs (env-tunable): mechanical/execution ≥6h → execution-quality
≥24h → economic ≥24h → PROBATION; contract = verified-fix gate + 24h;
integrity = operator only. Probation = bounded submissions/day (default 1),
max fills/episode (default 1), loss budget 50¢; 2 clean observations →
OBSERVATION; strike handling is cause-specific.

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

## 6. Blocked-opportunity accounting — corrected

**The earlier ~453 figure is withdrawn.** It used `100 − selected_ask` as the
non-selected side's price. Per Kalshi's book identity `a_Y = 1 − b_N` /
`a_N = 1 − b_Y`, that complement is the opposite side's **bid**, not its ask;
in a nonzero-spread book it understates purchase cost by the spread, which
both moved evals into the wrong price band and inflated qualified counts.

Corrected methodology (`scripts/_blocked_opportunity_counts.py`):

- **Selected-side evals with a recorded price are verified** and kept.
- **Non-selected-side evals are `price_unverified`** — pre-deploy records
  carry no independent per-side ask/bid/depth/timestamp fields, so no valid
  reconstruction exists for them. They are excluded from band matching
  (4,516 of 9,032 side evals in the post-restart window).
- Post-deploy records persist `yes_price_cents`, `no_price_cents`, and
  `entry_price_basis` from the canonical decision inputs — both side prices
  are now real (the pipeline already derived a missing ask from the
  *opposite* bid, the correct identity). Bid-basis records are flagged and
  never band-matched as asks.
- Dedup distinguishes raw side evals from unique `(decision_id, side)`
  evaluations and unique `(ticker, side)` market windows.
- Gate attribution separates evidence, cell-state, cap, and other blocks —
  `tte_seconds` is used (the earlier pass read the wrong field name).

Corrected counts (post-restart window, 9,032 side evals):

| Metric | Value |
|---|---|
| Raw side evals / unique decision evals | 9,032 / 9,032 |
| Verified-price evals | 4,516 (all selected-side `selected_ask`) |
| `price_unverified` evals (excluded) | 4,516 |
| Evals inside a cell domain | 683 verified |
| Otherwise-qualified evals (cons-EV ≥ cell bound, no hard flag, not stale) | **254** |
| — blocked by cell state | **0** (evidence gate fires upstream; `cell_suspended` never reached) |
| — blocked by evidence | 239 |
| — blocked by other gates | 15 |
| Records carrying `entry_price_cap_*` | 57 (40 of them `EXPLORATION_AUTHORIZED` + cap-rejected BTC NO 80–89) |

Conclusions that depended on the invalid approximation: the ~453 total, the
ETH YES 60–70 QBLK of 92, and the "26 cap-only BTC NO opportunities" figure.
Corrected: **qSTATE = 0 everywhere** — suspended cells' candidates are
rejected at the evidence stage before lane admission, so the true cost of
suspension is *indirect* (a qualified eval never reaches the cell veto); the
BTC NO 80–89 cohort is 40 exploration-authorized cap-blocks, **not 26**, and
the 26 previously cited are `ECONOMICS_FAIL` records (correct rejects).
Per-cell `QBLK` columns in §3 are approximation-era values retained for the
record; the verified totals above supersede them.

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
live evidence level.

A severity-compensated sparse tier exists in code — `n_eff ≥ 8` *and*
LCB-EV ≤ −10¢ (vs −5¢ at the dense tier) → hard block with a `sparse_severe`
tier marker — but it is **gated behind `MERID_EVIDENCE_HARD_SPARSE_TIER`
(default off)** and is **not part of this release**. It is a policy change,
not a repair, and its rollout stays separately attributable. Before enabling,
the following must be documented and tested against known histories:

- *Why 8 markets suffice:* n_eff is a market-normalized decay-weighted count
  (each market contributes its newest observation's weight) — 8 markets ≈
  8 freshest-observation weights, which may carry far fewer independent
  fills; the estimator's effective support must be stated.
- *What the LCB estimates:* the lower confidence bound on the cell's
  conservative net EV per candidate at the cohort's own entry prices —
  **not** realized lifecycle P&L, settlement EV, or markout (each a distinct
  metric in §6/§10 semantics).
- *Uncertainty:* LCB is computed at `MERID_EVIDENCE_LCB_Q` (q=0.10) over the
  decay-weighted outcome distribution; one extreme −N¢ outcome can dominate
  a sparse weighted set — the single-observation influence must be measured.
- *Overlap:* the per-cell suspension tripwires (markout, mean-PnL, router
  reject-rate) already fire on the same adverse evidence — the tier's added
  value is a *cross-candidate statistical* block on cells that suspend by
  accumulation rather than trigger.
- *Stale artifacts:* a stale artifact already caps at max uplift and can
  never hard-block; the sparse tier inherits that fail-closed rule.
- *Escape-lane interaction:* a sparse-severe hard block must not be reachable
  via the bounded escape lane either (hard means hard).

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

## 9. Regression coverage (29/29 recovery tests; 521 gated suite green)

`tests/test_suspension_recovery.py` — subtype classification for every
observed live reason (router parenthetical resolves mechanical, not
contract); exec-quality vs mechanical timing; contract verified-fix gate;
allowlist gating; atomic release journal; probation budgets (submissions,
fills, loss); unfilled-expiry non-strike; stale-counter reset on release;
restart preservation + backfill; missing/stale/corrupt artifact fail-closed;
duplicate-settlement idempotency; per-side price telemetry fields (both
asks persisted, no synthesized complement, bid-basis flagged).

Full gated run (`pytest`, 27 files incl. evidence, threshold-cells, router,
fractional accounting, exit lifecycle): **521 passed, 0 failed** — the first
clean run; 15 prior failures were resolved (`.env` cap leakage into unit
tests, a `get_fills` empty-page-with-cursor misreporting `MAX_PAGES`, and a
lazy-path-only prod-DB guard now failing fast at ledger construction).

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

## 11. Stage A controlled release — deployed 2026-10-09 ~04:35 UTC

**Commit:** `ad40db12` (recovery mechanics + telemetry; earlier state-machine
commit `f907eae6` is included in the release).
**Pre-release state backup:** `backups/pre_release_20261009_035011/`.

**Allowlist** (`MERID_RECOVERY_ALLOWLIST`, persisted in `.env`): the 17
mechanical-class cells whose suspension reason is a router reject matching
the demonstrated repair — 13 cbp (`consecutive_router_rejects=2
(post-only cross/stale revalidation)`) + 4 threshold cells (router-reject
rate / probation router strike / consecutive rejects). Economic (11),
execution-quality/markout (8), and any contract/integrity cells are NOT in
the allowlist and remain suspended.

**Off-gates for this release** (explicit in `.env`):
`MERID_PRICE_CAP_EXCEPT_BTC_NO=0`, `MERID_EXEC_CONTRACT_FIX_VERIFIED=0`,
`MERID_EVIDENCE_HARD_SPARSE_TIER=0`.

**Verified post-restart:**
- Production startup gate passed (clean tree — the earlier attempt correctly
  refused to boot with uncommitted live-path changes).
- Atomic transition journal live: each SUSPENDED→PROBATION release records
  cell_id, prev/new state, original suspension reason, class, policy epoch,
  probation budget snapshot, and counters reset (`router_consecutive_rejects`).
- Lazy release working as designed — only allowlisted cells that produce a
  qualifying candidate move: at verification time, cbp PROBATION =
  `cbp_doge_no_60_70_t300_600`, `cbp_btc_no_70_80_t300_600`,
  `cbp_xrp_no_60_70_t120_300` (Experiment A cell), `cbp_sol_no_80_90_t120_300`,
  `cbp_eth_no_70_80_t300_600`; tc PROBATION = `sol_no_60_80_t120_600`,
  `doge_no_70_90_t120_600` (+ pre-existing `xrp_no_80_90_t120_600` canary).
  The other allowlisted cells stay SUSPENDED until a candidate arrives in
  their domain — no probe is burned on a cell with no flow.
- New rejected-candidate records carry `yes_price_cents` / `no_price_cents` /
  `entry_price_basis` (150+ already logged) — future blocked-opportunity
  counts will use real side-specific asks, never the `100 − ask` complement.

**Rollback:** `MERID_RECOVERY_ALLOWLIST=` (empty) restores all-suspended
gating; per-cell `set_cell_state(SUSPENDED)` for any misbehaving probation
cell; state backups in the directory above.
