# MERID pinned-favorites audit — 2026-10-31

Point-in-time audit of the live Kalshi 15m system, structured around the three
questions: (1) are stale inputs causing bad decisions, (2) are eligibility rules
excluding valuable trades, (3) can execution capture the apparent edge.

All numbers below are ledger-derived (`data/kalshi_fills.db` joined to
`data/kalshi_order_attempts.db` payload `decision_lane`, plus
`logs/settlement_outcomes.jsonl`, `logs/rejected_candidates.jsonl`,
`logs/pinned_fav_maker_shadow.jsonl`) or code-verified with references.

---

## 1. What "pinned favorites" actually controls (resolved in code)

- **"Pinned" is a decision-lane label, not a market list.**
  `decision_lane == "pinned_fav"` is stamped at candidate emission in
  `agent_grid_15m.py` and owned by `merid/prediction/directional_regime.py`
  (`pinned_fav_enabled/band_match/block`). There is no manual ticker registry;
  the universe is constructed deterministically (§4).
- **"Favorite" = whichever side's own-side price is in band.** Both sides are
  evaluated; fills confirm dual-side operation (`buy yes@92-98` and
  `sell yes@2-10` = NO@90-98 canonical equivalents).
- **Band = [92, 98]c on the resting own-side BID** in maker mode
  (`MERID_PINNED_FAV_MAKER_LO/HI`, `entry_price_basis=own_side_bid_post_only`).
  Checked at emit (`pinned_fav_band_match`), at the admission gate
  (`pinned_fav_block`), at the mid-fallback clamp + pre-send assert in
  `loop_15m.py:10399-10426`, and at the wire via the lane-band passivity floor
  (`post_only_passivity_below_lane_band`, observed firing 3× in 4d).
- **Caps binding in-lane:** lane-scoped moneyness cap
  (`MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_{SIDE}_{ASSET}` = 98 for all in `.env`)
  consulted before per-asset caps; TTE window **90–840s** (`.env` overrides the
  121s code default); `MIN_P=0.90` reachability (Bachelier z≈1.28);
  `MIN_EV=-12c` (maker); `DAILY_MAX=480`; `MAX_CONTRACTS=6`.
- **Doc drift (finding):** `AGENTS.md` documents `PINNED_FAV_MAX_CONTRACTS=2`
  and `ENTRY_MAX_REST_S=45`; `.env` resolves `6` and `15`. Loss fills this era
  are 6-contract (600cc) — the documented tail bound is not the resolved one.
  Stake_at_risk_cap (35% of shard cash ≈ $4.64 on $13.26) is the effective
  ceiling and rejected 19 attempts in 4d.

## 2. Are stale inputs causing bad decisions?

Mostly no — freshness is layered and fail-closed at the right places — with two
real gaps (one operational, one by design).

**Source (RTI).** `cf_rti_adapter.py:CfbRtiObservation` carries
source_ts_ms + observed_ts (wall) + observed_ts_mono_ns; staleness is gated on
the monotonic clock (`MERID_MAX_CFB_RTI_AGE_MS=5000`, chosen to tolerate the
~1s CF tick cadence; `MERID_RTI_EXECUTION_MAX_AGE_MS=3000` for execution
paths). Both `avg_60s_data` (trailing) and
`last_60s_windowed_average_15min` (final-minute) are parsed as distinct fields
(`kalshi_cf_rti_ws.py:399-415`) — the field-selection bug class the plan flags
is handled. Index IDs match Kalshi docs (BRTI, ETHUSD_RTI, SOLUSD_RTI,
XRPUSD_RTI, DOGEUSD_RTI + aliases). Preflight measured `rti_stream_fresh:
assets=5 max_age_ms=699` at the last restart.

**Book.** Per-sid seq tracking with gap → invalidate → fresh snapshot
(`ws.py:2845-2920`), crossed-market invariants + per-level seq sanitization
(`orderbook.py:402-413`), freshness state machine (LIVE/DEGRADED/STALE/…, 15s
threshold, `book_freshness.py`). **Conflation: `MERID_KALSHI_OB_UPDATE_INTERVAL_MS=1000`**
is active — the documented remedy for the 10-30 ~1100 deltas/s lag storm.
Trade-off to monitor: public book is ≤1s stale while own-order updates arrive
earlier; for a lane whose edge is defined by the resting bid this mostly
affects fill-time revalidation quality, not fill receipt. Mark provisional and
measure fill-time book age distribution before tightening.

**Submit-time.** `execution/submit_revalidation.py` recomputes EV at the final
permitted limit: prob-age ≤30s, book-age ≤5s, max_price bound derived from
required edge (stale approvals can't be reused at worse prices), own-liquidity
overlay with fail-closed unattributable handling, post-only cross →
`submit_reapproval_required`. Named route rejects confirm it fires:
`net_of_cost` 8, `stale_decision_dropped` 5, `pre_submit_passivity` 2,
`post_only_passivity_below_lane_band` 3 (4d).

**Artifacts.** `STALE:CELL_EVIDENCE_INSUFFICIENT` appears on ~2/3 of evidence
verdicts (last 37min sample) — but that is the designed uncertainty-reserve
degradation (evidence tiers 2d/4d/7d), not silent staleness. Real staleness
found:
- **`data/cf_rti_ticks.db` — dead since 2026-10-15.** Scheduled task
  "MERID RTI archiver" is Ready-not-Running. Live trading unaffected (loop has
  its own stream), but replay/audit coverage of settlement bands has a 16-day
  hole.
- **`data/empirical_price_calibration.json` — 27d old vs 14d TTL.** Currently
  `EMPIRICAL_CAL_MODE=shadow` so nothing live depends on it, but the shadow
  comparison it feeds is scoring a stale artifact; the weekly refit hasn't run
  in ~4 weeks.
- `probability_tail_calibration.json` — 16d old; within its policy but aging.
- `epc_wide_fit.json` — 7d of 14d TTL.
- `live_entry_evidence.json` — fresh (12h refresh task Running).

**Operational finding — reconciliation halts are a plumbing artifact, not
divergence.** Three `p0_preflight_failed → LIVE_ENTRIES_HALTED` transitions
today (18:51, 18:57, 19:08), all on `exchange_reconciliation`:
`extra_internal=447 > allowed_extra=431`, `problematic_internal` = internal
`settlement:*` pseudo-fills the REST `/fills` page can't return. The tolerance
tracks a moving REST window while internal settlement rows accumulate —
fail-closed correct, self-resolving (passed 19:13 & 21:30), but it converts a
known bookkeeping asymmetry into repeated entry halts. Recommend making
`allowed_extra` account for `settlement:`-prefixed rows deterministically
instead of by tolerance drift.

## 3. Are eligibility rules excluding valuable trades?

Yes — measurably, but the binding constraint is the reserve stack, and the
excluded-band counterfactual is thinner than win-rate suggests.

**Rejection mix (last ~37min, n=2926):** `NO_POSITIVE_EXECUTABLE_EDGE` 82%,
`NO_ELIGIBLE_PRICE_BAND` 14%, `EDGE_BELOW_DYNAMIC_THRESHOLD` 3%,
`TTE_ENTRY_CUTOFF` 1.4%, `EVIDENCE_HARD_BLOCK` 0.2%, `STRUCTURAL_RISK_VETO` 1.
The reserve stack (risk_reserve ~5.7c + fees + measured ASR) dominates; band
exclusion is second.

**Counterfactual for the excluded 85–91c band** (the instrument already exists:
`pinned_fav_maker_shadow.jsonl`, gate flags + `would_qualify` per eval).
Deduped to one hypothetical fill per market-side at first-qualifying bid:

| cohort | n | win% | naive P&L/contract |
|---|---|---|---|
| ALL (85–91c, both sides) | 662 | 91% | **+2.52c** upper bound |
| SOL yes/no | 69/82 | 93% | +4.33 / +3.98c |
| BTC yes/no | 81/91 | 91/90% | +3.30 / +2.44c |
| XRP yes/no | 71/5 | 90/100% | +3.38 / +9.40c |
| DOGE yes/no | 58/80 | 91/90% | +2.81 / +1.69c |
| **ETH yes/no** | **50/75** | 88% | **−0.50 / −0.09c** |

Caveats required by the plan: this is an all-fill-at-bid bound — passive fills
at 85–91c are adversely selected exactly when the pin breaks, so executable
value is strictly below +2.5c; and shadow records carry `strike_price: null`
(provenance gap in the shadow store — `p_source=market_state.model_fair_prob`
is present but the strike/RTI pair isn't persisted per record).

**The live floor is the bigger problem.** Realized fills cluster losses exactly
at the band floor — same signature that falsified 76–89, then 90–91, now 92–93
(§5). Excluding <94c while keeping the rest is supported by ledger evidence;
extending below 92 is NOT supported as a live move — only as continued shadow.

## 4. Universe & discovery

- Universe = `fifteen_minute_market_locator.SERIES_BY_ASSET` (5 series) ×
  `format_kalshi_event(current 15m bucket)` — deterministic construction,
  current bucket only. **Coverage is complete by construction** for the traded
  product (5 markets live at any time; preflight confirms
  `market_catalog_initialized: 5 markets`).
- Real discovery gap is structural, not per-window: hourly/above-below/range
  crypto families are out of universe entirely. If a broader universe audit is
  wanted, it starts with a series-ticker discovery pass, not ticker pins.
- `MarketIds.no = event+"-01"` is a vestigial construct — real 15m tickers are
  `-{minute_offset}`; verify nothing requests `-01` tickers (minor).
- `settlement_outcomes.jsonl` holds 45,421 settlements — good outcome coverage
  for counterfactual joins.
- Historical migration: fills DB has 1,754 rows; old fills may predate the
  attempts ledger (320 `unattrib` entry fills can't be lane-joined) — a known
  attribution gap for pre-attempt-ledger history.

## 5. Baseline economics — pinned-fav lane, ledger-realized

**Current config era (2026-10-28 → 10-31, MAKER_LO=92):** 89 pinned-fav-only
markets, 310 contracts, **−$4.83 net = −1.56c/contract**. 84W/5L at market
level. (All-ledger 11d incl. legacy bands: 223 markets, −$12.52, 194W/29L.)

| slice | markets | contracts | cash |
|---|---|---|---|
| held <92c | 7 | 42 | −$2.77 |
| **92–93c** | **37** | **134** | **−$7.05** |
| 94–95c | 18 | 56 | +$2.96 |
| 96c | 6 | 24 | +$0.83 |
| 97–98c | 21 | 54 | +$1.21 |
| YES side | 44 | 152 | −$5.78 |
| NO side | 45 | 158 | +$0.95 |
| settled wins | 44 | — | +$9.05 |
| exited wins | 41 | — | +$4.47 |
| **settled pin-breaks** | **4** | — | **−$18.35** |

Four pin-breaks (−5.40 DOGE@90, −5.58 SOL@93, −5.52 ETH@92, −1.84 BTC@92 —
three of four at the 92–93 floor, all 6-contract size) erase +$13.52 gross.
By asset: ETH −$3.68/84cc, SOL −$0.92/86, DOGE −$1.33/80, BTC +$0.13/38,
XRP +$0.97/22.

Context: the lane is a budgeted evidence probe (`MIN_EV=-12c`, intent is to
replace counterfactuals with fills), so −1.6c/cc realized is *within* its
mandate — but the loss signature says the floor pocket is paying for bad fills,
not clean evidence.

**Execution conversion (4d, 283 attempts):** FILLED 93 (33%), CANCELED 70 (rest
expiry/reprice), REJECTED 120 with named reasons — `market_not_entry_ready` 30,
`order_intent_contract` 27, `stake_at_risk_cap` 19, `Unified risk check` 12,
`net_of_cost` 8, `stale_decision_dropped` 5. Every attempt is maker-role;
no taker leakage since the immutable ExecutionPolicy + maker→taker veto.

## 6. Correctness report (code-verified)

- Book normalization: NO prices → NO-space (100−p); YES ask = complement of
  best NO bid; `use_yes_price` persisted across snap/delta; crossed-market
  invariants + per-level seq sanitization. ✓ `orderbook.py`
- Seq gaps: sid-scoped tracking (correct per Kalshi docs), gap → invalidate →
  fresh snapshot. ✓ `ws.py:2845-2920`
- Fees: `kalshi_fee_cents_exact` = rate·C·P·(1−P) ceil'd to $0.0001 — matches
  contract + verified fills; whole-cent helpers deprecated for gating. Caveat:
  single global schedule (taker .07 / maker .0175) — no per-series multiplier
  check; maker fee on live fills recorded 0.0 → current maker cost is
  over-reserved (conservative direction, but it biases lane EV downward).
- Precision: ledger canonicalization in Decimal + centi-contract ints; book hot
  path converts float→int cents at ingest; fixed-point `delta_fp`/`count_fp`
  handled. One wart: delta size `int(round(size_delta))` truncates sub-contract
  fp sizes — only affects depth display granularity, not orders.
- Revalidation: §2 above — strongest layer of the stack.
- Fill semantics: `proceeds_dollars` signed correctly for both buy-yes and
  sell-yes (NO-position) legs; canonical side/action separation verified on raw
  rows.
- Funnel completeness: `all_failed_gates_json` records the full gate vector,
  not first-failure only (`gate_evaluation.py`); provenance chain
  cand→order_decisions→order_attempts→fills→settlement is complete and
  queryable. `forecast_events.jsonl` carries artifact hashes
  (code/walkforward/epc/tail/config) — the evidence manifest mostly exists.
- Missing from funnel: upstream obs→book-receipt→feature→decision→wire-ack→fill
  latency percentiles are scattered (WS-WIRE-LAG, decision_ts, attempt ts,
  fill ts) but not joined into a single record per decision.

## 7. Promotion decisions

| lane/zone | evidence | decision |
|---|---|---|
| pinned-fav 94–98c | +$4.50 gross in-era; exits+settles positive | retain as baseline |
| pinned-fav **92–93c floor** | −$7.05/134cc; every pin-break at floor | **suspend or raise floor to 94** — third consecutive falsified floor pocket; the resting bid at the floor fills exactly when the pin breaks |
| ETH all | −$3.68 live; only asset negative in shadow too (−0.5/−0.09c) | suspend both lanes pending ETH calibration review — consistent cross-instrument signal |
| NO-side in-lane | +$0.95/158cc live, positive in shadow | keep provisional; not yet enough for cap raise |
| 85–91c extension | +2.5c naive upper bound; adverse-fill risk unpriced | **shadow only** — do not promote on settle-outcome evidence alone |
| XRP in-lane probe | +$0.97/22cc, early | keep bounded probe |
| normal-path/other lanes | not this audit's scope | unchanged |

## 8. Upgrade ranking (expected value × evidence × risk)

1. **Cut the 92–93 floor** (or add a fill-side floor-block like
   `passivity_below_lane_band` already does for reprices): cheapest, biggest
   measured loss concentration. Evidence: ledger-realized.
2. **ETH suspension/diagnosis** (both live and shadow negative — a calibration
   or feed-quality issue, not a band issue). Check ETH RTI divergence vs
   secondary feed before trusting either number.
3. **Fix `allowed_extra` for settlement pseudo-fills** — stops repeated
   preflight halts without weakening reconciliation.
4. **Restart the RTI archiver + backfill gap policy** — restores replay
   coverage; mark archival gaps in replay reports.
5. **EPC refit** (artifact is 13d past TTL in shadow mode; weekly cadence
   slipped ~3 weeks).
6. **Join the latency chain into one record** (obs→decision→wire→ack→fill) —
   the instrumentation exists, the join doesn't.
7. **Doc/config drift fix**: reconcile `PINNED_FAV_MAX_CONTRACTS`,
   `ENTRY_MAX_REST_S`, `MAKER_MIN_TTE` between AGENTS.md and `.env` — the
   contract currently overstates tightness.
8. **Passive-fill realism for shadow bands**: the 85–91 counterfactual needs a
   trade-through estimator (fill only when ask prints ≤ bid after entry) before
   any promotion discussion — the current bound overstates.
9. **Per-series fee multiplier check** in CI (comment already flags it;
   schedule is global M=1 and live fills suggest maker≈0 — direction is
   conservative but should be verified against the Series API).

Deferred/not recommended: widening the band below 92, re-enabling any canary
overlay, or promoting on win-rate alone — the 91% cohort win rate at ~88c is
~2–3c of headroom that adverse selection can consume entirely.

---

## Follow-up (2026-10-31 evening) — containment executed

### Corrected cohort decomposition (overlap-aware)

| cohort | markets | contracts | net cash | W/L |
|---|---|---|---|---|
| **retained: held 94–98 ex-ETH** | **33** | **9000cc** | **+$3.29** | **33/0** |
| floor 92–93 all | 37 | 13,400cc | −$7.05 | 33/4 |
| floor 92–93 ex-ETH | 27 | — | −$1.65 | — |
| held <92 | 8 | 4,800cc | −$2.49 | — |
| ETH all-band | 22 | 8,400cc | −$3.68 | — |
| ETH ≥94 only | 11 | — | +$1.38 | 11/0 |

The retained cohort is loss-free this era — but small (avg +10c/market), so it
is a *conditional* reference lane, not validated alpha. Floor is negative even
ex-ETH. ETH's live losses are all at ≤93 — the same floor mechanism as other
assets; ETH's *shadow* negativity (85–91c, both sides) is the independent
signal justifying its separate quarantine.

### Pin-break mechanism (4 reconstructed decisions + partial 5th)

Five era losses (not four — `KXETH15M-26OCT282030-30` NO@93 −$1.53 partially
exited). Decision/side_ev/snapshot joins show:

- Every entry ran **claimed net_ev −1.84..−6.91c** — the −12c lane floor
  (`effective_required_c=-12.0` overriding `required_edge_cents≈2.1`)
  intentionally bought them as evidence probes. Two carried
  `edge_bias_correction_c` of −2.4/−4.0 (model marking itself down).
- z-scores 1.23–1.40, TTE 370–685s — thin mid-window pins, not converged
  favorites. `p_selected = Φ(|rti−K|/σ√T)`; min_p 0.90 ≈ z≥1.28, and
  `_pf_low_p_bypass` releases the pin on CHALLENGE_ELIGIBLE/CELL_EVIDENCE_PASS.
- Books fresh but DEGRADED (3 of 4 `REST_VERIFIED_DEGRADED`, 83–233ms, ws/rest
  diff ≤1 tick); one `WS_FRESH_VERIFIED` 49ms. Not stale-input failures.
- Fill latencies 1.1s (ETH@92, toxic signature) / 2.6s / 46s / 48s / 70s —
  consistent with informed flow hitting resting floor bids.
- `requested_contracts=6.0` on all four — the sizer itself asked for 6.

### Actions applied (.env — pending restart)

- `MAKER_LO`/`PRICE_LO` 92→94 — all four enforcement points verified to read
  `_pinned_fav_lo/hi`; quarantined cohort records `pinned_fav_band` + shadow.
- `PINNED_FAV_MAX_CONTRACTS` 6→2 — the .env-documented conditional restore
  ("re-pin lower if a pin-break repeats"). Per-order semantics verified.
- ETH caps `NO_ETH` 98→0 + new `YES_ETH=0` → `pinned_fav_moneyness_cap` veto
  (verified resolving: `0.0/0.0`).
- `p0.py` +`pinned_fav_policy_resolution` check — echoes the resolved band,
  caps, min_p/min_ev/tte/daily_max/max_contracts with env sources on every
  preflight (fails closed if unresolvable).

### Infra status

- RTI archiver restarted (`Start-ScheduledTask`); verified +140 rows/30s ≈
  1Hz×5 assets into `cf_rti_ticks.db`. Hole 10/15→10/31 stands, marked —
  trigger is at-logon-only with no gap alert (recommend watchdog).
- Reconciliation false-positive fix (`900db577`, settlement-row exclusion)
  confirmed in deployed SHA `031a6b9d`; 19:08 halts predated it. The 7-case
  regression matrix remains unwritten.
- `cand_ad44c0c18e8c4d0c4e8120cd` (SOL loss) has no strategy_decisions row —
  a provenance gap in decision recording worth its own ticket.

---

## Last 36 Wins: Behavioral Replay

Canonical export: `data/pinned_fav_wins_replay_2026-10-31.json` (36 positions
with fills→attempts→decision/side_ev/snapshot/events joins + outcomes).

### Cohort freeze

- Definition: most recent 36 pinned-fav positions with net>0 by last entry
  fill time — **36 positions = 36 distinct tickers = 36 distinct 15m
  buckets** (1:1, no multi-fill inflation). Span: 10-30 17:53→10-31 16:26 UTC.
- All inside the reported −$4.83 era — the streak is *within* that result,
  not additional evidence outside it (era: 84W/5L over 89 positions).
- **Uniform 2-contract orders** (`count_fp=2.000000` on all 55 filled order
  legs; losers ran 6.0 except BTC's 2.0 → −1.84, its proportionally smaller
  loss). Sizing transition: all fills 6-contract through 10-29 ~16h, all
  2-contract from ~19h onward — the `.env` "raised 2→6 on 10-31" comment is
  misdated; effective sizing was already 2 via the risk/lane clamp chain.
  Net +$3.38 over 36 positions (avg +9.4¢/position).
- **The winning streak occurred in a smaller-size operating regime.
  Unequal sizing amplified the era's dollar losses; the replay does not
  establish that smaller size improved selection.** See the counterfactual
  ledgers below — normalization does not change the cohort's sign.
- Mix: XRP 11, DOGE 9, ETH 8, SOL 5, BTC 3 — YES 22 / NO 14.
  **15 of 36 at the quarantined 92–93¢ pocket; 8 of 36 ETH** — the pockets
  are not uniformly toxic on frequency; they fail on tail.

### Size-normalized counterfactual ledgers (41-position replay cohort)

Separating selection performance from exposure allocation. Entry prices and
net are observed fills; **fees were ~0** (maker fills — observed total
$0.03 over 98 contracts) so fee scaling is immaterial here and labeled as
such rather than assumed.

| ledger | sizing rule | net | contracts | note |
|---|---|---|---|---|
| observed | actual (2-ct wins, 6-ct losses) | **−$16.49** | 98 | winners +$3.38 / 72 ct; losers −$19.87 / 26 ct |
| 1-contract normalized | every position at 1 contract | **−$2.24** | 41 | net ÷ observed contracts per position |
| 2-contract capped | actual if ≤2; losers scaled ×2/6 | **−$4.47** | 82 | assumes first 2 contracts of each 6-ct order fill at the observed avg price; ignores queue position and partial-fill risk |

Read-through: sizing amplified the dollar loss ~3.7× (−16.49 → −4.47), but
**the cohort is net-negative at every sizing rule** — losses are near-total
stake wipes (−76.4¢/contract) against thin wins (+4.7¢/contract). Selection
in this cohort was negative independent of exposure allocation; the wins
prove prices were fair, not that fills were cheap.

### W vs L discriminators (same measurements both sides)

| feature | winners (n=36) | losers (n=4-5) | verdict |
|---|---|---|---|
| contracts | 2.0 uniform | 5.2-6.0 | era artifact — dominates $ outcome, not a decision discriminator |
| TTE at decision | med 289s; 23/36 <300s | med 462s; all >300s | **real timing mechanism** — winners entered with more uncertainty resolved |
| \|z\| | med 1.48 (94+: 1.67, 92-93: 1.30) | med 1.35 | mild separation — winners more converged |
| calibrated p (held) | med 0.96 | med 0.92 | same direction as z |
| edge_bias_correction | med 0.00 | med −1.22 | self-markdown flag present only on losers |
| claimed net_ev | med **−5.92c** | med −3.15c | **inverted** — reserve stack anti-predictive inside admitted cohort |
| submit→fill | med 10.9s | med 46s (incl. 1.1s toxic fill) | non-monotonic — weak discriminator |
| book degraded | 34/36 REST_VERIFIED_DEGRADED | 3/4 degraded | ambient, not a discriminator |
| book age | med 18ms | med 120ms | fresh both sides |

### Filled vs unfilled (era attempts, held-px buckets)

- held 92-93: 158 attempts → **39% fill rate** (62F/38C/58R)
- held 94-98: 100 attempts → **23% fill rate** (23F/28C/49R)

The floor fills *more often* — **a fill-rate asymmetry consistent with
adverse selection**: a resting floor bid is hit precisely when the ask
reprices down through it. Denominators are comparable (same lane, era,
attempt classification: F=filled, C=canceled, R=rejected/expired). Not yet
established: resting durations before fill, amendment frequency,
cancellation opportunities between submit and fill, evidence changes, and
executable markouts around fills — so this labels a mechanism consistent
with adverse selection, not causal proof. A matched analysis (durations,
amendments, markouts) remains open shadow work.

### Fragility classification

- Evidence-at-fill: fresh everywhere (book ≤233ms, evidence FRESH); the wins
  are process-valid, not stale-fill accidents. Replay completeness: full
  lifecycle events for all 36 (submit→fill→settle chains intact). The
  near-break axis (settlement margin vs strike) is **unverifiable** for this
  era — the RTI archiver was dead 10/15→restart; prospectively covered now.
- Outcome comfort: all wins small (+0.02..+0.16/position ≈ +1-16¢ gross);
  no near-break margin data → cannot distinguish comfortable vs close wins.
- Honest classification: **"valid process + favorable stretch"**.
  Break-even, shown explicitly: population = all 89 pinned-fav positions in
  the audited era (84W/5L → 94.38% *position-count* win rate). Required
  rate from *observed per-contract payoffs*: loss leg −76.4¢/ct
  (−$19.87/26 ct), win leg +4.7¢/ct (+$3.38/72 ct) → break-even =
  76.4 / (76.4 + 4.7) ≈ **94.2%**. Observed 94.38% sits essentially at
  break-even, consistent with the ≈0 normalized ledger. Weighting caveat:
  the win rate is an unweighted position count while required rate is
  contract-payoff-weighted; at pure entry-price math (avg 93.94¢
  contract-weighted, ~0 maker fees) the naive floor is 93.94%. Either
  reading gives the same conclusion: the streak is fair pricing minus
  tail, not discovered edge.

### Candidate explanations

1. **Supported: unequal sizing amplified the dollar-loss asymmetry.**
   Winners and losers share band, lane, gates, book states; losers are the
   6-contract era, winners the 2-contract era. The normalized ledgers bound
   the claim: sizing explains the ~3.7× exposure amplification, not the
   sign — the cohort is net-negative at every tested size.
2. **Supported: TTE timing separates outcomes** — losses all entered >300s;
   64% of wins <300s. Early-window floor pins carry more breakable
   uncertainty.
3. **Supported: floor fill-rate asymmetry (39% vs 23%)** — different
   execution behavior across pockets, consistent with adverse selection;
   causal proof awaits matched durations/amendments/markout analysis.
4. **Supported: the reserve stack doesn't rank the admitted cohort** —
   winners claimed *worse* EV; feeds the §6 reserve-decomposition study.
5. **Contradicted: "ETH is broken"** — 8/36 wins are ETH; its live losses
   were floor+size driven. Shadow negativity remains the ETH signal.
6. **Contradicted: "92-93 is uniformly toxic"** — 15/36 wins are 92-93.
   The pocket fails on tail economics (39% fill rate consistent with
   adverse selection, against a ~94.2% payoff-weighted break-even), not on
   frequency.

### Decision consequences

- Keep the 92-93 quarantine (net-negative pocket at any size), keep cap=2
  (tail bound), keep ETH suspended (shadow+live combined signal, thin
  live-side evidence).
- New candidate mechanism for shadow validation: **TTE floor** — wins
  concentrated <300s, losses all >300s. Hypothesis: raise
  `MAKER_MIN_TTE_S` (currently 90s binds early side? no — TTE is
  *remaining*; the binding gate would be a MAX or a late-window preference).
  Not a live change: 4-sample loss TTE distribution is thin; measure on
  shadow + held-out first.
- Prospective capture requirement: archiver now running → settlement
  margin (near-break) becomes measurable for future cohorts.

### Research leads — preserved as shadow-only, none promoted

| finding | next analysis | live policy now |
|---|---|---|
| winners concentrated <300s TTE; 4 losses >300s | held-out analysis controlling for asset, entry price, sizing era, and probability | **no TTE change** |
| `edge_bias_correction` −1.22 med on losers, 0.00 on winners | trace when it was computed, its units, and how it affected admission | **no new veto** |
| claimed EV ranks winners (−5.92c) below losers (−3.15c) | decompose reserves/evidence adjustments within comparable cohorts — is the value a final probability-based estimate, a conservative admission score, or cell-evidence-modified? | **no reserve relaxation** |
| book degradation common to winners and losers | retain as health metric only; stop treating it as the primary explanation | **no change** |
| floor/ETH pockets contain wins but poor tail economics | net expectancy and loss concentration, not win frequency alone | **keep quarantines** |

The EV inversion shows the recorded score did not rank these observed
outcomes as expected; it does not yet establish that the reserve stack is
useless. Reserve decomposition remains §6 work.
