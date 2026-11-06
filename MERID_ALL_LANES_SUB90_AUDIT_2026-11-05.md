# All-Lane Below-90¢ Calibration, Execution, and Gate Audit — 2026-11-05

Dataset: `_pf_audit_decisions.jsonl` Oct 25–26 extract (111,395 decision rows),
unique-episode view by (lane, ticker, side), last-observation forecast, joined
to `settlement_outcomes.jsonl` (47,814 tickers). Purchased-side normalized:
win = the evaluated side's settlement result; px bucket = purchased-contract
price reconstructed as `implied_px = p·100 − gross_edge_cents` (reconstructed —
verify `gross_edge` definition/units before policy use). Forecast-reliability
results only; maker fillability and taker VWAP not measurable here.

## Lane inventory observed in-window (from decision records)

| lane | decision rows | real ENTER eps | price domain seen |
|---|---|---|---|
| generic (normal path) | 108,411 | — | all buckets incl. 0–10¢ |
| pinned_fav | 1,674 | 44 (90–100¢ only) | 90–100¢ + counter-side |
| maker_bid | 545 | 13 | 20–80¢ entries; wins 60–80¢ |
| empirical_marginal_maker | 468 | 1 | evals 10–80¢ |
| cheap_no_settle | 194 | 31 | 20–40¢ entries |
| drift_fav | 98 | 43 | 40–80¢ entries |
| current_build_provisional | 5 | 3 | 40–50¢ |
| evidence_pooled_transfer / evidence_escape / threshold_cell (owners) | ~240 | 0 | shadow/eval only |

Not seen in-window (config exists, no decisions recorded): settlement-lane,
mband, cheap_tail_canary, canary_4c_lcb, live_canary (all OFF per AGENTS).

## Denominator reconciliation (prior report)

90 pf settled episodes = 24 (94–98¢) + 20 (90–93¢) + 40 (<90¢ counter-side) +
6 unpriced. The 45 unique ENTER episodes ⊂ evaluated episodes: ENTER = 44
in-band + 1 unpriced; all 90 include non-entered side evals.

## Reliability: lane × purchased-px × p-band (selected cells; full table in `_all_lanes_out.txt`)

**Overconfidence pockets (positive gap = predicted > observed):**
| lane | px | p-band | n | win% | mean_p | gap |
|---|---|---|---|---|---|---|
| pinned_fav | 90–100 | 0.80–0.90 | 10 | 50% | 0.882 | +0.38 |
| pinned_fav | 90–100 | 0.90–0.95 | 15 | 80% | 0.926 | +0.13 |
| generic | 90–100 | 0.80–0.90 | 11 | 64% | 0.867 | +0.23 |
| drift_fav | 50–60 | 0.50–0.80 | 12 | 33% | 0.560 | +0.23 |

**Under-confidence pockets (model understates favorites):**
| lane | px | p-band | n | win% | mean_p | gap |
|---|---|---|---|---|---|---|
| empirical_marginal_maker | 60–70 | 0.50–0.80 | 20 | 85% | 0.650 | −0.20 |
| generic | 60–70 | 0.50–0.80 | 12 | 83% | 0.608 | −0.23 |
| drift_fav | 40–50 | <0.50 | 12 | 67% | 0.384 | −0.28 |
| maker_bid | 60–70 | 0.50–0.80 | 21 | 81% | 0.659 | −0.15 |
| cheap_no_settle | 70–80 | 0.50–0.80 | 19 | 74% | 0.638 | −0.10 |

**Near-calibrated:** generic 0–10¢ (n=186, p 0.023 → 2%), generic ≥0.95 @
90–100¢ (n=141 → 100%, −0.02), cheap 20–30¢ counter-evals (p~0.13 → 15–17%
across maker lanes), generic 85–90¢ (p 0.87 → 90–100%).

**Cross-lane pattern:** the model is systematically *under-confident on
mid-priced favorites* (60–80¢: gaps −0.07 to −0.23 across four lanes) and
*over-confident at the pinned-favorite boundary* (90–93¢, +0.13 to +0.38) —
the same Bachelier-vs-pin asymmetry seen in the pf audit, now confirmed
system-wide rather than lane-specific. Extreme tails (0–10¢) are calibrated.

## Realized ENTER economics (unique episodes, selected side only)

| lane | px bucket | n | win | gross EV at bucket-mid (approx) |
|---|---|---|---|---|
| cheap_no_settle | 20–30 | 15 | 33% | +8¢/contract |
| cheap_no_settle | 30–40 | 16 | 38% | +3¢ |
| drift_fav | 40–50 | 7 | 86% | +35¢ |
| drift_fav | 50–60 | 5 | 60% | +5¢ |
| drift_fav | 60–70 | 13 | 54% | **−11¢** |
| drift_fav | 70–80 | 18 | 72% | −3¢ |
| maker_bid | 60–80 | 8 | 100% | +25–35¢ |
| maker_bid | 20–50 | 4 | 0% | losing pocket (n=4) |
| pinned_fav | 90–100 | 44 | 82% | in-band wins fund sub-94 losses |

- cheap_no_settle's 20–40¢ cohort wins more than the contract price implies —
  the under-confidence gap is *profitable direction* for a buyer. But these
  are settlement-view numbers: maker fill selection on cheap NOs is adverse-
  selection-prone; needs route-level counterfactual before any conclusion.
- drift_fav's 60–80¢ entries lose on settlement math (−11¢/−3¢ per contract
  gross at bucket mid before fees) — consistent with the over-confidence
  pocket at 50–60 (+0.23). Candidate for restriction or recalibration.
- maker_bid's realized entries concentrate 60–80¢ at 100% (n=8) — small but
  consistent with the under-confidence finding (buys winners cheap-ish).

## Gate interaction (independently-applicable failures per lane)

Generic path: cost_basis/edge_threshold/positive_ev/evidence/qualified each
fail on ~91–95k of 108k rows — the normal path rejects nearly everything
evaluated; bounded lanes exist to admit what generic gates veto. cheap_no_settle
ENTERs coexist with yes_positive_ev/edge_threshold/cost_basis failures on all
194 rows — its entries also ride the bounded-lane override. drift_fav fails
both-side EV gates on all 98 rows. Cross-lane: all lanes share the same gate
vocabulary; no lane-specific blocker taxonomy found. no_book_flow(514 pf),
book_trusted(65), no_depth(66) = integrity layer firing in-lane.

## Dispositions

| item | disposition | basis |
|---|---|---|
| pf 94¢ floor | RETAIN | overconfidence at 90–93 confirmed system-wide (+0.23 generic too) |
| cheap_no_settle 20–40¢ | EXPAND SHADOW + route counterfactual | settlement-positive but maker-selection untested |
| drift_fav 60–80¢ | CANDIDATE RESTRICT / recalibrate | entries lose −3 to −11¢/contract gross; +0.23 overconf at 50–60 |
| maker_bid 60–80¢ | RETAIN + more evidence | 8/8 in-window, under-confident model = margin of safety |
| model p at 60–80¢ favorites | RECALIBRATE-AND-RETEST | systematic −0.07..−0.23 under-confidence, 4 lanes |
| model p at 90–93¢ | KEEP RESTRICTED | +0.13..+0.38 overconfidence, both pf and generic evals |
| 0–10¢ tails | RETAIN | calibrated (n=186) |
| unpriced/missing-input evals | REPAIR INSTRUMENTATION | 6 pf eps had no reconstructable px; INPUTS_MISSING dominates low-TTE |

## Limitations

- Oct 25–26 only (extract truncated by DB contention); Nov 1–5 unextracted.
- implied_px is reconstructed, not logged — treat bucket boundaries ±1–2¢.
- n per cell is small outside generic lane; CIs shown in full table.
- Settlement-view ≠ executable: no maker fill model or taker VWAP here.
- cheap_no "profitable" cells are pre-fee, pre-selection counterfactuals.
- ENTER dedup now side-corrected; earlier counter-side ENTERs were an
  artifact and are excluded above.
