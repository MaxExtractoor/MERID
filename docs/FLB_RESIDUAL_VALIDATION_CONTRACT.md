# FLB Residual Validation Contract (Frozen)

Status: FROZEN — awaiting post-v4 settled-candidate accumulation.
Purpose: determine how much price-conditional shortfall remains after the
current correction stack (tail cap + streaming bound + calib_gap) and the
non-FLB deductions, before changing `MERID_FLB_LONGSHOT_SLOPE` or the band
policy. Production policy is unchanged; all variants run offline only.

## Scope and data

- Records: post-v4 `decision_telemetry.jsonl` decision_records only
  (`yes/no_p_selected`, `fe_*` stage chain, per-component cost ledger,
  threshold decomposition). No pre-v4 fallback reconstructions.
- Domain: purchased-side entry price < 35c (the FLB domain), both sides.
- Required per-decision fields (reject record if missing):
  asset, side, entry_price_cents, seconds_to_expiry, market_id/ticker,
  decision_ts, model_version, calibration_version, config_version,
  p_selected (bounded), p_point (pre-bound estimate where emitted),
  every ledger component (entry_fee, exit_cost_reserve, model_risk_reserve,
  adverse_selection_reserve, policy_giveback_reserve, impl_shortfall_reserve,
  edge_bias_correction), required_edge decomposition incl. flb_premium,
  settlement outcome + counterfactual PnL basis.
- Artifact versions recorded per record; analysis must be separable by
  (model_version, calibration_version, config_version).

## Partition rules (both required)

- Chronological: fit period strictly precedes evaluation period.
- Market-grouped: every ticker belongs wholly to fit OR eval (split at
  settlement time). No ticker may appear in both; both sides of a ticker stay
  in the same partition. 60s-bucket dedupe alone is NOT sufficient.
- Label availability: every fit label settled before the earliest eval
  decision timestamp. Assert max(fit.close_ts) < min(evl.decision_ts).
- Learned inputs (calibration artifact, streaming bounds, evidence artifact)
  must be reconstructed to their fit-period state, or the study is labeled
  current-policy replay and no out-of-sample claim is made.

## Opportunity definition

- One entry per (ticker, side): first eligible decision (fixed entry rule).
- No repeated-snapshot accumulation. Repeated observations of one market are
  diagnostics, not independent trades.
- Report: unique tickers, unique settlement intervals, admissions per ticker,
  max simultaneous exposure, contract quantity, total capital assumed,
  fee and execution assumptions (ask fill vs counterfactual fill model).

## Variants (all four, on identical inputs)

1. CURRENT_FLB — production hurdle as recorded.
2. ZERO_FLB — flb_premium removed from required_edge; all else unchanged.
3. NONNEGATIVE_RESIDUAL_FLB — residual penalty fitted on fit period,
   clipped at 0. Invariant test: admissions(NONNEG) <= admissions(ZERO).
4. SIGNED_RESIDUAL_ADJUSTMENT — the signed version, explicitly labeled an
   admission-subsidy experiment, reported separately; never described as
   "less conservative FLB".

Candidate-level export for every variant: ticker, side, px, nev,
H_with_FLB, H_exFLB, residual_charge, threshold_delta, admission_change,
counterfactual_pnl. Assertions: mutually-exclusive outcome counts sum to
evaluated side count.

## Residual target decomposition (no conflation)

Compute and report separately, per price bucket:
- probability_residual = p_selected_side − realized_outcome (0/1)
- execution_residual = actual/simulated fill − decision executable price
  (ask basis; fees separate)
- policy_payoff_residual = expected payoff under the actual exit/hold rule
  − realized payoff under the same rule
- admission_buffer = explicit policy margin (required_edge terms), labeled
  conservatism choice, not an expected loss.

The FLB refit target is the residual admission shortfall AFTER the other
components — NOT (historical nev − cf_pnl) when nev embeds reserve buffers.

## Uncertainty

- Cluster-robust standard errors by ticker (settlement group).
- Report SE basis explicitly; row-level SEs are invalid under
  within-market correlation.
- Sparse buckets (<30 opportunities) must be pooled; no standalone
  coefficients from n<30 buckets.

## Decision rule for changing production

FLB may be refit or removed only if, on untouched eval markets with
frozen artifacts:
- the residual penalty is nonzero and positive where the current charge binds, OR
- ZERO_FLB admits a cohort whose opportunity-level PnL is positive with
  cluster-robust significance (|mean| >= 2*SE),
- AND all downstream gates in replay confirm executability assumptions.

A negative or zero fitted residual alone justifies demoting FLB to
"unproven prior" in documentation — it does not by itself authorize
removal or replacement.

## Known prior artifacts

- logs/flb_study_extract.jsonl — 377,486 sub-35c settled side-ev rows
  (mixed vintages; superseded for final decision, retained for diagnosis).
- logs/signed_adj_extra_admissions.csv — the 309 admissions attributable
  purely to the signed subsidy.
- logs/reserve_validation_export.csv — post-v4 ledger rows.
- Fit-period bucket census (historical, deduped first-entry):
  0-4c:296, 5-9c:5, 10-14c:15, 15-19c:20, 20-24c:51, 25-29c:149, 30-34c:1255
  — mid-tail buckets are sparse; prior bucket means carry low n.
