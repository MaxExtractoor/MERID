# Version-Aware Evidence Audit — 2026-11-05

Purpose: reclassify every historical lane/bucket finding by bug exposure,
component version, and measurement validity. Accounting truth (what traded)
is preserved separately from strategy-validation evidence (what it proves
about the current build).

## 1. Bug & deployment timeline (verified anchors)

| id | component | affected interval | detection signature | contaminates | still valid |
|---|---|---|---|---|---|
| B1 | sizer shard/cash resolution gap (`loop_15m` ~7192: `_shard=None` skips cap; cache misses) | stake-cap intro 10-30 → 11-05 patch committed, **not deployed** | uniform `count_fp=6.0` attempts, 74 records/41 unique opps rejected `stake_at_risk_cap` | sizing, exposure, submission rate | pre-trade p, settlement labels |
| B2 | sizing cash staleness (`fresh_cached_shard_cash` 15s vs 60s funding cycle) | until 11-05 patch | cap silently inoperative ~75% of cycles (code comment 11-02) | sizing correctness | outcome reliability |
| B3 | execution-layer fixes 11-02 (retry wire identity, uncertain-outcome preservation, fractional resting orders, post-send exposure retention, response-qty validation, duplicate ownership) | pre-11-02 attempts | commit cluster 0da71e0b..4f730c41 | attempt/fill attribution, P&L reconciliation pre-11-02 | forecasts, settlements |
| B4 | orderbook_sequence_gap / not_initialized integrity state | ongoing (76% of invalid_confidence) | confidence_valid fails, DATA_QUALITY_VETO | executable-price counterfactuals, maker fill models | settlement labels; forecasts iff inputs unaffected |
| B5 | INPUTS_MISSING vol_source below ~150s TTE | continuous | p=0.5 placeholder on all sub-150s shadow rows | all low-TTE forecast calibration | nothing below floor — no valid p exists |
| B6 | ENTER side-attribution in *my* audit script (counter-side evals labeled ENTER) | earlier report only — not a system bug | phantom sub-10¢ "entries" | prior ENTER-by-bucket table (corrected) | system `sel` field is correct |
| C1 | pf floor epochs: ≤90 →10-24→ 90 →10-28→ 92 →10-31→ 94 | config epochs | .env / AGENTS history | cross-epoch pooling of "in-band" results | per-epoch analysis |
| C2 | NO-side lane moneyness mirror caps | 10-27 / 10-30 (XRP probe) | `pinned_fav_moneyness_cap` reason mix | NO-side veto comparisons across epochs | per-epoch |
| C3 | stake cap 0.35 introduced | 10-30 | first `stake_at_risk_cap` rejections | submission-rate comparisons pre/post | — |
| C4 | Stage B clip patch | committed 11-05 ~18:15, **process predates → not deployed** | no post-18:15 attempts; last attempt 12:34 | — | post-restart = verified-current cohort |

## 2. Cohort classification of existing findings

**Verified unaffected (usable as-is):**
- Settlement labels for all settled tickers (settlement map independent of
  every bug above).
- Recorded `p_selected` values on rows where B4/B5 did not fire — forecast
  calibration on valid-input evals.
- The 90-episode pf reliability table, *as an Oct-25-26 floor-90-epoch
  measurement* — pending C1 epoch framing (see downgrades).

**Reconstructed:**
- Unique-episode ENTER economics (B6 corrected via sel-side filter).
- Stake-cap missed-submission counterfactual (B1): 74 records → 41 unique
  opps; clip math verified, but fill/executable outcome stays *unknown* —
  do not book as missed P&L.

**Contaminated or unknown:**
- Pre-11-02 attempt/fill attribution for sizing/exposure analysis (B3 era).
- Maker counterfactuals on any B4-affected book state.
- All sub-150s TTE forecast cells (B5 — no valid p).
- Polling-row-level statistics (must dedupe — done in current scripts).

**Verified current deployment:** EMPTY — nothing post-dates the un-deployed
Stage B patch. First post-restart submissions start this cohort.

## 3. Downgraded conclusions (per instruction)

| prior wording | reclassified status |
|---|---|
| "94¢ is a calibration boundary" | single-epoch (floor-90) historical hypothesis; 20 eps below-floor; needs replication on floor-92/94 epochs + verified-current data |
| "cross-lane confirms the boundary" | generic 90–100/0.80–0.90 cell (n=11, +0.23) is *not* a matched cohort — different px band, p band, and lanes share the same model+feed so it isn't independent confirmation |
| "60–80¢ under-confidence across 4 lanes" | candidate pattern; lanes share one model/input pipeline → one defect could produce all four; clean version-specific replication required |
| "0–10¢ tails calibrated (n=186)" | reported historical reliability, pending cohort-validity + CI review |
| "drift_fav restrict/recalibrate" | losses may reflect B1/B3-era plumbing; holds only if they persist in unaffected/reconstructed cohorts |
| "maker_bid 8/8 margin" | small historical winning cohort; no basis for current execution margin |

## 4. What each pending question now requires

- Lane floor/band changes: evidence from ≥2 config epochs AND verified-current.
- cheap_no 20–40¢ "profitable" cells: maker-fill counterfactual on B4-clean
  book states only; settlement-view stays labeled as such.
- EV haircut decomposition: instrument components first; current 1.47–7.09¢
  adder variance is unexplained, so any single-epoch fit is untrustworthy.
- Model recalibration: chronological split keeping same event out of
  multiple partitions; freeze rules before testing on later epochs.

## 5. Standing constraints (unchanged)

- No production restart without explicit authorization (Stage B unverified).
- No veto loosening, band expansion, or EV-floor change from contaminated or
  single-epoch evidence.
- Keep safeguards that exist for accounting reasons even where their
  historical justification is under review — absence of proof ≠ proof of
  absence.
