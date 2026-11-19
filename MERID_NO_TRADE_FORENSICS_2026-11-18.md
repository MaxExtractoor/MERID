# MERID No-Trade Forensics — 2026-11-18

**Trigger:** operator killed the production server ("not executing any trades").
**Verified scope:** last 3h of decision ledger + 2h of `logs/full.log`
(20:59→23:00 UTC, run `20261118201551_13256`), `live_runtime_state.json`,
`kalshi_fills.db`, `decision_audit_evidence_outcomes.db`, faulthandler dumps.

## Bottom line

The system was `LIVE_ENTRIES_ENABLED` (preflight passed, kill switch clear,
`allow_new_entries=True` every tick) and **still produced zero executions for
1141 consecutive ticks**. Nothing is hard-halted; the funnel starves at three
sequential choke points: **no gross edge found (~76% of all rejections) →
evidence-cell vetoes (~28% of evaluated sides) → entry-trap guard kills the
survivors**. A fourth, operational problem — event-loop/IO contention — makes
all three worse by degrading quote freshness.

## The funnel (measured, not inferred)

| Stage | Evidence | Verdict |
|---|---|---|
| Loop gate stack | `allow_new_entries=True` on all 1141 logged ticks; only 1 `ENTRY_BLOCKED` (transient `canonical portfolio unavailable` at restart) | ✅ Open |
| Decision selection | 22 `ENTER` vs 27,706 `NO_TRADE` in last 3h; **100%** of top-level vetoes `NO_EDGE` | Model selects almost nothing |
| EV gates | `no_positive_executable_edge` **4,326** rejections (~76% of the day's rejections); `edge_below_threshold` 342 | Dominant blocker |
| Evidence layer | `MATCHING_TOXIC_CELL` 924, `CHALLENGE_INSUFFICIENT` 777, `SOFT_PENALTY_INSUFFICIENT` 599, `CELL_EVIDENCE_INSUFFICIENT` 231 (of 4k side_ev rows) | ~30% of evals evidence-blocked; `CELL_EVIDENCE_PASS` 1396 shows the incremental store IS feeding cells |
| Post-selection guard | 6/6 recent ENTERs killed by `entry_trap_veto` (`own_side_ask_falling` 4-20c, `stale_model_divergence` dp≈0.01); 1 by `ALLOCATION_REJECTED/EXPECTED_VALUE_BELOW_MINIMUM` | Zero admitted candidates survive |
| Submission/fill | Last fill 13:28 UTC (~10h dry); fills ledger intact (no dup fill_ids; 2171-vs-27 divergence = venue `/fills` window + legacy `fill_source=''` rows) | No orders reaching venue |

## Flaws found, ranked by contribution

### F1 — Structural: model finds no edge; reserves correctly keep it out (dominant)

`strategy_decision_side_ev` percentiles over last 30min of NO_TRADEs:

- `gross_edge_cents`: p50 **−1.64c**, p75 +0.07c, p90 +1.57c
- `expected_net_ev_cents`: p50 **−6.83c**
- Reserve stack p50: model-uncertainty 2.3c + giveback 1.46c +
  impl-shortfall 1.0c + adverse-selection 0-1.5c + entry fee 0.42c ≈ **~5.5c**
- `effective_required_c`: p50 2.0c
- `calibrated_probability` p50 0.50 vs `executable_entry_price` p50 50c —
  the model is priced at parity with the market almost always.

Interpretation: the calibrated model's disagreement with executable prices is
smaller than the ~3c spread + ~5.5c reserve stack on nearly every evaluation.
The gate is doing its job — but it means the formula path can essentially
never fire in the current regime. Worth a dedicated calibration audit: if the
empirical-price-calibration overlay is regressing p toward the book, the
model has no opinion left to trade on. This is a **strategy/alpha finding,
not a gate bug**.

### F2 — Event-loop / IO contention (operational, amplifies everything)

- `drain_lag_ms=18000` observed on a log record; `GRID-CYCLE-TIMEOUT`
  fired (75s bound exceeded, cycle cancelled fail-closed).
- `faulthandler_dump.log` is **351MB**; top blocked frames:
  `unified_spot_service.fetch_sync` (2,619) → `requests`/`urllib3`
  `connect`/`ssl_wrap` (~2.4k) — synchronous Coinbase HTTP fetches still
  occupying executor threads in TCP+TLS handshakes despite the Nov-01
  shared-session fix.
- `full.log` wrote **88MB in 2h**; `audit_write_wait_ms` p95 was already
  measured at 9.7–13.8s (HDD spindle + 8.5GB audit DB).
- Consequences: stale quotes at decision time (163
  `market_open: stale/missing/illiquid` rejects today), spurious
  entry-trap vetoes (a stalled book looks like a repricing book), grid
  timeouts, and the evidence-refresh 308s query timeouts fixed earlier.

**Highest-leverage operational fix available**: move the audit DB + logs
off the spindle / cut log volume / make spot fetch truly async or pooled —
all three feed the same contention.

### F3 — Self-sealing evidence layer (partially remediated, still blocking)

`MATCHING_TOXIC_CELL` + `CHALLENGE_INSUFFICIENT` + `SOFT_PENALTY_INSUFFICIENT`
≈ 2,300 of 4,000 evaluated sides. These cells were built by the losing
probe-cohort admits of the previous config. The config-scoped measured-loss
fix (fdd2a448) scoped the veto for `pinned_fav`/`drift_fav`/`cheap_no_settle`,
but `evidence_transfer_margin`/`challenge_insufficient` still gate the rest —
the same self-sealing pattern AGENTS.md documented: cells built by a config
that no longer exists refute admissions the new config could make. The
evidence-outcome store is healthy and feeding cells; the cells themselves
are the poisoned cohort.

### F4 — Entry-trap guard effectively = "any ≥3c own-side ask drop in 45s vetoes"

`stale_model_divergence` requires `|Δp| ≤ 0.02` over the lookback. The model's
calibrated p moves ~0.01 per 45s in practice — the condition is nearly
always true, so the veto reduces to a book-drop check at the 3c threshold
(2c tighter than the nominal 5c `MERID_ENTRY_TRAP_DROP_C`). During falling
tape this vetoes **every** candidate for ~45s after each repricing leg.
The guard's dip-chase protection is measured (+correct), but the sticky-p
half of the check is not discriminating — it cannot distinguish staleness
from a genuinely slow model. Options: raise `MERID_ENTRY_TRAP_STICKY_P_MAX_DP`
exempts nothing today; consider exempting the maker route (resting bids
earn the validated fill edge even on gentle repricings) or keying the veto
to adverse-selection markouts rather than raw drop.

### F5 — Secondary gates (each <5%, listed for completeness)

- `price_band_both_sides_disabled` 266 — both regime price bands disabled
  (observed TTE 30–60s); near-expiry band behavior.
- `min_tte_entry_disabled` 183 + `market_open TTE<min` 105 + `too_early` —
  boundary gates; normal.
- `market_discovered: no contract in entry window` 145 +
  `market_open stale/missing/illiquid` 163 — data availability; partially
  inflated by F2 contention.
- `cost_basis_override_no` 90 — model selects NO at below-floor p; blocked
  per the anti-directional contract. Working as designed.
- `pinned_fav_maker_only` 9, `settlement_lane_price_cap` 2, misc <10.

### F6 — Capital/risk constraints (not blocking, but tight)

- Bankroll **$7.38** vs `MERID_FIXED_EXPOSURE_CAP_USD=11.00` —
  everything clamps to ~1–6 contracts.
- `uncertain_submission_recovery`: **205 quarantined order attempts +
  25 exit-quarantined** — historical submission-uncertainty debt; not
  blocking, but worth an explicit sweep decision.
- `drift_lane_state.json` still records `cheap_no_settle` emissions today
  (5, DOGE/ETH tickers) despite `MERID_CHEAP_NO_LANE_ENABLED=0` — verify
  these are shadow/telemetry records and not real order intents.

## What is NOT a flaw (verified working as designed)

- Live-state machine: `LIVE_ENTRIES_ENABLED`, auto-enable after preflight.
- Loop entry gate stack: green throughout the window.
- Loss-stop suppression: triple-choke consistent (env/code/events).
- Anti-directional guard, cost-basis floors, TTE floors: firing per contract.
- Fills ledger integrity: no duplicate fill_ids; settlement pseudo-fills excluded.
- Evidence-outcome store: watermark extraction progressing (~99k rows),
  artifact refreshing (last success 331s, rows=69,150).

## Recommended next actions (priority order)

1. **F2 operational**: move `decision_audit.db`/logs to faster media or
   reduce write volume; confirm `unified_spot_service` uses the shared
   session everywhere (some call sites may still build ad-hoc requests).
   This is the only fix that improves every downstream gate at once.
2. **F3 evidence**: decide per-cell whether toxic/challenge cells built
   by the retired probe configs should reset (evidence epoch bump or
   scoped release) — same pattern as the `pinned_fav` measured-loss fix.
3. **F4 entry-trap**: reconsider `stale_model_divergence` for maker routes
   — resting bids don't suffer dip-chase the way taker crosses do.
4. **F1 strategy**: calibration audit — is the model genuinely at parity
   or is the EPC overlay anchoring p to the book? (Separates "no edge in
   this market" from "the model lost its opinion".)
5. **F6 hygiene**: sweep the 205+25 quarantined attempts; confirm
   cheap_no state records are telemetry only.

## Fixes applied this session

**Evidence backfill isolation** (`merid/execution/decision_audit_ledger.py`,
earlier today): live-trickle extraction commits before the 1h backfill
chunk; a chunk timeout now defers instead of failing the whole refresh, and
the cursor only advances on success. The refresh-sidecar showed this exact
failure (`query: interrupted` at ~308s) before the fix, and a successful
69k-row refresh after.

**Heartbeat-log throttling** — ~75% of the measured log volume on the same
spindle as the 19GB audit DB:

- `data/unified_spot_service.py`: added `_hb_log` — the 1s-refresh
  heartbeat (`Refreshing all assets`, `Refresh complete`, `Fetched
  {asset}`, `Returning spot price`) now emits at most once per key per
  `MERID_SPOT_LOG_THROTTLE_S` (default 60s). Failure logs untouched;
  degraded/stale `DataState` transitions emit at INFO every interval keyed
  by state so a state change is always logged once.
- `merid/event_venues/kalshi/market_catalog.py`: `CLOSE-TIME-PARSE`
  success demoted to DEBUG (warning path kept); `SNAPSHOT-CREATE` and
  `CATALOG-SNAPSHOT … Returning` heartbeat logs throttled to
  `MERID_CATALOG_LOG_THROTTLE_S` (default 60s) via module-level
  `_SNAP_LOG_STATE` on wall clock (not replay time — ops concern).

Both files `py_compile` clean. Impact: the ~9 lines/s spot heartbeat and
per-tick catalog chatter drop to ~1 line/min each — the remaining log
volume is per-tick grid/diagnostic lines (agent_grid_15m, ~82k/2h), which
carry the funnel evidence this audit relied on and are next in line only
if contention persists. **Effective on next restart** — the running
process keeps old behavior; there is no runtime reload of log sites.

**Not changed (policy, not defect):** entry-economics thresholds, evidence
cell state, entry-trap guard parameters, lane caps. The measured verdict
stands — the dominant blocker is genuinely-thin gross edge vs the ~5.5c
reserve stack, not a malfunctioning gate.

## F1 resolved — what kills the edge (measured, restart session)

Setup: `strategy_decision_side_ev.raw_probability` is the **pre-anchor**
Bachelier output; `calibrated_probability` is the final p after
market-anchor shrink + walkforward + evidence caps. Joined 1,480 recent
evals + 7,348 settled evals against `strategy_decision_outcomes`.

**Finding 1 — EPC is not the anchor.** `MERID_EMPIRICAL_CAL_MODE=shadow`
and `MERID_EMPIRICAL_CAL_PATH=data/epc_wide_fit.json`: telemetry only,
never touches a live probability. The parity is produced elsewhere.

**Finding 2 — the market-anchor shrink IS the parity machine.**
`MERID_MARKET_ANCHOR_MIN_W=0.25→MAX_W=0.85` ramps over the *whole* 900s
window (`trade_decision.py:4385-4428`), shrinking `p_model` toward market
mid in **logit space**. At typical entry TTE≈300s, w≈0.61 — ~60% of every
quoted probability is the book itself. Measured compression on 1,480
evals: raw deviation p90 = ±5.7c (tail to +12.7c) collapses to calibrated
gross edge p90 = +1.57c (max +5.4c). After the ~5.5c reserve stack, almost
nothing clears.

**Finding 3 — is the anchor destroying real signal? Mostly no — except
the tails.** Realized-vs-forecast on 7,348 settled evals, bucketed by raw
model deviation (raw_p − exec_price):

```
bucket      n    realized_wr  mkt_px   cal_p   vs_mkt   vs_cal
<-5c      582     51.9%      49.6c    46.1%   +2.3     +5.8
-5..-1   2186     55.5%      55.3c    52.0%   +0.2     +3.5
-1..+1   1881     49.7%      50.0c    46.6%   -0.3     +3.1
+1..+5   2099     43.9%      44.5c    41.0%   -0.5     +2.9
>+5c      600     50.3%      46.5c    49.5%   +3.8     +0.9
```

- Mid-band: market ≈ realized within ±0.5% — the anchor premise ("book is
  near-calibrated") **holds**, and the raw model's mid-band deviations
  are noise. Shrinking there is protective.
- Tail (`>+5c` raw deviation): realized beat the market by **+3.8%**
  (n=600, borderline-significant ~±4% stderr) while cal_p sat 0.9% low —
  the raw model caught real underpricing, the anchor pulled a right
  answer back toward a wrong market. Convergent with the EPC artifact's
  independent +6.8..9.4c out-of-sample measurement — same FLB pocket.
- cal_p is **systematically 1-6% low in every bucket** — the full chain
  (anchor + walkforward + evidence caps + edge-bias corrections) shaves
  real edge off every eval, compounding the reserve-stack squeeze.

**Verdict:** not "the model has no opinion" — the pipeline *designs away*
most of it and is correct to do so mid-band, but throws away the tail
signal that is this system's only measured positive-edge cohort.

**Operator options (documented, NOT applied):**
(a) deviation-adaptive anchor weight — keep strong shrink when raw agrees
    with market, release when |raw−market| is large (the tail is exactly
    where the anchor hurts);
(b) EPC `shadow→live` inside its validated cells only;
(c) trim `MAX_W` — crudest, loses mid-band protection.
Before acting: re-run this bucket split per asset × side × TTE bucket —
the +3.8% tail effect could be regime/subset-driven.
