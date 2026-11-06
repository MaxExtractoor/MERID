# MERID Pinned-Favorites Lane Deep Audit — 2026-11-05

Scope: maker + taker paths, both-sides-disabled price bands, min-TTE entry gating,
invalid-confidence vetoes. Evidence windows: settled counterfactuals 2026-11-01..05
(~4.7d), realized fills 2026-10-25..11-05, in-engine veto taxonomy 2026-10-25..26
(partial extraction) + Nov-1+ targeted queries. Sources: `decision_audit.db`
(strategy_decisions, snapshots, events), `rejected_candidates.jsonl`,
`lwf_shadow.jsonl`, `late_window_shadow.jsonl`, `pinned_fav_maker_shadow.jsonl`,
`settlement_outcomes.jsonl`, `kalshi_fills.db`, `kalshi_order_attempts.db`.

Counterfactual conventions (same as 10-31 audit): maker = fill at own-side BID +
exact maker fee; taker = fill at own-side ASK + exact taker fee; settle P&L =
win → +(100 − px − fee), loss → −(px + fee); one hypothetical per
(ticker, side, bucket) at first qualifying observation.

---

## 1. Gate chain (verified)

1. Pre-engine: `price_band_both_sides_disabled` → `pinned_fav_reachable()`
   injects the 92-98c pseudo-regime when armed. **Maker mode reachability is on
   own-side BID** (94-98), TTE 90-840. Confirmed: zero band-disabled records had
   an own-side bid in 94-98 inside lane TTE — the injection works exactly as
   designed; nothing in-band is lost pre-engine.
2. In-engine: `pinned_fav_block()` → `pinned_fav_{band,moneyness_cap,tte,
   maker_no_p,maker_low_p,low_ev,daily_cap}`, surfaced as `first_block` inside
   `yes_qualified`/`no_qualified` (not as top-level reason codes).
3. Final: `confidence_valid` → `no_trade_reason="invalid_confidence"`,
   PRC `DATA_QUALITY_VETO`. Fires post-selection on all 4 route records
   (taker/maker/maker_bid/empirical_marginal_maker).
4. Route: maker mode suppresses ask-priced taker+maker; `maker_bid` post-only
   is the only live vehicle (`economic_cap=99, selected_side_limit=98,
   post_only=true, chase_cap=100` confirmed in attempt payloads).
5. Submission: order gate — `net_of_cost`, `market_not_entry_ready`,
   `duplicate_entry`, **`stake_at_risk_cap` (new 10-30)**.

---

## 2. Veto populations + settled economics

### 2a. Price bands — both sides disabled (pre-engine, TTE 120-150s window)

| cohort | settled | win | avg/contract |
|---|---|---|---|
| taker in-band 94-98 (ask in-band, bid <94) | 80 | 95% | **+0.41c** |
| maker above 98 (bid ≥98.5) | 556 | 99% | **+0.59c** |
| taker above 98 | 481 | 99% | +0.42c |
| maker below floor 93 | 152 | 89% | −3.88c |
| maker below floor 92 | 136 | 92% | −0.48c |
| maker below floor 91 | 119 | 90% | −1.51c |
| maker below floor 90 | 77 | 92% | +1.52c |

Verdict: **floor 94 stays** (91-93 still toxic on fresh data; 90 marginal +small,
n=77 — insufficient to move). Taker at in-band asks when the bid falls below 94
(wide-spread converged books) is thin-positive but unreachable anyway — maker
mode never selects it. The 99c+ maker pocket is positive (+0.59c, 99% win) but
razor-thin: one adverse settle at 98.8c entry erases ~84 equal-sized wins
(~101 at 99.0c, ~207 at 99.5c — gross 1.2c/0.95c win vs ~99c loss); prior "never re-open 99-100"
call stands given pin-break history.

### 2b. Min-TTE — `min_tte_entry_disabled` (the real question)

| cohort | TTE | settled | win | avg/contract | model p? |
|---|---|---|---|---|---|
| post_engine maker in-band 94-98 | 120-150 | 453 | 97% | **+0.65c** | **none — all INPUTS_MISSING** |
| post_engine taker in-band 94-98 | 120-150 | 405 | 97% | −0.01c | none |
| late_window maker in-band | 30-89 | 131 | 98% | +1.15c | none |
| late_window taker in-band | 30-89 | 142 | 98% | +1.17c | none |
| late_window maker above_98 | 30-60 | 200 | 100% | +1.02c | none |

**Decisive finding:** all 7,276 `post_engine` shadow records Nov-1+ are
`min_tte_entry_disabled` AND `probability_status=INPUTS_MISSING`
(`missing_input_fields:["vol_source"]`, `p_calibrated_side=0.5` placeholder).
**No model probability exists below ~150s.** The vol pipeline's inputs are
absent at TTE≤150, so:

- The lane's own floor (90s) is a dead letter — a candidate at 90-150s would hit
  `pinned_fav_maker_no_p`/invalid-confidence even if the 180s global floor were
  lifted.
- The global `MERID_ENTRY_MIN_SECONDS_TO_EXPIRY=180` is **aligned with model
  input availability**, not an arbitrary binder. The +0.65c maker number is a
  price-only counterfactual — realizable only if vol exists there.
- TTE 90-120 and 150-180 pockets are **uninstrumented** (lwf covers >120≤150;
  late_window ≤89). Cannot measure before changing.

Verdict: **do NOT relax the effective min-TTE now.** First fix vol_source
availability below 180s (or confirm a hard pipeline cutoff), then re-measure.
The late-window profits (30-89s, +1.1c both roles) belong to the settlement
lane's domain (min 15s), not pf.

### 2c. Invalid confidence — `confidence_valid` → `invalid_confidence`

Nov 1-5: **4,728 rows / 2,290 unique candidates** (PRC `DATA_QUALITY_VETO`),
~510/day, TTE clustered 180-480s (mid-window, not edge artifacts).

Reason taxonomy (from `strategy_decision_snapshots.confidence_reasons`):

| reason | rows |
|---|---|
| orderbook_sequence_gap | 3,623 (76%) |
| orderbook_not_initialized | 140 |
| orderbook_stale (1-4.8s) | ~150 |
| rti_book_skew | ~40 |
| no_executable_depth | 29 |
| final_minute_entry_disabled | 15 |
| data_state_not_healthy | 8 |

Economics of vetoed candidates at own-side ask 92-99c: 956 unique settled,
96.8% win, **−101.6c total** (~flat-to-negative at taker pricing — and these are
book-integrity-failure moments, so real fills would be adversely selected, i.e.
worse than the ask-price bound).

Verdict: **retain, fully fail-closed.** 76% sequence gaps = genuine WS/book
integrity failures; the veto costs nothing measurable and protects exactly the
moments adverse selection is worst. Consistent with the 10-31 rejection-audit
finding that transport/clock-skew shows up as book-trust failures — a transport
problem to fix upstream, not a gate to relax.

### 2d. In-engine lane vetoes (Oct 25-26 partial extraction; surfaces as `first_block`)

| first_block | rows | note |
|---|---|---|
| pinned_fav_moneyness_cap (no_qualified) | 7,350 | **pre-override**: normal-path NO caps (79/89/75/75/1) applied in-lane |
| pinned_fav_low_ev (yes_qualified) | 2,790 | |
| pinned_fav_moneyness_cap (yes_qualified) | 1,592 | XRP-YES@89 pre-override |
| pinned_fav_maker_low_p | 113 | |
| pinned_fav_tte | 22 | |

Post-override check: NO-side pf submissions **resumed** Nov 1+ — 69 `buy_no`
attempts vs 66 `buy_yes` in order_attempts. The 10-27/10-30 lane-scoped caps
(NO_*=98, YES_XRP=98, YES_ETH unset→uncapped) are working as intended.
`entry_price_cap_*` records in rejected_candidates Nov-1+ (n≈40, mostly wins at
94-98c) are **normal-path** caps on ask-basis evaluations of the same markets —
not pf-lane vetoes.

### 2e. EV gate on bid-basis pf candidates

`no_positive_executable_edge` at pf prices (Nov 1-5): maker_bid bid-basis
+0.63c avg (511 settled, 96% win), empirical_marginal_maker +0.37c (411);
ask-priced maker −0.57c, taker −0.89c. Model p_selected on the cohort: 0.90-1.00
(median ~0.95). Claimed net EV ≤ 0 yet realized bid-basis P&L positive → the
adverse-selection/uncertainty haircut is **overcharged in the 94-98 maker band**
(same anti-predictive pattern the 10-31 audit flagged). Maker/taker asymmetry
confirmed again: identical prices settle positive at bid, negative at ask.

### 2f. Below-floor pocket (85-91 shadow, all TTE)

`would_qualify`: 475 settled, 86% win, **−2.86c** — the floor raise is still
correct on fresh data. `fail:gate_tte_pass` −0.87c (354), `fail:gate_min_ev_pass`
−0.44c (1120), `fail:gate_min_p_pass` −0.09c (1997). `fail:gate_daily_cap_pass`
+1.65c (269) is **confounded** (cap-blocked subset = busiest days), not evidence
to raise the 480 cap — live volume is 26-90/day anyway.

---

## 3. Realized lane performance + the real Nov-1..05 stall

Realized fills Oct 25–Nov 5: **YES 94-98: 44 fill events, 123.84 contracts,
100% contract win rate, +524.3c net (+4.234c/contract, +11.92c/fill-event,
avg entry 95.75c, 2.3c fees)** — the in-band lane is delivering on a
per-contract basis; the earlier per-fill figure overstated per-contract economics. YES 85-93 (pre-floor-raise window): 76 fills,
62 wins, −1020c — floor validated again. NO-side pf: 0 fills all window
(attempts only resumed Nov 1 post-override; all rejected downstream).

**Nov 1-5 the lane went nearly silent** — ~26 attempts/day, ~6 ACK, 2 FILLED.
Order-attempt rejection taxonomy Nov-1+ (125 rejected / 6 acknowledged):

| reason | count |
|---|---|
| `stake_at_risk_cap:pct=0.35` | **66** |
| `market_not_entry_ready:NOT-EXECUTABLE` | ~9 |
| `net_of_cost` (moved against intent at submit) | ~5 |
| duplicate_entry / book_not_initialized / sweep | ~8 |

**The stall is the stake-at-risk cap × MAX_CONTRACTS interaction, not a pf gate
failure.** `MERID_MAX_STAKE_PCT_SHARD_CASH=0.35` (added 10-30) hard-rejects when
`price×count/100 > 0.35×shard_cash` (`order_router.py` ~15905) — it did **not
clip** (fixed 2026-11-05: now resizes to the largest admissible centi-contract
qty bounded by both the stake cap and fee-inclusive cash; sizer also resolves
the trading shard + router's own balance cache so the cap applies upstream).
Reconciliation: the "66" are **74 attempt records covering only 41 unique
(ticker,side) opportunities** (21 tickers rejected ≥2×), all requested
`count_fp=6.0` — sizing never clipped because `exchange_index`/`_cash`
resolution silently skipped the cap (`loop_15m.py` ~7192). With shard cash
~$13.57, cap=$4.75; a 6-lot @ 95c stakes $5.70 → now clips to 4.99. The cap is
correctly motivated (40%-of-bankroll concentration produced the 10-29/30
pin-break losses); the forfeit was plumbing, not policy.

---

## 4. Recommendations

### FIX
1. **stake_at_risk_cap → clip, don't reject.** In `order_router.py` (~15898-15921),
   when `_stake > _stake_cap`, size `count_fp` down to the largest centi-contract
   step fitting the cap (and the existing shard-collateral minimum) instead of
   rejecting. Keeps the 10-30 protection while recovering ~66 submissions/5d at
   current bankroll. Alternative without code change: `MERID_PINNED_FAV_MAX_CONTRACTS`
   → 4 until shard cash > ~$17.
2. **Vol-source availability <180s** is an input-pipeline gap that makes the
   lane's 90s floor unreachable and poisons every <150s counterfactual with
   INPUTS_MISSING. Identify whether `_resolve_annualized_vol` (agent_grid_15m)
   has a hard remaining-seconds cutoff or is staleness-driven; this gates any
   future TTE relax.

### RELAX — only after instrumentation
3. **Effective min-TTE 180→~120s for the pinned_fav maker_bid route only** is
   the one evidence-backed candidate (+0.65c, 97% win, n=453 at 120-150s) — but
   it is price-only (zero model p). Do not relax until vol exists there and the
   90-120/150-180 gaps are instrumented. Never relax for the taker route
   (same cohort: −0.01c).

### RETAIN
4. **Band 94-98 both routes.** 91-93 toxic (−1.5..−3.9c), 99+ razor-thin
   (+0.59c, tail-asymmetric) — both edges confirmed on fresh data.
5. **invalid_confidence veto** — 76% sequence gaps; vetoed cohort ≈ flat.
   Fail-closed is correct.
6. **min_p 0.90 / maker_low_p, EV floors (−15/−12), daily cap 480,
   moneyness honor + lane-scoped caps** — all behaving as designed;
   daily cap not binding; the +1.65c cap-blocked shadow subset is confounded.

### INVESTIGATE
7. **Adverse-selection/uncertainty haircut calibration at 94-98 maker** —
   bid-basis EV-rejected cohort settles +0.63c with p 0.90-1.00. Measure the
   haircut vs realized fill outcomes before any floor change; the current stack
   may be overcharged ~1-2c in-band.
8. **99c+ maker pocket**: +0.59c (556) — keep vetoed; revisit only if the
   pin-break pattern stays absent and haircuts recalibrate.

### INSTRUMENT
9. Extend TTE shadow coverage to 90-180s (both sides of the floor); extend the
   pf maker shadow band to cover the live 94-98 window (currently 85-91 only —
   live-band maker vetoes are invisible today).
10. Persist `confidence_reasons` into the `confidence_valid` gate `observed`
    payload (currently only `confidence:null, source`) — the snapshot join was
    required to audit this class; `liquidity_role` is null on kalshi_fills rows.

---

## 5. Instrumentation/audit caveats

- `pinned_fav_*` vetoes surface only as `first_block` inside `*_qualified`
  gate observed — not in `reason_codes`, `events.reason_code`, or
  `rejected_candidates.reject_reason`. Nov-1+ counts need a gate-JSON scan
  (DB I/O-contended by the live process; Oct 25-26 distribution shown above).
- `decision_ts` epoch note: extract window constant used 1762041600
  (2025-11-02); DB data starts ~Oct 25 2026, so coverage was unaffected.
- Nov 4 had zero fills (process down/halted — worth checking separately; not
  a pf-lane issue).
- The taker in-band positive cohorts (+0.41c) are unreachable under maker mode
  by design — reported for completeness, not as a missed-opportunity claim.
