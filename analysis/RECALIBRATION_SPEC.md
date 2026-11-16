# Two-Sided Probability Recalibration — Implementation Spec

**Status:** approved direction (operator), pending implementation
**Motivation:** Brier test (n=6,132 settled decisions) showed model ≈ market (0.1323 vs 0.1336) — no incremental info — AND a reliability S-curve: over-confident on low `p_yes`, under-confident on high `p_yes` (forecast 0.75 → observed 0.92). Root cause is architectural: the entire calibration stack is **cap-only / tighten-only** and cannot raise an under-confident claim.

## Existing calibration stack (do NOT replace — extend)

| Layer | File / symbol | Behavior |
|---|---|---|
| PAVA cap artifact | `data/probability_tail_calibration.json` via `load_tail_calibrator()` → `cap_p_yes`/`cap_p_no` | Caps `p` at `observed_win_rate + MERID_TAIL_CALIBRATION_BUFFER` (0.05); full-range since `MERID_CALIBRATION_CAP_FULL_RANGE=1` |
| Streaming bound | `merid/prediction/streaming_calibration.py` → `streaming_bound_detail` | Per asset×side×price×TTE, PAV-monotone, tighten-only, rebuilt each settlement |
| Walk-forward | `_WALKFWD_CAL_PATH`, `MERID_WALKFWD_CAL_ENABLED` | `C_{asset,tte}(p_raw)` on settled data |
| Deviation guard | `MERID_TAIL_CALIBRATION_DEVIATION_GUARD` (0.15) | Fail-closed on probability *inflation* outside tail |
| Venue clamp | `_lane_p_lo/_lane_p_hi` | [0.05,0.95] normal, lane-aware up to 0.99 |

Applied in `merid/prediction/trade_decision.py` ~lines 4430–4523 (`p_yes_for_yes`, `p_no_for_no` post-tail-cap), then streaming bound ~4532+, then drift reserve ~4576+, then `compute_edge` ~5065.

## The defect

`cap_p_yes`/`cap_p_no` only ever *reduce* `p`. When a bucket's observed win-rate is **higher** than the model claim (under-confidence at the high end), no layer can raise `p` toward the observed rate — so genuine edge is structurally suppressed. Symmetrically, the cap relies on an artifact fitted on a stale cohort (documented Aug–Sep window) and may under-correct current over-confidence.

## Fix design — bounded, two-sided, evidence-gated

Add a **lift** path alongside the existing cap, inside the SAME calibrator and SAME evidence discipline as `edge_bias` (`evidence_policy.py`):

1. **Refit artifact on current settled cohort.** Re-run `scripts/calibrate_tail_probability.py` (or its successor) against the merged fill+veto+settlement cohort covering the recent regime — do not reuse the Aug–Sep fit. Output must carry per-bucket `n_eff`, `observed_win_rate`, and a `lift`/`cap` delta vs model claim.

2. **Lift rule (new, in `cap_p_yes`/`cap_p_no` or a sibling `adjust_p_*`):**
   - For each asset×side×price×TTE bucket, compute `gap = observed_win_rate − model_claim`.
   - **Cap side (existing):** if `gap < 0` (over-confident), shrink `p` down toward `observed + buffer` — unchanged behavior.
   - **Lift side (new):** if `gap > 0` (under-confident) AND `n_eff >= MERID_RECAL_MIN_NEFF` (new env, default ~12, mirror `EDGE_BIAS_MIN_NEFF`) AND the lift is statistically significant (|gap| > z·SE, reuse `EDGE_BIAS_REBATE_Z` pattern), raise `p` toward `observed − buffer`, **shrunk** by `n_eff/(n_eff + PRIOR_K)` exactly like `edge_bias_correction_cents`.
   - Hard bounds: lift ≤ `MERID_RECAL_LIFT_CAP` (default ~0.10 prob), never above venue `_lane_p_hi`, never lift a settlement-lane `p_yes_raw` (lane keeps its own ceiling — preserve the 2026-10-19 invariant at trade_decision.py:5040).

3. **Env knobs (add to `live_config.py` + `.env`):**
   - `MERID_RECAL_TWO_SIDED` (default `0` — ship dark, enable after shadow)
   - `MERID_RECAL_MIN_NEFF` (default 12)
   - `MERID_RECAL_LIFT_CAP` (default 0.10)
   - `MERID_RECAL_PRIOR_K` (default 8)
   - `MERID_RECAL_LIFT_Z` (default 1.0)

4. **Ordering invariant:** lift applies at the SAME point as the existing cap (post-tail-cap, pre-streaming-bound, pre-clamp). The streaming tighten-only bound still applies AFTER — so a lift can never exceed the freshest settlement-derived bound. Deviation guard still fires on *inflation* — a legitimate lift that crosses the guard must be allow-listed by bucket evidence (add `recal_lift_applied` indicator + reason so the guard/audit can distinguish measured lift from inflation).

## Tests (new file `merid/tests/test_two_sided_recal.py` or extend existing)

- Unit: `cap_p_yes`/`cap_p_no` (or new `adjust`) returns unchanged when `gap≈0`, caps when over-confident, lifts when under-confident + sufficient `n_eff`, does NOT lift below `MIN_NEFF`, respects `LIFT_CAP` and venue clamp, never lifts settlement-lane path.
- Shrinkage: lift magnitude scales with `n_eff/(n_eff+PRIOR_K)`.
- Regression: existing cap-only behavior identical when `MERID_RECAL_TWO_SIDED=0`.
- Integration: a synthetic decision where under-confident bucket produces higher `p_selected` → higher `net_edge` only when two-sided enabled.

## Rollout gates (do NOT skip)

1. Ship `MERID_RECAL_TWO_SIDED=0` (dark). Refit artifact; verify lift/cap deltas are sane per bucket.
2. Shadow/A-B: run with flag off vs on over a settled window; compare Brier (model vs market) and net-edge distribution — lift must improve Brier without inflating loss tail.
3. Enable `=1` only if shadow shows Brier improvement AND no adverse-selection/markout regression.
4. Keep `MERID_RECAL_LIFT_CAP` conservative; the lift exists to capture *measured* under-confidence, not to manufacture edge.

## Explicit non-goals

- Do NOT touch `compute_edge` reserve math, gate thresholds, moneyness caps, or order routing.
- Do NOT lift settlement-lane or pinned-fav lane probabilities (they have their own audited ceilings).
- Do NOT change the deviation guard's fail-closed semantics — only exempt *evidenced* lifts.
- This improves forecast accuracy; it does NOT by itself create edge (model must still beat market+costs). Expect modest effect.
