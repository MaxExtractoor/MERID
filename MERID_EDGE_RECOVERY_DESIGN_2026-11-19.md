# Edge-Recovery Design — literature-grounded solutions for the four open items

**Date:** 2026-11-19. **Status:** design + recommendations; only verification
checks executed. Companion to `MERID_NO_TRADE_FORENSICS_2026-11-18.md` (which
measured the blockers) — this document picks the fixes.

---

## 1. Deviation-adaptive market anchor (the parity machine)

### What the literature says

**Logit-space pooling is correct; fixed weights are not.** The system already
blends in logit space, which is the right geometry — Ranjan & Gneiting (2010)
prove that *linear* pooling of two calibrated forecasts is necessarily
miscalibrated, so the logit blend avoids a real defect. The defect is the
**weight**: `MIN_W=0.25→MAX_W=0.85` over 900s is a hard-coded precision
assumption, and precision is not constant.

**Precision weighting (DerSimonian–Laird / inverse-variance).** The Bayesian-
correct blend is `w = τ_mkt / (τ_mkt + τ_model)` — weight each forecaster by
its precision *in that context*. The market's precision is **state-dependent**:
a tight, deep, freshly-quoted book has high precision; a wide, stale, thin
book after a spot move has low precision. `w` should be computed from book
state, not wall clock.

**Satopää partial-information / extremization (2014).** When forecasters share
information (model and book both track the same spot process), any
central-tendency aggregate is provably inefficient — it throws away the part
of the disagreement that is *real signal*. But extremizing blindly is also
wrong: disagreement is signal only when it is *attributable* — i.e., when you
can say which side is stale. The right structure is: **attribute the
disagreement first** (who's stale?), then weight.

**Online expert weighting (Hedge / Vovk Aggregating Algorithm).** The
minimax-optimal way to split weight between two forecasters online is
exponential weights on their realized losses. **MERID has the exact data for
this**: every evaluated side — traded or not — is scored against settlement
(`side_ev` + `strategy_decision_outcomes`). No selection bias, no exploration
cost. Per-(asset × TTE-bucket) online Brier scores of `market_mid` vs
`p_raw` give a *measured* market-precision term to replace the fixed ramp.

### Measured basis (forensics doc §F1)

- Mid-band: market ≈ realized within ±0.5% — anchor is protective; keep it.
- Tail (`|raw−mkt|>5c`): realized beat market +3.8% (n=600) — the raw model
  caught real mispricing; the anchor pulled it back to a wrong book.
- The tail signal is almost certainly **book staleness after spot moves**:
  large raw-vs-market disagreement clusters right after spot reprices faster
  than the Kalshi book does.

### Recommended design (three layers, each independently flag-gated)

1. **Staleness-conditioned market precision (do first — mechanism, not
   symptom).** Scale `w` down when the book quote is stale relative to spot:
   `w *= staleness_factor(ws_age_ms, spread_c, depth_cc, spot_move_sigma)`.
   Inputs already exist in `market_state` (`ws_age_ms`, `rest_age_ms`,
   spread, depth, `book_health`). Cheap, defensive, no new model risk.
   Implementation point: `trade_decision.py:4385-4428`, same block as the
   existing `MERID_SETTLEMENT_ANCHOR_RELEASE` scaling — one more multiplicative
   factor, fail-closed to current behavior when inputs are missing.

2. **Online Brier expert-weighting (shadow first).** New module
   `merid/prediction/anchor_weight_learner.py`: consumes settled evals from
   the audit DB (a consumer like `model_calibration_log`), maintains
   EWMA Brier scores `B_mkt`, `B_model` per (asset, tte-bucket), publishes
   `w_mkt = clip(σ(κ·(B_model−B_mkt)), w_floor, w_cap)` to a JSON artifact the
   decision layer reads (mtime-reload, same pattern as the EPC artifact).
   Ship in **shadow mode**: compute and log `w_learned` alongside the fixed
   ramp; flip `MERID_ANCHOR_WEIGHT_MODE=learned` only after the artifact
   shows the learned weight tracking realized performance. Defaults:
   `w_floor=0.15, w_cap=0.85`, EWMA halflife ≈ 2 days (~190 settlements).

3. **Disagreement release (last, optional).** Only if 1+2 leave tail alpha
   on the table: when |raw−mkt| > κ AND staleness factor is low (fresh book
   genuinely disagrees with model — rare), allow the model's weight to
   exceed the cap. This is the Satopää case — but it needs the attribution
   machinery from steps 1–2 to distinguish "model right" from "model noise".

**What NOT to do:** don't crank `MIN/MAX_W` down flat — mid-band the market
*is* the best estimate; don't extremize toward raw deviations — the <−5c
bucket showed the raw model *wrong* directionally (realized +2.3% vs market,
−5% vs raw).

---

## 2. EPC shadow→live — blocked by staleness, not by evidence

**Discovery:** `MERID_EMPIRICAL_CAL_PATH=data/epc_wide_fit.json` is **25 days
old**, past the 14-day `MERID_EMPIRICAL_CAL_MAX_AGE_DAYS` fail-closed gate.
The overlay is a **no-op right now** — even shadow lookups return miss, and
`empirical_cal_observations.jsonl` confirms it (last row Nov 7 ≈ artifact
date + 14d). The promotion question is upstream of mode: **the artifact must
be refit before anything can be promoted.**

### Champion-challenger protocol (literature: shadow → gated promotion → canary)

1. **Refit** via `scripts/fit_empirical_price_calibration.py` on the recent
   window (walk-forward splits already built in). Check `epc_wide_fit.json`'s
   own LCB cells against the post-Oct-24 settlement data for confirmation.
2. **Shadow-verify**: restore fresh artifact → shadow mode emits
   observations again → accumulate ≥N settled cell-matches
   (the pipeline already logs `cell_id`, `p_model` per eval).
3. **Promote per-cell, not globally.** `epc_wide_fit` has 128 cells; promote
   only cells whose OOS lower-confidence edge is positive on the fresh fit
   AND confirmed by ≥N live shadow observations. The artifact schema carries
   `edge_lcb_c` per cell — use it as the per-cell promotion key
   (e.g. `MERID_EPC_LIVE_CELLS=epc_no_50_59_m3,epc_no_60_69_m4,…` or a
   `min_lcb` threshold field in the artifact).
4. **Canary is already built in**: EPC only substitutes p; the bounded-lane
   caps, evidence gates, and reserve stack still bind every admit — a live
   cell can't size beyond existing caps. Rollback is the mode flag.
5. **Recurring staleness**: schedule the refit (weekly) — a
   `stale_artifact` alarm belongs in the health surface; today's failure was
   silent for 11 days.

**Expected effect:** the 103k-observation fit claims +LCB edge in the
favorite-tail cells — the same pocket where the anchor-tail measurement
found +3.8%. These are the two independent measurements agreeing.

---

## 3. Evidence cells — epoch boundary + exploration budget (not a bulk reset)

### What the literature says

Non-stationary-bandit theory (Garivier & Moulines): for **abrupt** regime
change, sliding-window/hard boundaries beat discounting; for **gradual**
drift, discounting (D-UCB) suffices. The 2025 empirical comparison
(arXiv:2511.19240) is blunter: pure discounting can suffer learning failure
under abrupt change, while windowed/epoch views stay robust.

**Config change = abrupt drift.** A toxic cell built by the retired
probe-config admits is *correct evidence about a different policy* — it must
not bind admits under the new config. That is exactly what the
`pinned_fav_measured_loss` fix did by hand (veto scoped to the
negative-edge tier). The systematization is an **epoch key**, not a reset.

### Recommended design

1. **Config-epoch keying (preferred over reset).** Cells already carry
   `policy_epoch` on outcomes. Make the veto paths compare only outcomes
   whose `policy_epoch` matches the admit's lane-config signature
   (a compact hash of the lane's admission-affecting env vars, or an
   explicit `MERID_EVIDENCE_EPOCH` bumped on lane-config changes). Same
   effect as a reset but *auditable and reversible* — old evidence stays
   for telemetry; nothing is deleted.
2. **Keep the rehab probe as the exploration arm — but it needs a real
   budget.** Today a probe only fires when a candidate reaches the evidence
   check (i.e., already cleared economics). Per the forced-exploration
   literature, allocate a bounded probe budget that doesn't require the
   full edge floor: e.g. `MERID_REHAB_PROBE_MAX_EV_FLOOR=-2c` on a
   dedicated 1-contract probe lane, still inside `BOUNDED_POST_ONLY_LANES`
   caps. The probe's job is *measurement*, not profit — pricing it like a
   trade is what starves it.
3. **Bulk cell reset: reject.** It erases the protection the cells encode
   (they *did* measure real losses) and can't distinguish cells poisoned by
   config vs cells honestly toxic under current config. Epoch keying gets
   the same benefit without the blast radius.

---

## 4. Quarantine sweep — triage by failure fingerprint, release by class

DLQ-replay doctrine (industry consensus): **never bulk-redrive; classify by
failure fingerprint, release recoverable classes in batches, keep poison.**

### Recommended procedure

1. **Classify** the 205 order-attempt + 25 exit quarantines by root-cause
   fingerprint. Expected classes: (a) transient-infra (loop stall, WS gap,
   DB contention — the F2 environment), (b) `submission_unknown`
   reconciliations already resolved, (c) semantic/integrity defects
   (side-mapping, provenance — *these stay*).
2. **Release rule per class:**
   - (a)+(b): releasable after a verified-flat or verified-filled three-way
     match (venue REST ↔ position_cache ↔ fills_ledger) — the mechanism
     `position_cache` already uses to clear `_reconciliation_halted`.
   - (c): permanent quarantine; these are the guard working as designed.
3. **Order attempts vs exits are different stores.** Order attempts
   (`kalshi_fills.db` quarantine markers / router state) are safe to clear
   once their ticker is verified — a cleared attempt only unblocks *future*
   entries. Exit quarantines (`position_cache._quarantined_tickers`) must
   each be re-verified against live venue positions before release.
4. **Batch + audit**: release in batches of ~25, reconcile between batches,
   keep a manifest (`data/quarantine_sweep_<date>.json` with per-item
   fingerprint, decision, verification evidence). Reversal = re-quarantine
   from the manifest.
5. **Precondition**: do this *while* the current healthy runtime is up —
   reconciliation needs live venue reads.

**Non-negotiable:** the sweep is verification, not deletion. Any attempt
whose terminal state can't be confirmed stays quarantined — an unresolved
`submission_unknown` is evidence, not debris.

---

## Sequencing

| Order | Item | Effort | Risk |
|-------|------|--------|------|
| 1 | EPC refit + staleness alarm | script exists | none (shadow) |
| 2 | Anchor staleness factor (layer 1) | small, live-path, flag-gated | low |
| 3 | Quarantine triage + batch release | procedure + manifest | low-med |
| 4 | Evidence epoch keying | medium, evidence-layer | medium |
| 5 | Online Brier anchor learner (shadow) | new module + artifact | none live |
| 6 | EPC per-cell promotion | after 1 + shadow window | bounded |
| 7 | Rehab probe exploration budget | after 4 | bounded |
| 8 | Disagreement release (anchor layer 3) | only if needed | high |

Items 1, 2, 3, 5 are safe to implement now (shadow/flag-gated or procedural).
4 needs the epoch-signature design reviewed. 6–8 gate on measured results.
