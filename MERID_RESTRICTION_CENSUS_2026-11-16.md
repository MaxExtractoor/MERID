# MERID Restriction Census and Recoverable Opportunity Audit

**Date:** 2026-11-16
**Scope:** Gate registry, decision funnel, blocked-bucket scorecard, stale-restriction hunt, RTI gap root-cause, prioritized reopen queue.
**Method:** Offline analysis of `data/*.db`, `.env*`, `merid/prediction/*`, `AGENTS.md`, plus the prior PCA scan (`MERID_PCA_SYSTEM_SCAN_2026-11-15.md`). No live config, order, or exchange state was modified.

---

## 0. Interpretation corrections — verified against data, not assumed

The prior scan's figures are treated as reported results. Each critique below was checked against the repositories and databases before adoption.

### 0.1 "All asset betas ≈ −0.9" — sign is arbitrary, not directional exposure

**Verdict: critique is correct; the number was mislabeled.**

The PCA was run on the **correlation matrix of standardized 15m log returns**. PC1 loadings on a correlation PCA are all the same sign by construction (the eigenvector orientation is arbitrary — flipping all signs yields the identical solution). The "−0.9" figure came from regressing each asset's returns on the PC1 score; the sign depends entirely on which way the eigenvector was oriented. It is **not** evidence that the portfolio is short the market, and it says nothing about contract sensitivity or position exposure.

The four quantities the critique asks to separate are distinct and were conflated:

| Quantity | What it is | Where it lives |
|---|---|---|
| Market factor | Common linear variation in underlying crypto returns | RTI price PCA (PC1 ≈ 84% of variance) |
| Contract sensitivity | How a specific contract's value changes with that underlying move | Bachelier pricer / payoff mapping — **not computed here** |
| Position exposure | Contract sensitivity × signed position size | `kalshi_positions.db` + order side/action |
| Realized P&L attribution | What actually contributed to trading P&L | `trade_attribution_fact.db` settlements |

**Correction:** report PC1 as "one dominant common-return factor," not as a directional position. Any factor gate must be built on contract-aware exposure (sensitivity × signed size), which requires the payoff mapping — not on PCA loadings alone.

### 0.2 "62% NO-side" — real concentration signal, wrong directional label

**Verdict: partially correct; the concentration finding survives, the "bearish" label does not.**

- 62% of entries are NO-side, and in 479 multi-asset windows 65% took the **same side on every asset**. That is a genuine same-window correlated-exposure concentration signal regardless of direction semantics.
- But "NO-side" is not automatically "bearish exposure." Each Kalshi contract has its own proposition (e.g. "BTC above $X at expiry"). Buying NO on "BTC above" is a bet the proposition fails — directionally against an up-move *for that contract*, but the portfolio-level direction depends on the mix of propositions, strike distances, and existing inventory. The critique's point about `order_direction` (outcome side vs book side) is well taken: position sign must be derived from the contract definition, not inferred from the YES/NO label.

**Correction:** keep the same-window same-side concentration metric; drop the "negative-carry / bearish posture" framing until contract-aware signed exposure is computed.

### 0.3 Negative P&L is not yet a diagnosis of negative carry

**Verdict: correct; mechanism is undiagnosed.**

The −$843 (settlement-attributed, 125 days) is realized P&L. It does **not** establish negative carry. The attribution must separate:

1. Forecast error (model probability vs realized outcome)
2. Price paid relative to contemporaneous forecast
3. Spread and execution effects
4. Fees (Kalshi's parabolic taker fee, rounded up to $0.0001, with per-order accumulator — see `kalshi_fee_cents_exact` in `AGENTS.md` §6a)
5. Inventory exits and settlement timing
6. Accounting / timestamp errors

Fill-level fee data exists in `kalshi_fills.db` (`fee_cents`-family fields) but has not been decomposed against forecast error here. **No carry conclusion is warranted.**

### 0.4 "3,077 consecutive 15-minute returns" — grid integrity is broken

**Verdict: critique is correct; this is a real methodological flaw in the prior scan and must be disclosed.**

The RTI backfill coverage was ~29% of buckets, clustered in traded-hours windows. The prior scan computed returns over **consecutive retained observations**, not the intended 15-minute calendar grid. Where coverage gaps exist, a "15m return" may actually span multiple hours of stale/asynchronous prices. Per the critique's acceptance rule:

> Do not bridge missing intervals and label the resulting return as a 15-minute return. Preserve the intended time grid, actual elapsed time, coverage flags, and exclusion reasons.

**Impact on the PC1=84.2% figure:** correlations computed on a non-uniform, gap-bridged grid are likely **inflated** — stale prices repeat and induce spurious co-movement. The true contemporaneous correlation is probably lower. The 84.2% should be treated as an upper bound pending a strict-grid rerun.

**Required fix before any covariance feeds a gate:** rebuild returns on the strict 15m grid — keep only intervals where both endpoints have valid ticks within a freshness tolerance, record `elapsed_seconds` and `coverage_flag` per return, and exclude (not bridge) gaps. Rolling correlations must then be recomputed on that clean grid.

### 0.5 Tail-risk conclusion was too strong

**Verdict: correct.**

PC1 explaining 84% of *linear variance* does not imply all five assets crash together, does not quantify crash probabilities, and says nothing about tail dependence. PCA's objective is variance maximization, which is precisely why it is blind to joint tails. Any "all assets crash together" claim requires a separate extreme-value / tail-dependence analysis (e.g. tail copula, exceedance co-occurrence), not PCA.

---

## 1. Gate registry — effective restriction inventory

Sources: `.env` (current), `.env.bak_devin_20261014` (historical), `merid/prediction/directional_regime.py`, `merid/prediction/trade_decision.py`, `merid/prediction/threshold_cells.py`, `merid/config/live_config.py`, `AGENTS.md` §14, `data/deployment_state.json`, `data/threshold_cell_lane.json`, `data/directional_throttle_state.json`, `data/fade_gate_state.json`, `data/drift_lane_state.json`.

### 1.1 CONFIRMED CONFIG DRIFT — moneyness price caps (highest priority)

| Item | Documented/audited policy (`AGENTS.md` §14) | Effective `.env` (current) | Production evidence |
|---|---|---|---|
| Global NO cap | 50c | **89c** | `entry_price_cap_90c_gt_89c` enforced on XRP NO |
| Global YES cap | (unspecified in §14) | **89c** | same resolver |
| BTC-NO cap | 79c, 51–64c blocked | **89c, no blocked band** | — |
| ETH-NO cap | 89c, 51–64c blocked | **89c, no blocked band** | — |
| DOGE/SOL-NO cap | 75c | **89c** | — |
| XRP-NO cap | **1c (hard-blocked, audited −9.54 USD, "unpriceable down-moves")** | **89c** | XRP NO now trades to 89c |
| `MERID_MONEYNESS_BLOCKED_BAND_CENTS_*` (51–64c toxic pockets) | present in `.env.bak_devin_20261014` | **absent** | — |

**What happened:** the per-asset audited moneyness structure documented in `AGENTS.md` has been replaced by a flat 89c cap on both sides. The Nov-6 `MERID_PRICE_CAP_EXCEPT_*` probes were designed to let above-cap candidates through only at +2c EV — but with caps now at 89c, the probes' 75–89.99c window is almost entirely *under* the cap, so they are largely moot. `MERID_MONEYNESS_EV_RELIEF_ENABLED=1` (Nov-8) has a relief range of 10–89.99c — also now entirely under the cap, making the relief path effectively dead code for the normal path.

**This is not a subtle drift.** XRP-NO went from a hard block (cap=1c, on documented −9.54 USD audited losses) to an 89c cap. The 51–64c toxic pockets that were explicitly blocked are now open. Whether this was a deliberate operator decision after the Nov-6/8 probes, or accidental drift, **cannot be determined from the repo alone** — `.env` mtime is 2026-11-15 18:22 but the cap values may have been set earlier. **Requires operator confirmation.**

**Settled-P&L evidence on the reopened bands** (971 settlements joined to entry prices, full period Jun–Nov):

| Side | Price band | n | total P&L (c) | avg (c/trade) |
|---|---|---|---|---|
| NO | 20–29c | 21 | +95 | **+4.52** |
| NO | 30–39c | 85 | −1,925 | **−22.65** |
| NO | 40–49c | 82 | −2,349 | **−28.65** |
| NO | 50–59c | 69 | −519 | −7.52 |
| NO | 60–69c | 72 | +52 | **+0.72** |
| NO | 70–79c | 102 | −1,477 | **−14.48** |
| NO | 80–89c | 64 | −1,263 | **−19.73** |
| NO | 90–99c | 72 | +246 | **+3.42** |
| YES | 30–39c … 90–99c | ~360 | all negative | −3.05 to −16.89 |

The 80–89c NO band — newly opened by the cap raise — ran **−19.73c/trade**. Caveat: this cohort is dominated by pre-change lane/probe fills (pinned-fav 98c, settlement 99c, EV-relief), not necessarily normal-path post-change entries; the Nov-10→15 cohort is too sparse (48 settlements) to isolate the post-change normal-path performance, and **zero** NO 80–89c entries appear in that recent window.

### 1.2 Gate registry (non-moneyness)

| Gate / mechanism | Source | Effective state | Classification |
|---|---|---|---|
| `MERID_DISABLE_CRYPTO15M_GATE=1` | `.env` | crypto-15m gate disabled | investigate — may be intentional or stale |
| `MERID_MODEL_EDGE_FLOOR_CENTS=4.0` | `.env` | 4c model edge floor | necessary (economic) |
| `MERID_TRADE_DECISION_MIN_REQUIRED_EDGE=0.02` | `.env` | 2c min required edge | necessary (economic) |
| `MERID_FIXED_EXPOSURE_CAP_USD=11.00` / `MAX_CONTRACTS_PER_ORDER=11` / `MAX_STAKE_PCT_SHARD_CASH=1.0` | `.env` | small caps | necessary (risk) — but see §3 concentration |
| `MERID_MONEYNESS_GATE_ENABLED=1`, `MIN_DIST_BP=5.0`, `MIN_ABS_Z=0.5` | `.env` | moneyness gate on | necessary; caps drifted (§1.1) |
| `MERID_MONEYNESS_EV_RELIEF_ENABLED=1` | `.env` | relief on, range now under cap | **effectively dead code** — review |
| `MERID_PRICE_CAP_EXCEPT_*` (BTC-NO, all YES, DOGE-NO, SOL-NO) | `.env` | armed | mostly moot under cap=89; review |
| `MERID_REGIME_DETECTOR_ENABLED=0`, `LOSS_BRAKES_ENABLED=0`, `LOSS_EXITS_ENABLED=0` | `.env` | regime/loss brakes OFF | **investigate** — were these disabled deliberately? |
| `MERID_CHEAP_NO_LANE_ENABLED=1`, `SETTLEMENT_LANE_ENABLED=1`, `PINNED_FAV_ENABLED=1`, `DRIFT_LANE_ENABLED=1`, `MBAND_LANE_ENABLED=1` | `.env` | bounded lanes on | necessary (audited domains, own kill switches) |
| `MERID_ENTRY_TRAP_VETO_ENABLED=1` | `.env` | on | necessary |
| `MERID_EVIDENCE_HARD_BLOCK_MODE=challenge`, `EVIDENCE_MIN_CELL_NEFF=4.0`, `EVIDENCE_REHAB_PROBE=1` | `.env` | evidence gating strict | necessary; **dominant blocker** (§2) |
| `MERID_WINDOW_PLAN_ENABLED=1`, `WINDOW_QUOTA_ENABLED=0` | `.env` | window plan on, quota off | review |
| Threshold cells (`threshold_cells.py`) | code + `data/threshold_cell_lane.json` | 6 cells OBSERVATION, `probation_timeout`, 0 fills | **stuck state — investigate** (§4) |
| `fade_gate_state.json` | data | `allowed` | healthy |
| `directional_throttle_state.json` | data | post-drawdown epoch | investigate — is throttle still binding? |
| `drift_lane_state.json` | data | present | lane active |

### 1.3 Deployment-state conflict (open operational question)

`data/deployment_state.json` reports **paper/demo/simulated**: `trade_mode=paper`, `MERID_ALLOW_LIVE_TRADES=false`, `KALSHI_USE_DEMO=True`, `enable_execution=False`. This **conflicts** with the `AGENTS.md` durable `auto_execution_mode: 1` live contract. Yet `kalshi_fills.db` (2,089 fills) and `trade_attribution_fact.db` (3,759 settlements) show real trading occurred Sep 14 → Nov 15.

**Interpretations (unresolved):**
- (a) `deployment_state.json` is a stale snapshot from a paper/shadow instance, and production runs elsewhere.
- (b) Production is genuinely in paper/demo mode, and the fills/settlements are simulated or from a prior live period.
- (c) The state file is not the authoritative runtime indicator.

**This must be resolved before any "live" conclusion.** The audit cannot confirm whether the system is currently live-trading, paper-trading, or halted. Do not infer live status from `AGENTS.md`'s contract alone.

---

## 2. Decision funnel — where opportunities actually stop

### 2.1 Primary-reason distribution (8,000-row sample, `strategy_decisions`)

| primary_reason | count | share |
|---|---|---|
| `NO_EDGE` | 7,874 | 98.4% |
| `selected` | 122 | 1.5% |
| `DATA_QUALITY_VETO` | 4 | 0.05% |

The funnel is overwhelmingly edge-gated: nearly all candidates fail on estimated edge before any downstream gate matters.

### 2.2 Gate failure counts (same sample, all evaluated gates)

| gate | fails | gate | fails |
|---|---|---|---|
| `yes_edge_threshold` | 7,337 | `no_positive_ev` | 7,325 |
| `yes_qualified` | 7,337 | `no_cost_basis` | 7,325 |
| `no_edge_threshold` | 7,337 | `no_qualified` | 7,212 |
| `yes_evidence` | 7,331 | `no_evidence` | 6,804 |
| `book_trusted` | 3,131 | `no_regime` / `no_countertrend_lane` | 2,089 |
| `yes_moneyness` / `no_moneyness` | ~1,102–1,617 | `no_book_flow` / `yes_book_flow` | ~1,076 / 589 |
| `yes_depth` / `no_depth` | 395 / 263 | `no_conviction` / `yes_conviction` | 272 / 243 |
| `confidence_valid` | 177 | `market_time` | 61 |

**Key read:** after edge, **evidence gating** (`*_evidence`, `no_cost_basis`, `no_positive_ev`) is the dominant secondary blocker — failing on ~7.3k of 8k. Moneyness fails on only ~1.1–1.6k, so the cap drift (§1.1) is *not* currently the binding constraint on volume; it matters for *which* prices are admissible when a candidate does pass edge+evidence.

### 2.3 Threshold-cell funnel (bounded lanes)

| metric | run A | run B |
|---|---|---|
| matched | 3,316 | 14,564 |
| blocked by evidence | 3,205 | 22,578 |
| blocked by price band | — | 27,942 |
| legacy evidence labelled | — | 8 |
| **emitted / submitted / filled** | **0 / 0 / 0** | **0 / 0 / 0** |
| cell states | 6 OBSERVATION | 0 |

Six cells (`sol_no_30_60`, `sol_no_60_80`, `xrp_no_80_90`, `eth_no_50_60`, `eth_no_60_70`, `doge_no_70_90`, all `t120_600`) sit in `OBSERVATION` via `probation_timeout`, ages 1,800s → hundreds of thousands of seconds, with **zero fills and no auto-promotion**. The state machine is `PROVISIONAL → OBSERVATION → SUSPENDED → manual review`; `OBSERVATION → PROMOTED` is manual-only. These cells are matched but never emit because evidence gating blocks ~97% of matches.

**Classification:** this is a *stuck-lifecycle* issue, not a profitable-bucket suppression — the cells have no fills to evaluate, so there is no evidence they would be profitable. They are candidates for **shadow instrumentation**, not reopening.

---

## 3. Blocked-bucket scorecard — counterfactual evidence

### 3.1 Rejected-candidate counterfactual (`rejection_counterfactual_report.py`)

134,637 rejected candidates, all classified. Hypothetical P&L if *all* were taken: **−83,073c total, −0.62c/trade**.

| gate | saved | missed | flat |
|---|---|---|---|
| `no_eligible_price_band` | 14,217 | 3,092 | 2,829 |
| `no_positive_executable_edge` | 61,799 | 50,348 | 6 |
| `no_edge_below_lane_floor` | 104 | 759 | — |
| `yes_edge_below_lane_floor` | 216 | 769 | — |
| `calibration_evidence_no` | 0 | 58 | — |
| `calibration_evidence_yes` | 4 | 35 | — |

**Marginal shortfall bands** (the only ones that should inform threshold changes):

| shortfall | n | counterfactual P&L | avg |
|---|---|---|---|
| 0–1c | 11 | +314c | +28.6c |
| 1–2c | 35 | +662c | +18.9c |
| 2–3c | 14 | +770c | +55.0c |
| 3c+ | 104 | +1,770c | +17.0c |
| N/A (non-marginal) | 134,473 | −86,590c | −0.64c |

The marginal bands are positive but **severely underpowered** (11–104 obs). The script itself warns only the 0–1c band should inform a threshold change, and the huge N/A bucket dominates. **Do not loosen edge thresholds on this evidence.**

**Price-bucket counterfactual P&L** (non-monotonic, shows the toxicity is band-specific):

| price bucket | counterfactual P&L (c) |
|---|---|
| 00–09c | −12,699 |
| 10–19c | **+57,606** |
| 20–29c | **+47,322** |
| 30–39c | −77,097 |
| 40–49c | −32,189 |
| 50–59c | +36,576 |
| 60–69c | −7,198 |
| 70–79c | −31,130 |
| 80–89c | −30,069 |
| 90–99c | −32,427 |

Cheap 10–29c looks strongly positive counterfactually; mid/high bands are deeply negative. This is consistent with the settled-P&L table (§1.1) and suggests **the recoverable opportunity, if any, is in the cheap tail — not in reopening high-price caps.**

**Structural-veto sub-gates:** `bounded_domain` −112c/53 obs, `countertrend_lane` +62c/16 obs — both too small to act on.

### 3.2 Recoverable-activity estimate

The honest answer to "which buckets are still blocked?" is: **very few, and the evidence does not support reopening them yet.**

- The funnel is 98.4% edge-gated; downstream gates rarely bind.
- All-rejected counterfactual is net-negative.
- The only positive counterfactual pockets (10–29c price band, marginal 0–1c shortfall) are either already partially traded or statistically underpowered.
- The confirmed config drift (§1.1) *removed* restrictions — the question is whether that removal was justified, not whether to remove more.

---

## 4. Stale-restriction hunt — findings

| # | Finding | Evidence | Classification |
|---|---|---|---|
| 1 | **Moneyness caps drifted from audited structure to flat 89c** | `.env` vs `AGENTS.md` §14 vs `entry_price_cap_90c_gt_89c` in audit | **Confirmed drift — needs operator intent** |
| 2 | **XRP-NO hard block (cap=1c, −9.54 USD audited) lifted to 89c** | `.env` + §14 | **Confirmed drift — highest-risk reopening** |
| 3 | **51–64c blocked bands removed** | absent from `.env`, present in `.bak_devin_20261014` | **Confirmed drift** |
| 4 | **`MERID_MONEYNESS_EV_RELIEF` + `PRICE_CAP_EXCEPT` now largely dead code** | relief range 10–89.99c ⊂ cap=89 | **Stale mechanism — review** |
| 5 | **6 threshold cells stuck OBSERVATION, 0 fills, no auto-promotion** | `threshold_cell_lane.json` | **Stuck lifecycle — shadow-instrument, don't reopen** |
| 6 | **`MERID_REGIME_DETECTOR_ENABLED=0`, `LOSS_BRAKES=0`, `LOSS_EXITS=0`** | `.env` | **Investigate — deliberate or stale?** |
| 7 | **RTI tick archive 03–07 UTC gap, daily, all 10 days** | `cf_rti_ticks.db` hour histogram | **Collection/retention gap — repair target** |
| 8 | **`decision_audit.db` partially malformed; `kalshi_book_archive_live2.db` malformed; `_audit_snapshot` not a DB** | sqlite errors | **Data-health — repair before trusting audit queries** |
| 9 | **`deployment_state.json` paper/demo vs `AGENTS.md` live contract** | state file vs fills/settlements | **Unresolved — determine authoritative runtime mode** |

---

## 5. 03–07 UTC RTI gap — root cause

**Verified facts:**
- Kalshi 15m markets **operate 24/7** — settlements exist at every UTC hour (0–23), fills at every hour (50–115/hr).
- `cf_rti_ticks.db` has a **consistent 03:00–07:00 UTC gap every day** across all 10 days of coverage.
- The system trades during 03–07 UTC (fills present), so either (a) the live model gets RTI via a path not written to `cf_rti_ticks.db`, or (b) the model runs degraded during those hours.

**Classification:** the gap is in the **tick-archive collection/retention layer**, not market availability and not settlement (settlements use Kalshi REST outcomes). Whether the *live decision path* had fresh RTI during 03–07 UTC is **unverifiable** from available stores — `decision_audit.db` is partially malformed and the cold archive query timed out.

**Required next step:** check the live RTI websocket subscription schedule and the `cf_rti_ticks` writer's active window; confirm whether `data_state`/`DATA_QUALITY_VETO` rates spike at 03–07 UTC in a healthy audit source. Treat as a **repair target** (restore coverage → shadow-score the session → evaluate economics → only then consider it "reopened"). A backfill does not prove live inputs existed at decision time.

---

## 6. Prioritized action queue

Following the audit spec's Stage A→D, and respecting "repair accidental suppression first; investigate broad historical restrictions second; relax economic gates only with cost/risk/uncertainty evidence":

### Stage A — No-capital audit (now)
- [ ] **Resolve the moneyness drift intent.** Was flat-89c deliberate (post-probe) or accidental? Get operator confirmation; if deliberate, update `AGENTS.md` §14 and retire `EV_RELIEF`/`PRICE_CAP_EXCEPT` dead code; if accidental, restore the audited per-asset caps + blocked bands.
- [ ] **Resolve deployment-state conflict.** Determine authoritative runtime mode (live vs paper vs halted). The fills/settlements prove trading happened; confirm it is the intended live account.
- [ ] **Repair malformed DBs** (`decision_audit.db` pages, `kalshi_book_archive_live2.db`, `_audit_snapshot`) or quarantine them so audit queries stop failing silently.
- [ ] **Strict-grid PCA rerun** (§0.4): rebuild 15m returns only where both endpoints are fresh, record elapsed-time/coverage flags, recompute correlations before any covariance feeds a gate.
- [ ] **Contract-aware exposure computation** (§0.1–0.2): map each contract's payoff sensitivity to the underlying, multiply by signed position size, *then* evaluate the same-window same-side concentration — do not use PCA loadings or YES/NO labels as proxies.

### Stage B — Shadow challengers (predeclared, no capital)
- [ ] **Cheap-tail pocket (10–29c):** the only strongly positive counterfactual band. Shadow-score candidates in this band with conservative taker execution (available depth + Kalshi parabolic fee) before any live canary.
- [ ] **Marginal 0–1c edge shortfall:** positive but n=11. Extend the rejected-candidate log to grow this sample; do not act until n is adequate.
- [ ] **Threshold cells:** instrument the 6 OBSERVATION cells to log *why* evidence blocks them (which evidence gate, what Neff is missing) — they may be un-promotable by construction.
- [ ] **RTI 03–07 UTC:** restore archive coverage, shadow-score that session's decisions against a no-gap baseline.

### Stage C — Small live canaries (only after B shows positive incremental value net of costs)
- [ ] Candidates: cheap-tail 10–29c pocket, and *only if* the moneyness drift is confirmed deliberate, the 80–89c NO band under tight EV floors.
- [ ] Bounds: explicit incremental loss budget, per-market and total caps, retain all account/venue/data-integrity/emergency safeguards, auto-rollback on predefined failures.

### Stage D — Scale or retire
- [ ] Retire `EV_RELIEF`/`PRICE_CAP_EXCEPT` if confirmed dead under cap=89.
- [ ] Replace per-asset caps with contract-aware factor exposure **only after** the strict-grid covariance and payoff mapping exist — benchmark against the simpler current gates on breaches/stability/unnecessary-rejection, not in-sample fit.

---

## 7. Limitations

- Settlement `event_ts` is ingestion time, not market time (known from PCA scan) — price-band P&L joins used ticker-derived market dates where possible but coverage is partial (971/3,759 settlements joined).
- Entry prices come from order `price_cents` (limit price), not necessarily fill price — band assignment has some noise.
- Counterfactual P&L assumes settlement outcome at held price minus entry fee; it does **not** model queue position, partial fills, or adverse selection — per the spec's conservative-execution requirement, these are upper bounds.
- The cold decision archive and current audit DB could not be fully scanned (malformed / timeout) — hour-of-day gate rates for 03–07 UTC are unverified.
- PCA figures (PC1≈84%, ENCB≈1.9) are from the gap-bridged grid and are likely inflated (§0.4); treat as provisional.

---

## 8. Bottom line

The restriction census found **one confirmed, high-impact config drift** (moneyness caps flattened to 89c, lifting the audited XRP-NO hard block and the 51–64c toxic-band blocks) and **several stale/dead mechanisms** (EV-relief, price-cap-except probes, stuck threshold cells). It did **not** find a large pool of unjustifiably blocked profitable buckets — the funnel is edge-gated, the all-rejected counterfactual is net-negative, and the only positive counterfactual pocket (10–29c) is the right *shadow* candidate, not a reopen.

The correct next move is **not** to loosen gates. It is to (1) get operator intent on the cap drift, (2) resolve the paper-vs-live state conflict, (3) repair the data-health issues that are silently degrading audit trust, and (4) shadow-score the cheap-tail pocket with conservative execution before any capital is committed.
