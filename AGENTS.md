

```yaml
---
auto_execution_mode: 1
description: MERID/Kalshi 15m automatic live-trading startup and execution contract
live_startup_policy: auto_enable_after_preflight
live_entry_authorization: durable_operator_config
---
```

# MERID Agent Notes

You are a senior Python engineer reviewing, modifying, debugging, validating, or operating the MERID Kalshi crypto 15-minute trading system.

`auto_execution_mode: 1` is an explicit durable operator instruction to enable live Kalshi trading at the next production server restart. On every production startup, the system must perform the required startup preflight automatically. If preflight passes, it must transition to `LIVE_ENTRIES_ENABLED` and begin executing eligible trade decisions without requiring a separate approval token, manual release action, dashboard click, CLI command, or per-run operator confirmation.

This durable authorization applies only to the configured production process and authenticated live Kalshi account. It does not override reconciliation, circuit-breaker, trusted-fill, exit-protection, production-environment, venue-identity, model-release, or risk gates.

The system must never submit an entry merely because it restarted. It may execute the **next eligible strategy decision** after successful preflight and normal entry gating.

## Current runtime state — 2026-11-16 reconciliation

This section is the authoritative statement of *resolved live config* as of
2026-11-16. Where a dated section below conflicts with it, **this section
wins**; the dated sections are retained as historical rationale, not current
contract. Env vars override code defaults; `.env` is git-ignored, so a
deployment must set these explicitly.

### Loss stops are DISABLED (supersedes all stop-loss/loss-cap mechanics below)

- `MERID_DISABLE_LOSS_STOPS=1` and `MERID_LOSS_EXITS_ENABLED=0` are set.
- `LOSS_STOP_TRIGGER_REASONS` (LOSS_CAP, HARD/SOFT/TRAILING_STOP,
  EDGE_STOP/DECAY, etc.) are suppressed at the `stop_candidate` choke point,
  vetoed again in `order_router`, and `position_monitor._evaluate_stop_loss`
  returns `disabled_by_policy`; both loss-salvage carve-outs are force-off.
- **Still live:** `POSITION_MISMATCH`, `STALE_DATA`, `OPERATIONAL_RISK`,
  `RECONCILIATION`, `expiry_liquidation`, manual/emergency exits,
  take-profit, settlement closeouts, and the EV-gated discretionary path
  (`MERID_ENABLE_EV_EXIT_GATE=1`, `MERID_DISCRETIONARY_EXIT_MODE=ev_gated`).
- `MERID_ENABLE_STOP_CANDIDATE_SUBMISSION=1` stays on so the *operational*
  exits above can still submit.
- Every dated section below that describes `LOSS_CAP`, `HARD_STOP`,
  `trailing_stop`, `loss_cut*`, `EDGE_STOP`/`edge_decay`, or
  `model_invalidation` as an active mechanical loss exit is **superseded** —
  those reasons no longer fire live. Re-enable only via an explicit,
  evidence-backed reversal of `MERID_DISABLE_LOSS_STOPS`.

### Audit writer: shed tiers + bounded prune (new since the writer notes below)

- Decision-spine priority is **dynamic**: side-selected decisions stay
  `high` (never shed); pure no-trade evaluations submit `normal`.
- `_shed_admit` tiers: `high` never shed; `normal` shed past
  `MERID_AUDIT_SHED_DEPTH` (120); `low` sampled; an **emergency tier** past
  `MERID_AUDIT_SHED_CRIT_DEPTH` (350) keeps only 1/`MERID_AUDIT_EMERGENCY_SAMPLE_DIV`
  (16) of `normal` writes so the backlog drains.
- `decision_audit.db` hot retention is now **scheduled**: a daemon thread runs
  bounded `prune_old_rows()` every `MERID_AUDIT_PRUNE_INTERVAL_S` (1800s),
  yielding to the writer via the existing lock/progress-handler protections.
  `audit_writer_unhealthy` still gates entries — readiness is earned by
  draining, never by relaxing the gate.

### Reconciliation / fills (repairs since the contract text below)

- `fills_poller` uses a **watermark-anchored lookback**
  (`_poll_lookback_since_ts_ms`: newest-observed fill − 120s, clamped 15m,
  seeded from the durable circuit-breaker watermark) instead of the old
  `now − 20s` window that permanently dropped delayed fills.
- `position_cache` defers `SYNC-CLOSE`/expired-position removal while a
  non-terminal exit attempt ≤300s exists for the ticker, and clears
  `_reconciliation_halted` on a verified-flat three-way match (including
  tickers absent from the REST payload) rather than waiting for settlement.
- `ORDER_NOT_TERMINAL` exit re-arms now check venue order status first and
  skip re-arming a terminal order.

### pinned_fav lane — containment RESTORED 2026-11-18 (post DOGE pin-break replay)

AGENTS.md's 2026-10-31 containment documents band **94–98c** and
`MERID_PINNED_FAV_MAX_CONTRACTS=6`. The resolved `.env` had drifted to
85–99c / 11 contracts (flagged below as unverified). On 2026-11-18 a
DOGE NO@87c pinned-fav maker fill (`KXDOGE15M-26NOV172130-30`, 6ct,
−$4.94, settled YES) landed deep inside the thrice-falsified <94c floor
pocket — the exact cohort the 2026-10-31 audit quarantined (−705c/37mkts
at held 92–93, −249c at held <92). The pending band decision is now
decided by ledger evidence: `.env` restored to the audited containment:

```text
MERID_PINNED_FAV_PRICE_LO=94   PRICE_HI=98
MERID_PINNED_FAV_MAKER_LO=94   MAKER_HI=98
MERID_PINNED_FAV_MAX_CONTRACTS=6
MERID_PINNED_FAV_MIN_EV_CENTS=-15.0   MAKER_MIN_EV_CENTS=-12.0
MERID_PINNED_FAV_DAILY_MAX=480   MAKER_MIN_P=0.90
```

Companion code hardening (same replay): the measured-evidence
`pinned_fav_maker_low_p` bypass in `compute_trade_decision` now enforces a
hard reachability floor (`MERID_PINNED_FAV_EVIDENCE_BYPASS_MIN_P`, default
0.80) — cell evidence substitutes for the *pin*, never for reachability —
and re-asserts the lane daily cap the block returns before checking.
Regression coverage: `tests/test_pinned_fav_lane.py` low-p/bypass block.
Note: `.env` is loaded into `os.environ` at process start, so the running
process keeps the old 85–99/11 values until the next production restart —
the restored band binds on restart, not live.

### Anti-directional hold guard + cheap_no disabled (2026-11-18, second DOGE replay)

Replay of `KXDOGE15M-26NOV172330-30` (NO buy 27c via `cheap_no_settle`,
exited ~3c, settled YES, −$1.44): the model priced `p_yes=0.721` while
the system bought the NO side at `p_no=0.279`.  End-to-end audit found
**no side-mapping inversion**: intent, wire payload (`contract:no,
action:buy`), fill canonicalization, and signed-YES exposure all agree
(`side_conflict=1` on the ledger is a benign counterparty-form artifact,
`exposure_mismatch=0`); a 9,555-entry scan shows `p_selected` always
equals the held side's calibrated probability.  The failure is
structural: `cheap_no_settle` requires a YES-heavy book (complement
≥55c) then buys the minority NO side — anti-directional *by design*,
gated only by p≥0.12 and net_ev≥−10c.  Ledger verdict: −$9.08 on the
0/5 cluster, −$5.75/18 trades since Nov 1, and the 23k-sample
calibration audit shows cheap contracts are net-negative (FLB — the
model overstates longshot p).

Repairs (asset-agnostic, all five assets share the path):

- **`MERID_CHEAP_NO_LANE_ENABLED=0`** in `.env` — the lane is disabled.
- **Anti-directional hold guard** in `trade_decision.py`: every
  selection stamps `held_side_minority` (held-side p below
  `MERID_ANTI_DIRECTIONAL_P_FLOOR`, default 0.5).  A minority hold from
  a lane NOT in `MERID_MINORITY_HOLD_LANES` vetoes
  `anti_directional_<side>` — the formula path, maker_bid, pinned_fav,
  settlement_convergence, trend_yes_hi and late_taker must always hold
  the side the model calls more likely.  Registered minority-hold lanes:
  drift_fav, reversal_scalp, threshold_cell, current_build_provisional,
  evidence_cell_escape, marginal_band, late_edge_probe,
  cheap_tail_canary.
- **Hard floor** `MERID_ANTI_DIRECTIONAL_HARD_FLOOR` (default 0.10):
  vetoes EVERY lane regardless of registration — no coherent entry
  holds a side the model prices <10% likely (FLB makes realized worse).
- **`cheap_no_settle` dropped from the default registry** —
  re-enabling it is now a two-key operator decision
  (`MERID_CHEAP_NO_LANE_ENABLED=1` AND re-registering it in
  `MERID_MINORITY_HOLD_LANES`), not a one-flag flip.
- Regression coverage: `tests/test_anti_directional_guard.py` (5 tests:
  registered-lane admit+stamp, unregistered veto, floor override,
  hard-floor veto, majority stamp).

Remaining known bleeder for a future pass: `mid_yes` (YES 41–93c) is
−$4.82/35 since Nov 1 — not an inversion (majority holds), likely
mid-band adverse selection worth its own cohort audit.

### Third loss replay — pf floors tightened to −3c (2026-11-18)

Replay of `KXDOGE15M-26NOV180545-45` (NO buy 95c, `pinned_fav` maker,
`p_no=0.950`, edge=−5.6c, TTE~330s): pin broke mid-window; the bid's
toxic-mid cancel raced the fill and lost (fill at ~17s — inherent to
resting maker orders, not a bug).  `expiry_liquidation` salvaged 42c at
TTE~115s → −$3.18; settled YES so the salvage was correct.

**Ledger verdict on the favorite lane:** every fill in the ledger is a
negative-EV probe (edge<0 at admission by construction).  The only
positive-edge entry in the window (XRP yes@51c, edge=+0.001) won
+108c.  The pf band wins ~90% at +4..6c and loses −50..−95c on breaks —
a ~19:1 asymmetry where realized cohort incl. tail is ~breakeven at
best.  The 94–98c band containment is right; the −12c EV floor is not:
it admits *parity-priced* favorites (p≈price), whose only edge is the
hoped-for FLB understatement.

**`.env` (2026-11-18):**
`MERID_PINNED_FAV_MAKER_MIN_EV_CENTS` −12.0→−3.0 and
`MERID_PINNED_FAV_MIN_EV_CENTS` −15.0→−3.0.  At −3 an admit needs gross
p−price ≳ +2.5c — the model must see genuine underpricing.  Would have
blocked both recent in-band losers (−5.6c and −5.0c).  Escalation if
still bleeding: 0 (effectively off at favorite prices) or
`MERID_PINNED_FAV_ENABLED=0`.

**Deliberately NOT changed:** the mid-window discretionary exit.
`loss_stops_disabled` kills the stop trigger path; a `value_switch_exit`
trigger would still be vetoed by the evidence envelope below bid 85c /
TTE>120s — and the 173-exit audit measured that cohort forfeiting ~+$8
(58% of stopped-out positions recovered).  The expiry salvage is the
measured-correct close for broken pins.

### Model anchoring vs. reality — verified calibration audit (2026-11-16)

Deduplicated full prediction stream (`model_calibration_observations`,
first-observation-per-(ticker,side) joined to `settlement_outcomes`,
**n=23,415** market-side evals):

- **Brier = 0.158** (SOL 0.155, XRP 0.154, DOGE 0.156, ETH 0.158, BTC 0.166).
  Per-asset meanPred ≈ realized ≈ 50.0%, gap ≈ 0.0pp. The model is *reasonably
  anchored* on average — not badly miscalibrated.
- **Systematic favorite-longshot bias (FLB)** remains:
  - p∈[0.1,0.3) predicted 15–25%, realized 12–24% → **over-confident on
    longshots/cheap contracts** (they win less than priced → −EV).
  - p∈[0.8,0.9) predicted 85%, realized 88% → **under-confident on
    favorites** (they win more than priced → small +EV).
- **Cheap contracts (0–40c) confirmed net-negative on 23k samples**
  (realized −0.7 to −2.5c/contract both sides). Do **not** interpret
  "venture into cheaper contracts" as supported — the data rejects it.
  The realized +EV concentrates in the **high-price favorite band
  (~70–90c)**, which is exactly the pinned_fav lane's audited domain.
- **Caveat:** this measures *calibration of p*, not *profitability*. A
  calibrated model still needs executable edge after reserves/fees. The
  reserves stack (model-uncertainty, giveback, impl-shortfall,
  adverse-selection, edge-bias) is largely **unmeasured priors** because
  fill cohorts are starved (n=0–46) in the current low-trade regime —
  several of those reserves cannot self-correct without fresh fills.

### Known latent stack flaws (audit 2026-11-16 — status noted per item)

- **`pinned_fav_band_match()` flag-independent ownership — FIXED 2026-11-17**
  (`a4ef87b2`): `yes_qualifies` / `no_qualifies` no longer suppress the normal
  path on band *presence*; suppression is now keyed on the lane's actual
  qualify verdict (`_X_pf_qualifies` / `_yes_trend_hi_qualifies`). A band
  price that fails lane economics stays reachable by the ordinary path on
  pure positive edge, and a disabled lane can no longer dead-zone its
  window. See the rescue-lane section below.
- **pf lane bypasses directional-regime guards — FIXED 2026-11-16**
  (`206e5541`): `_yes_pf_qualifies` / `_no_pf_qualifies` are re-bound after
  `_yes_regime_ok` / `_no_regime_ok` are computed, so a favorite can no
  longer enter against a confirmed adverse regime (the SOL-loss class).
  `regime_entry_block` still exempts deep-ITM favorites, so genuinely
  settled contracts are unaffected.
- **Walk-forward calibrator is stale and price-blind**:
  `data/calibration/walkforward_calibrator.json` (built 2026-11-08) segments
  only by (asset, tte_bucket); its "mid" cells are `identity` for BTC/DOGE/
  ETH/SOL. It cannot correct the price-dimension FLB above because it
  averages over all held prices. A price-aware (side×price-bucket)
  recalibration layer is the correct next step — see
  `analysis/RECALIBRATION_SPEC.md` for the walk-forward methodology.
- **EPC overlay exists but is inert**: `MERID_EMPIRICAL_CAL_MODE=shadow`
  points at `data/epc_wide_fit.json` (fitted 2026-10-24, 128 cells). The
  artifact aged past `MERID_EMPIRICAL_CAL_MAX_AGE_DAYS=14` on ~2026-11-07,
  so `_epc.lookup` now fails closed and **shadow observations stopped
  2026-11-07**. Its fit source `logs/rejected_candidates.jsonl` was rotated
  to ~18h of hot data — the Sep–Oct calibration history now lives only in
  the `data/archive/decision_audit_YYYY-MM.db(.gz)` monthly archives.
  `logs/model_calibration_observations.jsonl` (~33 days, n≈23k
  ticker-sides with `p_model`) joined to `settlement_outcomes.jsonl` is the
  viable current calibration source — it is what the n=23,415 audit above
  used. Note the prior EPC artifact was *falsified* (claimed +3..+9c,
  realized −1.3..−3.3c, Brier worse than the book) — promotion to `live`
  is gated on the OOS protocol in `.env`, do not shortcut it.
- **Decisive unbiased-data result (2026-11-17)**: refitting EPC on
  `model_calibration_observations` (101,834 obs, Oct14-Nov11, both sides,
  10-89c, 3-10min TTE) yields **0 of 128 cells validated** - mean cell edge
  **-2.12c**, best cell LCB -0.7c, and top cells' two halves disagree in
  sign. On an unbiased sample there is **no reliable price x TTE edge net
  of fees**; the earlier validated cells were a `rejected_candidates`
  selection artifact (that log only records already-suspect rejects). The
  fit script now accepts either source (`--candidates`), but an empty
  validated set means EPC correctly stays inert - do not force it live.
  The pf lane's audited edge lives at 92-98c / 300-840s, mostly *above* the
  EPC grid's 89c/10min ceiling, so this cell granularity would not capture
  it anyway.
- **Feedback loops verified live, not broken**: `live_entry_evidence.json`
  (Nov 16), `exit_markouts.jsonl` (Nov 16), `kalshi_fills_intent_index.json`
  (Nov 16) all write fresh data. The reserve cohorts are starved of *fills*
  (few trades -> thin markout/giveback/impl/adverse samples), a throughput
  constraint, not a pipeline defect.
- **Cheap-contract exposure already exists, bounded**: the `cheap_no` lane
  (`MERID_CHEAP_NO_LANE_ENABLED=1`, NO 25–40c, TTE≥240s, min-p 0.12,
  min-net-EV −10c, ≤11 contracts, 1/ticker, 96/day) is the sanctioned
  cheap-side probe. The 23k-sample audit shows this cohort is net-negative
  — treat its fills as *paid evidence*, and do not widen it on the
  expectation of positive EV without fresh settled proof.
- **Calibration ≠ profitability**: `p_yes`/`p_selected` are already
  well-calibrated (Brier 0.158). Recalibrating p further has small
  leverage; the binding constraint on trade count is the reserve stack
  (giveback/impl/adverse/edge-bias) whose cohorts are starved (n=0–46)
  because there are few fills. Generating fills via the bounded lanes is
  what lets those reserves measure current conditions — that, not a p
  recalibration, is the realistic path to more trades.

### 85c+ admission audit + rescue-lane spec (2026-11-17)

**Audit — what can admit an entry at held price >=85c:**

- `settlement_convergence` lane (TTE 15-150s, p>=0.84, `MAX_PRICE=99`):
  requires **positive** net edge >= `MERID_SETTLEMENT_LANE_MIN_NET_EDGE_CENTS`
  (=0.75c). Pure-edge; not a bypass.
- `pinned_fav` lane (band 85-99c, maker TTE 15-840s): admits down to
  `MERID_PINNED_FAV_MAKER_MIN_EV_CENTS=-12` / taker `-15` — a **bounded
  negative-EV probe**, gated by p>=0.90, band, TTE, daily cap (480),
  <=11 contracts, maker-only, plus all common structural gates (depth,
  evidence, throttle, bookflow, coinflip, trendside, regime-guard now
  bound, risk, audit). This is the *only* non-pure-edge admission at
  85c+ and it is deliberate, not a leak.
- No other lane reaches 85c+: cheap_no 25-40c, drift 40-74c,
  late_edge_probe 10-69.99c, mband/balanced bands cap below ~90c.
- **No unintentional bypass found.** Every 85c+ fill is either a
  settlement-lane positive-edge entry or a bounded pf probe.

**Rescue-lane semantics — IMPLEMENTED 2026-11-17 (`a4ef87b2`):**

The `(settlement_lane or not _pf_price)` / `(settlement_lane or not
_hi_price)` suppression terms in `yes_qualifies`/`no_qualifies` now key on
the lane's actual qualify verdict (`_yes_pf_qualifies`,
`_yes_trend_hi_qualifies`, `_no_pf_qualifies`) instead of the
flag-independent band match. A pf/hi-band price that fails lane economics
is no longer dead-zoned — it falls through to the ordinary path, which
still applies its full gate stack (edge bound, min_p, regime, conv,
ct-lane, price-cap, late). The rescue only ever *opens* the case the lane
declined; it never closes a previously-open path, weakens no gate, and
cannot double-admit (a side is owned by exactly one lane).

**Honest impact note:** at the *current* pf band (85-99c) the ordinary path
almost never rescues, because its own gates are stricter there — the
near-certainty `min_p_selected` (~0.997 at 88c) plus the reserve stack mean
an 85c+ favorite essentially cannot clear positive edge on the normal path
(that is precisely why the pf lane exists, with its own higher p-cap
headroom). The rescue is therefore primarily a *correctness/dead-zone fix*:
it removes the latent suppression hazard so a widened band or relaxed
gates cannot silently disable normal admission, and it lets any in-band
price that genuinely clears ordinary economics trade. It does **not** by
itself create new 85c+ trades — those still require the pf probe lane or
the settlement lane's positive-edge bar.

**Tests** (`tests/test_pinned_fav_lane.py`, all passing): pf-owned
admission unchanged; disabled-lane and gate-fail rescue admit via the
ordinary path on positive edge (YES and NO); no double-admission / lane
stamp stays non-pf on rescue; existing disabled-terminal-reason and
NO-moneyness-cap-veto regressions still pass.

**Suite verification (2026-11-17):** the pf/lane/regime/edge battery
(~500 tests) passes with the rescue in place.  Two unrelated stale
failures were repaired in `a67e5384` (regime-TTE floor vs conftest pin;
bounded-lane set missing `late_taker_ioc`/`late_edge_probe`).  One
**pre-existing** failure remains and is flagged, not silently fixed:
`tests/prediction/test_maker_bid_lane.py::test_bid_basis_selects_and_stamps_lane`
expects `decision_lane=="maker_bid"` but the candidate now resolves to a
`current_build_provisional` cell — intentional since `34a8237f` (lane-owned
admissions keep their lane id on bid routes).  Whether that provisional
cell *should* own this 46c/300s candidate is a lane-design question for
review; the bid-priced entry mechanics it also asserts still pass.
  **RESOLVED same-day:** the stale expectation was repaired by pinning
  `MERID_PROVISIONAL_LANE=0` in the test fixture (the lane legitimately
  owns the cell; `maker_bid` is the generic fallback label).  See the
  losing-streak section below for the companion suite repairs.

### Losing-streak forensics + sibling-lane regime guard (2026-11-17)

**Symptom:** post-maintenance window produced 10 settled entries,
~-$1.39 realized; the bleed was concentrated in `cheap_no_settle`
(5 fills, 0/5, -$9.08 gross): SOL NO@29c, DOGE NO@29c, SOL NO@28c,
ETH NO@33c, DOGE NO@37c.

**Root cause (code defect, fixed):** the rescue-lane qualifiers —
`_no_cheap_qualifies`, `_no_drift_qualifies`, `_yes_drift_qualifies`,
`_yes_trend_hi_qualifies`, `_yes_late_taker_qualifies`,
`_no_late_taker_qualifies` — are OR-branches inside
`yes_qualifies`/`no_qualifies` and, like `pinned_fav` before `206e5541`,
never consulted `_X_regime_ok` (which binds only the normal-path
branch).  `regime_entry_block` therefore never saw cheap-NO candidates:
ETH 0700 and DOGE 0800 entered NO during `RALLY_CONFIRMED` — the exact
countertrend class the Oct-1 audit and the directional-regime module
exist to veto.  `reversal_scalp` lanes are exempt by design (bounded
countertrend instruments gated by their own regime+bounce match).

**Fix:** `MERID_RESCUE_LANE_REGIME_GUARD` (default on) in
`trade_decision.py` re-binds all six sibling qualifiers to
`_X_regime_ok` immediately after the pf re-bind — same variable-rebind
discipline so selection, lane stamping and block reasons stay
consistent; the deep-ITM exception and per-side penalty/veto mode still
apply through `_X_regime_ok`.  NEUTRAL-regime lane probes are
unaffected; only confirmed-adverse-regime countertrend admission is
removed.  Indicators: `*_regime_blocked` per lane +
`no_cheap_qualifies` snapshot key.

**Regression coverage:** `tests/test_rescue_lane_regime_guard.py` —
7 tests: rally blocks cheap NO (indicator + no selection), neutral
admits via `cheap_no_settle`, selloff keeps trend-aligned NO (label
aged past the trend-freshness arm), `MERID_RESCUE_LANE_REGIME_GUARD=0`
restores admission, normal path stays independently regime-bound,
trend-side symmetry, deep-ITM exception unchanged.

**Companion fixes found by the suite sweep:**
- `submit_revalidation.input_from_intent`: fraction-vs-cents bound
  normalization used `req_edge_dec <= 1`, which also caught every
  NEGATIVE cents value (-10c -> -1000c).  Now `abs(v) <= 1` — real
  latent bug for any cents-stamped lane floor.
- `unified_market_state.OrderbookSnapshot`: added missing
  `best_no_bid`/`best_no_ask` (duality mirrors); `spread_cents` now
  returns `abs(ask-bid)` matching `compute_side_microstructure` and all
  threshold consumers.
- `test_golden_path_15m.py`: removed three dead imports
  (`Crypto15MIndicators`, `UnifiedEdge`, `Strategy`/`StrategyDecision`),
  corrected `TTERegime` import path (`merid.risk.tte_regime`).

**Honest residual:** the regime guard removes the confirmed-rally/selloff
countertrend subset — 2 of the 5 cheap_no losses (ETH, DOGE-0800).  The
remaining 3 losses entered in NEUTRAL regime where the lane is *designed*
to probe; n=5 is too thin to declare the lane broken, but if the
NEUTRAL-regime cheap-NO cohort keeps losing, the correct next step is a
settled-cohort gate on the lane itself (same hysteresis pattern as
`fade_gate`), not a wider regime block.

### Live restart + first verified end-to-end trade (2026-11-17 ~06:03-06:16 UTC)

Canonical restart via `start_15m.ps1` (uvicorn pid 9348, git_sha `e725c2a5`,
`KALSHI_ENV=live`, auto_execution path — no manual token).  Preflight passed
and emitted `live_startup_preflight_passed` + `live_entries_enabled` at
06:05:06 UTC (`run_id=20261117060347_9348_0655c846`,
`reconciliation_snapshot_id=recon_27b8bcee75b2`, `model_release_id=bachelier_twap`).
205 stale order attempts + 25 exit attempts were quarantined as settled-market
non-exposure during P0 preflight — correct, not resolved.

**First live trade of the session — complete verified lifecycle:**

- **Candidate:** `KXDOGE15M-26NOV170115-15`, side `no`, lane `pinned_fav`
  (maker probe), emitted `CANDIDATE_EMITTED` 06:09:35 UTC at ~5.5min TTE,
  `p_no=0.9696`, claimed edge -2.4c (inside the -12c maker floor — bounded
  probe by design).  Prior pf-owned evals on BTC/DOGE in the same window
  vetoed `pinned_fav_maker_only` until a maker route was selectable.
- **Order:** `order_decisions` allowed=true, buy NO 600cc (6ct) limit 94c,
  post-only GTC -> wire `POST /portfolio/events/orders` side=ask price=0.07
  (= buy NO @~93c equivalent), exchange_index=2, success.
- **Fill:** resting order filled 06:10:23 UTC (~38s after submit);
  `kalshi_fills` row: sell YES 6.00 @0.07/0.93, proceeds -$5.58, fee 0.
- **Position:** 6 NO @93c avg; market ran toward NO (held-side bid 98c).
- **Exit:** `hard_profit_lock` triggered 06:11:26 UTC -> sell NO 600cc
  limit 95c, `approved_by_firewall`; fills 06:11:42-45 UTC as buy YES
  4.00+2.00 @0.013 (= sell NO @98.7c effective), exit fees $0.0054.
- **PnL:** -$5.58 entry + $5.9166 exit - $0.0054 fees = **~+$0.33
  (+5.9% on $5.58, ~2min hold)**.  Reentry guard then correctly refused
  same-market re-entry (`prior_pnl=12c`).
- **Reconciliation stress test (passed):** portfolio authority went
  `MISMATCH_LEDGER` at 01:11:30 local while the just-filled position had
  not yet propagated to exchange REST (`exchange_positions=[]` vs
  ledger/cache 6 NO @93c).  The loop emitted `ENTRY_BLOCKED` for ~43s —
  new entries correctly halted during uncertainty — then
  `PORTFOLIO-AUTHORITY-TRANSITION state=RECOVERED ... MATCHED` at
  reconcile_attempt=9.  This is the intended fail-closed behavior.
- **Residual mid-flight:** `RESIDUAL_POSITION_DETECTED 600->200cc` during
  the two-leg exit fill; resolved by the second fill leg.  TP-derivation
  logged `INVALID_TP_*` clears and re-synthesized the exit contract —
  noisy but non-blocking; worth a look if it recurs on normal exits.

**Lane-activity pattern observed live:** pf-owned decisions appear as
`decision_lane=pinned_fav` + `pinned_fav_maker_only` STRUCTURAL_RISK_VETO
while the taker route is selected; the lane only emits once a maker-basis
candidate is selectable (`CANDIDATE_EMITTED`).  All-favorite windows
(e.g. 0130 market: XRP NO@94-97c p~0.93-0.96, ETH NO@93c, BTC NO@91c) were
correctly vetoed maker-only rather than crossing the spread — consistent
with maker-only `ExecutionPolicy`.

**"What a win looks like" — the verified template:** preflight pass ->
`LIVE_ENTRIES_ENABLED` -> lane-owned candidate -> `CANDIDATE_EMITTED` ->
`order_decisions allowed` -> post-only wire ack -> fill -> position
monitor -> profit-lock exit -> fills ledger -> reconcile MATCHED ->
reentry guard.  This session produced exactly that trace once; more
samples accrue as favorites emerge in later windows.

### ⚠ CRITICAL OPERATIONAL FINDING — audit-writer saturation blocks entries (2026-11-17)

Observed live during the 2026-11-17 restart+monitor session:

- `decision_audit.db` is **8.49 GB**; writer heartbeat shows
  `ledger_write_latency_ms` degraded to **~9-17 s per batch** under load.
- The shed tiers work (`normal_dropped` cumulative >1,600) but
  **high-priority side-selected writes are never shed** — with pf/lane
  probes actively selecting sides every eval cycle, admitted volume still
  exceeds drain rate.  Queue depth climbed 380 -> 734+ in ~15 min and
  never recovered.
- `audit_writer_unhealthy` -> `ENTRY_DISABLED_GLOBAL_GATE global_allow=False`
  blocked **all** entries from 01:11:26 local onward this run.  The single
  verified trade (DOGE pf probe, +$0.33) filled at 01:10:23 — inside the
  ~6-minute healthy window after `LIVE_ENTRIES_ENABLED`.
- **This is chronic, not new:** the previous run's err log
  (`server_console_20261116_170903.err.log`) contains **2,567**
  `audit_writer_unhealthy` entry-blocks spanning ~6h; the run before that
  another 362.  pf-lane "allowed" verdicts in `rejected_candidates` that
  produced no orders were very likely blocked by this same gate — the
  lanes are not dead ends; the audit spine is the choke point.
- `MERID_AUDIT_PRUNE_YIELD_QUEUE_DEPTH=400` means the scheduled
  `prune_old_rows` (1800s cadence) *yields* while backlog >400 — it cannot
  rescue a deep backlog; and on an 8.5GB DB a prune is itself expensive.

**Root cause:** audit write latency scales with DB size; the DB has never
been archived/VACUUMed to the monthly-archive layout, so every insert pays
B-tree depth on ~8.5GB.  **Fix requires downtime** (stop server ->
archive/prune/VACUUM or rotate to a fresh DB -> restart) or a code change
that caps/shards the hot table.  Until then, expect entries to be blocked
for the majority of uptime — restart clears only the *in-memory* backlog
and buys minutes, not a fix.

### RESOLVED — audit-DB archive + maintenance restart (2026-11-17 ~05:24-06:05 local)

The saturation above was fixed by **set-based archival**, not VACUUM:

- `data/decision_audit.db` (8.49 GB, ~666k decisions) -> archived all rows
  with `decision_ts` older than ~2 days (**435,000 parent decisions +
  ~2.5M child rows** across side_ev/events/outcomes/snapshots) into
  `data/archive/decision_audit_2026-11.db` (~5.5 GB), then deleted them
  from the hot DB.  File stays ~8.5 GB on disk (VACUUM skipped — see
  below) but row count dropped ~2/3, so write latency recovered.
- **Method that worked:** materialize old `decision_id`s once into a
  small indexed map, then `INSERT ... SELECT ... CROSS JOIN` per child —
  forces one sequential scan per table.  The stock
  `scripts/archive_decision_audit.py` chunked `IN (...)` pattern and an
  `IN (SELECT ...)` variant both degenerate to ~0.2 MB/s random
  autoindex probes on child tables (no decision_id index usage); do not
  reuse them on this DB size/disk.
- **Known gap (accepted):** the parent copy ran under an earlier cutoff
  (~50 min drift between runs), so **~7,435 parent rows were deleted
  without being archived**; their child rows remain in the archive
  (orphaned by `decision_id`).  Analytical value is largely preserved
  in children (side_ev probabilities/EV, events ticker/reasons,
  snapshots book state); parent-level fields for that 1.7% slice are
  lost.  Reconstructable from `decision_telemetry.jsonl` if ever needed.
- **VACUUM deliberately skipped:** index rebuilds are random-I/O bound
  (~0.13 MB/s observed) and would take hours on this disk; the freed
  pages already restore write latency.  Revisit during a quiet window
  or via `PRAGMA auto_vacuum=INCREMENTAL`.
- **Live verification (run `20261117102744_6272_8c647085`, git
  `15a732e7`):** preflight passed 05:28:23 local, `LIVE_ENTRIES_ENABLED`
  via auto_enable.  **Zero `audit_writer_unhealthy` / zero
  `ENTRY_DISABLED_GLOBAL_GATE` events across ~35+ min of live entries**
  (vs 2,567 blocks/6h before).  Three live fills executed and settled:
  SOL NO ~29c x6 ($1.74, cheap_no_settle probe — adverse-selected,
  markout -10.5c @30s, rode to settlement), DOGE YES 95c x5 ($4.75,
  pinned_fav), DOGE NO ~94c x6 ($5.64, pinned_fav).  DOGE post-only
  orders twice rejected `post only cross` (stale maker price) — clean
  no-fill, intent exhausted.  REST settlement/balance path is
  rate-limited (30x HTTP 429) so settlement prints lag; positions
  reconciled closed via `accept_exchange`.

## Automatic live startup

When all of the following are true:

```yaml
auto_execution_mode: 1
runtime_profile: production
venue_environment: live
```

the next server restart must automatically execute the live startup sequence below.

### Required startup sequence

1. Generate a fresh `run_id` and unique `process_id`.

2. Load configuration with environment variables taking precedence over repository `.env` values.

3. Fail startup closed if any configuration identifies test, mock, replay, simulator, sandbox, demo, shadow, paper, direct-execution bypass, debug-order, or manual-order behavior.

4. Authenticate against the configured Kalshi live account and verify:
   - Credentials are present and valid.
   - Account identity matches the configured intended live account.
   - The venue is Kalshi live production, not demo or sandbox.
   - The canonical live Kalshi order router is installed and selected.
   - No test adapter, stub adapter, paper adapter, or mock adapter can receive an entry order.

5. Start the required Kalshi WebSocket implementation and verify:
   - Required market-data subscriptions are active.
   - Order and fill subscriptions are active.
   - The connection is receiving current messages.
   - The trusted fill watermark is available and advancing.
   - Subscription, ordering, symbol, and provenance checks pass.

6. Fetch authoritative exchange state through REST:
   - Account balance and buying power, **per exchange shard** (`balance_breakdown`).
   - Open orders.
   - Current market positions.
   - Recent fills.
   - Required market metadata and market-state information, including each market's `exchange_index`.

6a. Ensure trading-shard collateral. Kalshi collateralizes orders on the exchange shard that hosts the market (crypto 15m markets: shard 2 since 2026-08-24). Cash on shard 0 cannot back a shard-2 order; the exchange rejects it with `insufficient_balance`. Preflight must:
   - Resolve the trading shard from market metadata (`MERID_KALSHI_TRADING_SHARD` may pin it).
   - If the trading shard holds less than `min(MERID_FIXED_EXPOSURE_CAP_USD, total cash)`, move idle cash from other shards with an intra-account transfer (`POST /portfolio/intra_exchange_instance_transfer`). This is a collateral relocation inside the same account, never a withdrawal, and is governed by `MERID_AUTO_FUND_TRADING_SHARD` (default on).
   - Fail closed (`trading_shard_collateral` FAIL) if the trading shard still cannot back the minimum order of one centi-contract (0.01) plus fee (`MERID_MIN_TRADING_SHARD_COLLATERAL_CENTS`, default 1c). Use Kalshi's exact `balance_dollars` / `balance_breakdown` strings, not the truncated integer `balance`, for all cash comparisons.
   - Sizing uses the trading-shard cash (not total equity) as spendable bankroll and reserves the exact parabolic taker fee; fractional counts are rounded **down** to the centi-contract grid.
   - Kalshi charges `rate * C * P * (1 - P)` rounded **up to $0.0001** (0.01c), verified against live V2 fill records (1 contract @47c -> $0.0175; @1.1c -> $0.0008). It is **not** ceil'd to a whole cent. Live sizing, the shard-collateral gate, and the round-trip net-of-cost gate must use `kalshi_fee_cents_exact`; the whole-cent integer helpers are conservative upper bounds only and reject every sub-1-contract order if used as gates. Spread cost is per contract and must be scaled by the fractional count.
   - The loop re-checks every 60s and the order router rejects locally with `insufficient_shard_balance:...` instead of submitting an order the exchange will refuse.

7. Recover all uncertain submission outcomes by `client_order_id`, `intent_id`, and exchange order lookup before considering entries enabled.

8. Build a fresh derived state projection from immutable ledger events plus authoritative exchange REST state. Do not reset caches in place as a rollback shortcut.

9. Reconcile, per active ticker and in signed YES centi-contracts:
   - Exchange positions.
   - Durable fills ledger.
   - Position cache.
   - Position monitor.
   - Global slot allocator.
   - Pending-order and risk-reservation exposure.

10. Quarantine expired or closed-but-unsettled positions under the existing expired-ticker policy. Do not let a quarantined, expired market block active-ticker reconciliation or new entries.

11. Verify all active positions and resting orders are reconciled, protected, or safely quarantined.

12. Verify reduce-only exits, order cancellation, and flatten capability are configured and available. This is a non-mutating readiness validation; do not place a live connectivity-test order.

13. Verify no critical unresolved condition is present:
   - `side_mismatch`
   - `action_mismatch`
   - `qty_mismatch`
   - `overfill`
   - `missing_order`
   - `unmatched_fill`
   - `settlement_mismatch`
   - `missing_settlement_for_settled_market`
   - `missing_pnl`
   - Critical bankroll drift
   - Unresolved unknown submission
   - Broken trusted fill watermark
   - Reconciliation divergence
   - Untrusted side conflict
   - Missing protective-exit capability
   - Trading-shard collateral below the one-contract minimum

14. Verify the live model configuration is approved:
   - Use Bachelier-only with TWAP-appropriate volatility unless another model has a documented approved release.
   - Disable hybrid Bachelier-plus-delta signals—velocity, MACD, RSI, OBI, FVG, and regime—unless explicitly validated and approved.
   - Apply held-side tail calibration per the loaded artifact's scope. With `MERID_CALIBRATION_CAP_FULL_RANGE` (default on) the YES curve caps at every held price; a fitted non-dual NO curve (`no_curve_is_dual=false`, e.g. `tail_pava:n10220`) is applied the same way, while a provisional dual NO curve remains a cheap-tail stop-gap gated by `MERID_TAIL_CALIBRATION_NO_DUAL_RAW_FLOOR`/`_TRANSITION`. `MERID_TAIL_CALIBRATION_PRICE_FLOOR` (default 0.35) bounds the tail region whenever full-range is off.
   - NO-side entries are enabled — governed by measured per-asset moneyness bands, not a blanket tail block. Global `MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO=50` with audited overrides: BTC-NO max 79c (51-64c pocket blocked), ETH-NO max 89c (51-64c blocked), DOGE/SOL-NO max 75c, XRP-NO max 1c (hard-blocked: audited -9.54 USD, unpriceable down-moves). Deep NO tails >=80c additionally face the tail-LCB gate (`MERID_TAIL_LCB_MIN_PRICE_CENTS=80`). Band changes require the same settled-fill + veto-counterfactual audit evidence that produced the current split. These per-asset caps also bind inside bounded sub-lanes: the pinned-fav lane enforces them via `pinned_fav_moneyness_cap` (`MERID_PINNED_FAV_HONOR_MONEYNESS_CAPS`, default on). **2026-11-06 (cap-exception probes):** the `MERID_PRICE_CAP_EXCEPT_*` family (generalized Experiment B) lets an above-cap candidate through only when its reserve-stacked net EV clears `MERID_PRICE_CAP_EXCEPT_MIN_EV_CENTS` (default +2c) at the fresh executable price inside `75 < px <= 89.99`; armed in `.env` for BTC-NO, all YES, DOGE-NO, SOL-NO to re-measure the stale-evidence cohort under the post-2026-11-02 execution stack. Blocked-band vetoes are never cleared, throttle still binds, and each probe kills via its flag returning to 0. The global side baselines do not bind in-lane — the lane's audited domain sits above them by design. 2026-10-27 (NO-side mirror): `MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_{SIDE}_{ASSET}` is a lane-scoped cap consulted before the per-asset moneyness cap; `.env` sets it to 98 for BTC/ETH/DOGE/SOL NO, restoring the YES-side in-lane semantics (the audited <90c caps never measured the >=90c maker band and had made the lane YES-only). The settlement-convergence lane carries the same mirror: `MERID_SETTLEMENT_LANE_MONEYNESS_CAP_CENTS_{SIDE}_{ASSET}` (99 for BTC/ETH/DOGE/SOL NO in `.env`) is consulted before the per-asset cap inside the lane's own cap resolver, so NO converged favorites are not vetoed by the audited normal-path caps there either. 2026-10-30 (operator-directed XRP probe): the pinned-fav lane now also carries `MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_YES_XRP=98` and `_NO_XRP=98` — a bounded evidence probe inside the maker band (2-contract submissions, maker-only, p>=0.90, EV floors, shared 480/day budget). The normal-path XRP caps (YES@89 / NO@1) and the settlement-lane XRP exclusion are unchanged pending the probes settled fills. Normal-path caps are unchanged. The pinned-fav maker band floor history: `MERID_PINNED_FAV_MAKER_LO=92` (2026-10-28) after the 90-91c pocket proved toxic — post-floor cohort ran 73% win / -1405c over 82 contracts including every post-floor loss, while px>=92 ran 100% / +611c over 103 (prior raise: 82/76->90 on 2026-10-24). **2026-10-31 containment: floor raised 92 -> 94 and ETH briefly quarantined; quarantine lifted same-day (eth_pf_reopen_2026-10-31: NO_ETH=98, YES_ETH unset -> lane default) — see the 2026-10-31 containment section for the current effective band.**
   - Require the corrected full fee and execution-cost model for every entry decision.

15. If every preflight step succeeds, persist an immutable startup release record and set:

```python
live_runtime_state = "LIVE_ENTRIES_ENABLED"
entry_halted = False
```

16. Begin evaluating normal strategy decisions. Route a live order only when the individual decision passes all entry gates.

17. Emit structured telemetry:

```text
live_startup_preflight_passed
live_entries_enabled
run_id
process_id
kalshi_account_id
venue_environment=live
reconciliation_snapshot_id
fill_watermark
model_release_id
```

### Preflight failure behavior

If any startup preflight condition fails:

```python
live_runtime_state = "LIVE_ENTRIES_HALTED"
entry_halted = True
```

The system must:

- Block every new entry.
- Preserve cancellation, reduce-only exits, stop-loss handling, and flatten capability.
- Retain risk reservations for unknown submission outcomes.
- Emit the exact structured denial reason.
- Persist a durable preflight failure record.
- Retry only the specific safe recovery/synchronization action required to resolve the failure.
- Never silently switch to paper execution, simulation, or mock routing while reporting live readiness.
- Never blindly retry a potentially accepted exchange order.

The next restart may retry automatic preflight. It may enable entries only after all preflight checks pass.

## Live-entry authorization

A new entry is authorized when all of the following are true:

```python
auto_execution_mode == 1
runtime_profile == "production"
venue_environment == "live"
live_runtime_state == "LIVE_ENTRIES_ENABLED"
not circuit_breaker.is_halted
not reconciliation_halted_for_ticker
startup_preflight_is_current
kalshi_websocket_is_healthy
trusted_fill_watermark_is_current
rest_sync_is_current
canonical_live_router_is_active
protective_exit_capability_is_available
model_release_is_valid
```

The individual trade decision must additionally pass:

- Market is active and eligible.
- Fresh executable own-side price is available.
- Market state and settlement-reference provenance are valid.
- Risk limits, bankroll limits, slot limits, and pending-order exposure limits pass.
- No existing exchange/cache position exists for the ticker.
- No resting entry order, unresolved order, or unknown submission outcome exists for the ticker.
- Final-minute restrictions pass.
- Entry has a unique `intent_id` and `client_order_id`.
- The order includes `run_id`, `process_id`, and a structured `reason`.
- Full net edge after corrected fees, spread, expected slippage, and execution costs passes the configured threshold.
- Tail calibration is valid for the held side and price bucket.
- Required RTI provenance is valid if the settlement path uses CF Benchmarks RTI.
- The market's exchange shard holds at least `limit_price + fee` per contract of cash.

The live system must not submit entries outside this canonical decision path.

### Execution mode: full live, no canary lanes

Production runs one decision path: the core Bachelier/TWAP lane with the held-price floor, π* premium, and executable-cost EV gate. Bounded sub-lanes within that path — settlement (`MERID_SETTLEMENT_LANE_*`), pinned-fav (`MERID_PINNED_FAV_*`), cheap-NO (`MERID_CHEAP_NO_*`), mband (`MERID_MBAND_*`), and `current_build_provisional` cells — are production features with their own audited domains and kill switches; they are not canary overlays. The exploration overlays (`MERID_CHEAP_TAIL_CANARY_*`, `MERID_CANARY_4C_LCB`, `MERID_LIVE_CANARY`) are **off** and must stay off unless a documented, approved experiment re-enables one. Order size is bounded by the account (`MERID_MAX_CONTRACTS_PER_ORDER`, `MERID_FIXED_EXPOSURE_CAP_USD`), not by a canary flag; raise both together as the bankroll grows. A low account balance is not a reason to halt entries — the system must size to what the trading shard can collateralize and otherwise trade normally.

`MERID_OBSERVE_ONLY` is an operator emergency read-only switch. `start_15m.ps1` derives its default from `auto_execution_mode` (1 → `0`); it must never silently default to read-only while this contract says auto-execute.

## Runtime halt and recovery

Automatic live startup authorization remains valid only while runtime safety remains healthy. Immediately set:

```python
live_runtime_state = "LIVE_ENTRIES_HALTED"
entry_halted = True
```

when any of the following occurs:

- The circuit breaker trips.
- Reconciliation divergence occurs.
- Trusted fill watermark stops advancing or regresses.
- Required WebSocket subscriptions fail, become stale, or lose required provenance.
- REST state becomes stale.
- A critical golden-record discrepancy occurs.
- Critical bankroll drift occurs.
- An unmatched or untrusted fill is detected.
- A submission outcome is unknown and requires recovery.
- The configured account or venue identity changes.
- The selected order router is no longer the canonical live Kalshi router.
- Protective exits, cancellation, or flatten capability become unavailable.
- A required environment safety control is disabled.
- The active model release, tail calibration, or RTI provenance becomes invalid.

During an entry halt:

- Do not submit new entries.
- Continue consuming exchange fills through `apply_fill_once(fill_id, ...)`.
- Preserve trusted live position state.
- Preserve risk reservations until confirmed release or recovery.
- Continue reduce-only exits, protective handling, cancellation, and flattening.
- Reconcile authoritative REST and WebSocket state.
- Quarantine untrusted discrepancies without mutating position state.

Entries may automatically resume after a runtime halt only when:

1. The specific failure has been resolved.
2. A new reconciliation snapshot passes.
3. The trusted fill watermark is current and non-regressing.
4. No critical audit discrepancy remains unresolved.
5. Required exits and live routing remain available.
6. The process remains in production/live mode with `auto_execution_mode: 1`.
7. A durable `live_runtime_recovery_passed` event is persisted.

Do not call a direct application-level `resume()` method to bypass these conditions.

## Environment and routing rules

Production startup with `auto_execution_mode: 1` must fail closed if any of the following are true:

- `paper`, `shadow`, `simulation`, `replay`, `mock`, `test`, `demo`, or `sandbox` routing is enabled.
- A direct venue submission bypass is enabled.
- A debug/manual-order feature is enabled.
- Credentials are missing, conflicting, invalid, or attached to an unexpected account.
- The configured Kalshi endpoint is not live production.
- Reconciliation, trusted-fill canonicalization, exit firewall, or protective-exit controls are disabled.
- The active router is not the canonical live Kalshi router.
- The selected model is not approved for live use.
- The tail calibration artifact is missing, invalid, or unapproved for either held side (a provisional dual NO curve is acceptable only as the documented tail-scope fallback, not as the fitted NO curve `MERID_CALIBRATION_CAP_FULL_RANGE` assumes).

The system must log the resolved runtime configuration at startup, excluding secret values, including:

```text
runtime_profile
auto_execution_mode
venue_environment
router_implementation
kalshi_account_id
paper_mode
shadow_mode
simulation_mode
replay_mode
exit_firewall_mode
require_exit_parentage
model_release_id
tail_calibration_artifact_hash
trading_shard
shard_balances
auto_fund_trading_shard
```

## Preserved non-negotiable safeguards

All existing rules in this contract remain mandatory, including:

- Exact integer centi-contract quantities.
- `Decimal` price, fee, cost-basis, and PnL arithmetic.
- Signed YES exposure accounting.
- Global immutable `fill_id` idempotency.
- The `intent_id → client_order_id → order_id` identity chain.
- Durable `apply_fill_once(fill_id, ...)` handling across router, WebSocket, and REST sources.
- Quarantine of unmatched and untrusted fills.
- Trusted-fill canonicalization before live-position mutation.
- Raw exchange execution facts as the authoritative exposure source.
- Reduce-only exits that cannot expand or reverse exposure.
- Per-ticker reconciliation against exchange, ledger, cache, monitor, allocator, and pending-order exposure.
- Retention of risk reservations for unknown submission outcomes.
- Protective-exit provenance and fail-closed requirements.
- CF Benchmarks RTI source, freshness, symbol, ordering, and provenance gates.
- Circuit-breaker fail-closed behavior.
- Automatic preservation of exits whenever entries are halted.
- Live-router provisional fills must be promoted (not duplicated) when the
  authoritative exchange fill arrives. The promoted record keeps the user's
  canonical side/action from the originating intent, but overwrites the
  yes/no leg prices, fee, execution audit fields, and cash proceeds with the
  exchange's authoritative values. The canonical leg price and signed
  proceeds are recomputed from the authoritative legs and the user's outcome
  side so counterparty-form fills cannot flip position cost basis.
- Realized PnL is computed from authoritative signed cash proceeds where
  available, not from leg-price conversions, so cross-leg and
  counterparty-equivalent fills produce the correct PnL.

## Coding directive

Implement the next-restart live switch as a **startup state machine**, not as a broad bypass or a simple boolean checked inside the order router.

Required state transitions:

```text
STARTING
  → PREFLIGHT_RUNNING
  → LIVE_ENTRIES_ENABLED
```

or, on any failed condition:

```text
STARTING
  → PREFLIGHT_RUNNING
  → LIVE_ENTRIES_HALTED
```

For a post-startup safety failure:

```text
LIVE_ENTRIES_ENABLED
  → LIVE_ENTRIES_HALTED
  → RECOVERY_RUNNING
  → LIVE_ENTRIES_ENABLED
```

The final transition back to `LIVE_ENTRIES_ENABLED` requires a successful fresh reconciliation and durable recovery event. It must not occur from an in-memory boolean reset, a direct router call, or an uncoupled `resume()` path.

`auto_execution_mode: 1` must cause the next restart to run this state machine automatically and execute the next eligible live trading decision after `LIVE_ENTRIES_ENABLED` is reached.
## Settlement-aligned exit gate (2026-09)

All discretionary exits are observe-only until `MERID_ENABLE_EV_EXIT_GATE` is
enabled in the resolved live config. A discretionary exit is any reason whose
economic justification is "the model or price says sell" — including
`stop_loss`, `trailing_stop`/`trail`/`ratchet_trim`, `loss_cut*`,
`take_profit`/`ratchet_floor`/`scale_out`, `signal_reversal`/`edge_decay`,
`model_invalidation`, and non-mechanical `time_exit` (`time_stop`,
`adaptive_timing`).

Operational exits (`reconciliation`, `manual`, market closed/cancellation,
documented mechanical closeouts) and emergency exits (`expiry_liquidation`,
hard risk) remain live with their existing mechanical checks. Unknown reasons
fail closed.

2026-10-24 — signal-family operational exits (`signal_reversal`, `edge_decay`,
`model_invalidation`) additionally face a **conservative-hold veto**
(`MERID_SIGNAL_EXIT_EV_VETO`, default on): when the evaluator can price the
sell-vs-hold comparison and the net sell value does not exceed the
conservative hold value, the exit is held as `HOLD_SELL_VALUE_INFERIOR`
instead of bypassing. An unpriceable exit (no bid, no model value) keeps the
mechanical bypass — the fallback the 2026-09-23 deadlock fix requires — and a
genuine breach (sell value above conservative hold + margin) proceeds
mechanically without added persistence. This closed the false-stop hole where
signal exits sold at 42-52c on contracts that settled YES while the same
evaluator was holding discretionary stops as inferior sells.

The final authority for a discretionary exit is the settlement-aligned
sell-vs-hold comparison in
`merid/event_venues/kalshi/settlement_aligned_exit.py`, enforced at
`loop_15m._run_exit_price_guard` and at `stop_candidate.maybe_submit_stop_candidate`:

```text
NetSellValue          = executable same-side bid - exit fee - slippage
ConservativeHoldValue = calibrated held-side settlement probability
                        - uncertainty reserve - residual hold risk
exit allowed          <=> NetSellValue > ConservativeHoldValue + switch_margin
                        for >= MERID_EXIT_EV_MIN_CONSECUTIVE observations
```

Entry price is sunk and never enters the decision. Required inputs: a fresh
sequence-confirmed executable bid for the held side (never the ask, a mid, or
a synthetic opposite-side conversion) with enough visible depth for the order,
a fresh sequence-confirmed execution-eligible CF Benchmarks RTI/model
observation, calibrated model inputs (a default/fallback volatility source or
missing calibration artifact is a hard blocker), and complete entry
provenance. Missing or stale data yields `HOLD_DATA_INSUFFICIENT` — never a
sell.

Evaluator statuses are explicit: `SELL_SIGNALLED` (economics + persistence
cleared), `HOLD_SELL_VALUE_INFERIOR`, `HOLD_PERSISTENCE_NOT_MET`,
`HOLD_DATA_INSUFFICIENT`, `HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED` (inside the
final RTI averaging window, default 60s — a dedicated settlement-phase
evaluator is required there; ordinary spot/velocity model value is not an
adequate proxy), `HOLD_OUTSIDE_CANARY_SCOPE` (sell signalled but outside the
configured canary envelope), `BYPASS_OPERATIONAL`, `BYPASS_EMERGENCY`, and
`BLOCK_UNKNOWN_REASON`. Only `SELL_SIGNALLED` may authorize a live
discretionary order, and only while the gate is enabled;
`MERID_EV_EXIT_GATE_KILL=1` restores observe-only immediately (read live on
every evaluation — no restart required).

The persistence counter is keyed by (market_pk, position_id, held_side,
policy_version, canonical reason, model vol/calibration version). Any context
change, data-validity failure, non-breach, zero quantity, exit attempt start,
or exit fill resets it — a stale signal can never combine with a later
unrelated one.

Every evaluation, exit fill, and settlement is recorded so each real exit can
be replayed against the hold-to-settlement counterfactual, keyed by the
canonical full market ticker (`exit_evaluations.jsonl`,
`exit_counterfactuals.jsonl`). Startup emits a machine-readable `EV-EXIT-GATE`
policy line; whenever the legacy path would have submitted a discretionary
exit, an `EXIT-LEGACY-INVERSION-AUDIT` record logs the trigger price versus
the canonical held-side bid and the EV verdict (critical severity on price
divergence or EV disagreement). Each evaluation records `asset`,
`visible_bid_depth`, `fee_model_version`, `fee_order_type_assumption`,
`p_held_raw_cents`/`p_held_calibrated_cents`, `rti_phase`, `model_vol_source`,
and `model_calibration_version`; the guard annotates evaluations with the
legacy verdict (`legacy_outcome` record lines) so replay can join the legacy
comparison population by `evaluation_id`.

### Gate status (current): enabled in `ev_gated` mode

The gate is ON: `MERID_ENABLE_EV_EXIT_GATE=1` and
`MERID_DISCRETIONARY_EXIT_MODE=ev_gated` in the resolved live config. Every
discretionary exit must pass the settlement-aligned sell-vs-hold evaluation;
operational and emergency exits keep their mechanical bypasses subject to the
signal-family conservative-hold veto above. The shadow
phase below is retained for provenance — it ran across BTC, ETH, SOL, XRP,
and DOGE with all discretionary exits shadowed while the loop emitted
`EV-EXIT-SHADOW-SUMMARY` per asset and `EV-EXIT-SHADOW-GLOBAL`
(positions evaluated, legacy triggers, EV sell/hold/data-insufficient/
near-settlement/uncalibrated counts, side mismatches, legacy-EV disagreements,
median RTI/book age, median bid depth, attempts in flight, unmatched fills).
`scripts/ev_exit_shadow_report.py` joins `exit_evaluations.jsonl` to
`exit_counterfactuals.jsonl` by canonical `market_pk` and prints the promotion
table segmented by asset/side/reason/price bucket/RTI phase: realized vs
counterfactual hold P&L, exit opportunity cost, win rate, Brier/ECE, data-age
medians, and invalid-data rate. A high `HOLD_DATA_INSUFFICIENT` rate means the
inputs are not ready — it is not evidence the gate is too strict. Under pytest
the singleton registry never writes to `logs/`; `MERID_EV_EXIT_LOG_DIR`
overrides the directory, `MERID_EV_EXIT_DISABLE_PERSIST` disables writes.

### Canary scope (parsed, not active)

The live mode resolved to `ev_gated`, not `ev_gated_canary` — the canary
envelope is not active. If the mode is set to `ev_gated_canary`,
a `SELL_SIGNALLED` decision must additionally satisfy the canary envelope or it
becomes `HOLD_OUTSIDE_CANARY_SCOPE`: `MERID_EV_EXIT_CANARY_ASSETS` (e.g. `BTC`),
`MERID_EV_EXIT_CANARY_SIDES` (e.g. `YES`), `MERID_EV_EXIT_CANARY_REASONS`
(first live reason: `value_switch_exit` — the evaluator's own decision, not a
trailing-stop or take-profit trigger), `MERID_EV_EXIT_MAX_CONTRACTS` (default 1),
`MERID_EV_EXIT_MAX_ORDERS_PER_WINDOW` (default 1, counted per canonical market
key at authorization), `MERID_EV_EXIT_MIN_SECONDS_TO_EXPIRY` (120) /
`MERID_EV_EXIT_MAX_SECONDS_TO_EXPIRY` (600). `MERID_EV_EXIT_REQUIRE_*` flags
(`FRESH_RTI`, `SEQUENCE_CONFIRMED_BOOK`, `ENTRY_PROVENANCE`,
`SUFFICIENT_BID_DEPTH`, `CALIBRATED_MODEL`) default to the strict posture.
Do not widen the envelope without a replay report showing clean behavior.

## Current-build dual-side provisional lane (2026-09-30)

`merid/prediction/current_build_provisional.py` implements the
`current_build_provisional` execution lane: a bounded, versioned
live-learning regime that evaluates YES and NO independently for
BTC/ETH/SOL/XRP/DOGE under current-build economics. Its contract:

- **Domain (hard, fail-closed):** executable ask 20-89c, TTE 120-600s,
  quantity 1 contract, post-only maker only, no taker/IOC fallback, at most
  one reprice (the router's one-shot `_post_only_repriced_once` bound), one
  open order globally, max 3 fills/day lane-total, 1 fill/asset/day, 1
  fill/cell/day, and 1 YES fill/day initially. Env overrides may only narrow
  the domain.
- **Thresholds:** per asset x side provisional min net EV (BTC/ETH 2.0c NO /
  2.5c YES; SOL/XRP/DOGE 2.5c NO / 3.0c YES), env-overridable via
  `MERID_PROVISIONAL_MIN_EV_C[_<ASSET>_<SIDE>]`. The threshold is residual
  margin measured AFTER fees, executable-side price, book/depth reserve,
  pre-submit revalidation, passive construction, and source-degradation
  reserves � it never waives current costs.
- **Evidence policy:** legacy/pre-change evidence (including old
  hard-block verdicts) is demoted to `LEGACY_RISK_LABEL` + uncertainty
  reserve for this lane � it can change labels and monitoring intensity but
  cannot veto a current-build, current-market, positive-EV candidate.
  Current-build hard safety failures (untrusted book/spot, stale
  revalidation, non-passive construction, domain violation, mapping
  invariants, risk/account blocks, nonpositive EV) remain hard blocks.
  `MERID_PROVISIONAL_EVIDENCE_OVERRIDE=0` restores legacy vetoes as an
  emergency off-switch.
- **Cell authority:** a registered `threshold_cells` cell owns its
  asset x side x price x TTE region absolutely � even when SUSPENDED or
  when `MERID_THRESHOLD_CELLS=0` kills that lane (`cell_region_registered`
  is consulted state-blind). Provisional cells (`cbp_*`) claim only
  genuinely unregistered regions and never rescue a blocked registered band.
- **Execution policy:** intents carry an immutable `ExecutionPolicy`
  (`required_post_only`, `allow_taker_fallback=False`, `max_reprice_attempts=1`,
  `max_order_lifetime_s=45`) plus `provisional_cell_id`; `max_rest_seconds`
  is set to the lane lifetime (45s) so unfilled orders expire and free the
  global open-order slot promptly. `MERID_PROVISIONAL_MAKER=0` suppresses
  emission rather than coercing to taker.
- **Suspension (fail-closed, per cell):** immediate � first fill with 5s
  markout <= -3c, fill-time revalidated EV <= 0, first-trade PnL
  < -(entry edge + 2c), post-only order filling as taker, side/mapping
  invariant violation, or two consecutive router rejects. Rolling
  (default 3-fill window) � mean net PnL < -1c, median 5s markout < -1c,
  two-of-three negative 5s markouts, or router reject rate > 40% after
  >=5 attempts.
- **Evidence separation:** records persist under
  `data/evidence/current_build/<build_sha>/<model_version>/` and carry
  build_sha, model_version, calibration_version, policy_version
  (`cbp_v1`), admission_lane, asset/side/price/TTE buckets, decision- and
  fill-time EV, post-only limit, depth, fill latency, 1s/5s/30s markouts,
  realized/settlement PnL, and terminal reason. Legacy artifacts are never
  merged into this store.
- **Promotion:** `promotion_review_report()` marks a cell
  `promotion_ready` only on current-build evidence (>=10 passive attempts,
  >=3 fills, non-negative mean PnL and median 5s markout, reject rate <=
  suspension ceiling, zero post-only breaches, not suspended). Promotion to
  the permanent registry is an explicit review act � never automatic off a
  single winner.
- **Kill switches:** `MERID_PROVISIONAL_LANE=0` disables the lane (all
  candidates fall back to the formula path); lane state lives in
  `data/current_build_provisional_lane.json` (test-isolated via
  `MERID_PROVISIONAL_STATE_PATH` / `_LIFECYCLE_PATH` / `_EVIDENCE_DIR`).
- **Adverse-selection reserve (2026-10-01):** the authoritative EV gate's
  `adverse_selection_reserve_per_contract` is now measured � the resolved
  cell's rolling 5s markouts (widened to the asset+side aggregate when the
  cell has < `MERID_ADV_SEL_MIN_SAMPLES`=2 samples), floored at
  `MERID_ADV_SEL_FLOOR_CENTS`=0.5 and capped at `MERID_ADV_SEL_CAP_CENTS`=5.
  `MERID_ADV_SEL_RESERVE_ENABLED`=0 restores the zero reserve.  The value
  rides `TradeDecision.adverse_selection_reserve` into the gate, the audit
  `adverse_selection_haircut_cents` column, the order-decision ledger, and
  agent telemetry � previously all hardcoded to zero.
- **Entry rest bound (2026-10-01, value corrected 2026-10-31):** all entry
  lanes bound resting life at `MERID_ENTRY_MAX_REST_S`=15s per the approved
  operator setting (documented here as 45s since 10-01; `.env` and the
  resolved runtime value are 15 — the env wins and is the approved value).
  Exits keep the 180s `OrderIntent` default.  Unbounded resting life let
  stale orders fill into repriced books (ETH NO@34 fill at 150s, fill-time
  edge -23.5c).
- **Promotion review trigger (2026-10-01):** `promotion_review_report`
  now fires automatically once per (build, cell) when both review
  thresholds are met (attempts >= `MERID_PROVISIONAL_REVIEW_MIN_ATTEMPTS`
  AND settled fills >= `MERID_PROVISIONAL_REVIEW_MIN_FILLS`), recorded to
  the evidence store and `promotion_review_<cell>.json`.  Attempts and
  router counters accumulate in `submissions_total` /
  `router_attempts_total` / `router_rejects_total` � the daily maps reset
  per UTC day and could never reach the review threshold under the
  5/day per-cell submission cap.
- **Audit lane provenance (2026-10-01):** `strategy_decisions` now carries
  `admission_lane`, `admission_owner`, `provisional_cell_id`, `build_sha`;
  `strategy_decision_side_ev` carries per-side `admission_owner`,
  `threshold_source`, `legacy_risk_label` � current-build evidence is
  queryable apart from legacy rows.
- **Live-evidence export guard (2026-10-01):** the settlement-triggered
  rebuild of `data/live_entry_evidence.json` skips writes under pytest
  unless `MERID_LIVE_EVIDENCE_PATH` is explicitly redirected, and the
  export only counts `is_eligible_for_research=1` rows � test fixture
  settlements can never contaminate the live evidence floor.

Tests: `tests/test_current_build_provisional.py` (grid/domain, thresholds,
precedence over the formula, registered-cell authority, legacy demotion,
caps, suspension rules, evidence store, promotion report, decision-level
lane stamping, bounded-domain gate, fill-space normalization,
adverse-selection reserve, promotion-review trigger,
audit provenance columns).

## Empirical price-calibration overlay (2026-10-04)

Signal-quality finding: the Bachelier model is shrunk toward the market mid
(`MERID_MARKET_ANCHOR_*`) and adds ~no information beyond price (Brier
0.2170 vs market 0.2177). The book itself is mis-calibrated: NO-side
favorites held 50-89c with 3-7 min to expiry win more often than price
implies (walk-forward over 4 splits: +6.1c to +9.2c/trade OOS, all 95%
lower bounds > 0). YES-side cells fail OOS and are excluded.

- Module: `merid/prediction/empirical_price_calibration.py`; artifact
  `data/empirical_price_calibration.json` (fail-closed if missing,
  bad schema, or older than `MERID_EMPIRICAL_CAL_MAX_AGE_DAYS`=14).
- Mode: `MERID_EMPIRICAL_CAL_MODE` = off | shadow (default) | live.
  Live raises the matched side's p to price + shrunk cell uplift (upward
  only); every downstream gate still applies.
- Refit (weekly, artifact goes stale after 14 days):
  `scripts/fit_empirical_price_calibration.py`
- Validate before refit goes live: fit with `--end <split> --out <tmp>`
  then `scripts/eval_empirical_price_calibration.py --artifact <tmp>
  --start <split>`; require a positive 95% lower bound.
- Forward scoring: `logs/empirical_cal_observations.jsonl` (one row per
  ticker/side/TTE-minute) joined to `logs/settlement_outcomes.jsonl`.
- Other audit tools: `scripts/signal_quality_audit.py`,
  `scripts/market_calibration_audit.py`,
  `scripts/stop_settlement_counterfactual.py`.

## Evidence freshness + 15m audit ops (2026-10-14)

- **Evidence age tiers are widened** (`MERID_EVIDENCE_DEGRADED_AFTER_S`=
  172800, `_STALE_AFTER_S`=345600, `_UNUSABLE_AFTER_S`=604800,
  `_DEGRADED_MAX_CONTRACTS`=3): the entry-evidence artifact is a rolling
  prior — an aging artifact now degrades gracefully instead of vetoing or
  fail-closing flow. UNUSABLE (>7d or missing file) still blocks
  evidence-dependent entries; `MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL`
  remains as a file-loss fail-safe.
- **Artifact refresh runs out-of-process**: the 48h join takes ~56min on
  the ~19GB decision_audit.db, so `MERID_LIVE_EVIDENCE_EXPORT=0` stays.
  `scripts/live_evidence_refresh.py` runs it on a query_only connection;
  scheduled task `MERID live evidence refresh` runs every 12h.
- **Bounded-lane sizing**: `MERID_BOUNDED_LANE_MAX_CONTRACTS` (default 1)
  caps BOUNDED_POST_ONLY_LANES per-order contracts; set to 6 in .env —
  lane-specific caps subordinate it where present (pinned-fav enforces 2,
  see the 2026-10-31 containment section).
- **15m market audit**: `scripts/kalshi_15m_audit.py --days N` replays
  settlement (60s TWAP from archived CF-RTI snapshots), feature
  monotonicity vs signed ATR distance (ATR_15m = rolling median
  |close-open| over prior 96 windows), symmetry, per-asset logistic fit,
  and maker/taker fee reconciliation. Writes `data/kalshi_15m_audit.db`
  and `reports/kalshi_15m_audit_<ts>.json`.  Runs in ~1-3min on 3d: one
  idx_decisions_ts range scan + one sequential snapshots rowid-range
  scan (snapshot rowid tracks insert order — no per-row PK probes).
  `--snapshot PATH` copies the DB first if the live writer is hot.
  Ledger quirks the audit corrects for: stored seconds_to_close is
  stale/quantized and ':taker' records stamp ttc=0 while actually sitting
  minutes before close — effective ttc is recomputed from the row-
  consensus close_ts; stored close_ts drifts per row.  Kalshi's S_open
  is the PRIOR window's last-60s band; the displayed strike is used as
  the open reference when that window wasn't sampled.  settlement_
  reference_price is absent on ':pre' rows in the final ~40-70s — close
  reconstruction there is coverage-limited (flagged low-confidence).
- **Live RTI tick archive** (2026-10-14): `scripts/rti_archiver.py` opens
  its own authenticated Kalshi `cfbenchmarks_value` WebSocket (broadcast
  channel, no order endpoints) and persists every per-second frame —
  value, CF rolling `avg_60s`, windowed-15m field when present, src/recv/
  local timestamps, seq — to `data/cf_rti_ticks.db` (WAL).  Filters to the
  5 traded assets (`MERID_RTI_TICK_ASSETS`); 10-day retention pruned
  hourly; logs to `data/rti_archiver.log` when run under pythonw.
  Scheduled task `MERID RTI archiver` runs it at logon with restart-on-
  failure — independent of the trading server, so server restarts don't
  gap coverage.  Start manually: `Start-ScheduledTask -TaskName
  'MERID RTI archiver'`; the task action runs `.venv\Scripts\pythonw.exe`.
- **Audit prefers tick bands**: `kalshi_15m_audit.py` resolves each
  window's open/close 60s band from rti_ticks when coverage is complete
  (>=10 samples AND max inter-tick gap <=15s incl. band edges — a
  mid-band archiver restart is rejected, not silently averaged).  CF's
  own `avg_60s` at the band edge is stored as a crosscheck
  (`tick_band_coverage.avg60_xcheck_*` in the report; observed agreement
  ~0.01-0.7 ticks).  Snapshot `settlement_reference_price` and
  `kalshi_strike` remain the fallbacks for pre-archive windows.

- With the live server running, full-conftest pytest runs can hang on
  shared state; use `--noconftest` for targeted suites (EPC, terminal
  codes, residual-exit, provisional, router tests all self-isolate).
- Structural gates (countertrend/bookflow/conviction/throttle) are now
  counterfactual-logged to `logs/rejected_candidates.jsonl` and map to
  terminal codes `LOW_CONVICTION` / `STRUCTURAL_RISK_VETO`.

## Fill price semantics (kalshi_fills ledger)

- `execution_price_cents` and `canonical_leg_price_cents` are always the
  **YES-leg price**, for both `yes` and `no` actions.  A NO position's
  held-side cost = `100 - leg_price` (+ fees); a NO exit's proceeds =
  `100 - leg_price` (- fees).
- `action`/`side` columns are the *submitted* order legs.  The
  canonical position is in `canonical_position_side` /
  `canonical_position_action`: `sell yes` = short YES = a **NO
  position** (betting down); `buy no` canonicalizes to the same thing.
- P&L example (0200 window): `buy no` YES-leg 42 -> NO@58 cost; `sell
  no` YES-leg 28 -> NO realized 72c = +14c gross.  Reading the leg price
  as the NO price inverts winners and losers - this mistake was made once;
  always convert via `100 - leg`.
- `client_order_id` prefixes: `merid_*` = entry, `stopcand_sc-*` =
  stop-candidate/arbiter exit, `exit_*` = guard-path exit.

## 2026-10-29 execution-safety fixes (post-restart loss review)

Root cause of the day''s -552c loss: a `pinned_fav` post-only bid at the
92c `MAKER_LO` floor was rejected `post only cross`, then the maker->taker
IOC conversion (`order_router._convert_to_ioc`) swept the repriced book
and filled 4@91.5 + 2@91.6 � *below* the floor the lane exists to defend �
and the market settled NO.  The lane had no immutable `ExecutionPolicy`;
`resolve_bounded_lane_execution_policy` covered only cell/provisional lanes.

Contract changes now in force:

- **`pinned_fav` immutable maker contract**: `resolve_bounded_lane_execution_policy`
  returns `required_post_only=True`, `required_liquidity_role="maker"`,
  `allow_taker_fallback=False`, `max_reprice_attempts=1`,
  `max_order_lifetime_s=300` (fill-quality tracker TTL) for every
  `decision_lane=="pinned_fav"` intent �
  unconditionally (a non-post-only pinned_fav intent fails closed at
  `PRE_WIRE_POST_ONLY_UNAVAILABLE`).  Stamped at intent construction in
  `loop_15m.py` like every other bounded lane.
- **No maker->taker on policy-vetoed entries**: `_convert_to_ioc` declines
  entry conversion when `execution_policy.allow_taker_fallback is False`
  (`[MAKER->TAKER-POLICY-VETO]`).  A `post only cross` on the lane now
  means skip/requote-passive � never an IOC into the falling ask.
  Reduce-only exits keep their authorized one-shot conversion unchanged.
- **Lane-band floor on passive repricing**: `_post_only_strict_passivity`
  rejects a buy reprice that would land below `_lane_entry_band_cents`
  (`post_only_passivity_below_lane_band`).  The ask repricing to <=92c is
  the pin breaking; resting at 91 is the adverse fill.
- **Reachability gate**: `p_selected` is the Bachelier z-distance
  `Phi(|cfb_rti-strike| / sigma*sqrt(T))` � the same "index far enough
  from strike" filter external research maps to z>=1 (their +9.6c vs -1c
  per-fill split).  `MERID_PINNED_FAV_MAKER_MIN_P` raised 0.85 -> 0.90
  (~z>=1.04 -> ~z>=1.28), still admitting the observed winning cohort
  (p_sel 0.91-0.98) while vetoing the thinnest-reachability tail.
- **Lane sizing cap**: `MERID_PINNED_FAV_MAX_CONTRACTS` (default = generic
  bounded cap) set to 6 — operator-directed sizing realignment
  2026-10-31, restoring the pre-containment envelope.  Deep-favorite
  binaries lose the whole stake on
  a pin break � 6 @ ~91.6c was ~38% of bankroll.  6 @ 94-98c stakes
  ~$5.6-5.9 per order (~40% of the ~$14.4 bankroll) on a single
  settlement tail — the same concentration that produced the 10/29-30
  pin-break losses; re-pin lower on the audit doc's rollback criteria.
  The cap is authoritative over risk-scaled sizing:
  `MERID_PER_TRADE_LOSS_BUDGET_CENTS`=600 with
  `MERID_RISK_SCALED_SIZING_ENABLED`=1 proposes ~6 contracts inside the
  94-98c band (600/94 ~= 6.4), and the lane cap binds the final
  constructed quantity — the P0 `pinned_fav_policy_resolution` echo
  prints the interaction on every preflight.  Scope is per-order at
  construction, effectively per-market via the one-position-per-ticker
  gate; cross-market exposure is not bounded by this cap — independent
  tickers may each hold a 6-contract position under the global
  `MERID_FIXED_EXPOSURE_CAP_USD` slot allocator.
- **Terminal-market exit suppression**: `exit_arbiter._arbitrate_locked`
  returns `market_terminal` and declines all proposals once the market is
  provably past close+`MERID_EXIT_MARKET_DEAD_AFTER_S` � previously ~46
  `never_transmitted` model_exit attempts in ~80s on a settled market.
  Unresolved attempts still reconcile via `market_terminal_inferred`;
  resolved rows are marked `market_settled`/FLAT.
- **Launcher forensics**: `start_15m.ps1` redirects the uvicorn child''s
  stdout/stderr to `logs/server_console_<ts>.{out,err}.log` and appends a
  `logs/server_lifecycle.jsonl` row (pid, exit code, stderr tail) on exit �
  the 10/29 crash-loop died five times post-RSA-auth with no artifact
  because output went to the console window only.  In-app
  `faulthandler_dump.log` and the 80s hang dump are unchanged;
  `dump_traceback_later` stays banned (3.11 access violations).

Deliberately unchanged: `model_exit` profit-takes at 97-99c (the
audit-derived exit envelope measured high-price sells *saving* vs terminal
reversals � local evidence beats the external hold-to-settle result, and
`exit_counterfactuals.jsonl` keeps measuring the fork); `emergency`/
`HARD_STOP`/`LOSS_CAP` mandatory-risk triggers stay mechanical per the
structured-authorization contract (revisit only with a settled
counterfactual audit of the 00:27 stop-out class).

## 2026-10-31 pinned-fav containment (post-audit, operator-approved)

Findings basis: `MERID_PINNED_FAV_AUDIT_2026-10-31.md` + canonical replay
export `data/pinned_fav_wins_replay_2026-10-31.json`.  The pinned-fav live
era was net-negative (~-$4.83); losses clustered at the 92-93c floor and in
6-contract orders.  Policy is containment, not promotion: nothing below was
validated as profitable.

- **Band 94-98c**: `MERID_PINNED_FAV_MAKER_LO`/`PRICE_LO` raised 92 -> 94.
  The 92-93 pocket showed ~-$7.05 tail economics plus a 39%-vs-23% fill-
  rate asymmetry consistent with adverse selection (a resting floor bid
  fills when the ask reprices down through it).  Emit (`pinned_fav_band_
  match`), gate (`pinned_fav_block`), the loop clamp in `loop_15m.py`, and
  the wire passivity floor (`_lane_entry_band_cents` -> `order_router.py`)
  all resolve the same env helpers, so this is a single-source change —
  not a fifth override.
- **ETH quarantine** *(lifted 2026-10-31, cohort `eth_pf_reopen_2026-10-31`)*:
  the 0/0 lane caps were removed by operator-directed controlled reopen —
  `NO_ETH` restored to the 2026-10-27 mirror value 98, `YES_ETH`
  intentionally unset (-> no in-lane cap, matching BTC/DOGE/SOL YES).  A
  policy decision, not evidence of reversal; post-reopen ETH results form
  a separate cohort.  Rollback criteria and exposure bounds are declared
  in the audit doc appendix.
- **Retained 94-98 ex-ETH lane**: monitored reference lane only — 33
  markets, +$3.29 in the replay slice, zero losses.  Thin sample; it is a
  restricted baseline for continued evidence collection, **not** a
  validated profitable strategy.
- **Cap 6 authoritative over loss-budget sizing** *(realigned 2026-10-31
  from the audit-era 2)*: documented in the lane cap bullet above —
  loss-budget proposes ~6.4 in-band, cap binds final qty at 6.0.
- **Entry rest**: `MERID_ENTRY_MAX_REST_S`=15 resolved (see corrected rest
  bound bullet).
- **Sizing-era uncertainty**: fills were uniformly 6-contract through
  ~2026-10-29 16h UTC and uniformly 2-contract from ~19h onward —
  *observed* timing; the specific config change that caused it is not
  proven.  The `.env` comment "raised 2->6 on 10-31" is misdated (the 2-ct
  regime predates it by ~40h).  Treat as an operating-regime boundary when
  comparing cohorts, not a proven causal fix.
- **Restart + verification requirement**: production restarts go through
  `start_15m.ps1` only (duplicate-launch guard on port 8011; no shutdown
  endpoint exists — kill the listener, let the launcher write
  `logs/server_lifecycle.jsonl`, relaunch).  Before shutdown, reconcile
  open orders/positions and cancel resting orders incompatible with the
  policy — do not assume restart cancels them (15m GTC lifetime bounds the
  exposure).  Post-restart, verify on the *real* process — not a config
  probe — that the `pinned_fav_policy_resolution` P0 line reports band
  94-98, ETH caps YES none / NO 98 (post-reopen resolution),
  `max_contracts=6.0`, the loss-budget subordination line, plus
  SHA/run_id/config hash.  Verify the first constructed order's
  `count_fp` equals the bound value (2.0 under the audit-era cap, 6.0
  under the realigned cap), not just the env var.  On any check
  failure: halt new submissions; do not revert to the old exposure.
- **Settlement pseudo-fill exclusion**: ledger-native payout legs
  (`fill_source="settlement"`, `fill_id` prefix `settlement:`,
  `ingestion_source="settlement_rest"`) are excluded from fill-identity
  reconciliation — they are cash movements, never trades.  Regression
  suite: `tests/event_venues/kalshi/test_kalshi_p0_fill_identity_
  reconciliation.py` (7 cases incl. genuine-extra-execution fail-closed).
- **Shadow-only research leads** (no live change): late-window/TTE
  preference, `edge_bias_correction` as admission signal, claimed-EV
  inversion vs outcomes (reserve decomposition), floor fill-rate
  asymmetry matched-duration/markout analysis.  `p0.py` is not in
  `LIVE_MONEY_PATH_FILES` — a noted protection gap for follow-up.

**2026-11-06 addendum — lane TTE floor + resting-cancel reconciliation**
(`MERID_TTE_ENTRY_GATES_AUDIT_2026-11-06.md`): the lane was written for a
90s engine floor; `MERID_ENTRY_MIN_SECONDS_TO_EXPIRY=180` dead-lettered the
90-180s slice and left a 60-90s hole under the settlement lane.  Changes:

- `MERID_PINNED_FAV_MAKER_MIN_TTE_S=60` (was 90) — lane window now 60-840s,
  covering both the 90-180s dead-lettered slice and the 60-90s hole.
- `MERID_PINNED_FAV_TTE_FLOOR_EXEMPT=1` (default on): the engine floor
  passes an own-side bid inside the maker band (94-98c) at TTE >30s so
  `pinned_fav_block` applies its strict gates — it is a lane exemption,
  **not** a generic floor lowering.  `=0` restores the floor.
- `MERID_PRE_EXPIRY_CANCEL_MIN_S_PINNED_FAV=45`: pf-lane resting orders get
  their own cancel floor; the generic 120s threshold would otherwise pull
  a 90-180s maker entry before it could rest to fill.  All other lanes
  keep 120s.  Exits were already exempt.
- Evidence basis: settled-basis counterfactual shows converged favorites
  >=94c bid thin-positive at TTE 60-89s (+0.3-0.7c); all lane gates (band,
  min_p 0.90, min EV -12c, moneyness caps, 480/day budget, 6-contract cap)
  unchanged.  Treat 60-180s pf fills as a measured probe cohort — kill via
  the exemption flag, not by raising the floor for other lanes.

## Admission lineage and side-export verification

- A selected side's `effective_required_source=lane_floor:drift_fav` or
  `lane_floor:cheap_no_settle` must retain that admission owner through
  `decision_lane` and `entry_lane`. A matching provisional/threshold cell
  is not evidence that its own admission bound passed. Do not attach its
  execution cell ID to a rescue owned by another lane: lane identity drives
  sizing caps, lifecycle budgets, and position-specific exit handling.
- Export calibrated probabilities from `selected_outcome` first; consult
  `best_side` only when there is no selection. The ungated edge leader can
  legitimately differ from the qualified side, and their held-side
  calibration pairs need not match.
- Targeted offline verification: `.venv/Scripts/python.exe -m pytest
  --noconftest tests/test_lane_identity_repairs_2026_11_08.py
  tests/test_side_mapping_properties.py tests/test_exit_order_side_mapping.py
  tests/test_agent_grid_side_mapping.py -q`.
- Use indexed decision-ID joins for `strategy_decision_events` investigations;
  an unindexed time-range aggregation can scan the entire large events table.

## 2026-11-08 operator-directed legacy-price relief and late-entry policy

The operator requested reopening stale moneyness restrictions under current
execution economics. `MERID_MONEYNESS_EV_RELIEF_ENABLED=1` in local `.env`
allows BTC/ETH/SOL/XRP/DOGE, independently on YES and NO, to overcome the
normal-path legacy price caps and blocked pockets only at executable held
prices 10-89.99c with finite reserve-stacked net edge >=2c/contract. The
original veto is retained as `{side}_legacy_price_veto`, with
`{side}_moneyness_ev_relief` marking the policy change. This is an
operator-directed policy change, not a claim of demonstrated profitability
or a promotion of historical counterfactual fills. The feature defaults off
without explicit configuration; `=0` restores legacy price vetoes. Its value
participates in the resolved live configuration hash.

Coin-flip, calibrated probability, evidence, tail-LCB, book freshness/depth,
structural, throttle, final executable-cost, position, collateral, startup,
and risk gates still bind. The relief does not widen the disabled 90c+ tail
or the settlement-convergence lane's own price limits. Pinned-fav may use
the same positive-EV relief when configured within its domain; its existing
94-98c production domain and immutable maker policy are unchanged.

The generic entry floor is now 120s, consistently in engine/risk/resting
monitor defaults and local `.env`; candidates with 150s remaining can reach
normal economics. At <=120s the engine still refuses generic entries; the
existing pinned-fav/settlement exceptions keep their own contracts. Drift,
cheap-NO and marginal rescue lane minimums are not lowered. Existing generic
pre-expiry resting cancellation remains 120s. No live process restart or
exchange mutation is part of this offline change. `.env` is ignored by Git:
deployments must explicitly set the relief flag and the desired entry floor.

Offline verification (full conftest may stall with the production server
running): `.venv/Scripts/python.exe -m pytest --noconftest
 tests/test_moneyness_ev_relief.py tests/test_directional_regime.py
 tests/test_pinned_fav_lane.py tests/test_postrestart_fixes.py
 tests/test_settlement_lane.py -q`.

Research basis: Kalshi market lifecycle documentation identifies `close_time`
as the trading boundary, independently of expected settlement time; Kalshi's
Crypto Markets help and CRYPTO15M terms confirm final-minute CF index
averaging. Lalor/Swishchuk, *Market Simulation under Adverse Selection*
(arXiv:2409.12721v3), supports retaining execution/adverse-selection reserves
rather than treating unfilled historical bids as guaranteed profitable fills.

Read-only runtime audit: `scripts/window_funnel_report.py --days 0.05` scanned
10,072 recent evaluations / 2,954 episodes on 2026-11-08, reporting 183
emitted episodes and no joined wire attempts. Indexed decision-ID event joins
found `entries_block_reason=audit_writer_unhealthy` plus entry-trap vetoes;
server heartbeat samples showed 3,200-3,600 pending writes with oldest age
>1,200s. These are separate from moneyness/TTE policy. Do not bypass writer
readiness or erase queued/failure evidence to restore entries. Live recovery
requires writer health and the normal fresh reconciliation/recovery contract.
Counterfactual rows in the funnel are not guaranteed fills or independent
profitable trades. Pinned-fav offline fixtures must redirect
`MERID_PROVISIONAL_STATE_PATH` too: otherwise production markout history
(e.g. a 21.5c ASR) changes unrelated admission-test economics.

## 2026-11-09 post-partial residual-stranding repairs

Forensic basis (live XRP 091200/091030 markets): `ratchet_trim` closed 3 of
4 contracts by design, then the residual runner (a) could strand because
`position.exit_reason`/`exit_triggered` stayed set, (b) could wedge behind
a dead `RESOLVING_ON_EXCHANGE` attempt, and (c) had no dedicated floor —
EDGE_DECAY EV-vetoed, HARD_STOP shadowed, settlement-guard premium-gated —
so it rode to a 0 settlement.

- **Residual-runner breakeven floor** (`MERID_RESIDUAL_RUNNER_FLOOR`,
  default 1): once `ratchet_trimmed` or `scale_out_triggered` is set, the
  monitor tracks the residual's own-side peak and emits a mandatory-risk
  `LOSS_CAP` when the bid breaches `max(entry_basis, peak -
  MERID_RESIDUAL_RUNNER_TRAIL_CENTS)` (default 8c).  LOSS_CAP bypasses the
  discretionary EV gate, the winning-side hold veto, the profit floor, and
  the price-stop shadow; a banked winner can never round-trip to zero.
- **Terminal partial release**: `_reconcile_exit_intent` now releases the
  in-flight lock on `filled`/`executed` (and canceled/rejected-with-fills)
  orders once the attempt's confirmed fills are reflected in
  `position.size` (pre-size snapshot is stamped on the in-flight record at
  mark time).  Full closes still resolve via the flat path.
- **Dead-wire release**: an exit attempt absent from the exchange with
  zero confirmed fills for `MERID_EXIT_IOC_DEAD_AFTER_S` (90s)
  terminalizes `not_accepted_confirmed` and releases the lock instead of
  retaining `SUBMISSION_UNKNOWN` forever.
- **Stale-flag re-arm**: at the top of `_check_position`,
  `exit_triggered`/`exit_reason` are cleared when no in-flight intent
  exists — re-arms `auto_exit_99c`, hard locks, and every other trigger on
  residuals without weakening the in-flight dedupe itself.
- **Slot expiry buffer**: `MERID_SLOT_EXPIRY_BUFFER_SECONDS` (default
  120s, was hardcoded 600s) frees a settled position's per-asset slot
  inside the next 15m window instead of ~10min after close.

Tests: `tests/test_residual_runner_repairs_2026_11_09.py`.

2026-11-08 writer-throughput repair: the audit writer now group-commits —
`_writer_main` drains everything already queued (up to
`MERID_AUDIT_WRITER_BATCH`, default 128) into one `BEGIN IMMEDIATE`/commit
via `_write_tx` per-item SAVEPOINTs, so per-item commits no longer bound
drain rate on the spindle. A failed batch still records durable
`decision_audit_writer_failures.jsonl` entries per required item; the
`audit_writer_unhealthy` entry gate, lag budget, and reconciliation
contract are unchanged — readiness is earned by draining, not by relaxing
the gate. The `MERID_AUDIT_SHED_DEPTH` fallback in
`_sampled_out_rejection` was also aligned to `_shed_admit`'s 700 so
noise-class rejection sampling engages inside the 700–1500 band.

## Session-loss replay and trailing-exit reason semantics

- `strategy_decision_outcomes.realized_net_pnl_cents` is a legacy-named
  per-contract entry-to-settlement thesis counterfactual, not account P&L.
  Inspect `capital_realized_pnl_cents` and reconcile quantities and fees
  against authoritative signed `kalshi_fills.proceeds_dollars`; those cash
  proceeds already include fees, so do not subtract `fee_cost` again.
- Monitor `trail` intents must preserve `trailing_stop` semantics across
  the intent-contract bridge. Mapping them to `exit_manual` causes the
  arbiter to request `EXTERNAL_AUTHORITY`, which correctly denies the
  position-monitor issuer. Live XRP-26NOV100915 trailing attempts at
  14:06:46 and 14:08:21 UTC demonstrated this failure.
- Offline verification: `.venv/Scripts/python.exe -m pytest --noconftest
  tests/test_exit_orphaned_position_linkage_2026_10_28.py
  tests/test_exit_order_side_mapping.py tests/test_side_mapping_properties.py -q`.
- Automatic exit transport must preserve canonical reason semantics, including
  take-profit, scale-out, model/signal, time, and market-obligation exits.
  Unknown automatic reasons must not fall back to operator/manual authority.
- The operator's latest requested policy is automated pre-settlement liquidation
  for all remaining quantities, including trimmed runners. The monitor attempts
  full closeout at T-120s regardless of lane or unrealized loss; deadline exits
  bypass settlement-value holds and profit floors. New settlement-only entries
  are rejected, entries require more than 150s remaining, and resting entry
  expiration is capped at T-120s. Liquidity or venue failures can still prevent
  fills; unknown submissions remain locked for authoritative reconciliation.
- Drift-lane tests must isolate repository environment overrides and measured
  adverse-selection artifacts. The rescue fixture pins its reserve and uses a
  directional candidate that passes the shared conviction/coin-flip gates.
  These synthetic economics are not evidence that the lane's live strategy is
  profitable; measured drift adverse selection remains bound in production.
- Legacy scaling defaults off and must not be enabled based on scaler unit tests
  alone: its child executor clones order identity and bypasses canonical routing;
  aggregate fill accounting and per-child reservations need end-to-end repair.
- Expanded isolated verification: `.venv/Scripts/python.exe -m pytest
  tests/test_exit_orphaned_position_linkage_2026_10_28.py
  tests/test_exit_arbiter_held_never_dispatched.py
  tests/test_residual_runner_repairs_2026_11_09.py tests/test_order_scaler.py
  --noconftest -q` (107 passed on 2026-11-10).
- Follow-up verification: `tests/test_exit_guard_2026_08_19.py`,
  `tests/test_exit_floor_and_parse_2026_10_20.py`,
  `tests/test_exit_attempt_terminal_mirror_2026_11_07.py`,
  `tests/test_exit_attempt_submitting_wedge_2026_10_19.py`,
  `tests/test_exit_lifecycle_integration_2026_10_08.py`,
  `tests/test_exit_intent_callback.py`, `tests/test_exit_policy_resolution.py`,
  `tests/exit_acceptance/accept_settlement_lifecycle.py`,
  `tests/test_exit_liveness_stress.py`, and
  `tests/test_entry_exit_invariant_2026_08_08.py` supplement the prior 483-test
  run; they do not establish an unqualified full-suite pass. Custom
  `tests/exit_acceptance/accept_exit_integration.py` invokes pytest at module
  import and must not be collected with pytest without a dedicated isolation fix.
- `scripts/check_kalshi_positions.py` requires its repository path, UTF-8 output,
  and explicit credential-file loading; inspect exchange positions and balance
  before restart and verify live preflight before claiming automatic trading
  readiness. `scripts/cleanup_port_8011.ps1` requires administrator privileges.

## 2026-11-13 Gate/lane restriction audit — counterfactual verdicts

Multi-week first-entry-per-(ticker,side) counterfactual over
`logs/rejected_candidates*.jsonl` (5.4M rows, 2026-10-25→11-13) joined to
`logs/settlement_outcomes.jsonl` and `data/decision_audit.db` snapshots.
Extractor/report scripts: `scripts/extract_first_entries.py`,
`scripts/counterfactual_multiday.py`, `scripts/validate_cells_fast.py`.

- `no_positive_executable_edge` (dominant veto, ~80% of rejections):
  14,133 first-entries settle at **-1.56c mean / -22,100c total** — the gate
  is economically correct. Do NOT relax the core executable-edge gate.
- Cheap-tail settle edge (10-24c YES cells +6..+14c settle P&L) is the
  already-documented **settle-only** cohort: `drift_lane.py` docstring and
  `MERID_CHEAP_NO_COUNTERFACTUAL_REPORT_2026-11-06.md` prove it is negative
  under every scalp/exit rule. The 2026-11-10 operator settlement-closeout
  policy makes it uncapturable — lifting the edge gate for it admits losers.
- `no_eligible_price_band`: YES aggregate +2.34c (n=258) is the same
  settle-only/marginal pocket; NO side -4.36c. Bands stay.
- `cost_basis_override_no` -16.44c, `EVIDENCE_HARD_BLOCK` -8.87c settle —
  evidence/cost gates are net savers. `tte_entry_cutoff` late entries lose
  at settlement (-5.35c). `MERID_ENTRY_MAX_REQUOTES_PER_KEY` and all daily
  caps are non-binding (0 exhaustions in 26k attempts; ~16 entries/day vs
  96-1440 caps).
- `cheap_no_settle` + `settlement_convergence` lanes are dead **by the
  2026-11-10 operator pre-settlement-liquidation policy**
  (`settlement_lane_incompatible_with_closeout` in order_router.py), not by
  stale config. cheap_no stays enabled as a zero-cost counterfactual probe
  (`submission_attempted=false`); it generates the settle-cohort telemetry
  without exchange traffic.
- `late_edge_probe` (10-69.99c bid, TTE 60-120s, EV>=+3c) is deployed and
  disjoint from pinned_fav's 94-98c domain — its PRICE_HI cap does NOT gate
  pinned_fav. Zero submissions as of 2026-11-13; verify telemetry after a
  few days before judging reachability.
- Actual flow since 2026-11-10: 42 entries / 43 exits, net ~-$6.49 —
  activity is opportunity-bound, not gate-bound. The path to more fills is
  new alpha (e.g. lead-lag shadow lane, `MERID_LEAD_LAG_SHADOW_LANE_DESIGN_2026-11-12.md`)
  or exit-capture improvement on admitted trades, not looser gates.

### 2026-11-13 `late_taker_ioc` lane (bounded taker rescue)

New production sub-lane in `drift_lane.py` + `trade_decision.py` +
`agent_grid_15m.py`, armed by `MERID_LATE_TAKER_LANE_ENABLED=1` in `.env`
(code default off).  Domain: ask-priced (taker) evaluations only,
ETH+NO by default, own-side ask 50-59.99c, TTE 120-240s, claimed net EV
>= +1c lane floor, 1-contract bounded sizing, per-ticker 1 / daily 24
durable caps (`data/drift_lane_state.json` lane record
`late_taker_ioc`), IOC taker cross allowed for probe-restricted
emissions (`MERID_LATE_TAKER_IOC_CROSS`, default on).  Evidence:
`logs/late_taker_shadow.jsonl` fee_inclusive_edge>0 cohort joined to
settlement — ETH NO 50-59c settled +4.57c mean (n~89, 60% win) with
+4.69c mean markout; all other asset/side cells settled negative, so
scope stays ETH+NO until equivalent evidence exists.  Verification:
`tests/test_late_taker_lane.py` (11 tests) +
`tests/test_evidence_lane_floor_probes.py`.
