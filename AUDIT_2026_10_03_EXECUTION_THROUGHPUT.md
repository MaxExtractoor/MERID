# MERID Execution Throughput Audit — 2026-10-03

Follow-up to `AUDIT_2026_10_02_SESSION.md`. Question: why does a live server
running ~24h produce only a handful of trades when the 15-minute loop offers
~96 entry windows/day across 5 assets?

## Measured funnel (last ~24h, cutoff 2026-10-02T20:00Z)

| Stage | Count | Source |
|---|---|---|
| Asset-cycle decision evals | ~15,079 | `decision_telemetry.jsonl*` scorecards |
| Decisions touching provisional lane | 10,074 | `current_build_provisional_lifecycle.jsonl` |
| Unique intents emitted | ~10 | same file |
| Exchange submissions | ~4 | fills ledger + lifecycle `pre_wire` stage |
| Fills | ~4 (all NO, all :maker) | fills ledger |

**Intent rate ≈ 0.4/hr. Admission rate ≈ 0.07% of evals.** The binding
constraints are not one kill-switch; they are layered, and two of them are
defects rather than policy.

### Terminal codes (per asset-cycle, last 24h)

| Code | Count | Share |
|---|---|---|
| NO_POSITIVE_EXECUTABLE_EDGE | 5,225 | 34.6% |
| NO_ELIGIBLE_PRICE_BAND | 4,586 | 30.4% |
| EDGE_BELOW_DYNAMIC_THRESHOLD | 3,815 | 25.3% |
| TTE_ENTRY_CUTOFF | 1,309 | 8.7% |
| EVIDENCE_HARD_BLOCK | 88 | 0.6% |
| BOOK_NOT_TRUSTED | 39 | 0.3% |
| SIDE_NOT_LIQUID / SPOT_NOT_TRUSTED | 16 | 0.1% |

Edge economics (first + third rows) kill **60%** of all evals. But median
shortfall when the edge gate fires is deep — BTC 3.7c, ETH 2.5c, SOL 3.6c,
XRP 4.3c, DOGE 4.7c — so most evals are unreachable; the harvestable band is
the p10–p25 near-miss slice (~0–2c below threshold).

Best-side distribution is nearly balanced (NO 4,861 / YES 4,278) — the
current all-NO fill ledger is not a model skew, it is the YES suspension.

---

## P0 — Defects (fix first; both suppress executions that policy already approved)

### P0-1. Provisional taker intents are stamped maker-only and die pre-wire

`agent_grid_15m.py` (~L8696) defaults `MERID_BOUNDED_TAKER_CROSS=1`: when a
bounded-lane candidate qualifies on **taker** economics, the intent is
correctly flipped to `post_only=False, TIF=ioc, execution_mode="taker"`.

`loop_15m.py` (~L10464-10476) then stamps **every**
`current_build_provisional` intent with
`ExecutionPolicy(required_post_only=True, required_liquidity_role="maker",
allow_taker_fallback=False)` unconditionally — ignoring the posture the
decision layer chose. `maker_taker_integration.py` (~L137-163) flags
`_execution_policy_violation`, and `order_router.py` (~L19529-19547) rejects
with `PRE_WIRE_POST_ONLY_UNAVAILABLE`.

Evidence: **21 `PRE_WIRE_POST_ONLY_UNAVAILABLE` reject events against only
~10 intents in 24h** (plus one live Kalshi 400 "post only cross"). The
taker-evaluated candidates are the *highest-edge* admits (they cleared the
threshold net of taker fee) — the system is systematically discarding its
best candidates while the weaker maker-evaluated ones get through.

Fix options (pick one):
- **(a) Honor the cross flag at stamping time (recommended).** In
  `loop_15m.py`, stamp `required_post_only=True` only when the candidate's
  resolved posture is maker (`post_only=True`). When the bounded-taker-cross
  produced an IOC intent, stamp a taker contract instead:
  `required_post_only=False, required_liquidity_role="taker",
  allow_taker_fallback=False, max_order_lifetime_s≈IOC`. Keeps the
  immutable-contract model — the contract just reflects what was admitted.
- (b) `MERID_BOUNDED_TAKER_CROSS=0` — one-line revert to unconditional
  maker for bounded lanes. Costs nothing structurally, but throws away the
  highest-edge candidates the lane was designed to catch.

Regression tests needed: provisional taker-evaluated candidate →
`post_only=False, tif=ioc`, no `PRE_WIRE_*` violation; provisional
maker-evaluated candidate still rejected if it arrives marketable;
`evidence_cell_escape` / `threshold_cell` behavior unchanged.

### P0-2. YES side is suspended indefinitely — half the trade surface is off

`directional_regime.py` persistent state
(`post_drawdown_2026-10-01`): `yes.suspended until=null` from
`catastrophic:cbp_sol_yes_30_40_t300_600:first_fill_markout_5s=-7.50c`.
One SOL provisional fill with a -7.5c five-second markout tripped
`record_side_catastrophe` and parked the entire YES side pending manual
review. Every YES-evaluated candidate that clears economics dies here;
~550/day fully-qualified best-side=YES evals are blocked (earlier session:
127 in a 5.5h window).

Options:
- Release YES via the operator release path (`release_side("yes")` /
  throttle-state patch), or
- Narrow the catastrophe scope: suspend the offending **cell** (or
  asset+side) rather than the whole side, and convert `until=null` into a
  bounded cool-down (e.g. 4h) with auto-review. A single -7.5c/5s markout
  on one 1-contract cell should not be a global kill — it is within the
  lane's own `PROVISIONAL_MIN_EV_FLOOR_C=-6` measurement envelope.

Keep: the per-cell catastrophe *detection*. Change: blast radius and TTL.

---

## P1 — Structural gates worth relaxing (ordered by headroom)

### P1-1. Disabled tails eat 30% of evals — no deep-ITM entry lane exists

Price bands: 1-9c and 91-99c are hard-disabled in `market_regime.py`; the
only deep-ITM admission is the settlement lane (`SETTLEMENT_LANE_MIN_TTE_S=30`,
`MIN_P=0.84`, `MIN_OBSERVED=10`, `MAX_PRICE=97c`). 4,586 evals/24h died in
the tails — markets that have already moved decisively, which mid-window is
most of them. The prior audit showed ≥76c trend-aligned entries are the
profitable cohort.

- Enable the existing `trend_yes_hi` lane (already built, flag off: p≥0.94,
  EV≥3c, TTE 120-300, breadth≥4) — low risk, bounded, validated design.
- Add the symmetric NO-side deep-ITM lane, or extend settlement-lane TTE
  from 30s → 60-90s with the same p/observed floor. The
  `late_window_shadow.jsonl` stream is already logging what-if evals at
  tte<180s — but it records market state only, not hypothetical EV; add EV
  fields before widening so the relaxation is evidence-based.

### P1-2. Edge threshold — targeted relief only

60% of evals die on edge, but median miss is 2.5-4.7c. Blanket relief would
mostly admit noise. The exploitable slice is the 0-2c near-miss band where
the prior counterfactual showed positive expectancy (0-1c below gate,
50-89c held price). `MERID_EDGE_MID_BAND_RELIEF_CENTS` (default 1.5c) is
already active for the formula path — **verify it applies inside cell
paths**: provisional/threshold cells replace the formula threshold with
`cell.min_net_ev`, so formula relief may not reach them. Options:

- Apply the same 1-1.5c relief inside cell resolution for the 50-89c price
  bands (cell `min_net_ev` - 1.0c, floor at provisional floor).
- Or lower per-cell `MIN_EV` env overrides by ~1c for NO-side cells in
  50-89c only (`MERID_PROVISIONAL_MIN_EV_C_*_NO`), leaving YES unchanged
  until the suspension question is resolved.
- Do NOT reopen <35c: counterfactual was negative there.

### P1-3. TTE floors (8.7%)

Band floors: balanced 120s, transition 180s, skewed 240s; settlement lane
covers <30s. The 30-120s pocket is dead. Shadow-log EV in `late_window_
shadow` first; then extend the balanced band floor 120→90s guarded by
settlement-distribution phase, or widen settlement lane TTE as in P1-1.

---

## P2 — Throughput ceilings (cap the daily max even if the funnel opens)

- **Strip concentration** (`directional_regime.strip_concentration_block`):
  1 same-side entry per 15-min strip across **all 5 assets** → hard ceiling
  ~4 entries/hr/side. With YES suspended, ~4/hr total is the theoretical
  max today; realized is ~0.2/hr so it rarely binds *yet* — but it will as
  soon as P0/P1 land. Raise to per-asset scope, or 2-per-strip with EV
  ranking.
- **Per-asset entry window** (`order_router._asset_entry_windows`): 1
  entry/asset/15-min window, in-memory. Reasonable churn control; keep
  unless fill quality supports re-entry.
- **Provisional daily caps**: fills total 6/day, per-asset 2, per-cell 1,
  submissions 20/day, open orders total 2 (`MERID_PROVISIONAL_*`). If the
  provisional lane is intended as the primary admission path (threshold
  source today: provisional 5,417 vs cell 953), the 6-fills/day cap is the
  binding constraint on daily trade count. Scale gradually (6→12,
  per-asset 2→4) once pre-wire deaths stop.
- **Fixed exposure** $0.90 / 1 contract — fine, leave.

Not binding now: evidence escape (2/24 used), book trust (46/24h), depth
(11), spot trust (5). Leave all.

---

## P3 — Root cause framing

The system has ~15 sequential veto layers, each individually defensible,
collectively admitting ~0.07% of evals. The single biggest *structural*
gap: when a 15m market has moved decisively (the normal mid-window state),
price lands in the disabled tails or fails the band→edge path, and the only
lane that can admit it (settlement) exists for ~30s/window. The funnel is
tightest exactly where the win rate is highest (deep ITM, late TTE), and
loosest where expectancy is thinnest (marginal edges early in window).
The P0 fixes + P1-1 (deep-ITM lane) attack that asymmetry directly.

## Ranked action list

| # | Change | Type | Expected intake | Risk |
|---|---|---|---|---|
| 1 | Stamp provisional policy per resolved posture (honor BOUNDED_TAKER_CROSS) | code | recovers >half of emitted intents (21 pre-wire kills/24h) | low — contract still immutable, just correct |
| 2 | Release YES suspension; scope catastrophes per-cell + TTL | state/code | ~doubles qualified-candidate pool | med — YES expectancy unvalidated; keep cell suspension |
| 3 | Enable `trend_yes_hi` (+ symmetric NO lane) | config | opens the 30% tail-reject pool where win rate is highest | med — strict thresholds already built in |
| 4 | Cell-level edge relief ~1c, 50-89c NO only | config | admits p10-p25 near-miss slice | low-med — adverse selection on maker fills |
| 5 | Shadow-EV in late_window_shadow, then TTE floor 120→90s balanced band | code+config | opens 30-120s pocket | med — use settlement distribution guard |
| 6 | Strip concentration → per-asset scope; provisional caps 6→12/day | config | raises ceiling ~5x | low once 1-2 land |
| 7 | Keep: band floors ≥180s on skewed, <35c tails closed, evidence gate, book/spot trust, 1c+ entry band on unvalidated cells | — | — | — |
