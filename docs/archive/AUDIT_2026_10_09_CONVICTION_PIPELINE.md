# Conviction Pipeline Audit — BTC/ETH/SOL/XRP/DOGE 15m (2026-10-09)

Scope: the full probability-production pipeline for Kalshi 15-minute crypto
binaries — what the model predicts, which inputs drive it, calibration quality,
information beyond market prices, and whether edge survives fees/execution.
Priority items: (a) the ~45-point probability changes in ~2s, (b) settlement vs
scalp conviction separation, (c) whether admission restrictions — not the model
— produce the NO-side population.

All findings below were verified against code + data on 2026-10-09.
Data windows: order_attempts last 3 days (n=325); decision-audit snapshot scorecard
= last ~4.1h, 15,078 settled evals → 811 deduped evals / 77 markets; EPC
observation stream = 2,673 obs → 2,665 deduped / ~1,000 markets.

---

## 0. Headline results

1. **The 45-point/2s "probability changes" are not model moves — they are a
   side-normalization defect in the order router.** In
   `_revalidate_entry_economics` (`merid/event_venues/kalshi/order_router.py:5058`),
   `intent.side` carries Kalshi wire format (`"BUY_NO"`), is lower-cased to
   `"buy_no"`, and then tested with `== "no"` at line 5135 — which never matches.
   Every `BUY_NO` intent falls into the YES branch, so `p_sel_fresh` is set to
   the freshly recomputed **p_yes** (the complement of the held-side
   probability). `ev_new = ev0 + Δpx + (p_yes_fresh − p_no0)·100` then computes a
   phantom −40…−77pt edge decay and vetoes with
   `stale_decision_model_edge_decayed`.
   - Verified by exact replay: recomputed `p_yes_fresh` matches the logged
     `p_sel_fresh` to 4 decimals on all 12 full-model vetoes (fresh RTI spot,
     decision-snapshot vol, same walk-forward/tail-cap chain).
   - In the sampled cases the *true* fresh `p_no` (`1 − p_yes_fresh`) had often
     **increased** (e.g. BTC 0.762→0.849) — conviction strengthened while the
     veto reported it collapsing.
   - All 23 `stale_decision_model_edge_decayed` vetoes in the 3-day attempt
     window are `buy_no`; all 44 in the extracted `data/_conviction_audit_reval.json`
     window are `buy_no`. The stale-decision protection is effectively
     **disabled for YES and inverted for NO**.
   - Introduced 2026-09-29 in commit `0c876c4d` ("Re-run Bachelier+calibration
     in stale-decision warn band").
   - Second-order damage: these vetoes count as router rejects → they feed
     `consecutive_router_rejects` cell suspensions (the dominant suspension
     cause in `AUDIT_2026_10_09_SUSPENSION_PROBATION.md`). The bug manufactures
     negative evidence against NO cells.
   - **FIX APPLIED** (`order_router.py:5058-5070`): `_side_l` is now normalized
     through `extract_outcome_side` (already imported at line 189) with a
     defensive fallback to the raw lower-case value. Regression coverage added
     in `tests/test_stale_decision_model_revalidation.py`
     (`test_model_revalidation_buy_no_wire_format_side`,
     `test_model_revalidation_buy_no_rejects_on_real_decay`) — all 8 tests
     pass. The existing test suite used canonical `side="no"` intents, which is
     why the wire-format bug shipped unnoticed.
   - After deploying, expect `stale_decision_model_edge_decayed` vetoes to
     reprice correctly (only fire on genuine decay) and `buy_no` suspensions
     attributable to this defect to stop accruing.

2. **`confidence`/`conviction` names at least four unrelated quantities.**
   Field inventory in §3. Worst offender: `TradeDecision.p_yes_uncertainty`
   is assigned `model_risk_reserve` (an economics reserve), not an uncertainty
   interval (`trade_decision.py:6006`).

3. **Settlement conviction is being used as scalp conviction.**
   `edge_based_exit_evaluator.py:72-88` prices the held position's "current
   edge" as `entry_model_probability − current_market_probability` — i.e., the
   entry-time *settlement* probability frozen at entry, with no fresh forecast
   and no resale-value model. No scalp forecast exists anywhere in the stack.

4. **On out-of-sample data the calibrated model ≈ market mid, and the deployed
   calibration chain is a near-no-op.** Per-asset Brier (all-valid-forecasts,
   deduped): raw vs calibrated differ by <0.005 on 3/5 assets; market mid beats
   or ties the model on BTC, DOGE, ETH, XRP. SOL is materially miscalibrated
   in the 0.5–0.8 range (see §5).

5. **The mostly-NO population is real model preference amplified — not created
   — by admission mechanics, and the inversion bug suppressed NO further.**
   Candidate stream is ~4:1 `buy_no`:`buy_yes` (210:50 attempts / 3d). So the
   NO tilt exists at model/candidate level *before* admission gates.
   The router then rejects `buy_no` at 62% vs `buy_yes` at 58%, including 23
   inversion-bug vetoes that cannot fire on YES intents.

---

## 1. What the model predicts (settlement target verification)

`merid/prediction/settlement_distribution.py:1-6` documents and implements the
correct target: **the contract settles on the simple average of 60 one-second
CF RTI values in the final minute before expiry** — the model prices the future
average `A_e`, not the terminal tick. `SettlementWindowAccumulator`
(settlement_distribution.py:65-120) keys samples at 1s resolution, dedupes
retransmits, and `SettlementDistribution` returns `p_yes_raw` with
`model_version="settlement-average-normal-v2-discrete"`, `observed_count`,
`remaining_count`, `phase ∈ {pre_window, in_window, expired, invalid}`.

- `agent_grid_15m.py` builds this state from the CF RTI adapter and passes the
  distribution into `compute_trade_decision`.
- In the final window the market-anchor weight is scaled by
  `remaining_count/60` (trade_decision.py:3371-3382) — market authority fades
  as the model's banked samples dominate. Correct direction.
- Outside the window (`seconds_to_expiry > 60`), the Bachelier digital
  (`_compute_bachelier_components`, trade_decision.py) prices
  `Φ((log(S/K) − ½σ²τ)/(σ√τ))` — instantaneous-terminal-spot approximation of
  the average. For TTE > ~90s the terminal tick and the 60s average are
  highly correlated, so the approximation is acceptable *as a prior*, but it
  is still a different event. The `_compute_model_risk_reserve` +0.20
  "near-expiry" bump (trade_decision.py:2481-2486) exists precisely because
  the flat Bachelier misprices the final minute — the settlement-lane path
  exempts it.
- **Rule-completeness gap**: `strategy_decisions.settlement_rule_version`
  exists in the schema but no contract-rules digest (rounding, equality
  treatment, source-of-record) is pinned per decision — a `strike == avg`
  tie-break or CF-Benchmarks rounding change would silently shift p. Add
  `contract_rules_sha256` (already computed in agent_grid_15m.py:8565) to the
  decision snapshot.

## 2. Probability lineage — actual chain vs required chain

Required chain and where each stage currently lives / whether it is persisted:

| Stage | Where | Persisted? |
|---|---|---|
| Market contract/rules | contract_spec (`contract_rules_sha256` indicator) | indicators only, not decision row |
| Underlying observations | CF RTI adapter → SettlementState | `snapshots.spot_price`, `settlement_reference_price`, `spot_age_ms`, `settlement_reference_age_ms` ✓ |
| Feature construction | `zscore`, `log_moneyness`, `vol_forecast`, `vol_source` | snapshots ✓ (`vol_age_ms` often null) |
| Raw model estimate | `p_yes_raw` (Bachelier or settlement dist) | `snapshots.raw_p_yes` ✓ |
| Market anchoring | logit shrink, w=0.25→0.85 by TTE (trade_decision.py:3355-3398) | `indicators.market_anchor_weight/prob`, `p_yes_pre/post_anchor` ✓ (indicators dict) |
| Walk-forward calibration | `_walkforward_calibrate_p_yes` (trade_decision.py:307) per asset×TTE cell | not persisted per-eval (only final calibrated p) |
| Empirical price-calibration overlay | EPC per-side price-bucketed (~3440) | `logs/empirical_cal_observations.jsonl` (applied flag + p_model/p_empirical) |
| Tail cap | `cap_p_yes`/`cap_p_no` (3465-3526), artifact `probability_tail_calibration.json` | not per-eval persisted |
| Deviation guard | fail-closed on >0.15 inflation (3529+) | reason codes |
| Conservative reserve | `model_risk_reserve`, adverse-selection reserve | edge_breakdown / decision fields ✓ |
| Side selection | `best_side`, `selected_outcome` | ✓ |
| Economics | `EdgeBreakdown`, `EntryCostStack.pi_star`, EV gate | `gate_results_json`, `ev_gate_result` ✓ |
| Evidence admission | provisional/threshold cells, `admission_lane` | ✓ |
| Submission revalidation | router `_revalidate_entry_economics` | `_prov` log fields + `probability_inputs` on intent ✓ (fresh inputs only — see gap) |

**Provenance gap (the important one):** `probability_inputs`
(agent_grid_15m.py:9874-9893) correctly ships decision-time
`spot/strike/tte/vol/p_yes_calibrated/p_selected/anchor` on the intent, and the
router logs *fresh* inputs — but the decision record does not persist the
per-stage intermediate probabilities (post-anchor p, post-walkforward p,
post-EPC p, pre/post-tail-cap p per side). The replay that proved the
inversion bug was possible only because the log carried `p_sel_fresh`; for
original decisions we could not recover the intermediate chain. **Persist the
per-stage vector** (`p_raw`, `p_anchored`, `p_wf`, `p_epc`, `p_tailed`, per
side) in `strategy_decision_snapshots` — the schema already has `raw_p_yes`
and `calibrated_p_yes`; add the intermediates as columns or a JSON blob.

Event vs receive vs decision time: `decision_ts`, `observed_at_ts`,
`spot_age_ms`, `book_age_ms` exist and are distinct — good. `latest_rti_ts`
/`latest_rti_age_ms` are captured in SettlementState but not always propagated
into the snapshot (`spot_age_ms` was null in a sampled row while
`settlement_reference_age_ms` was 1652ms).

## 3. Conviction field inventory (verified semantics)

| Field | What it actually is | Units | Horizon | Producer | Consumers | Defect |
|---|---|---|---|---|---|---|
| `p_yes_raw` | Bachelier/settlement-dist P(YES settles) | prob | settlement | `_compute_bachelier_components` / SettlementDistribution | anchor → wf → epc → tail chain | OK |
| `p_yes_calibrated` | post-anchor+wf+EPC+tail-cap P(YES) | prob | settlement | trade_decision chain | p_selected, ledgers | OK but per-stage values unpersisted |
| `p_selected` | calibrated prob of selected side | prob | settlement | trade_decision | EV gate, router, **edge_based_exit_evaluator** | reused as resale value (see §4) |
| `confidence` (TradeDecision) | `1 − (data+book+model+regime penalties)` | score [0,1] | n/a | `_compute_confidence` (2492-2620) | entry validity gate, telemetry | NOT a probability; name collides with 3 other "confidences" |
| `p_yes_uncertainty` | **= `model_risk_reserve`** | prob | settlement | trade_decision.py:6006 | audit only | **mislabeled: it is the edge reserve, not an uncertainty estimate** |
| `model_risk_reserve` | `model_uncertainty + bumps(data/regime/TTE)` | prob | settle | `_compute_model_risk_reserve` (2470) | net_edge, pi_star, EV gate | `model_uncertainty` is a static env constant (`MERID_MODEL_UNCERTAINTY`, default 0.05 — agent_grid_15m.py:8504), not learned; same value charged in 3 parallel gates |
| `pi_star` | exec_price + fee + slippage + uncertainty + adverse + required_edge | prob | settle | `EntryCostStack` (2099) | admission compare | OK (identity holds per docstring) |
| `side_ev` / `eff_ev` | `p_selected − price − stacked reserves` | cents | settle | compute_edge / EV gate | admission, evidence cells | settlement EV; not scalp EV |
| `uncertainty_reserve` | = `model_risk_reserve` | prob | settle | trade_decision.py:5789 | EV gate | duplicate label for same number |
| `confidence` (signal path) | `0.5 + edge_fraction` | score | n/a | agent_grid_15m.py:6732 | momentum signal gating | name collision, unrelated quantity |
| `conviction` | FVG + trend + sentiment composite | score | n/a | strategy.py:2263-2284 | directional strategy eval | name collision, unrelated |
| `fvg_confidence`/`bias_confidence` | indicator scores | score | n/a | FVG/momentum modules | signal votes | name collision |

**Reserve stacking audit (§7 of ask):** the same `model_uncertainty` constant
is charged (a) inside `confidence` as `model_penalty`, (b) inside
`EdgeBreakdown.net_edge` as `model_risk_reserve`, (c) inside `pi_star` as
`model_uncertainty_prob`, (d) inside the EV gate's `net_ev` as
`uncertainty_reserve`. These are parallel hurdles rather than one P&L charge —
but they mean a candidate must clear the same uncertainty term in three places
while the number itself is a static config, not a measured error. The evidence
layer can add `sparse_uplift_cents` on top (agent_grid_15m.py:9857). At minimum
rename `p_yes_uncertainty` → `uncertainty_reserve_frac` and record a real
posterior interval separately.

## 4. Settlement conviction vs scalp conviction — confirmed conflation

- **Entry**: `p_selected` is a settlement-horizon probability; `net_edge`/`pi_star`
  price a hold-to-settlement trade minus a *modeled* expected-exit-cost
  reserve (`MERID_EXPECTED_EXIT_*`, trade_decision.py:367-386). Entry is
  honestly settlement-valued.
- **Exit**: `edge_based_exit_evaluator.py:72-88` computes exit "edge" as
  `entry_model_probability − current_price` — the *entry-time settlement
  probability*, frozen. It never re-forecasts; a spot move after entry leaves
  stale conviction in the denominator. `settlement_aligned_exit.py:8-11` is
  more defensible (NetSellValue vs ConservativeHoldValue = calibrated
  settlement prob − reserves) but still compares sell-now vs hold-to-settlement
  — no resale-at-horizon model.
- **No scalp target exists.** Nothing in the stack estimates E[bid(t+h)] or
  P(profitable exit before boundary). The earlier
  `AUDIT_2026_10_08_EXPECTANCY_LOSS_CONTAINMENT.md` found filled-exit cohort
  +$15.25 with 68% win rate but lifecycle expectancy −$0.031/episode driven by
  `resid_no_attempt` — i.e., unmodeled exit mechanics dominate. That is exactly
  the signature of using settlement conviction where scalp conviction is needed.

**Required (per ask §9):** define one scalp target explicitly —
e.g. `P(held-side bid ≥ entry + 2c within T s | state)` — fit it on executable
bids (no_depth/yes_depth are snapshotted), and drive discretionary exits from
it. Keep settlement `p_selected` for hold-vs-settle comparisons only.

## 5. Calibration scorecard

### 5a. All valid forecasts (last ~4.1h, dedup 1/market-minute; n_markets≈77)

| Asset | n_eval | raw Brier | cal Brier | mkt-mid Brier | raw LL | cal LL | mkt LL | extreme-p obs WR |
|---|---|---|---|---|---|---|---|---|
| BTC | 151 | 0.2054 | 0.2043 | **0.2036** | 0.591 | 0.587 | 0.585 | 92.5% (n≈26) |
| DOGE | 163 | 0.2141 | 0.2215 | 0.2142 | 0.611 | 0.631 | 0.610 | 83.3% (n≈21) |
| ETH | 160 | 0.1862 | 0.1871 | **0.1844** | 0.548 | 0.549 | **0.544** | 93.0% (n≈29) |
| SOL | 164 | 0.2535 | 0.2581 | 0.2580 | 0.697 | 0.707 | 0.707 | 81.8% (n≈21) |
| XRP | 173 | 0.2218 | 0.2219 | **0.2139** | 0.624 | 0.623 | **0.606** | 94.1% (n≈18) |

Reliability highlights (calibrated): SOL mid-range is badly off — bin 0.6–0.7
predicted 0.649 vs observed 0.286 (n=28); 0.7–0.8: 0.744 vs 0.552 (n=29).
XRP 0.6–0.7: 0.653 vs 0.310 (n=29). BTC is noisy both directions
(0.2–0.3 under, 0.6–0.7 over). The 0.8–1.0 bins run 93–100% observed vs
~0.85–0.93 predicted — mild *under*confidence at the top, plausibly the
anchor+tail-cap overshooting downward.

Caveats: ~15-16 markets/asset; per-bin Wilson CIs are ±10-20pts; the sample is
one 4-hour regime. Treat as indicative, not definitive — rerun on a week of
rowid-tail extracts after the router fix lands.

### 5b. EPC observation stream (admitted candidates; 2,665 dedup evals / ~1,000 markets)

Held-side outcomes. All 2,673 obs are `side=no` — this stream only observes the
NO cohort, which is itself a measurement gap (no admitted-side YES evidence).

| Asset | n | mkts | model Brier | price-as-forecast Brier | p≥0.8 obs WR (n) |
|---|---|---|---|---|---|
| BTC | 530 | 205 | 0.1994 | 0.2021 | 84.0% (181) |
| DOGE | 529 | 196 | 0.1929 | 0.1940 | 83.7% (172) |
| ETH | 553 | 201 | 0.1646 | 0.1647 | 90.4% (188) |
| SOL | 537 | 200 | 0.1922 | **0.1914** | 86.0% (186) |
| XRP | 516 | 198 | 0.1965 | 0.1974 | 82.4% (182) |

Pooled: model 0.1889 vs price 0.1897 — the model adds ≈0.001 Brier over simply
forecasting "the contract price." p≥0.8 cohorts hold 82–90% — reasonable
extreme-region calibration on the *admitted* population, mild overconfidence
for BTC/DOGE/XRP.

### Interpretation

- The deployed transform stack (anchor → walk-forward → EPC → tail-cap) changes
  raw p by ~1% mean, |Δ| p90 ≈ 4-8pts, and does not measurably improve OOS Brier
  in this window. `MERID_WALKFWD_CAL` cells are mostly identity because
  fitted calibrators didn't beat identity — consistent with this result.
- Market anchoring is a TTE-ramped **heuristic** (w=0.25→0.85), not validated
  per-asset. Given model ≈ market in scores, the anchor is currently what keeps
  deployed p near-market — i.e., the model's independent information content is
  small, and the anchor is likely *correct* to be heavy. Removing it is not
  supported by evidence; neither is crediting the model for disagreement it
  does not profitably express.
- Kalshi exchange-wide calibration results do not transfer: this subpopulation
  (5 assets, 15m binaries, admitted candidates) shows materially worse
  mid-range calibration than the venue's aggregate claims.

### Leakage/hygiene

- Walk-forward artifact (`walkforward_calibrator.json`, fitted 2026-10-03) is
  per-(asset,TTE-bucket) Platt/identity chosen by OOS Brier — correct fitting
  discipline (fit on prior window, apply to later). Cells: e.g. BTC early
  identity (0.2389→0.2396), DOGE late Platt (0.1597→0.1584). Cells are few,
  not per-price×TTE micro-cells — good.
- Tail calibrator is PAVA-isotonic on market-deduped (2c bucket) observations
  (n=4,069 unique markets) — dedup level is right; `no_curve_is_dual=False`,
  `no_source="no_held_observations"` (the stale code comment at
  trade_decision.py:3482 claiming "currently a dual" should be corrected).
- EPC cells (`epc_{side}_{price}_{tte}`) are small-sample — the
  `applied=false` flag pattern in the obs log shows the estimator mostly
  refuses to apply; that restraint is appropriate.
- Remaining gap: the eval stream itself is admission-selected; and no fold
  enforces market-level separation across overlapping outcome intervals beyond
  the ticker×minute dedup used here.

## 6. The large probability changes — reproduction detail

Mechanism (order_router.py:5056-5160):
```
intent.side = "BUY_NO"
_side_l = intent.side.lower() = "buy_no"          # 5058
if _side_l == "no": ... else:                     # 5135 -> FALSE
    _p_side = _p_yes_f                            # 5153 (wrong side)
    _p_sel_fresh = clamp(_p_side)                 # 5159
_p_yes_fresh = 1.0 - _p_sel_fresh                 # 5160 (double-inverted)
_delta_p = (_p_sel_fresh - _p_sel0_f) * 100       # p_yes_fresh − p_no0
_ev_new = _ev0 + _delta_px + _delta_p             # → deeply negative
→ reject "stale_decision_model_edge_decayed"
```

Reproduction (from `data/_conviction_audit_reval.json`, `scripts/_conviction_replay_vetoes.py`
+ `_conviction_tail_cap_check.py`):

| asset | px¢ | tte0→now | p_no0 (decision) | p_yes_fresh | true p_no_fresh | logged p_sel_fresh | Δp |
|---|---|---|---|---|---|---|---|
| BTC | 85 | 158→156s | 0.762 | 0.151 | **0.849** | 0.1508 | −61.1 |
| SOL | 60 | 240→236 | 0.714 | 0.224 | 0.776 | 0.2244 | −49.0 |
| SOL | 91 | 59→56 | 0.864 | 0.099 | **0.901** | 0.0990 | −76.5 |
| BTC | 80 | 244→240 | 0.689 | 0.193 | 0.807 | 0.1929 | −49.6 |
| ETH | 91 | 54→52 | 0.864 | 0.088 | **0.912** | 0.0883 | −77.5 |
| ETH | 84 | 133→129 | 0.603 | 0.209 | 0.791 | 0.2090 | −39.4 |
| XRP | 57 | 311→307 | 0.660 | 0.432 | 0.568 | 0.4324 | −22.7 |
| BTC | 70 | 336→332 | 0.774 | 0.280 | 0.720 | 0.2796 | −49.5 |
| ETH | 72 | 422→416 | 0.786 | 0.248 | 0.752 | 0.2480 | −53.8 |
| XRP | 88 | 96→93 | 0.567 | 0.132 | 0.868 | 0.1323 | −43.5 |
| SOL | 25 | 720→714 | 0.628 | 0.666→cap 0.294 | 0.706 | 0.2935 | −33.4 |
| SOL | 27 | 696→690 | 0.628 | 0.653→cap 0.294 | 0.706 | 0.2935 | −33.4 |

Logged `p_sel_fresh` equals `min(cap, p_yes_fresh)` exactly (the two 25-27¢ rows
hit the YES tail cap at p_yes(price)+0.05 = 0.294). TTE changed ≤6s; the
probability did not change — the side did.

Perturbation attribution for the record: in every case the entire Δp is
explained by the inversion; spot/TTE/vol changes contributed <1pt on these
examples (verified via the recompute matching to 1e-4).

## 7. Side-selection vs policy exclusion (order_attempts, 3d)

- Candidate intents: buy_no 210, buy_yes 50, sell_no 39, sell_yes 12, bare
  yes/no 14. **Model/candidate layer produces ≈4:1 NO tilt** — the NO-heavy
  population is genuine model preference (arbitrage-free Bachelier + market
  anchor means the model's tradable disagreements concentrate where YES is
  priced rich relative to model p — i.e., buying NO).
- Reject mix (REJECTED=179): `order_intent_contract` 59 (mostly
  `duplicate_entry` dedupe — legitimate), `edge_lost_at_submit` 36 (fresh-ask
  moved past edge budget; all buy_no because the stream is buy_no),
  `stale_decision_model_edge_decayed` 23 (**all buy_no — the defect**),
  firewall 12, reprice_would_cross 10, ws_event_age 9.
- Fills: attempts ledger buy_no FILLED=43 vs buy_yes 14.
- **Ledger discrepancy (needs verification):** `kalshi_fills` canonical rows
  (3d, is_exit=0) show yes-buy 105 vs no-buy 7 — inconsistent with the attempts
  ledger's 43 buy_no fills. Either fills ingestion misses buy_no fills or
  `canonical_position_*` mislabels side. Resolve before trusting P&L-by-side
  accounting. (`fill_source`/`canonicalization_version` columns exist.)

So the earlier hypothesis "admission restrictions produce the NO population" is
only partially right: the NO tilt originates in model/candidate generation;
admission mechanics then (a) filter it legitimately (edge_lost, dedupe) and
(b) corrupt it illegitimately (inversion vetoes + resulting suspensions).

## 8. Per-asset recommendations

| Asset | Evidence | Recommendation |
|---|---|---|
| BTC | model ≈ market mid (0.2043 vs 0.2036 Brier); extreme bins mildly underconfident; inversion vetoes present | **fix + shadow**: ship router side-normalization fix; keep settlement lane; re-score on ≥1wk post-fix before touching thresholds |
| ETH | best model Brier (0.1871) but still ≤ market mid; reliability decent; 2 full-model vetoes were inversion artifacts | **fix + shadow** same as BTC |
| SOL | worst Brier (0.2581); mid-range reliability badly overconfident (0.65 pred / 0.29 obs); tail losses noted in prior audit | **recalibrate**: pooled-isotonic or wider Platt refit on post-fix data; meanwhile keep tighter admission (it is the riskiest asset right now) |
| XRP | model loses to market mid most clearly (0.2219 vs 0.2139); 0.6–0.7 bin overconfident; evidence-restricted cohorts already documented | **shadow**: no new XRP entries until post-fix evidence shows p beats mid on its own cohort |
| DOGE | calibration slightly worsened OOS (0.2141→0.2215); extreme WR 83% on ~90% claims | **recalibrate** with SOL; lean toward pooled calibration |

Global: **do not loosen any threshold, cell, or price cap on the strength of
current conviction readings.** The deployed p is largely the market mid plus a
small model residual; the residual has not demonstrated added score.

## 9. Defects found (exact locations)

1. **order_router.py:5058 + 5135-5160** — BUY_NO treated as YES in model
   revalidation; vetoes + rebound intent fields + suspension bookkeeping all
   corrupted. **Fixed** via `extract_outcome_side` normalization (regression
   tests added). Follow-up: audit `intent.p_selected`/`p_yes` rebound on ALLOW
   rows since 2026-09-29 — allowed BUY_NO intents may carry inverted stored
   probabilities into ledgers.
2. **trade_decision.py:6006** — `p_yes_uncertainty = model_risk_reserve`:
   mislabeled semantics. Rename + add a real uncertainty field (e.g., calibrator
   residual std per cell).
3. **trade_decision.py:2470-2489 + 6006 + 5789** — `model_uncertainty` is a
   static env constant charged as `model_risk_reserve` in net_edge, pi_star,
   and EV gate, and as `model_penalty` inside `confidence`. Decide which single
   gate owns it; do not let the same constant quietly drive both "evidence
   confidence" and "economic reserve" without that being explicit.
4. **edge_based_exit_evaluator.py:72-88** — exit "edge" uses entry-time
   settlement p as if it were current resale value; no fresh forecast. Either
   re-evaluate p at exit or replace with an explicit scalp target.
5. **Lineage gap** — per-stage probabilities (post-anchor/wf/EPC/tail, per
   side) not persisted per decision; original-side inputs unpersisted in
   revalidation logs. Add to `strategy_decision_snapshots` + `_prov`.
6. **trade_decision.py:3482** — stale comment claiming NO tail curve is dual;
   deployed artifact is real (`no_held_observations`, n_no=39,526).
7. **Ledger inconsistency** — fills canonical side counts disagree with
   attempts ledger; verify before using fills for side-level P&L.

## 10. What was NOT fully resolved (explicit gaps)

- Executed-population calibration: only ~2 ENTER decisions in the 4.1h scorecard
  window (NO_EDGE dominates). The EPC obs stream covers the admitted cohort but
  is NO-only. A full executed-population reliability table needs the
  rowid-tail extract over ≥7d post-fix.
- Depth/queue replay for scalp validation still absent — `yes_depth`/`no_depth`
  snapshots exist per decision (audit-able forward), but historical fills lack
  queue position, so scalp target validation must define "executable" as
  observed best bid/ask + depth ≥ size, acknowledging selection bias.
- `vol_age_ms`, `realized_vol_*` snapshot fields often null — input-freshness
  auditing incomplete for vol.
- Whether `canonical_position_side` or the fills ingestion is wrong (§7) needs
  a fills↔attempts join on client_order_id.
- Contract-rules equality/rounding version is not pinned per decision
  (`settlement_rule_version` exists; populate it from contract_spec).

## 11. Files/scripts produced for this audit

- `scripts/_conviction_replay_vetoes.py`, `_conviction_tail_cap_check.py` —
  veto replay + stage-attribution (proved the inversion numerically)
- `scripts/_conviction_probe_db.py`, `_conviction_scorecard_fast.py`,
  `_conviction_scorecard_obs.py`, `_conviction_attempts_side.py`,
  `_conviction_fills_side.py`
- `data/_conviction_scorecard.json`, `data/_conviction_scorecard_obs.json`
- Prior: `data/_conviction_audit_reval.json`
