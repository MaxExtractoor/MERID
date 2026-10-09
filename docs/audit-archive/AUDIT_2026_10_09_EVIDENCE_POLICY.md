# Evidence-Policy Audit — 2026-10-09

Scope: every evidence-bound admission mechanism on the BTC/ETH/SOL/XRP/DOGE
15m path, audited as a *policy layer separate from trade economics*. The
question per mechanism: does it protect against measured losses, express
uncertainty, or merely block evidence collection?

## 1. What `eff_ev` actually measures — resolved (case B)

`eff_ev` / `eff_net_ev_cents` in the cap-shadow log is
`_epc_eff_edge(side) * 100` — the **reserve-stacked conservative net EV in
cents**, per contract, at the executable ask:

```
net_edge = gross_edge                     # p_selected − executable ask
         − entry_fee                      # exact Kalshi taker fee
         − exit_cost_reserve              # p_trigger × taker exit fee
         − model_risk_reserve             # model-uncertainty charge
         − adverse_selection_reserve      # K·p(1−p) + FLB terms
```

When the empirical-price-calibration cell applied, `eff_edge =
max(net_edge, epc_adj_lcb/100)` — the cell's own conservative bound can
substitute but never clear a bar it doesn't reach
(`trade_decision.py:4253-4259`).

`bound` is `_side_edge_eff_bound` = the active `min_net_ev` threshold minus
marginal-band slack. For a provisional cell, `min_net_ev` is
`cell_min_ev_cents()` (`current_build_provisional.py:334`) — for XRP YES that
is **−4.0c**, set by `MERID_PROVISIONAL_MIN_EV_C_XRP_YES=-4.0` in `.env`
(clamped by `MERID_PROVISIONAL_MIN_EV_FLOOR_C=-6.0`).

So `eff_ev=-3.9c >= bound=-4.0c` means: *the reserve-stacked conservative EV
clears the cell's explicitly-negative exploration floor.* It is an
exploration authorization on a bounded lane — the candidate is expected to
lose ~3.9c/contract even in the central estimate. `economics_verdict=FAIL`
is now stamped for exactly this case (see §6).

Which of the user's three cases applies: **B — reserves included.** The
decomposition is now emitted per side: `central_net_ev_cents` (net_edge with
the two uncertainty reserves added back), `conservative_net_ev_cents`
(= net_edge), `reserves_cents` (model_risk + exit_cost + adverse_selection).

It is **not** settlement-EV-vs-scalp-EV (case C) — `p_selected` is the
settlement-probability estimate against entry cost; there is still no
separate exit-value model. Any scalp thesis for high-price cells remains
unmodelled.

## 2. Mechanism inventory

| Mechanism | File / function | Config & effective value | Rationale | Verdict |
|---|---|---|---|---|
| Cell-aware evidence gate | `evidence_policy.evaluate` | `MERID_EVIDENCE_CELL_POLICY=1`, margin `MERID_LIVE_EVIDENCE_MARGIN=0.015` | Beta-binomial posterior LCB10 → fee-adjusted net-EV test at candidate's own price | Keep — measured-loss protection, price-matched |
| Min effective samples | `min_cell_neff` | `MERID_EVIDENCE_MIN_CELL_NEFF=8.0` | Level usable at n_eff≥8 | Keep |
| Parent pooling | `_find_loo_parent`, `kappa_cap` | `MIN_PARENT_NEFF=8`, `KAPPA_CAP=30` | Partial pooling, leave-one-out | Keep |
| Sparse uplift | `sparse_uplift_max_c`, `sparse_full_neff` | `SPARSE_UPLIFT_C=2.0c`, `SPARSE_FULL_NEFF=50.0` | Uncertainty → required margin, max 2c | Keep, but see §3 — 50.0 is unreachable |
| Hard toxic block | `hard_min_neff`, `hard_ev_floor_c` | `HARD_MIN_NEFF=50`, `HARD_EV_C=5.0` | Dense matched cell with LCB EV < −5c + recent agreement → veto | **Dead code under 48h window** — see §3 |
| Stale evidence | `evidence_stale_s` | `EVIDENCE_STALE_S=3600` | Artifact >1h old: no hard block, max uplift | Keep |
| Escape lane | `escape_lane_enabled`, `escape_daily_max` | `ESCAPE_LANE=1`, `ESCAPE_DAILY_MAX=120` | Bounded post-only canary for zero/sparse evidence | Keep; quota lifted 12→120 on 10-06 |
| Challenge/soft-penalty | `adaptive_states_enabled`, `challenge_min_recent_n`, `soft_penalty_extra_c` | `CHALLENGE_MIN_RECENT_N=3`, `SOFT_PENALTY_C=2.0` | Recent outcomes contradicting stale prior → bounded challenge; else elevated reserve | Keep |
| Evidence transfer premium | `MERID_EVIDENCE_TRANSFER_EXTRA_CENTS` | `1.0c` | Pooled-transfer admit must clear bound +1c | Keep |
| Threshold-cell registry | `threshold_cells.py` | `config/threshold_cells_live.yaml`, 12 cells | Frontier-qualified cells replace formula bound; `MERID_THRESHOLD_CELLS=0` kills | Keep — but 6/12 SUSPENDED, 0 fills today |
| Cbp provisional lane | `current_build_provisional.py` | domain 20–89c / 120–600s; per-side min-EV; caps | Bounded evidence-buying on unregistered regions | Keep — **caps inflated to primary-lane scale 10-06** (24/cell, 120/day) while per-cell suspension machinery unchanged; lane now behaves as primary admission path, not a small experiment |
| Negative EV floor | `provisional_min_ev_floor_cents`, per-side overrides | `MIN_EV_FLOOR_C=-6.0`, `XRP/SOL/ETH YES=-4.0`; BTC/DOGE defaults +2.5/3.0 | 10-02 counterfactual: YES candidates killed only by economics chain realized +9.4..+19.1c/window on ETH/SOL/XRP | Exploration mechanism, working as designed — telemetry now labels it as such |
| Cbp cell suspension | `record_*` triggers | `SUSPEND_MIN_FILLS=3`, markout −3c, reject-rate 40% | Fail-closed per cell | **Bookkeeping conflation — see §4** |
| Threshold-cell suspension | same ladder | `SUSPEND_MIN_FILLS=5` etc. | Fail-closed per cell | Same conflation issue |
| Directional side throttle | `directional_regime.py` | `SIDE_THROTTLE_*`, catastrophe scope=asset, TTL 6h | Loss-streak / catastrophic-markout side parking | Keep; scope narrowed to asset 10-03 was correct |
| Moneyness gate + 75c cap | `entry_price_cap_block_reason` | `MONEYNESS_*`, `MAX_ENTRY_PRICE_CENTS=75` | Coin-flip veto + high-price cap (10-07 tail-loss audit) | Keep gate; cap relaxation gated on shadow cohort economics (in progress) |
| trend_yes_hi lane | `directional_regime` | `TREND_YES_HI_*` | 91–94c YES deep-ITM lane exempt from cap under strict gates | Keep |

## 3. The evidence deadlock — confirmed structural

`live_entry_evidence.json` rebuilds with `MERID_LIVE_EVIDENCE_WINDOW_HOURS=48`.
At the observed fill rate the *densest* cell is `ETH|no|50-74|mid` at
n_eff=11.75; every price-matched pooled level also sits far below 50.

Consequences:

- `hard_min_neff=50` is **unreachable** — no cell can ever accumulate 50
  effective samples inside a 48h window at this trade rate. The toxic-cell
  hard block is present but practically inert. (This is acceptable *while*
  the cbp lane demotes legacy evidence to labels, but the hard block is not
  the safety net it appears to be.)
- `sparse_full_neff=50` is equally unreachable → every cell pass is
  permanently `escape_required` → the generic evidence gate can *never*
  certify a cohort outright; it can only route through the bounded lanes.
- Functionally the system already lives in the workaround: inside the
  provisional domain (20–89c, 120–600s) the legacy verdict is demoted to
  `legacy_risk_label` and the cell's own min-EV owns admission.

Correct fixes by category: the deadlock itself is best addressed by widening
`MERID_LIVE_EVIDENCE_WINDOW_HOURS` (the data exists — the artifact just
truncates it) and/or raising effective sample counts via the pooling chain
that already exists — *not* by lowering `hard_min_neff` or the negative
floor.

## 4. Evidence-bookkeeping findings

| Confusion the audit asked about | Status |
|---|---|
| Repeated evaluations counted as samples | **Clean** — `build_cells` normalizes per market; one ticker's 5s evals ≈ 1 effective sample (e.g. ETH yes 25-49 mid: n_raw=30, mkts=12, n_eff=9.2) |
| Router rejection counted as a losing trade | **Conflated** — `consecutive_router_rejects=2` suspends cbp cells (12 of 31 suspended cells today). Post-only cross/stale-revalidation is quote-integrity failure, not realized P&L; it shares the same SUSPENDED state and manual-reset recovery as −69c first-trade losses |
| Order expiry counted as P&L | Not observed — expiry does not generate settlement outcomes |
| Unfilled orders counted as outcomes | Clean — evidence artifact builds from settled *entries* only |
| Settlement vs scalp outcomes | Settlement only; no separate scalp-exit outcome store exists (still open from the scalp-EV requirement) |
| Suspension recovery | **None automatic** — `SUSPENDED` requires manual reset; 31/39 cbp cells and 6/12 threshold cells are parked with no recovery-evidence path. This is deadlock-adjacent: suspended cells can't generate the outcomes that could clear them |
| >100c "entry" data quality | The 10-07 audit's "80–101c" label is the *dollar-cost* basis (price + fee ≈ 101c for ~96–99c entries), not a contract price above $1 — but the original label mixes units; execution price and all-in cost must stay separate columns (they now are in `side_verdicts`) |

## 5. Lane funnels, today

Threshold-cell lane (`threshold_cell_lane.json`):
`matched=1408 → blocked_by_evidence=759 → soft_evidence_override=20 → emitted=11 → allocator_rejected=1 → router_rejected=1 → submitted=0 → filled=0`

Cbp lane (`current_build_provisional_lane.json`):
`matched=8978 → blocked_by_evidence=6672 → legacy_evidence_labelled=767 → emitted=12 → allocator_rejected=3 → router_rejected=3 → submitted=4 → filled=1`

`blocked_by_evidence` dominates both funnels — and inside the cbp domain
that counter fires on the *demoted* legacy verdict, which should be a label,
not a funnel-block count. Funnel instrumentation needs the same verdict
split so `blocked_by_evidence` only counts binding verdicts.

## 6. What changed in code (bc07d1d4)

Per-side verdicts now stamp on every decision — `side_verdicts` in
indicators, cap-shadow records, and `rejected_candidates.jsonl`:

- `economics_verdict`: PASS iff `p_selected > min_p` (full cost basis).
- `evidence_verdict`: SUFFICIENT / SPARSE_PASS / INSUFFICIENT:<code> /
  STALE:<code> / HARD_BLOCK / NOT_EVALUATED.
- `exploration_verdict`: AUTHORIZED:<lane> / CAP_EXHAUSTED / LANE_DISABLED /
  FLOOR_FAIL / NONE.
- `admission_verdict` (mutually exclusive): PRODUCTION_ECONOMICS_AND_EVIDENCE_PASS,
  ECONOMICS_PASS_EVIDENCE_INSUFFICIENT, EXPLORATION_AUTHORIZED, ECONOMICS_FAIL,
  HARD_SAFETY_BLOCK.
- Reserve decomposition: central vs conservative net EV, total reserves.
- `hard_safety_flag` stays visible even when a current-build lane demotes
  a toxic-cell verdict to a label.

A fail-open admission with no evidence artifact now correctly reports
`ECONOMICS_PASS_EVIDENCE_INSUFFICIENT` (admitted, but cohort-unsupported)
rather than looking evidence-backed.

16 unit tests + 2 integration checks pass (`tests/test_evidence_verdicts.py`).

## 7. Per-cohort release read

Post-restart verification (clean boot 04:48Z, fills READY in ~10s, zero
residual test rows in `kalshi_fills.db`): the new verdicts are live in
`rejected_candidates.jsonl` — 130 unique decisions in the first ~10 min,
side-verdict rollup: **ECONOMICS_FAIL 244 | ECON_PASS_EV_INSUFFICIENT 16 |
EXPLORATION_AUTHORIZED 8 | HARD_SAFETY_BLOCK 0 | PRODUCTION_PASS 0**.

Terminology for this section: `central_net_ev` = net of entry fee and
expected exit cost only (uncertainty reserves added back);
`conservative_net_ev` = fully reserve-stacked net EV — the quantity
thresholds and floors actually test (`eff_ev` in cap-shadow records).

Sampled window is thin (~10 min, trending tape); treat per-cohort EVs as
first-look, not settled. What the verdicts already establish is *which axis
binds* per cohort:

| Cohort | Central / conservative EV | Evidence | Binding restriction | Recommendation |
|---|---|---|---|---|
| XRP NO 60-69c (all routes) | +6.5c / +2.5..+4.5c — clears its +2.0c bound | INSUFFICIENT:SOFT_PENALTY_INSUFFICIENT | evidence soft-penalty only | **Explore-track** — economics pass with conservative EV over bound; the soft penalty is an evidence-collection bound, not a measured-loss verdict. Prioritize a recovery-evidence path for this cell. |
| BTC NO 80-89c (all routes) | +3.7..+6.5c / +1.7..+2.0c | SOFT_PENALTY_INSUFFICIENT | `entry_price_cap_8Xc` pre-empts a cbp authorization that already exists (`EXPLORATION_AUTHORIZED:current_build_provisional`, 8 side-evals) | **Shadow now; Explore is gated on the cap decision** — the cap binds against an authorized, economics-passing cohort. This is exactly the marginal-coverage cohort the cap-relaxation measurement exists for. |
| XRP YES 60-69c | -7.5c / -9.5..-11.7c | SPARSE_PASS (sparse pooled level passes) | neg-floor FLOOR_FAIL (-7.5c below -4.0c floor) | **Reject** — fails even the exploration floor; working as designed. Do not loosen the floor to chase fills. |
| ETH YES 60-80c | negative conservative | toxic-labelled; `cbp_eth_yes_60_70` catastrophic-markout suspension live (until ~06:54Z) | side suspension + cbp suspend | **Shadow** — the markout evidence is real; revisit after suspension TTL with the recovery-evidence question in §8. |
| SOL YES 30-40c | near-floor | suspended on `first_trade_pnl=-31c` | measured loss | **Reject until exit-reliability ships** — this is the settlement-tail signature. |
| Threshold-cell NO bands (sol_no_30_60, doge_no_*, xrp_no_80_90) | positive LCBs at qualification time | historically qualified, live-suspended | SUSPENDED state; `ev_below_cell_threshold` firing on XRP NO 10-19/80-89 evals | **Shadow + recovery audit** — qualified cells need an evidence path back, not permanent manual gates. |
| Generic <75c cohorts (BTC 20-29/70-79, DOGE 10-29, XRP 10-49) | predominantly negative on both axes | mixed sparse pass/fail | `no_positive_executable_edge` | **Reject** — economics fail; evidence state is moot. |
| 75-89c YES sides (all assets) | -1.5..-12c conservative | sparse | cap + economics both fail | **Reject/Shadow** — cap is currently redundant with economics on the YES side; NO-side 80-89 is where the cap actually binds a passing candidate. |

Promote: **none** — no cohort currently shows positive conservative EV plus
adequate current evidence. The honest state of the policy layer is that it
is not blocking a demonstrably profitable cohort today; it is blocking two
plausible ones (XRP NO 60-69, BTC NO 80-89) whose economics pass but whose
execution evidence the current windows cannot produce. Those are
Explore/Shadow decisions, not Promote, and not a reason to loosen the
floors that are correctly rejecting (XRP YES, ETH YES suspended cells).

## 8. Open items

- Widen `MERID_LIVE_EVIDENCE_WINDOW_HOURS` (or persist the artifact across
  rebuilds) so `hard_min_neff`/`sparse_full_neff=50` are reachable —
  currently the toxic-cell hard block can never fire.
- Split router-reject suspensions from loss suspensions in cbp/threshold
  lane bookkeeping; quote-integrity failures deserve a separate
  (rate-limited, auto-recovering) state.
- Define a documented recovery path for SUSPENDED cells (N clean
  shadow-window days or explicit operator reset with reason).
- Scalp exit-value model: still absent — settlement calibration is being
  used where the strategy resells. Required before any high-price
  exploration lane promotion.
- Funnel counters should count *binding* verdicts only (align with
  `admission_verdict`) so demoted labels stop inflating
  `blocked_by_evidence`.
