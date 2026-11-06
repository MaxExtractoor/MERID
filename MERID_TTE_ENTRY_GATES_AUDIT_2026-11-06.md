# TTE Entry-Gate Deep Audit — 2026-11-06

Question: are `min_tte_entry_disabled` / `tte_entry_cutoff` over-blocking live
trading activity, and what should change? Sources: full gate-chain code read,
`logs/late_window_shadow.jsonl` (13,251 records, 2026-09-29→11-06),
`logs/lwf_shadow.jsonl` (49,774 records), `logs/pinned_fav_maker_shadow.jsonl`,
`logs/settlement_outcomes.jsonl` (47,948 settled tickers), `server_output.log`
(today 07:55→11:06), MERID_PINNED_FAV_AUDIT_2026-11-05.md,
MERID_ALL_LANES_SUB90_AUDIT_2026-11-05.md, plus external microstructure research.

---

## 1. The TTE gate stack — every layer a candidate crosses

Ordered by evaluation for a new entry on a 900s market (all file:line in
`merid/`):

| # | Layer | Gate | Effective bound | Reject reason |
|---|---|---|---|---|
| 0 | signal collection | `MERID_HARD_MIN_ENTRY_TTE_S` (agent_grid_15m.py:1677, :15641) | 90s → relaxed to `min(90, settle_min=15)` = **15s** when settlement lane armed on bachelier/hybrid | `hard_tte_cutoff:<Ns` |
| 1 | regime classifier | per-band `min_time_to_expiry_seconds` (market_regime.py:195), env-clamped by `MERID_REGIME_MIN_TTE_FLOOR_S=90` | all enabled bands **≥90s**; max 1200-1800 (never binds at 900s window) | `tte_entry_cutoff` / `price_band_both_sides_disabled` |
| 1b | lane pseudo-regimes | settlement ≤60s & ≥15s; pinned_fav maker 90-840 / taker 300-840; trend_yes_hi 120-300 (off) | lane-scoped | — |
| 2 | engine Layer-1 | `seconds_to_expiry <= 0` (trade_decision.py:3902) | — | `expired_or_no_time` |
| 2 | engine Layer-1 | `MERID_EXIT_ONLY_CUTOFF_S` (default 30) (trade_decision.py:3932-3939) | **≤30s**, exempt: settlement_lane | `final_minute_entry_disabled` |
| 2 | engine Layer-1 | `MERID_ENTRY_MIN_SECONDS_TO_EXPIRY=180` (trade_decision.py:479, :3948) | **≤180s**, exempt: settlement_lane only | `min_tte_entry_disabled` |
| 3 | post-selection bounded domain | `MERID_LIVE_ENTRY_MAX_TTE_S=840` (trade_decision.py:2221; pinned_fav uses lane max, also 840) | **>840s** | `bounded_domain_tte` |
| 4 | lane TTE bands | drift 180-840, cheap_no ≥240, edge_midwin 180-660, mband ≥180, window_quota 120-780 (off), marginal_band ≥180 | per-lane | lane block |
| 5 | resting monitor | `PRE_EXPIRY_CANCEL_THRESHOLD_MIN=2` hardcoded (resting_order_monitor.py:45, :936) | resting entries **cancelled <120s** | `pre_expiry_cancel` |
| 5 | resting monitor | `MAX_HOLD_SECONDS_15M=60` + `MERID_ENTRY_CHASE_REST_S=75` TTL | ~60-75s max rest | sweep/TTL |

Dead code found: `MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN=5.0` (agent_grid_15m.py:280)
— `validate_market_state_for_entry` has **zero callers**.

### Effective entry map for a 900s window (current .env)

```
TTE 900 |---- dead (bounded_domain_tte, first 60s) --------------------| 840
TTE 840 |==== all lanes: normal bands + pf taker + pf maker + drift ==| 300
TTE 300 |==== normal bands + pf maker + drift(+ cheap_no ends 240) ===| 240
TTE 240 |==== normal bands + pf maker (drift floor 180) ==============| 180
TTE 180 |---- DEAD: engine floor kills all non-settlement entries ----| 120
TTE 120 |---- DEAD + resting orders cancelled at <120s ---------------|  90
TTE  90 |---- DEAD: classifier floor 90 -> tte_entry_cutoff -----------|  60
TTE  60 |---- settlement lane only (in_window, >=8 samples, p>=0.84) --|  15
TTE  15 |---- dead ---------------------------------------------------|   0
```

- New-entry-eligible: ~660s/900s (**73%**) for the generic path.
- Maker fill window effectively ends at **TTE 120s** (pre-expiry cancel), not 180s
  — an order admitted at 190s gets ~70s of rest before the monitor pulls it.
- The **60-90s hole**: settlement lane caps at 60s (mechanically correct — banked
  samples only exist inside the final minute), pf-maker floors at 90s →
  converged favorites unreachable by any lane.
- **~27% of every window is entry-dead** by design (first 60s + last 180s),
  minus the 45s settlement-lane slice.

### Measured rejection volume

- `late_window_shadow` (30-90s band only): **13,251** candidates since 09-29
  (~350/day): `tte_entry_cutoff` 9,086 + `min_tte_entry_disabled` 4,165.
  ~28% of side-prices converged (≤10c or ≥90c); 72% mid-priced.
- Today's `server_output.log` (~3h): `min_tte_entry_disabled` 3,637 raw /
  `tte_entry_cutoff` 2,063 raw / `final_minute` 625 — second-largest funnel
  block after `no_positive_executable_edge` (~1,073 dedup'd TTE rejects).
- `lwf_shadow` (120-150s, >85c asks): engine reasons were
  `price_band_both_sides_disabled` 24,956 + `min_tte_entry_disabled` 23,600 —
  i.e. ~47% of high-price candidates in that slice die on the 180s floor.

---

## 2. Findings

### F1 — Config incoherence: lanes built for a 90s engine floor run under a 180s floor

`MERID_REGIME_MIN_TTE_FLOOR_S=90`, `MERID_PINNED_FAV_MAKER_MIN_TTE_S=90`,
`MERID_HARD_MIN_ENTRY_TTE_S=90` and the code comments ("the engine's own entry
floor (90s) still bounds actual entries" — market_regime.py:139; commit
8674a6cc message) all presume a **90s** engine floor. The actual
`MERID_ENTRY_MIN_SECONDS_TO_EXPIRY=180` (trade_decision.py:3948) exempts
**only** `settlement_lane`. Consequence: the 2026-10-22 dead-zone fix changed
the *label* of the rejection (classifier `tte_entry_cutoff` → engine
`min_tte_entry_disabled`) without changing reachability. The pinned_fav maker
lane's configured 90-180s slice is a **dead letter** — candidates pass the
classifier, reach the engine, and die at Layer-1 before economics run.

### F2 — The "vol unavailable below ~150s" conclusion is an ordering artifact

Nov-5 audit inferred `INPUTS_MISSING` / `missing_input_fields:["vol_source"]`
meant the vol pipeline stops producing inputs at TTE≤150. Actually
`_resolve_annualized_vol` (trade_decision.py:1397) has **no TTE cutoff** and
always resolves (realized → market_implied → default). The missing field is
stamped at trade_decision.py:4024 — **after** the Layer-1 return at :3948.
The floor fires first; vol is never computed; the shadow reads an empty field.
The dependency runs the other way: relaxing the floor is what makes vol exist
in the record. (Conservative verdict of that audit still applies — see F4 —
but the causal story in the record is wrong.)

### F3 — Instrumentation gaps exactly where decisions need evidence

- `late_window_shadow` band is 30-90s (`MERID_LATE_SHADOW_MAX_TTE_S=90`):
  the **90-180s engine-floor dead zone is uninstrumented**. Records DO carry
  spot/strike/vol for pre-engine rejects (vol present on 9,086/9,086
  `tte_entry_cutoff` rows) but post-engine `min_tte` rows lack vol (F2).
- `lwf_shadow`: 49,774 records, **100% `probability_status=INPUTS_MISSING`** —
  it evaluates pre-vol-resolution and never observes strike+vol →
  w7/w8 economics permanently `not_evaluable`. Zero evaluable records since
  deployment. Broken instrument.
- Settlement outcomes exist for a full offline replay (47,948 tickers).

### F4 — Counterfactual economics of the blocked cohort (fresh replay)

Maker fill-at-own-side-bid, exact maker fee `0.0175·C·P·(1-P)` ceil'd to
$0.0001, settle P&L joined on ticker (one hypothetical per ticker×10s-band):

| side | own-bid | TTE 30-59s | TTE 60-89s |
|---|---|---|---|
| yes | 94-98 | −0.27c (96.3%, n=161) | **+0.70c (97.8%, n=137)** |
| no  | 94-98 | +0.13c (96.8%, n=155) | −0.97c (96.0%, n=149) |
| yes | ≥98.5  | +0.99c (100%, n=288) | +0.45c (99.5%, n=571) |
| no  | ≥98.5  | +0.71c (99.7%, n=342) | +0.61c (99.6%, n=541) |
| yes | 90-93  | +0.42c (92.1%) | +2.45c (94.1%, n=17 thin) |
| no  | 85-93  | −4.5..+0.5c mixed | −16.6..−7.0c toxic |
| mid 10-89c both sides | mixed, mostly negative | — | — |

Consistent with Nov-5 audit (+0.65c maker in-band at 120-150s; +1.15c at
30-89s) and the Sep-23 adverse-selection finding for mid-priced late entries.
**The harvestable late-window cohort is converged favorites (own-bid ≥94c),
thin-positive; mid-priced late flow is measured-negative.** Counterfactual
assumes every bid fills — real fills are adversely selected (F5), so true
realizable numbers are lower.

### F5 — External evidence converges on the same picture

- Settlement mechanics verified independently: strike(N) = TWAP60(final minute
  of window N−1); settle = TWAP60(final minute of N) vs strike. Inside the
  final minute, residual uncertainty scales ~**r^1.5**, not √r — the
  banked-samples edge is real and is exactly the settlement lane's design
  (pondletter: projection misses $0.47 at T-10s vs spot's $4.22; Vela: live
  stat-arb on the same mechanism at ~T-45s).
- Mid-price late-window **taker** entries: independent live replication found
  −1.21 expected wins over 237 trades at T-60s (the market is calibrated; fees
  eat the residual mispricing). External bots that trade directionally still
  hold a ~120s floor themselves (sririthishpalani-max: entry window 2-10min).
- Maker fills near close are **maximally adversely selected**: convergence
  sweeps through resting bids on the losing side; Kalshi repricing lags spot
  3-7s so faster observers pick off stale resting quotes. Supports post-only +
  ≥94c floor discipline; argues against extending maker rest into <60s.
- FLB literature: on long-dated markets favorites get *overpriced* in final
  minutes (insurance demand by losing-position holders — Kalshi sports
  calibration study, Polymarket weather study). On 15m mechanical-settlement
  contracts the favorite price is bounded by settlement arithmetic instead —
  but paying ≥99c for a favorite remains asymmetric (one pin-break erases
  ~84-200 wins); "never re-open 99-100" stands.
- The stale-strike open-window edge is priced correctly (calibration error
  ≤0.030, all buckets negative-EV after fees) — the 840s ceiling costs nothing.

---

## 3. What needs to change — ordered, bounded, evidence-gated

### P0 — Fix measurement (zero live risk)

1. `MERID_LATE_SHADOW_MAX_TTE_S` 90 → **180**: instrument the engine-floor dead
   zone where the actual decision needs evidence.
2. Stamp vol context on the `min_tte_entry_disabled` path: the engine knows
   `_last_signal_vol_context` backfill already (agent_grid_15m.py:12864); emit
   `annualized_vol`/source into the `_no_trade` indicators for TTE rejects so
   post-engine shadow rows are repriceable.
3. Fix `lwf_shadow` INPUTS_MISSING: move its eval hook post-vol-resolution (or
   hand it the resolved vol/strike) — currently 100% blind.

### P1 — Lane-scoped exemption for the measured-positive cohort

Do **not** lower the generic 180s floor (triple-validated against
mid-price late entries). Instead exempt the one cohort with settled
counterfactual evidence — the pinned_fav **maker** domain:

- At trade_decision.py:3938/3948, extend the `not settlement_lane` exemption to
  a `pinned_fav_late` condition: `pinned_fav_maker_mode` armed AND own-side
  **bid** ≥ `MERID_PINNED_FAV_MAKER_LO` (94c) AND `pinned_fav_reachable`-style
  TTE check on a lane-specific floor.
- `MERID_PINNED_FAV_MAKER_MIN_TTE_S` 90 → 60 covers the 60-90s hole (the
  settlement lane owns <60s; banked-samples edge starts at T-60s anyway).
- Keep `MAKER_MIN_P=0.90`, moneyness caps, post-only, daily cap — the lane's
  own gates still bound admission. Expected yield is thin (+0.3-0.7c/contract
  on ~2-6 contracts) — a modest unlock, not a windfall.

### P2 — Reconcile the resting-order boundary

- Make `PRE_EXPIRY_CANCEL_THRESHOLD_MIN` (hardcoded 2min, resting_order_monitor.py:45)
  env-configurable, and lane-exempt the pinned_fav/settlement orders — otherwise
  a 90-180s maker admission gets <60s of rest before the monitor pulls it.
- Do **not** extend maker rest deep into <60s — external evidence says
  late-window maker fills are maximally adversely selected; the settlement
  lane already covers that slice with IOC.

### P3 — Housekeeping

- Correct the stale "engine floor (90s)" comments in market_regime.py:139 and
  directional_regime.py; reconcile `MERID_REGIME_MIN_TTE_FLOOR_S=90` with the
  real floor (it is currently dead-letter protection, harmless).
- Remove or wire `MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN`/`validate_market_state_for_entry`.
- Keep `MERID_LIVE_ENTRY_MAX_TTE_S=840` (evidence-raised 600→840 already) and
  the 180s generic floor.

### Explicitly NOT recommended

- **Blanket floor lowering** (180→90 for all candidates): re-admits the
  measured-losing mid-price cohort (Sep-23 audit + this replay + external
  replication all agree).
- **Re-opening 99-100c**: +0.45..+0.99c aggregate but one pin-break erases
  ~84-200 equal wins; asymmetric tail stays gated.
- **Taker entries <180s**: no evidence any cohort is taker-positive late;
  external replication measured taker late-window negative.

## 4. Bottom line

The user's instinct is half right: ~27% of every window is entry-dead and
~350-500 candidates/day bounce off TTE gates — but the **generic** floor is
protecting against measured losers, not blocking measured winners. The real
defects are (a) lane configs written for a 90s engine floor dead-lettered
under the 180s floor, (b) a 60-90s hole no lane covers, (c) shadow
instruments that can't produce the evidence needed to re-decide — lwf is 100%
INPUTS_MISSING and the 90-180s band is unrecorded. Fix measurement first (P0),
then open the pinned-fav maker 60-180s slice (P1) with the resting-cancel
boundary reconciled (P2). Expected effect: modest activity gain in the
converged-favorite cohort — not a broad activity unlock, which the data says
does not exist late in the window.

## 4b. Implementation shipped (2026-11-06)

- **P0a** — `MERID_LATE_SHADOW_MAX_TTE_S=180`: the shadow band now covers
  30-180s, instrumenting the previously unmeasured 90-180s dead zone.
  Verified `late_window_shadow` records already carry vol/spot/strike via
  the `_compute_signal_vol_context` backfill (6/13k missing) — the "vol
  doesn't exist below 150s" claim was an ordering artifact of the gate,
  not missing data on the records.
- **P0c** — `lwf_shadow_lane` v4: `p_cal` was None on ~100% of records
  (the engine floor rejects before producing a forecast — the lane's
  entire population by definition).  The record's own endpoint-normal
  `q_phi` is now promoted to `p_effective` under a new honest label
  `RECOMPUTED_ENDPOINT` (never presented as engine output;
  `model_evaluation_completed` stays false).  w7/w8 economics evaluate on
  either COMPUTED_VALID or RECOMPUTED_ENDPOINT.  Both non-engine call
  sites (`pre_engine_band`, `held_position`) now resolve the signal vol
  context for in-window evals so strike+vol reach the record.
- **P1** — `MERID_PINNED_FAV_TTE_FLOOR_EXEMPT` (default on): the engine
  floor passes an own-side bid inside the pf maker band (94-98c) at TTE
  >30s so `pinned_fav_block` can apply its strict gates (band, lane TTE,
  min_p 0.90, min EV, moneyness caps, daily budget).  Not a generic
  relaxation — `=0` restores the floor for the cohort.  Lane window
  widened to `MAKER_MIN_TTE_S=60`: the 60-90s hole joins the dead-lettered
  90-180s slice.
- **P2** — `MERID_PRE_EXPIRY_CANCEL_MIN_S_PINNED_FAV=45`: pf-lane resting
  orders get their own pre-expiry cancel floor instead of the generic
  120s — which guaranteed a 90-180s maker entry could never rest long
  enough to fill.  All other lanes keep 120s; exits were already exempt.

Kill switches: every change is env-gated; restoring the prior behavior is
`TTE_FLOOR_EXEMPT=0`, `MAKER_MIN_TTE_S=90`,
`PRE_EXPIRY_CANCEL_MIN_S_PINNED_FAV=120`, `LATE_SHADOW_MAX_TTE_S=90`.

---

# PART II — Favorite-side entry price floor ("the floor is too high")

## 5. What "the floor" actually is

The user's mechanism is structural and real: to show edge on a favorite, the
move must already have happened — and the moved price lands past the cap, so
the edge-proven candidate gets vetoed. The relevant stack:

- `MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_YES=75` — every YES >75c on the
  normal path dies `entry_price_cap_{px}c_gt_75c`
  (directional_regime.py:836-864). YES 76-93c sits inside *enabled* bands
  (transition_high 76-85, skewed_high 86-90) yet is 100% dead.
- `MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO=50` global; per-asset overrides:
  BTC-NO 79, ETH-NO 89, DOGE/SOL-NO 75, XRP-NO 1; block bands BTC/ETH-NO
  51-64c, XRP-YES 76-79c.
- `PINNED_FAV_MAKER_LO=94` — the converged-favorite lane's own floor.
- `disabled_tail` classifier covers 91-99c on the normal path.

So the **favorite-entry domain effectively starts at ~90-94c** (lanes) while
the normal caps shut the 75-93c zone — "validated candidates get vetoed" is
literally `entry_price_cap` / `no_eligible_price_band` / `cost_basis_override`
firing on edge-positive candidates.

## 6. Measured veto-cohort economics (fresh replay, whole-file offset sample)

Cap/band-vetoed candidates at 75-95c, settle-joined, taker-at-ask basis,
exact taker fee:

| cohort | n | win% | avg/contract |
|---|---|---|---|
| YES 90-95c TTE 180-600 | 51 | 96.1% | **+4.03c** |
| YES 90-95c TTE <180 | 16 | 100% | +7.43c |
| NO 75-79c | 8 | 87.5% | +9.50c |
| NO 80-84c | 22 | 90.9% | +8.00c |
| NO 85-89c | 12 | 100% | +12.44c |
| NO 90-95c TTE 180-600 | 65 | 92.3% | +0.43c |
| NO 90-95c TTE <180 | 14 | 78.6% | **−14.01c** |

Per-asset (thin): BTC-NO 80-84 +6.06c (n=9) — *conflicts* with the Oct-14
audit pocket (−17.2c, larger n); SOL-NO 80-84 −0.02c (n=6).

Read: the vetoed 75-89c cohort is measurably positive **except NO deep-tail
late** — the user's claim has real support, but n is thin and per-asset
history is mixed, which is exactly the bounded-probe case, not a blanket
removal.

## 7. Funnel context at 75-93c (offset sample, ~360k reject rows)

- `no_positive_executable_edge` dominates every 5c bucket (2.1k-6.5k/bucket)
  — most candidates there correctly fail EV. The cap vetoes only the
  edge-proven subset.
- `entry_price_cap` vetoes are modest in volume but surgically target the
  proven cohort (reasons: `*_gt_75c` YES-side at 81-89c most common,
  `*_gt_50c` NO-side at 87-89c, `*_gt_79c` BTC-NO at 80-81c).
- `no_eligible_price_band` peaks at 90-100c (2,960) — the disabled-tail wall
  below the pf floor.

## 8. Supporting external evidence

- UCD Kalshi economics WP: contracts >50c earn small **positive** returns;
  <10c lose >60% (fee+maker/taker microstructure model).
- Calibration is horizon-dependent: 7-day-out favorites at 80-90c are
  **overpriced** (−17.6pts, KalshiView n=1,821); 1-day-out favorites are
  **underpriced** (+2.9pts, pdata n=20k). On 15m mechanical-settlement
  markets the convergence regime dominates late — favors buying favorites
  mid-window, not final-minute.
- Nov-5 all-lanes audit: the model is **under-confident at 60-80c**
  (gaps −0.07..−0.23) — claimed edge at 75-85c is if anything understated;
  **over-confident at 90-93c** (+0.13..+0.38) — keep that pocket gated.
- Final-10-minutes insurance-demand FLB (Kalshi sports calibration paper):
  favorites get *overpriced* into settlement on long-dated books — argues
  for keeping the TTE floor on the favorite zone (admit mid-window, not
  <180s).
- Altstreet microstructure: 65-89c books carry ~2.5c median spread vs ~1c at
  90-99c — the zone is executable but the spread is a real cost; prefer
  maker/post-only when spread ≥ ~3c, taker/IOC when tight.
- Canary methodology (production-trading literature): separate risk
  budget/P&L attribution per version, automatic rollback bound to an
  automated metric, promotion on the full metric set — MERID's lane +
  daily-cap + markout-suspension shape already implements this.

## 9. What to change — ordered

### R1 — Open the 75-89c favorite zone as a bounded lane (recommended shape)

A `fav_convergence` lane rather than a global cap removal — keeps the cap's
protection and gives the cohort its own auditable gates:

- Domain: own-side executable 75-89c (below pf floor, above normal caps),
  TTE ≥180s (mid-window only — late favorite-buying is where the negative
  cells live: NO 90-95 late −14c, insurance-FLB).
- Admission: existing EV gate unchanged (NPEE must pass), tail_LCB gate
  covers ≥80c already, per-asset moneyness blocks retained (BTC-NO 80-84
  pocket stays blocked — measured −17.2c; XRP exclusions stay).
- Route: taker/IOC preferred — maker bids at 85-93c are adversely selected
  on pin-breaks (Nov-5 audit: −0.48..−3.88c); the positive counterfactual
  was measured on taker basis. Post-only only when spread ≥3c.
- Bounds: 1-2 contracts, per-ticker 1, daily cap ~48, markout suspension —
  a paid probe whose cost is bounded by definition.

### R1b — Existing precedent: `MERID_PRICE_CAP_EXCEPT_BTC_NO`

The system already carries the exact exception shape this data supports —
Experiment B (directional_regime.py:1885-1910, trade_decision.py:6329-6346):
BTC-NO at 75-89.99c may pass the cap **only when reserve-stacked net EV at
the fresh executable ask ≥ +2c/contract**, everything else unchanged. It is
currently disarmed (no .env entry). The measured recommendation is this
pattern generalized:

- Arm `MERID_PRICE_CAP_EXCEPT_BTC_NO=1` — BTC-NO 80-84 is the one pocket
  where evidence conflicts (counterfactual +6.06c n=9 vs Oct-14 −17.2c);
  the +2c conservative-EV requirement and 80-84 block band keep the
  exception tight. Its settled fills ARE the paid probe.
- If its fill data confirms the +7..+12c cohort, extend the same shape as
  `PRICE_CAP_EXCEPT_{SIDE}_{ASSET}` for ETH-NO 65-89, YES 76-89 — each
  gated on its own settled evidence, never the shared cap.

### R2 — Cheaper alternative: raise the caps directly

- `MONEYNESS_MAX_ENTRY_PRICE_CENTS_YES` 75 → 89 (opens YES 76-89 normal
  path; 90-93 stays disabled-tail + pf floor 94).
- NO per-asset: keep BTC 79 (+ optional `BLOCK_BAND_NO_BTC` 80-84 given the
  Oct-14 measurement), DOGE/SOL 75 → 79 bounded, ETH 89 keep, XRP 1 keep.
- tail_LCB ≥80c remains the calibration gate above the old cap.

R1 is the better fit for this codebase's convention (lane-scoped audited
domains, kill switches, paid-probe caps). R2 is a two-line change but
removes protection rather than scoping it.

### R3 — Keep gated

- 90-93c on the normal path: model overconfidence +0.13..+0.38 (Nov-5 audit)
  — the claimed edge there is inflated even though realized stays positive;
  pf floor 94 stays.
- 85-91c as *maker* bids (pf band extension): shadow shows min_p 0.90 vetoes
  79% and maker fills at those prices were measured toxic — wrong vehicle.
- NO ≥90c late-window: −14c measured — keep the 180s floor for favorites.

### The mechanism caveat to state plainly

"Price moved by the time edge exists" is *inherent* to favorite-buying — the
edge IS the convergence; it cannot be front-run at 60c because p hasn't
confirmed yet. The fix is not a lower floor on the same gate — it is to
stop vetoing the moved candidate once its edge validates. A 75-89c lane
with the unmodified EV+tail-LCB gates does exactly that.

## 9b. Stale-evidence audit (operator challenge: "the caps rest on bug-era data")

The operator's claim was tested against the realized fill record:

- **Exit path is real**: `exit_markouts.jsonl` — 256 exit_fills, 96% win
  overall, 100% since the 2026-11-02 fix wave; entry 70-80c +8.78c,
  80-90c +3.16c gross (net-positive after ~1.6-2.2c round-trip fees).
- **The no-exit population is where the losses are**: 248 entry tickers
  never reached an exit_fill; at settlement they ran −10.8c (70-80c),
  −16.0c (80-90c), −6.5c (90-100c).  On 2026-11-02 the tree literally
  fixed `unwedge held_unmarketable exits` plus ~50 order-lifecycle/
  execution repairs — the no-exit population is consistent with the
  bug-era hypothesis the operator raises.  Bug-era data cannot fully
  separate "exit couldn't fire" from "no profitable exit existed" — which
  is precisely the case for bounded live probes rather than either
  blanket relaxation or keeping the veto on faith.
- **Evidence-vintage classification**: every realized-fill cap basis
  (Oct-11 NO 60-75c −$9.49, Oct-28 pf 90-91c pocket, Oct-14 pockets)
  predates the fix wave → stale under the current stack.  Counterfactual
  settle-outcome evidence (51-64c pockets, NO≥90 late −14c, model
  overconfidence at 90-93c) is market-truth — it does not go through the
  exit path and stays valid as a *settle-basis* bound, though the exit
  policy can improve on it for the exit-capable subset.

## 9c. Implementation shipped (2026-11-06)

Generalized `MERID_PRICE_CAP_EXCEPT_*` probes (Experiment B generalized):

- `directional_regime._moneyness_cap_exception` now resolves scoped flags
  (`_{ASSET}_{SIDE}` > `_{SIDE}`; `BTC_NO` keeps the legacy name) plus
  scoped `LO_CENTS`/`HI_CENTS`/`MIN_EV_CENTS` tunables (defaults
  75.0 / 89.99 / +2.0c).  Fail-closed on missing inputs.
- `trade_decision.py` applies the exception to BOTH sides, only clears
  plain cap blocks (`_band_` reasons are never lifted), and keeps the
  side-throttle check; indicators stamp `{side}_price_cap_exception`.
- `.env` armed: `BTC_NO`, `YES` (all assets; XRP-YES 76-79 band still
  binds), `DOGE_NO`, `SOL_NO`.  XRP untouched (structural hard-block);
  ETH-NO untouched (cap 89 ≈ window top).
- Every passing candidate is a bounded probe: +2c reserve-stacked EV at
  the fresh executable price, tail_LCB ≥80c, all other vetoes intact —
  its settled fills ARE the clean-era re-measurement.  Kill = flag 0.
- Tests added in `tests/test_postrestart_fixes.py::TestMoneynessCapException`
  (8 cases: default-off, legacy flag, side-wide, per-asset scope, window
  bounds, scoped overrides, EV floor, fail-closed inputs).

Deliberately NOT relaxed (evidence is not stale): XRP-NO block, 51-64c
BTC/ETH-NO pockets (settle-basis counterfactual), ≥90c disabled tail +
pf floor 94 (model-overconfidence evidence, not bug-era), NO ≥90c
late-window (−14c settle counterfactual), the TTE floor stack (Part I).

## 10. Combined bottom line (Parts I + II)

Two real unlocks exist, both bounded and evidence-backed:
1. pinned_fav maker 60-180s exemption (Part I, P1) — thin-positive converged
   cohort currently dead-lettered.
2. `fav_convergence` 75-89c lane (Part II, R1) — the measured-positive
   cap-vetoed cohort, sized ~hundreds of candidates/week by funnel volume.

What the data does NOT support: blanket floor lowering (TTE or price),
90-93c reopening, maker-vehicle entries in the 75-93c zone, or any
late-window (<180s) favorite buying.
