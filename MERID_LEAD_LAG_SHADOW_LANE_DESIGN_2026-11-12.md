# MERID Lead–Lag Shadow Lane — Design Specification

**Date:** 2026-11-12 (amended 2026-11-12 — baseline, causality, and evaluation revisions)
**Status:** Design only. No live-effect changes are specified or implied.
**Experiment id (proposed):** `lead_lag_residual_v1`
**Scope:** BTC → {ETH, SOL, XRP, DOGE} cross-asset information as an incremental
correction to the existing settlement-average probability. BTC itself is a
control asset (no BTC→BTC arm).

This document is repository-grounded: every integration point, field, and
evaluation mechanism below was verified against the current code. The offline
feasibility screen protocol (§6.4) is specified here and executed separately;
its results determine whether prospective capture is warranted.

**Amendment summary (2026-11-12):**

1. `p_final_yes` (the post-chain probability the gates consume) is the primary
   incumbent for **economic** evaluation; `p_settle_raw` remains the
   mechanistic research baseline. Two explicit experiments (A and B, §5).
2. Historical signal discovery and historical deployability are separated:
   source-timestamped RTI can establish a statistical relationship but cannot
   by itself prove MERID received and could have traded that information in
   time. Every historical result is labeled source-time or receipt-time.
3. The screen is gated by a data-provenance report before any regression.
4. Maker execution is a separate research track; existing maker shadows are
   relabeled hypothetical-execution evidence.

---

## 0. Verified baseline (what already exists)

| Memo proposal | Verified implementation |
|---|---|
| Settlement-average probability | `merid/prediction/settlement_distribution.py` — discrete 60-sample Bachelier on `(expiry-60s, expiry]`, exact `Σ min(u_i,u_j)` covariance, bounded causal forward-fill, venue-clock skew handling, fail-closed. Enabled in production via `MERID_SETTLEMENT_DISTRIBUTION_V2=1` (`.env:425`). Its `p_yes_raw` overrides the endpoint Bachelier inside `compute_trade_decision` (`trade_decision.py:4202-4231`) and is published as `market_state.settlement_fair_prob` (`agent_grid_15m.py:8916`). |
| Conservative EV / exact fees | `kalshi_fee_cents_exact` (`parabolic_fees.py`), role-aware maker/taker EV with impact reserve (`agent_grid_15m.py:7330-7359`), per-side gate economics persisted in `strategy_decision_side_ev` (incl. counterfactual executability columns). |
| Cross-asset telemetry | `FeatureSnapshotBuilder` (`feature_snapshot.py`) builds one immutable per-tick snapshot shared by all five agents; each `AssetFeatureSlice` already carries `rti_returns` at 1/3/10/30/60/120 s, RTI provenance (`rti_source_ts_ms`, `rti_observed_ts_ms`, `rti_age_ms`, `rti_execution_eligible`), book/microstructure fields, and `btc_log_return` (300 s spot-window). `microstructure_features.cross_asset_lead_lag` exists as a heuristic ±2 pp edge delta feeding `cross_delta_pp` — telemetry/gated only, not a calibrated probability input. |
| Forecast telemetry | `forecast_event.py` — one `forecast_event_id` per `compute_trade_decision` evaluation; full probability stage chain (raw → anchor → walk-forward → EPC → tail → stream → final), admission result/reason, timing provenance, artifact hashes → `logs/forecast_events.jsonl`. `suppress_side_effects()` contextvar makes shadow re-evaluation side-effect-free. |
| Scheduled shadow harness | `shadow_evaluator.py::maybe_emit_scheduled` — re-runs the unchanged production chain at horizons {600,300,120,60}s under suppression with a 500 ms/cycle budget and an opportunity ledger (`logs/forecast_opportunities.jsonl`). Called from the single production decision site. |
| Decision audit DB | `data/decision_audit.db` — `strategy_decisions` (+`candidate_id`, `run_id`, `gate_results_json`) + `strategy_decision_snapshots` + `strategy_decision_side_ev` + `strategy_decision_outcomes` (~163k decisions, ~292k side-EV rows; archives under `data/archive/` back to 2026-09). |
| Offline scorer | `merid/analysis/forecast_audit/` — anchored per-(ticker,horizon) joins, walk-forward folds, block bootstrap (1800–14400 s blocks), label-availability policy, min-support gates. CLI: `python -m merid.analysis.forecast_audit`. |
| Settlement labels | `logs/settlement_outcomes.jsonl` via `merid/analysis/settlement_outcome_exporter.py` (definitive yes/no only; live poller + standalone exporter). |
| Veto counterfactuals | `rejection_counterfactual.py` → `logs/rejected_candidates.jsonl` (411 MB) + `scripts/rejection_counterfactual_report.py` (saved/missed/flat/unclassifiable). |
| Tick-level history | `data/cf_rti_ticks.db` — every `cfbenchmarks_value` frame (value, avg_60s, avg_60s_15m, `src_ts_ms`, `recv_ts_ms`, `local_ts_ms`, seq, raw_json) for all five assets; ~7 days coverage at time of writing (2026-11-05 → 2026-11-12, ~180k rows, retention ~10 d). **`recv_ts_ms` exists — receipt-time reconstruction is partially possible.** |
| Book history | `data/kalshi_book_archive*.db` — raw `orderbook_delta` frames (snapshots+deltas, in order, receipt timestamps) via `scripts/kalshi_book_archiver.py`; ~10.6 GB preserved snapshots (2026-11-06/07) plus live archive with ~24 h retention. `data/orderbook_reconstructor.py` exists for replay. |

**Single production decision site:** `compute_trade_decision` is called exactly
once per evaluation, inside `_call_trade_decision` at
`agent_grid_15m.py:9186`. The wrapper is invoked per route — `route="taker"`
always (`:9249`), `route="maker"` when maker entries are enabled and not late
(`:9279`), plus the bid-priced maker pass further down. A shadow hook placed
inside `_call_trade_decision` (adjacent to the existing
`maybe_emit_scheduled` call at `:9200-9206`) observes **every** live
decision-path evaluation with the complete input bundle.

**Persisted probability fields (verified):** `strategy_decision_snapshots.
raw_p_yes` = `decision.p_yes_raw` — the settlement-aware value when the V2
override applied, endpoint Bachelier otherwise; `calibrated_p_yes` =
`decision.p_yes_calibrated`, the final emitted probability post
anchor/walk-forward/EPC/tail/lane bounds — the closest persisted field to
`p_final_yes`. `endpoint_p_yes_raw`, `settlement_*` indicator fields, and
`market_anchor_prob` are **not** in the audit DB (market anchor survives only
in `logs/model_calibration_observations.jsonl`, coverage from 2026-10-14);
`yes_mid` from snapshot quotes is the available market-implied proxy.

---

## 1. Gap-check results

1. **Candidate snapshot exists but is split across stores.** The `candidate`
   dict (`agent_grid_15m.py:21161+`) carries microstructure fields into the
   order pipeline; the durable per-decision record is the audit DB trio above.
   Neither persists multi-horizon cross-asset RTI returns — only
   `microstructure_btc_log_return` (one 300 s spot-window scalar) and the
   heuristic `cross_delta_pp` survive into candidate telemetry, and those
   fields do not reach `strategy_decision_snapshots`. **The lead–lag lane
   must emit its own self-contained JSONL record** (the established shadow
   pattern); it cannot rely on retrospective feature reconstruction from the
   audit DB alone.
2. **RTI features needed already exist in memory.** `FeatureSnapshot.by_asset["BTC"].rtt_returns`
   holds BTC's log returns at the same lookbacks as every other asset, computed
   once per tick from source-timestamped RTI — causal by construction
   (`get_rti_return`, `cf_rti_adapter.py:956-982`). No new data plumbing is
   required for the primary feature set.
3. **Spot vs. index distinction matters.** `btc_log_return` in each slice is
   derived from `external_spot`/`spot_price` (300 s `SpotHistory`), *not* the
   CF RTI settlement index. For a settlement-anchored hypothesis the primary
   features must be RTI-based; the spot-based scalar is retained only as a
   labeled ablation.
4. **Historical reconstruction is partially feasible now.** `cf_rti_ticks.db`
   + `decision_audit.db` + `settlement_outcomes.jsonl` allow offline
   recomputation of RTI-return features for past decisions within the ~7-day
   tick-archive window — under **both** source-time (`src_ts_ms ≤ t_dec`)
   and receipt-time (`recv_ts_ms ≤ t_dec`) anchoring. Book-archive coverage
   is windowed, so executable-quote replay is limited to overlapping
   intervals — reported as indicative economics only.
5. **Maker-shadow evidence audit:** see §7.

---

## 2. Integration points (confirmed)

### 2.1 Emit hook — `agent_grid_15m.py`, inside `_call_trade_decision`

Immediately after `decision = compute_trade_decision(**td_kwargs)` (`:9186`)
and beside the existing `_shadow.maybe_emit_scheduled(...)` block
(`:9200-9206`), add:

```python
try:
    from merid.prediction import lead_lag_shadow as _lls
    _lls.evaluate_decision(
        run_id=run_id, td_kwargs=td_kwargs, decision=decision,
    )
except Exception as _lls_err:
    logger.debug("[LEAD-LAG-SHADOW] emit failed: %s", _lls_err)
```

At this point the following are all in scope, verified:

- `td_kwargs["settlement_distribution"]` — the `SettlementDistribution`
  (or `None` when V2 did not build; `decision.indicators["settlement_status"]`
  records `built`/`flag_off`/etc. via `_last_v2_dist_status`).
- `td_kwargs["feature_snapshot"]` — the per-tick `FeatureSnapshot` with all
  five assets' slices.
- `decision.indicators` — full stage chain: `p_yes_raw` (post-settlement
  override), `endpoint_p_yes_raw`, `settlement_raw_probability`,
  `settlement_forecast_mean/std`, `settlement_observed_count`,
  `settlement_remaining_count`, `settlement_phase`, `settlement_forecast_method`,
  `settlement_model_version`, `log_moneyness`, `z_score`,
  `market_anchor_prob`, `market_anchor_weight`, `fe_*` stage probabilities,
  `decision_lane`, gate economics.
- `decision.decision`, `decision.no_trade_reason`, reason codes,
  `decision.config_hash`, `decision.build_sha`.
- Quotes/sizing inputs in `td_kwargs`: `yes/no_bid/ask_cents`,
  `yes/no_depth_cc`, `fee_per_contract_cents`, `route`, `price_basis`,
  `adverse_selection_reserve`, `min_required_edge`,
  `seconds_to_expiry`, `strike_price`, `annualized_vol`,
  `settlement_reference`, `quote_age_ms`, `rti_age_ms`,
  `rti_book_skew_ms`, `book_sequence_confirmed`, `book_initialized`,
  `cfb_execution_eligible`.

The hook fires once per route evaluation (taker always; maker/bid-priced
passes when enabled). Each is a distinct evaluation with distinct economics —
the record's `route`/`execution_inputs` fields keep them separable; dedup is
per `decision_id`+`route`, never collapsed across routes.

### 2.2 What the lane must NOT do

- No writes to `decision.indicators`, `market_state`, order router, risk
  reservations, slot allocator, daily caps, evidence cells, or canary
  counters.
- No orders, cancels, or repricing. No participation in
  `pinned_fav`/`basket_direction` vetoes.
- No enablement of `hybrid_bachelier_deltas` or any disabled signal source.
- Exception-safe and time-bounded: wrap in try/except, target <2 ms per call
  (feature extraction is dict lookups; the unfitted v1 performs no model
  inference). If a fitted artifact is later mounted, inference must respect a
  small per-cycle budget analogous to `shadow_time_budget_ms()`.

### 2.3 Population coverage note

The hook observes every evaluation that reaches `compute_trade_decision` —
i.e., candidates that survived pre-decision admission far enough to have a
probability. Candidates rejected earlier (no market, stale data, infra
halts) carry no `p0` and are out of scope for *forecast* evaluation by
construction; their veto counterfactuals remain covered by
`rejected_candidates.jsonl` (§6.3).

---

## 3. Observation schema — `logs/lead_lag_shadow.jsonl`

One JSON object per `(decision_id, route)` evaluation. `schema_version: 1`.
Write-only, append-only, `default=str` serialization, best-effort (emit
failure increments a counter, never raises).

```text
record_type            "lead_lag_shadow"
schema_version         1
experiment_id          "lead_lag_residual_v1"
emitted_ts_utc         ISO-8601
run_id, process_id
decision_id            == forecast_event evaluation_id (join key)
candidate_id           decision_id prefix before ':'
route                  "taker" | "maker" | "maker_bid" | ...
execution_inputs       "actual" (production eval, not standardized replay)
price_basis            td_kwargs["entry_price_basis"]

ticker, asset, series_ticker
scheduled_contract_close_ts   forecast_event.scheduled_close_from_ticker(ticker)
seconds_to_expiry

# --- baseline probabilities (from decision.indicators; None if stage absent)
settlement_override_applied    bool
p_settle_raw                   indicators["settlement_raw_probability"]
                                == settlement_distribution.p_yes_raw
                                == published settlement_fair_prob
endpoint_p_yes_raw             indicators["endpoint_p_yes_raw"]
p_final_yes                    final emitted probability the gates consumed
                                (freeze exact indicator key at implementation —
                                verify fe_final_p_yes vs decision.p_yes_calibrated
                                agree on production rows first)
market_anchor_prob, market_anchor_weight
p_yes_raw_stage_chain          {raw, post_anchor, post_wf, post_epc,
                                post_tail, post_stream, final} — copied from
                                indicators fe_* keys when present

# --- settlement state
settlement_phase               pre_window | in_window | expired | invalid
settlement_observed_count, settlement_remaining_count,
settlement_filled_count        (bounded forward-fill count — data-quality feature)
settlement_forecast_method, settlement_model_version
settlement_forecast_mean, settlement_forecast_std
z_score, log_moneyness
settlement_dist_available      bool (V2 built)

# --- preregistered feature vector X_t (see §4)
features = {
  "own_rti_ret_{h}s":   {h: value|null for h in H},   # target asset
  "btc_rti_ret_{h}s":   {h: value|null for h in H},   # leader (BTC slice)
  "btc_rti_age_ms", "btc_rti_source_ts_ms", "btc_rti_observed_ts_ms",
  "btc_rti_execution_eligible",
  "own_rti_age_ms", "own_rti_execution_eligible",
  "btc_spot_log_ret_300s",          # ablation-only, external_spot based
  "feature_snapshot_ts", "feature_age_ms", "feature_valid",
  "feature_missing_reasons": [...],
}
feature_status            "complete" | "partial:<reasons>" | "unavailable"
causality_label           "live_receipt_time" (production features are
                          receipt-time by construction)

# --- market state (for economic replay + market-implied ablation)
yes_bid_cents, yes_ask_cents, no_bid_cents, no_ask_cents
yes_depth_cc, no_depth_cc, spread_cents
quote_age_ms, book_sequence_confirmed, book_initialized
cfb_execution_eligible, rti_book_skew_ms

# --- economics (replay inputs; existing machinery recomputes, never trusts)
fee_per_contract_cents, route, price_basis
adverse_selection_reserve, min_required_edge
decision_lane               indicators["decision_lane"]
model_uncertainty, data_quality, data_state, regime fields (from kwargs)

# --- incumbent gate outcome
decision                   "ENTER"|"NO_TRADE"|...
no_trade_reason, reason_codes[]
config_hash, build_sha, model/calibration artifact versions when present

# --- shadow model arms (v1: unfitted capture)
shadow_model_version       "lead_lag_residual_v1/unfitted"
shadow_p_yes_A_raw, shadow_p_yes_B_final, shadow_delta_logit
                           null in v1; populated once a frozen artifact is
                           mounted via MERID_LEAD_LAG_MODEL_PATH (hash recorded)
shadow_feature_ablation_set  which preregistered subset was used (once fitted)
```

**Immutability:** records are append-only; a corrected feature interpretation
ships as `schema_version: 2`, never by rewriting v1 rows.

---

## 4. Causal feature and timestamp rules

Preregistered feature set (small, single-question):

| Group | Features | Source |
|---|---|---|
| Leader returns | `btc_rti_ret_{h}s`, h ∈ {1, 3, 10, 30, 60, 120} | `feature_snapshot.by_asset["BTC"].rti_returns` |
| Own returns | `own_rti_ret_{h}s`, same H | `feature_snapshot.by_asset[asset].rti_returns` |
| Settlement state | `z_score`, `log_moneyness`, `settlement_phase`, `observed/60`, `remaining_count`, `seconds_to_expiry`, `filled_count` | `settlement_distribution` / indicators |
| Baseline | `logit(p̃0)` per experiment arm | §5 |
| Market-implied | `market_anchor_prob` (+ weight); proxy `yes_mid` offline | indicators / snapshot quotes |
| Feed quality | `rti_age_ms`, `rti_execution_eligible`, `feature_age_ms`, `feature_valid`, `missing_reasons`, BTC-slice equivalents | snapshot slice |
| Spot ablation | `btc_spot_log_ret_300s` | `snap.btc_log_return` (external_spot; NOT settlement index) |

Rules:

1. **Causality:** every feature derives from RTI observations whose
   *receipt* time precedes the decision — in production this is automatic
   (the snapshot is built from already-received frames); `get_rti_return`
   selects on source timestamps, and the observation carries both
   `source_ts_ms` and `observed_ts_ms`. Historical reconstruction must
   enforce `recv_ts_ms ≤ t_decision` for the deployable arm and may report
   `src_ts_ms ≤ t_decision` as the source-time upper bound — never conflate
   the two (§6.4).
2. **Frozen snapshot:** the per-tick `FeatureSnapshot` is built once before
   agents evaluate; all five agents read identical BTC features — no
   intra-tick look-ahead. Agents evaluate sequentially but the snapshot does
   not refresh mid-tick.
3. **Leader-feed health gate:** if the BTC slice has
   `rti_execution_eligible=False`, stale `rti_age_ms`, or
   `feature_valid=False`, the record is still emitted with
   `feature_status` marking the deficiency and shadow probabilities null —
   the correction abstains rather than imputing.
4. **Abstention, never imputation:** missing features → null + reason.
   No zero-filling, no carry-forward.
5. **BTC control:** `asset=="BTC"` records are emitted (pooled dataset +
   placebo arm — BTC's own returns are already in `own_rti_ret_*`; there is
   no separate BTC-leader feature for BTC). The lead–lag correction is
   *defined* only for non-BTC assets.
6. **Two related hypotheses kept distinct:**
   - H1 forecast: does BTC information improve settlement-outcome prediction?
     → evaluate with and without market-implied features.
   - H2 market residual: does it identify mispricing beyond the quote?
     → evaluate only in the arm that includes market probability.
   Report both; do not let H2's market anchor contaminate H1 attribution.
7. **Phase slicing:** `pre_window` vs `in_window` results reported
   separately — once ≥1 settlement samples are banked, the marginal value of
   lead–lag on the *remaining-path* forecast mechanically shrinks. A
   correction that produces a material probability move when the remaining
   path has negligible plausible influence is flagged as a diagnostic, not
   silently clipped (a structural remaining-path model is a separate,
   later model — not part of this screen).

---

## 5. Model definitions — two explicit experiments

The `p_settle_raw` vs `p_final_yes` distinction is not an indicator-key
detail: it determines what the experiment claims to improve. A model that
beats `p_settle_raw` may add nothing beyond what the market-anchor,
walk-forward, EPC, and tail stages already accomplish.

| Arm | Baseline `p0` | Question |
|---|---|---|
| **Experiment A — mechanistic** | `p_settle_raw` (settlement-distribution probability; == `settlement_fair_prob`) | Do cross-asset observations add information beyond the settlement model itself? |
| **Experiment B — production incremental** | `p_final_yes` (final emitted probability the gates consumed; persisted as `calibrated_p_yes` in the audit DB) | Does the same information add value beyond the complete incumbent? |

For each experiment, three fitted variants on identical observations:

| Variant | Definition | Purpose |
|---|---|---|
| **P0** | baseline unchanged | Incumbent |
| **P0-cal** | `sigmoid(α + β·logit(p̃0))` (+ optional asset intercept), fit per fold | Recalibration control — separates "the flexible model repaired calibration" from genuine cross-asset information |
| **P1** | `sigmoid(logit(p̃0) + α_i + γ′C_t + β′R_BTC,t)` | Lead–lag residual, §5.1 |

`p̃0 = clip(p0, ε, 1−ε)` with `ε = MERID_MODEL_PROBABILITY_EPSILON`.

### 5.1 First-model specification (small, attribution-friendly)

For target assets ETH, SOL, XRP, DOGE:

```
logit(p̂) = logit(p̃0) + α_i + γ′C_t + β′R_BTC,t
```

- `R_BTC,t` = BTC RTI log-returns at h ∈ {1,3,10,30,60,120} s — pooled
  coefficients across assets (asset intercepts `α_i` only; no per-asset
  slopes on first pass).
- `C_t` controls: own-asset returns (same H), `z_score`, TTE, settlement
  phase, feed age/eligibility, market-implied probability where not already
  represented by the chosen baseline.
- Matched control `P1-minus-BTC`: identical structure without `R_BTC,t` —
  tests whether BTC adds beyond target-asset momentum.
- Regularization: L2 logistic regression; shrinkage fixed before evaluation.
- `g_θ` frozen per fold; artifact hash recorded per shadow record once
  mounted (`MERID_LEAD_LAG_MODEL_PATH`, mirroring the
  `MERID_Q0_CALIBRATOR_PATH` pattern).

**v1 is capture-only:** emit features + both baselines + gate outcomes;
shadow probabilities null until a frozen artifact is mounted.

**Insertion-point neutrality:** where a future production correction would
sit in the chain (pre- vs post-anchor, etc.) is a later architectural
decision. This experiment establishes whether the information exists at
all; it does not prescribe bypassing any stage.

---

## 6. Evaluation methodology

### 6.1 Data-provenance gate — BEFORE any regression

Produce a coverage-and-causality table preceding every performance table.
Required checks:

| Check | Why it matters |
|---|---|
| Common coverage across RTI, decisions, outcomes, books | 7 days of ticks ≠ 7 days of usable joined observations |
| Source AND receipt timestamp availability per join | Determines whether historical availability is known or inferred |
| Exact decision-to-feature anchoring | Prevents using updates that arrived after the decision |
| Model/calibration version changes over the window | Prevents mixing materially different incumbents |
| Route and candidate duplication | Prevents counting repeated evaluations as new outcomes |
| Missing-frame / forward-fill provenance | Distinguishes observed from reconstructed settlement state |
| Book freshness/depth coverage | Determines whether economic replay is credible |
| Settlement-label completeness | Avoids selective scoring of easily joined outcomes |

**Receipt-time causality is the consequential issue.** Source time is
necessary, not sufficient:

```
t_received ≤ t_decision     — deployability (required for any "would have
                              traded" claim)
t_source   ≤ t_decision     — signal existence (source-time screen only)
```

The RTI archive carries `recv_ts_ms`/`local_ts_ms`, so a receipt-time arm
is feasible offline — with the caveat that the archiver is a *separate*
WebSocket connection from the trading loop's; its receipt times approximate,
but do not equal, the frames the live adapter consumed. Conservative
treatment: primary historical arm = receipt-time with an added delivery
margin sensitivity (+100 ms, +500 ms); label all results accordingly. If
receipt provenance fails coverage, the correct next step is prospective
capture, not more model tuning.

Historical books must likewise anchor to what was available *at* the
decision — latest book state with receipt ts ≤ decision ts, never nearest
on either side.

### 6.2 Sampling structure — two complementary datasets

**Forecast dataset** (primary): observations at a small preregistered set
of TTE checkpoints — {600, 300, 120, 60} s before scheduled close, matching
the existing shadow/forecast-audit horizons — using the latest causally
available evaluation at or before each checkpoint (staleness bound
preregistered, e.g. ≤90 s, mirroring `max_age_s=90` convention). Assets and
expiries become comparable; high-evaluation-rate periods cannot dominate.

- Contract weighting: one observation per (ticker, checkpoint); if all
  evaluations are used as a secondary analysis, normalize weights so a
  heavily evaluated contract does not overwhelm a lightly evaluated one.
- Cluster unit for uncertainty: the contract settlement (all its
  checkpoints/evals are one cluster), then day, then quarter-hour block.

**Decision dataset** (secondary, economic questions): route-level
evaluations retaining the real decision constraints — existing positions,
route eligibility, cooldowns, repeated-candidate suppression, risk and
collateral limits, previously submitted orders. One contract must not
become hundreds of independently executable trades because its signal
persisted. Use `candidate_id` grouping + `strategy_decision_side_ev`
counterfactual-executability fields already in the schema.

### 6.3 Validation protocol

- Anchored, chronological, expanding-window folds; all assets sharing an
  expiry stay in the same fold; label overlap across boundaries removed;
  recalibration fitted inside the training process only.
- Freeze the specification **before** inspecting the last holdout block;
  once inspected it is no longer untouched for subsequent revisions.
- Fewer specifications, not more search: ~7 days ≈ ≤672 quarter-hour
  groups ≈ ≤3,360 contract outcomes across five assets — and those are not
  3,360 independent market environments. The ~163k decision rows are
  repeated observations of a much smaller outcome set.
- Paired loss differences per observation `j`:

  ```
  d_j = L(p_control,j, y_j) − L(p_LL,j, y_j)     # >0 favors lead–lag
  ```

  Report mean paired log-loss and Brier improvements, calibration by
  asset × phase × band, fold-by-fold results, correction-size distribution,
  latency-stress results, and per-day/per-expiry contribution. Resample
  the *same blocks* for both models; extend the existing ≥1800 s block
  bootstrap with day-level and longer-block sensitivity. Bootstrap cannot
  manufacture independent regimes from one week.

### 6.4 Falsification tests (run before interpreting any positive)

| Test | Interpretation |
|---|---|
| P0-cal vs P1 | Lead–lag vs generic probability repair |
| Own-return-only control (P1-minus-BTC) | BTC adds beyond target momentum |
| RTI-primary vs labeled spot ablation | Settlement-consistent vs external-price effects |
| Additional latency (+100/+500 ms) | Relationship survives information aging? |
| Fresh-book vs stale-book cohorts | Dependence on outdated quoted probabilities |
| Pre-window vs in-window | Gains respect settlement phase |
| Leave-one-day-out | Concentration in one market episode |
| **Future-shifted feature diagnostic** | Leakage test — pipeline must detect an obviously unavailable relationship; never an eligible arm. Preserve serial structure where practical; a fully randomized feature is too easy a benchmark |

### 6.5 Preregistered decision criteria (no arbitrary universal threshold)

Before evaluation, freeze:

1. Primary scoring metric (proposed: paired mean log-loss difference,
   Brier secondary).
2. Minimum useful effect for this project.
3. Uncertainty criterion (e.g., block-bootstrap LCB on paired difference).
4. Latency stress bound.
5. Maximum tolerable deterioration in important cohorts (per-asset,
   per-phase).
6/7. Evidence required to extend prospective collection; review date and
   stopping policy.

A useful result may be **inconclusive** — if uncertainty still includes
economically useful effects, the archive may simply be too short. One
profitable day is not a promising result if it explains nearly all the gain.

### 6.6 Economic gate — taker-first, indicative only

For each distinct eligible opportunity:

```
EV_shadow = p_shadow,side − a_executable − f_exact − c_existing
```

using executable asks and the existing exact fee/impact machinery
(`kalshi_fee_cents_exact`, role handling, `adverse_selection_reserve`, lane
floors, eligibility gates). Taker-first because it depends on no unvalidated
maker-fill model; this does not imply taker superiority. If archive books
lack depth/timing fidelity, stop at indicative economics and state the
limitation. Separate: forecast value (all eligible), economic value
(realistically executable), counterfactual value (rejected candidates via
`rejected_candidates.jsonl` semantics — "missed" ≠ fillable), and actual
settled-fill performance.

### 6.7 Screen outcomes → next action

| Outcome | Interpretation | Next action |
|---|---|---|
| Data invalid | Causality or joins cannot support inference | Fix provenance or capture prospectively |
| Futility | No useful incremental signal within tested scope | Park lead–lag; retain findings |
| Inconclusive | Sample too small or latency uncertain | Minimal prospective capture, no live effect |
| Promising | Stable incremental forecast value with plausible economics | Frozen prospective validation |

"No statistically significant result" is not automatically futility.

### 6.8 Freeze list before prospective validation

Feature definitions/horizons; baseline indicator keys; model & calibration
versions; retraining schedule; eligibility/abstention rules; evaluation
checkpoints and weighting; primary metric; economic replay assumptions;
review date and stopping policy. Prospective data is first a held-out
evaluation stream — repeated retraining/inspection turns it into
development data; retain later periods for evaluation.

---

## 7. Execution audit — maker shadow evidence classification

Requested alongside the design: do existing maker shadows measure
fill-conditioned outcomes, hypothetical fills, or shadow P&L?

| Lane | Record basis | Fill model | Evidence class |
|---|---|---|---|
| `pinned_fav_maker_shadow.py` → `logs/pinned_fav_maker_shadow.jsonl` + `scripts/pinned_fav_maker_shadow_report.py` | Own-side bid inside shadow band (85–91c) at each market eval | `"fill_assumption": "filled_at_bid"` — every qualifying observation counted as filled at the recorded bid; joined to settlement outcomes; bootstrap CI gates | **Hypothetical fills → shadow P&L.** NOT fill-conditioned: no queue position, no trade-through requirement, no fill-probability model. Covariates recorded (`locked_book`, spread, quote_age_ms, depth) could support an offline fill model but none is applied. |
| `late_window_shadow.py` → `logs/late_window_shadow.jsonl` | TTE-floor rejections in 30–90 s band with executable quotes | Offline replay "prices a post-only maker fill at the recorded quotes" **plus a fixed 1–2 c execution/adverse-selection stress** | **Hypothetical fills + fixed haircut.** Constant stress, not measured fill conditioning. |
| `tail_band_shadow.py` → `logs/tail_band_shadow.jsonl` + `scripts/tail_band_ab_evaluation.py` | Canonical-rejected decisions in favorite/longshot bands | Settlement-joined realized P&L per band under the record's price | **Shadow P&L on assumed fills** (pre-registered gates). |
| `lwf_shadow_lane.py` → `logs/lwf_shadow.jsonl` | Lane-contract audit at 120–150 s TTE, taker-economics basis | Records lane verdicts/economics PASS-FAIL per side | **Lane-contract shadow records** (forecast + gate audit), not a fill simulation. |
| `shadow_evaluator.py` scheduled shadows | Unchanged production chain at fixed horizons | N/A — forecast events only | **Forecast telemetry**, not execution evidence. |

**Genuine fill-conditioned evidence exists only where real orders were
sent:**

- The live pinned-fav maker band produces real post-only orders → real fills
  → settled outcomes (audited cohorts behind e.g. the 2026-10-31 floor
  raise; `MERID_PINNED_FAV_AUDIT_2026-11-05.md`).
- The 2026-09-23 maker-entry audit measured fill conditioning directly on
  real orders: filled resting entries settled 41% vs 67% for unfilled —
  motivating the default-off maker-entry lane (`agent_grid_15m.py:9228-9236`).
  **Caveat for reuse:** win-rate differences alone are not a causal
  adverse-selection estimate — the cohorts must first be shown comparable
  on traded side, entry price, predicted probability, asset, TTE, quote age,
  volatility, cancellation policy, and event/day before the gap is read as
  selection cost.

**Conclusion:** no existing shadow lane measures `P(fill | quote state)` or
conditions outcomes on queue/trade-through dynamics. All sub-live-band
maker evidence is **hypothetical-execution shadow P&L**; fill-conditioned
measurement exists only for cohorts that actually traded. Maker execution
is therefore a **separate research track**: for actual-order cohorts,
estimate `E[Y_side − P_entry − F | filled, X]` and post-fill
price/probability changes at predefined horizons; for fill modeling, orders
need acceptance time, partial executions, cancellation timing, and book/trade
context. Do not create live maker orders solely for research labels without
the required approval; reuse authorized actual-order data and keep
hypothetical execution explicitly hypothetical.

---

## 8. No-live-effect constraints (summary)

- New module `merid/prediction/lead_lag_shadow.py`, write-only JSONL,
  exception-safe, no router/risk/allocator/cap interaction.
- Called only from `_call_trade_decision` post-decision; never mutates
  `decision`, `market_state`, or `feature_snapshot` (all reads).
- Env flags: `MERID_LEAD_LAG_SHADOW_ENABLED` (default `1`, consistent with
  peer shadows), `MERID_LEAD_LAG_SHADOW_LOG_PATH`,
  `MERID_LEAD_LAG_MODEL_PATH` (unset → unfitted capture mode),
  `MERID_LEAD_LAG_MODEL_MAX_INFER_MS` budget once fitted.
- Model artifacts, when they exist, are frozen files with recorded hashes —
  same provenance discipline as `MERID_Q0_CALIBRATOR_PATH`.

## 9. Acceptance evidence → existing release gate

The lane's output is *evidence*, not a promotion path. Mapping to the
AGENTS.md model-release requirements:

| Required evidence | Produced by |
|---|---|
| Settled-fill / forecast calibration on live population | §6.2–6.3 forecast evaluation on shadow records joined to `settlement_outcomes.jsonl` |
| Veto-counterfactual audit | `rejected_candidates.jsonl` semantics — forecast content only, never fill implication |
| Executable net-of-cost replay | §6.6 taker-first through existing fee/EV/floor machinery |
| Chronological stability / regime dependence | walk-forward folds + block bootstrap, phase/asset/day slicing |
| Documented approval | unchanged — promotion requires the existing audited release process; enabling a hybrid signal source remains a separate, explicit config/model-release change (`live_config.py` probability-source allowlist) |

The shadow lane itself can never satisfy or bypass any live-entry gate.

## 10. Open decisions to freeze at preregistration

1. ~~Primary anchor~~ — resolved: `p_final_yes` primary for economics;
   `p_settle_raw` mechanistic arm (§5).
2. Horizon set H = {1,3,10,30,60,120} s — confirm availability at the
   shortest TTEs (late-window evals may lack 120 s history →
   `feature_status=partial`, still recorded).
3. Whether `market_anchor_prob` enters H1 at all — excluded from the
   primary arm; the with/without pair is reported (§6.4 freshness cohort).
4. Fitted-model class — regularized logistic on the preregistered set;
   pooled BTC coefficients, asset intercepts only.
5. `p_final_yes` exact persisted key — verify `fe_final_p_yes` vs
   `decision.p_yes_calibrated` agree on production rows before freezing.
