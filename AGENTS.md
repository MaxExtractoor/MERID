

```yaml
---
auto_execution_mode: 1   # legend: 1 = run the startup state machine automatically and execute the next eligible decision after preflight; 0/absent = fail-closed, no auto-enable. Env MERID_AUTO_EXECUTION_MODE overrides (1/true/yes on, 0/false/no off).
contract_version: 1.0.0
last_reviewed: 2026-11-21
description: MERID/Kalshi 15m automatic live-trading startup and execution contract
live_startup_policy: auto_enable_after_preflight
live_entry_authorization: durable_operator_config
live_authorization_artifact: this file's front matter + resolved .env — both agent-writable; arming is NOT persisted, it is re-earned every process boot by the full preflight (runtime state defaults LIVE_ENTRIES_HALTED; a new process_id forces re-preflight)
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

### Data-plane isolation + ledger summary cache (2026-11-21, py-spy driven)

- **REST orderbook polling moved off the WS I/O loop** (`e6805c54`):
  `_rest_polling_loop` now runs on a dedicated daemon thread
  (`kalshi-rest-poll`, own asyncio loop + per-loop httpx client via the
  client's existing `_clients_by_loop` binding).  Previously its 2s
  full-book applies + transition evals shared the `kalshi-ws-io` loop
  with `orderbook_delta` processing.  `is_running()` counts the thread.
- **`fills_ledger.summary()` TTL cache**: `MERID_LEDGER_SUMMARY_CACHE_S`
  (default 2.0, 0 disables).  The full fills scan (per-market
  `parse_expiry_from_ticker` strptime) was ~20s/90s of MainThread time
  under dashboard polling; cache + `asyncio.to_thread` in
  `get_pnl`/`get_risk` removed it.  All `summary()` callers share the
  cache — risk-path readers see ≤TTL staleness (fills arrive
  poller-latency anyway).
- **Book-state flap persists by design**: `HEALTHY↔DEGRADED_REST_ONLY`
  transitions (~60/min) are the owner-latch hysteresis working —
  promotions need `_WS_PROMOTE_STREAK`+parity time, demotions are
  instant on divergence (>3¢) or unverified flags.  Degraded books
  remain `executable` and submittable; the flap is telemetry noise,
  not an entry blocker.  Do NOT relax `MERID_WS_ENTRY_MAX_AGE_MS` or
  `MERID_REST_BBO_MIN_DIV_CENTS` without cohort evidence.

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
MERID_PINNED_FAV_PRICE_LO=94   PRICE_HI=96   # HI narrowed 98->96 on 2026-11-20 (see below)
MERID_PINNED_FAV_MAKER_LO=94   MAKER_HI=96   # same
MERID_PINNED_FAV_MAX_CONTRACTS=6
MERID_PINNED_FAV_MIN_EV_CENTS=-3.0    MAKER_MIN_EV_CENTS=-3.0
MERID_PINNED_FAV_LATE_TTE_S=150       MID_MIN_EV_CENTS=0.0
MERID_PINNED_FAV_MIN_TTE_S=45         MAKER_MIN_TTE_S=45
MERID_PINNED_FAV_DAILY_MAX=480   MAKER_MIN_P=0.90
```

**TTE-conditioned EV floor (2026-11-18, external-tape epoch).** The flat
`-3` probe floor is now `max(base, mid)` conditioned on TTE via
`_pinned_fav_min_ev_cents_at_tte()`: inside `LATE_TTE_S=150` the bounded
`-3` probe floor binds; past it `MID_MIN_EV_CENTS=0.0` requires
non-negative model net edge.  External live-money evidence on this exact
product (KXBTC15M favorites): PMP tape study — 1,258 windows, TTE>150s
netted −0.76¢/contract after fees while the final 60s netted +2.67¢ (the
60-print settlement average collapses uncertainty faster than the book
prices it); moltbook live bot — 993 trades, 90–93¢ favorites at 4–8min
ran 91.7% win vs ~92–93% breakeven = −2% net.  Internal replay is
consistent: the 300–840s cohort is ~breakeven incl. tail (maker fills
earn ~1¢ better than the taker tape), and both in-band pin-breaks
(DOGE@87¢ edge −5.6¢, DOGE NO@95¢ edge −5.0¢, TTE ~330s) were
parity-priced mid-window entries — the exact measured-losing cohort.
Rollback: `MERID_PINNED_FAV_LATE_TTE_S=840` disables the split.
`MIN_TTE_S=45` opens the verified +EV window to entries (maker floor 45s
= the pf resting-cancel floor; sub-45s is owned by the settlement lane).

Companion code hardening (same replay): the measured-evidence
`pinned_fav_maker_low_p` bypass in `compute_trade_decision` now enforces a
hard reachability floor (`MERID_PINNED_FAV_EVIDENCE_BYPASS_MIN_P`, default
0.80) — cell evidence substitutes for the *pin*, never for reachability —
and re-asserts the lane daily cap the block returns before checking.
Regression coverage: `tests/test_pinned_fav_lane.py` low-p/bypass block.
Note: `.env` is loaded into `os.environ` at process start, so the running
process keeps the old 85–99/11 values until the next production restart —
the restored band binds on restart, not live.

### Claim-tail T0 amendments (2026-11-20/21, post split-audit)

Decision-spine split audit (`scripts/audit_claim_tail_splits.py` →
`reports/claim_tail_splits.json`; plan `reports/T0_DIFF_PLAN_2026-11-20.md`)
on the claim≥+2¢ cohort (n=3,061 evals / 232 mkts / ~4.7d):

- **pf band narrowed 94–98c → 94–96c** (`PRICE_HI`/`MAKER_HI`=96).
  FLB decomposition: eval-edge +4.4¢@90–93, **+1.4¢@94–96, −0.2¢@97–98**;
  pf claim≥+2¢ evals realized **−2.05¢ CI[−2.64,−1.26]** — the only
  CI-clean negative in the split set.  pf is ~1.4% of the cohort:
  small-bore change, must not absorb attention from the emission bug.
  **P1 (n-floor: do not score failed on n<25/bucket):** pf realized-
  by-bucket at 94–96 goes non-negative post-cap; if not → pin-break
  adverse selection, needs pin-distance work not basis change.
  96–98c exits band ownership → generic gate stack (not dark).
  Rollback: both HI back to 98.
- **Financial brakes ARMED:** `MERID_KS_TRAILING_EQUITY_HALT_PCT=0.40`
  (amended from proposed 0.25 after equity check — live equity FRESH
  $27.86 @ 2026-11-21T04:23Z; 25% band = $6.97 < one ~$11 max loss
  ≈39–41% dd would trip on first loser; 0.40 tolerates one max-size
  loss, halts on sustained bleed) + `MERID_KS_CONSECUTIVE_LOSS_HALT=12`.
  Peak initializes at first-seen equity (no persisted peak on disk);
  auto-resets on recovery; exits unaffected.
- **`cheap_tail_canary` de-registered** from `_minority_hold_lanes()`
  default — two-key semantics like `cheap_no_settle` (flag + registry).
- **Escape cap HELD at 480** (amended — was proposed 480→96): the
  claim≥+2¢ cohort shows **zero actual fills in 4.7d**; 81% of it is
  `admission_owner=evidence_escape` with `decision_lane` mostly NaN.
  Tightening the cap now would stack a second suppressor on an
  undiagnosed first one.  Set the cap only after emission rate and
  post-fix fill rate are known.
- **Canary/EPC deletion DEFERRED** until after the emission diagnosis —
  `trade_decision.py` is the suspect file; don't widen bisect surface
  mid-investigation.
- **Pre-registered measurement endpoint** (anti-retrofit): primary =
  **taker × FULLY_EXECUTABLE, pooled across lanes**; read at
  **n≥10,000 cohort evals or 3 weeks**, whichever first (4.7d/n=3,061
  is underpowered — CI ±7¢ at this n).  Decision rule: CI still
  straddling 0 at n=10,000 ⇒ kill the thesis.  No BH-FDR surface on
  tiny cells.
- **Emission die-off RESOLVED 2026-11-21 (spine + audit DB, no router
  involvement):** the claim≥+2¢ escape cohort never reaches the
  router — it dies inside `compute_trade_decision`.  Of 2,505
  `admission_owner=evidence_escape` claim≥+2¢ side-evals: **94%
  (2,363) fail the side edge gate** (`passed_edge_gate=0`;
  `exclusion_reason=*_edge_below_threshold`; median `required_edge`
  ≈7.5¢ vs claims of +2–6¢).  The remaining **142 pass the side gate**
  and still produce `decision=NO_TRADE / primary_reason_code=NO_EDGE`
  on every one — diverse decision-level vetoes
  (`countertrend_yes_selloff_regime` 17, `cost_basis_override_*` 24,
  `calibration_evidence_*` 16, `insufficient_depth_*` 10,
  `moneyness_coin_flip` 5, `bookflow_no_pressure` 5, …).  Selection
  rates by owner: escape 0/2,505, pooled_transfer 0/263,
  threshold_cell 0/37, provisional 3/216, settlement_convergence
  8/54, cheap_no 21/24 (disabled), pf 5/7.  **The router/provenance/
  post-only hypothesis is falsified** — zero candidates are emitted,
  so no router events exist to reject.  Implication: side_ev
  `expected_net_ev_cents` is a pre-decision-comparison claim; the
  measured "+3.85¢ realized" cohort is largely evals the engine's own
  economics already refuses.  The harvest question is now "does the
  decision-level NO_EDGE math agree with the eval-price counterfactual"
  — answerable by joining `reason_codes`/`gate_ev_cents` on the 142
  passers, not by router instrumentation.

### Order-path latency repair (2026-11-21, post audit_writer fix)

With entries unblocked, orders reached the wire but died to staleness:
`EXECUTION-STAGE-LATENCY` showed `intent_to_canonical≈4000ms` and
`construct_to_send≈1531ms` on every attempt (eval→wire ~7s; post-only
prices crossed before submission).  Root causes measured on the
production host (WD Blue 7200rpm HDD + i7-3770/8 threads, disk shared
with the 11GB audit store):

- **Per-commit fsync**: WAL+FULL `PRAGMA synchronous` commits measured
  p50=75ms / p95=303ms; each order pays ~5 serialized commits across
  identity/lifecycle.  `MERID_ORDER_ATTEMPT_SYNCHRONOUS=NORMAL` now
  applies per-connection in `OrderAttemptStore._get_conn` — WAL+NORMAL
  keeps full durability across process/app crashes (WAL replays on
  open); the only exposure is the un-checkpointed WAL tail on OS
  crash/power loss, which unmatched-order reconciliation already fails
  closed on.  `=FULL` restores per-commit fsync.
- **Executor starvation**: `finalize_order_identity` ran via
  `asyncio.to_thread` on the shared default pool
  (`min(32,cpu+4)=12` threads) and queued behind unrelated REST/poller
  work.  It now runs on a dedicated 2-thread
  `_ORDER_IDENTITY_EXECUTOR` bulkhead, and lifespan resizes the default
  executor to `MERID_ASYNCIO_DEFAULT_EXECUTOR_WORKERS` (default 24).
- **Duplicate REST book fetch**: `_ws_rest_divergence_guard` always
  pulls `port.get_orderbook`, then the pre-submit passivity check could
  pull it AGAIN when the WS book was stale.  The guard's fresh REST
  book is now stashed on the intent and reused by passivity while inside
  `MERID_PRE_SUBMIT_BOOK_FRESH_MS` (1500ms) — same freshness contract,
  one fewer RTT.
- **Decomposition stamps**: `route_entry_ms`,
  `route_entry_to_finalize_ms`, `identity_finalize_ms`,
  `post_identity_to_canonical_ms` added to EXECUTION-STAGE-LATENCY so
  the next stall localizes without another instrumentation round.

### Sure-bet tail execution + settlement-floor units repair (2026-11-22)

Operator directive: execute the tail-end "sure bets" (15m windows resolve
to a clear winner; buy the favored side late).  Rather than force trades,
the settled-eval record was used as the arbiter
(`decision_audit_evidence_outcomes.evidence_outcome_rows`, src=veto/fill,
`settled_yes` joined, `cf_status=FULLY_EXECUTABLE`, TTE 10–150s,
`calibrated_probability>=0.90`, held-side price>=85c, deduped to the
last look per ticker-side):

- **px>=98c band: +1.0–1.14c/contract realized, ~99.6% wins (n≈231 over
  ~3.5d).**  px 99c sub-band went 115W/0L; px 98–99c 115W/1L.
- **px 94–97c bands were NEGATIVE** (84.8–95.7% win vs ~95–98c
  breakeven): 94–96c −14.5c avg, 96–98c −0.9 to −2.2c, 97–98c −1.26c.
  The "sure bet" edge exists only where the banked settlement samples
  make the outcome near-mechanical AND the price still leaves >=~1c.
- Conclusion: a blanket late-favorite override would have lost money;
  the profitable slice is narrow (px>=98c).  Implemented as a
  **price-conditioned settlement-lane floor**, not a quota.

**Units regression found and fixed:** `d3c82004` treated
`MERID_SETTLEMENT_LANE_MIN_NET_EDGE` as cent-denominated, but the
constant has been edge-fraction since `fe5d612a`
(`env_CENTS/100` at module load → 0.0075 = 0.75c).  The "fix"
double-converted at all three consumers — LCB `required_cents`,
favored-side `min_edge`, and `selected_threshold` — leaving the
decision-path floor at ~0.0075c while the allocator still bound the
env 0.75c.  All sites now use `settlement_lane_min_edge(price_cents)`
(edge-fraction units, correct conversion per consumer) and the
allocator binds the same conditioned value — decision, intent
(`min_required_edge`), LCB gate, and allocator EDGE stage agree.

**New env (resolved .env):**
`MERID_SETTLEMENT_LANE_DEEP_MIN_PRICE_CENTS=98` and
`MERID_SETTLEMENT_LANE_DEEP_MIN_NET_EDGE_CENTS=0.30`.  At held-side
price >=98c the lane floor drops 0.75c→0.30c (still requires positive
net edge after fee+reserves, p-side gates, book trust, depth, sizing,
idempotency unchanged).  Below 98c the 0.75c base floor is restored
(the d3c82004 regression is reverted — effective behavior there is
unchanged because the allocator already enforced 0.75c).

Rollback: `MERID_SETTLEMENT_LANE_DEEP_MIN_PRICE_CENTS=101` disables
the deep band (no price reaches it); `MERID_SETTLEMENT_LANE_DEEP_MIN_NET_EDGE_CENTS=0.75`
matches base.  Watch: settlement-lane fills at >=98c vs the
counterfactual's +1.0–1.14c/contract; a realized pin-break cluster
(>=2 losses in the first ~20 fills) reverts the deep floor.

**Hold-to-settlement enforcement (2026-11-22, post BTC NO loss):** a
`settlement_convergence` fill was force-sold at 87c with ~115s to expiry by
the generic pre-settlement closeout / settlement-guard path even though the
held side later settled YES.  Lane provenance is now authoritative
end-to-end: `position_cache` stamps `decision_lane` on fill and REST
reconstruction, and `_position_decision_lane` falls back through
`entry_admission_lane` to the durable `order_attempts.payload_json.order.decision_lane`
(the store getter is `OrderAttemptStore()`, not a `get_order_attempt_store`
helper).  For `decision_lane=settlement_convergence` the monitor skips
mandatory closeout, settlement-guard candidates, the <=60s emergency
flatten, hard-profit-lock, and `AUTO_EXIT_99C`; `_emit_exit_intent` no longer
reclassifies its exits as `SETTLEMENT_GUARD`; and
`loop_15m._run_exit_price_guard` marks `mandatory_closeout`, `is_forced`,
and `is_emergency` false so the settlement EV gate / hold veto decide.
Ordinary lanes keep the T-120s mandatory closeout.  Regression coverage:
`tests/test_pre_settlement_closeout.py`.

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

### Fourth replay — measured-loss veto was self-sealing (2026-11-18)

Post-`fdd2a448` flat-scan audit: 536 in-band YES candidates (NO complement
2–8c, YES 92–98c) were all evaluated by `admission_owner: pinned_fav`,
but **zero** `pinned_fav_low_ev`/`pinned_fav_tte` vetoes appeared — every
one died at `pinned_fav_measured_loss` (43), `evidence_transfer_margin`
(257), or `challenge_insufficient` (99/75).  The measured-loss veto
compared the cell's weighted win rate to entry-price breakeven and fired
**unconditionally**, including for candidates carrying non-negative model
net edge.  That is self-sealing: the cell's loss record was built by the
negative-edge probe admits the tightened floor can no longer make, so
every future admit — including the edge≥0 cohort the new mid-window floor
now permits — was vetoed by losses of a config that no longer exists.
The lane could never re-measure; trade count stayed zero by construction.

**Fix (`trade_decision.py`):** `_pf_measured_loss` now also requires
`float(_ne_c) < 0.0` — the veto binds only the negative-edge probe tier
whose admits produced the record.  A non-negative-edge candidate is a
different claim (model sees genuine underpricing) that the cell's loss
history does not refute, so it proceeds to the normal evidence gates.
Negative-edge probe admits in toxic cells still veto exactly as before.
Applies uniformly to every lane flowing through the shared measured-loss
block (pinned_fav, drift_fav, cheap_no_settle) — for the −2c-floor lanes
nothing changes because their admits are negative-edge by construction.

**Regression coverage:** `tests/test_evidence_lane_floor_probes.py::
test_measured_loss_veto_is_config_scoped` asserts the veto expression
gates on the side's net-edge sign while keeping the weighted
win-rate-vs-breakeven test.  The existing toxic-cell pf test (dense
measured loser at the candidate's own bucket, negative-edge admit)
still vetoes — the tier split preserves it.

**Eval-latency finding (no code change):** the ~5s flat-scan spikes the
operator observed are audit-writer contention, not decision compute.
Per-eval `compute_trade_decision` is p50≈33ms/p99≈144ms (17k samples);
the audit heartbeat's `latency_ms` is the *sum* of synchronous
`record_trade_decision` row-build calls (~60/cycle), and
`audit_write_wait_ms` p95 ≈ 9.7–13.8s shows the HDD-bound writer thread
backlogged.  Enqueue is already `put_nowait` on an unbounded queue with
shed tiers (`high` never shed, `normal` shed past depth 120, emergency
tier past 350) and `MERID_AUDIT_WRITER_BATCH=128` — the pipeline is
correctly degraded, not blocked.  Watch: if `quote_age_at_decision_ms`
p95 stays >500ms or entries halt on `audit_writer_unhealthy`, the next
lever is writer throughput (SSD move / batch tuning), not gate
relaxation — readiness is earned by draining.

### Evidence layer — incremental outcome store (2026-11-18)

Post-restart audit found the evidence layer was the next self-sealing
layer: `live_entry_evidence.refresh.json` showed refresh **failing**
(`query: interrupted`, ~240s vs the 90s deadline, fail_streak=2, artifact
~5h old approaching the 8h `MERID_EVIDENCE_STALE_S` cliff).  The 4h
`MERID_LIVE_EVIDENCE_WINDOW_HOURS` was itself an Oct-17 disk-crisis
workaround; inside it, cells got n_eff 0.1–4 → `CELL_EVIDENCE_INSUFFICIENT`
dominated, and `recent_days` clamped to ~1h starved the challenge
mechanism.  Cap-shadow analysis confirmed evidence-insufficient was a
co-failure label, not the sole blocker (economics/reserves bind first) —
but once the artifact stales, evidence becomes the blocker for the
formula path.

**Research basis:** recency-weighted sufficient statistics are the
correct model for regime-tracking evidence (exponential halflife ≡ EWMA
of cell stats; QuantMemo/wraquant literature); the failure was
computational, not statistical — periodic full-window rescans of a 19GB
append-only outcomes table.  The canonical fix is incremental consumption
with a watermark (Doris table-streams, Redshift incremental statistics):
extract each settlement's evidence rows ONCE.

**Fix — `merid/execution/evidence_outcome_store.py` + ledger wiring:**
`_refresh_live_entry_evidence` no longer runs the three whole-window
scans.  It extracts settlement evidence rows into a small companion
store (`<audit>_evidence_outcomes.db`, derived from `db_path`,
`MERID_EVIDENCE_OUTCOME_STORE` override) via `extract_range`, which runs
the same three queries bounded to `[lo, hi]` (inclusive — frozen-clock
tests settle exactly at `now`).  Two cursors persist in the store:
`live_ts` (trickle, 5s overlap, idempotent via `row_key` dedup) and
`backfill_hi` (one `MERID_EVIDENCE_EXTRACT_CHUNK_S`=3600s chunk per
refresh, **newest-first** so the freshest 15m-market evidence lands on
the first refresh while older chunks accumulate; restarts resume
mid-backfill).  The live cursor commits before backfill so a chunk
timeout can't force the expensive seed to re-scan.  The artifact is then
rebuilt by `read_since(window)` on the small store — any window size is
now a cheap indexed read.

**`.env`:** `WINDOW_HOURS` 4→24 (6× evidence density; 48h is the target
once aggregation GIL cost is measured — the Python rollup over ~85k
rows/24h is the remaining cost, watch `latency_ms`), `QUERY_TIMEOUT_S`
90→180 (now bounds one chunk, not a window scan), `EXTRACT_SEED_S=7200`,
`EXTRACT_CHUNK_S=3600`, `STORE_RETENTION_DAYS=14`.

**Eval-spike update (measured 19:17 UTC):** `latency_ms` p50 ≈ 4–5s/cycle
with `audit_write_wait_ms` p95 ≈ 12s and `audit_write_exec_ms` p95 ≈
0.9–1.0s — the HDD-bound writer thread is saturated (45 rows/cycle vs
~1 row/s effective throughput; shed tiers hold queue ~30).  The writer's
constant GIL-held SQLite work is what starves the eval loop; per-eval
decision compute remains p50≈33ms.  Next levers if spikes persist:
writer batch/transaction tuning, `side_ev` shed-tier review, or moving
`decision_audit.db` to SSD — NOT gate relaxation.

**Regression coverage:** `tests/test_evidence_outcome_store.py` (6 tests:
path derivation, three-src extraction, idempotent re-extract,
frozen-clock `settled_at==hi` boundary, window/veto-filter reads,
prune+state).  `test_live_entry_evidence_gate.py` refresh tests pass
unchanged through the store path.

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

### Economics/evidence deep audit + edge_bias price bands (2026-11-22)

Full audit: `reports/ECON_EVIDENCE_AUDIT_2026-11-22.md`.  Headline:
~88% of side-eval kills are economic (`edge_below_threshold` +
`no_positive_executable_edge`) and economically *correct* — the
counterfactual cohort settles ≈ −1.56¢/contract.  The reserve stack has
no unconditional double-count; evidence artifact is fresh
(coverage_fraction=1.0, incremental store healthy).

**Confirmed measurement bug — edge_bias price pooling (FIXED, dark):**
`edge_bias.by_source` cohorts were keyed `ASSET|side|entry_source`
only, pooling the favorite-band under-claim (FLB) across the whole
price axis.  Deduped rebate-cap (−4¢) evals realized **+9.5¢/93% wr at
px90-101** but **~0¢/0.6% wr at px0-10** — cheap longshots were being
rebated for a bias measured on favorites, manufacturing phantom
claim≥+2¢ evals and contaminating the pre-registered claim-tail cohort.

- `evidence_outcome_store._EBIAS_SQL` now selects
  `executable_entry_price_cents`/`seconds_to_close` for ebias rows
  (columns pre-existed; old store rows keep NULL → pooled fallback,
  24h artifact window self-cleans).
- Ledger emits banded twins `ASSET|side|src|price_bucket` +
  `ASSET|side|*|price_bucket` alongside pooled keys (additive).
- `evidence_policy._edge_bias_lookup` prefers banded keys under
  **`MERID_EDGE_BIAS_PRICE_BANDS`** (default **OFF**): candidates
  `src|band → *|band → src → *`, first rec with epoch-aware n_eff ≥
  `EDGE_BIAS_MIN_NEFF` wins.  Flag off = byte-identical legacy lookup.
- `trade_decision` passes side exec price into
  `edge_bias_correction_cents`/`edge_bias_provenance`.
- Tests: `tests/test_edge_bias_price_bands.py` (9) +
  `test_edge_bias_correction.py` — 25 passed.

**Enable criteria:** after the claim-tail read at n≥10,000 evals / 3
weeks, or on explicit operator call (it makes claims more honest; does
not loosen gates — but it does shift the claim≥+2¢ cohort definition,
so mid-window enablement is an operator decision, not a default).

**External research cross-check** (in the report): Kalshi FLB is real
but ~1–3¢ max and sub-fee after spread on naive rules; makers > takers;
prices already well-calibrated near resolution; adverse selection is
the passive-fill tax.  Confirms: do not loosen the core edge gate;
the measured pockets are settlement px≥98 (live), pf 94–96c, and the
pending claim-tail read.  Next model-side item per
`analysis/RECALIBRATION_SPEC.md`: two-sided recalibration lift for
under-confident favorites (approved, ships dark).

### Exit-provenance clock-domain repair + resting-fill book capture (2026-11-23)

Post-DOGE-fill audit of `EXIT-POLICY-PROVENANCE` blocks
(`risk_params_state=ORIGINAL_PERSISTED` yet edge-decay/model-invalidation
exits refused).  Root cause was NOT the risk-params state — it was the
entry-book capture tier:

- **`UnifiedMarketState.book_updated_ts` is monotonic-domain** — copied
  verbatim from `KalshiMarketState.last_book_update_ts`
  (`time.monotonic() - measured_data_age`, the 2026-08-22 convention;
  `resting_order_monitor`, `settlement_aligned_exit`, `stop_candidate`
  all subtract it from `time.monotonic()`).  `book_age_s` subtracted it
  from `time.time()` (wall) → ~1.7e12s on every read → **every** entry
  fill persisted `entry_book_capture_quality=POST_FILL` and
  `entry_book_timestamp` rendered as 1970 (observed on the DOGE fill:
  provenance snapshot `entry_book_timestamp=1970-01-08`).  `_can_act_on_model_exit`
  then failed its `== "AT_FILL"` check → model-driven exits blocked for
  ALL positions, not just DOGE.
- **Fixes:**
  - `unified_market_state.book_age_s` now subtracts `time.monotonic()`
    (with a `>1e9` magnitude guard keeping legacy wall/epoch-stamped
    fallback values on the wall clock).
  - `_can_act_on_model_exit` accepts `AT_FILL_OR_NEAREST_PRE_FILL`
    alongside `AT_FILL` — resting/maker fills are detected
    asynchronously so the ingestion-time book is inherently post-fill;
    the bounded ≤30s near tier is the contemporaneous proxy the cache
    already assigns for that race.  `POST_FILL`/`UNAVAILABLE`/`UNKNOWN`
    still fail closed, as does missing signal/model metadata.  Aligns
    with the 2026-09-14 contract: book capture is a spread-stop
    invariant, not a prerequisite for trusted entry economics.
  - `position_cache` entry-book capture now keys off
    `thesis_side_from_intent` (held side) instead of the fill leg's
    `canonical_position_side` — SELL_YES-form fills (e.g. BUY_NO) were
    persisting YES-space bid/ask on NO positions.
  - `entry_book_timestamp` reconstructed as `now − book_age_s` (wall)
    instead of `fromtimestamp(monotonic)` → no more 1970 stamps.
- **Tests:** `tests/test_exit_provenance_clock_domain.py` (11) —
  monotonic/wall/unset age domains, NEAR-tier acceptance, POST_FILL /
  UNAVAILABLE / UNKNOWN / missing-metadata still blocked.
- **Note:** `Position.__post_init__` still nulls `entry_executable_*`
  for non-AT_FILL tiers — spread-stop book fields remain AT_FILL-only
  by design; model exits do not consume them.  `OrderbookSnapshot.ts`
  remains monotonic-domain in practice (doc says epoch — pre-existing
  doc drift, consumers use monotonic subtraction).

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

### 2026-11-19 pytest hang diagnosis + evidence key migration

- **Pytest "hang" root cause:** `tests/conftest.py::pytest_sessionstart`
  fingerprints every directory under `data/` before collection output.
  On the production box the tree is large enough that the walk exceeds
  any sane budget — pytest appears dead at 0% CPU before printing
  anything.  Bypass for focused runs:
  `MERID_TEST_SKIP_DURABLE_SCAN=1 python -m pytest <files>`
  (the conftest's own documented opt-out; CI keeps the default).
  Verified 2026-11-19: 36 tests pass in ~50s with the flag.
- **Evidence store key version:** `evidence_outcome_rows.mkey` is now
  canonical `ticker|side` for ALL sources (was bare `ticker` for
  'fill', `ticker|side` for veto/ebias — one market-side could hold
  ~2x effective weight).  `EvidenceOutcomeStore._connect()` migrates
  v1->v2 in place once (version marker in `evidence_extract_state`);
  the artifact records `evidence_key_version` + `coverage` fields.
  Offline 24h comparison (2026-11-19, ~568 market-sides): sum n_eff
  623 -> 531; 101 cells changed, largest drops in the 90-100c
  late/mid band (e.g. ETH|no|90-100|late 7.98 -> 2.62) — the fix is
  conservative-direction (sparser cells), not a loosening.
- **Store coverage caveat:** the companion store only backfills what
  `extract_range` has reached (newest-first, 1h chunks); configured
  lookback != available history.  The artifact's `coverage` block now
  reports `backfill_hi`/`coverage_fraction`/`latest_settled_at`.

## 2026-11-19 external-review response — financial brakes, backtest fees, forecast-audit verdict, EV floors

Response to the second external review round.  Items below are either
implemented in this change or documented resolved values; nothing here
re-enables the operator-disabled loss stops.

### Financial brakes (env-gated, OFF by default)

The review correctly identified that every financial downside bound was
disabled or unreachable (`MERID_DISABLE_LOSS_STOPS=1`,
`MERID_LOSS_EXITS_ENABLED=0`, `MERID_LOSS_BRAKES_ENABLED=0`,
`daily_loss_enabled=false`, `drawdown_halt_enabled=false`,
`MERID_BANKROLL_MAX_DRAWDOWN_PCT=100.0`,
`MERID_BANKROLL_CONSECUTIVE_LOSS_TICKS=1000000`).  Rather than
re-enable those mechanisms, `merid/risk/kill_switches.py` now carries
two deliberately loose, derived/auto-reset brakes evaluated inside
`can_trade()` — they halt NEW entries only; exits always pass the
order-router kill-switch gate:

- `MERID_KS_TRAILING_EQUITY_HALT_PCT` — halt when bankroll equity falls
  this fraction below its persisted peak (e.g. `0.25` = −25% from
  peak).  Peak equity persists in `risk_kill_switch.json` so restarts
  cannot silently reset the reference point.
- `MERID_KS_CONSECUTIVE_LOSS_HALT` — halt after this many consecutive
  losing `record_pnl()` outcomes (e.g. `8`).  The streak persists while
  armed and clears on the next winning settlement.

Both default to `0` = disabled, preserving the current operator posture.
They reuse `BANKROLL_DRAWDOWN` / new `CONSECUTIVE_LOSS` kill reasons,
auto-reset when the condition recovers or the brake is disarmed, never
override a manual emergency halt, and surface under
`get_status()["financial_brakes"]`.  Suggested starting values for an
explicit operator decision: `0.25` and `8` — loose enough never to fire
in normal operation, tight enough to bound the experiment-ending tail.

### Backtest fee modeling (opt-in)

`merid/backtesting/backtest_engine.py` now accepts
`fee_model="kalshi"` (default `"none"` preserves existing callers).
Fees use the canonical Kalshi parabolic model
(`rate·C·P·(1−P)`, taker 0.07 / maker 0.0175, Decimal-exact via
`merid.event_venues.kalshi.parabolic_fees`), are charged per side with
`entry_role`/`exit_role` maker|taker selection, and settlement/expiry
exits are exempt from trading fees.  `BacktestResult` reports
`total_fees_usd`, `net_total_pnl_usd`, `net_total_pnl_pct`; each `Trade`
carries `fees_usd`.  **Limitation:** this prices the traded contract's
entry/exit economics only — OHLC/candle history cannot reconstruct the
60-print RTI settlement average, so a fee-aware candle backtest still
prices terminal spot, not the averaged-settlement instrument.  The
settlement-aware path is the RTI tick store below.

### RTI tick store — settlement-path backtest is feasible

`data/cf_rti_ticks.db` retains ~1s CF Benchmarks RTI observations per
asset (rti_archiver; ~200MB and growing).  This is the same feed Kalshi
settles on, so an RTI-path backtest can replay the exact 60-sample
settlement construction the live `settlement_distribution.py` model
prices — including realized in-window samples fixing part of the mean.
Wiring this into `merid/backtesting/` is the correct next step; candle
backtests remain useful only for gross-path sanity, never for
settlement-instrument edge claims.

### Forecast-audit verdict — the model loses to the market mid

`merid/analysis/forecast_audit/` (brier + logloss, Brier Skill Score,
2000-replicate block bootstrap, paired comparisons) ran authoritative
audit 2026-11-14 on n=1449 units, integrity VALID.  Results:

- `final_vs_mid` d=−0.0125, CI [−0.0199, −0.0057], BSS=−0.082 — **FAIL**
- `raw_vs_mid` d=−0.0118, CI excludes 0 — **FAIL**
- `final_vs_q0` (vs calibrated market) d=−0.0176 — **FAIL**
- `mid_vs_baserate` BSS=+0.39 — PASS (sanity)
- `final_vs_const_half` BSS=+0.38 — PASS (trivial; prices ≠ 50c)

The unconditional forecast is a statistically significant *worse*
predictor than the market mid it trades against, including after the
market-anchor blend.  Any realized edge must come from the selection
layer (cells/lanes/evidence gates), not the base forecast — the audit
population is all forecast units across 60–600s horizons, so a model
can lose Brier overall yet remain +EV inside selected cells, but the
verdict means no unconditional forecast claim is currently defensible.
Per-horizon damage concentrates at 300s/600s (FAIL) vs 120s
(inconclusive).  The audit is currently a report, not a trading gate.

### EV floors and fee derivation (resolved values)

Entry economics require model net edge after the full cost stack
(spread + slippage + exact parabolic fees) to clear a decomposed
threshold (`_decompose_dynamic_min_required_edge` in
`trade_decision.py`): 2pp global floor + asset tier (BTC 1.5pp,
DOGE/XRP 2.5pp) + convexity `K·p(1−p)` + FLB premium <35c.  Per-lane
floors resolved from `.env` (cents of net edge per contract):

- `pinned_fav` probe tier (TTE ≤ `MERID_PINNED_FAV_LATE_TTE_S`=150):
  −3c by design (bounded negative-edge probe); mid-window floor 0c.
- `pinned_fav` maker tier: −3c (post-2026-11-18 tightening).
- `late_edge_probe`: +3c; `model_edge_floor`: 4c;
  `counter_regime`: 4c/2c; `veto_release`: 2c.
- pf resting-cancel floor at maker TTE ≥45s.

Fee derivation: Kalshi taker fee = `ceil(0.07·C·P·(1−P)·100)/100`
per order up to $0.0001 rounding (parabolic_fees.py); at 50c the
round-trip taker cost is ~7.3% of notional (≈4.75pp/side at 11ct), at
85–98c favorites ~1.1–2.2% — which is why the pinned-fav band targets
the cheap part of the fee curve.  **Sizing note:**
`MERID_PER_TRADE_LOSS_BUDGET_CENTS=1100` equals
`MERID_FIXED_EXPOSURE_CAP_USD=11.00` — per-trade and total portfolio
risk are the same constant; at current equity the $11 global cap makes
the portfolio effectively one-position-at-a-time, and the correlation
matrix/Kelly discount stays inert until that cap is lifted (restore
correlation-aware sizing in the same commit if it is).

## 2026-11-19 forecast-audit decomposition + settlement-path tooling

Follow-on to the forecast-audit FAIL verdict above — the audit now produces
the diagnostics needed to localize *where* (if anywhere) the model adds
information over the market mid, plus the settlement-path tooling the
fee-aware backtest gap required.

### Forecast audit v2 (`merid/analysis/forecast_audit/`)

- **q2 encompassing comparator** (`inference.py`, `report.py`):
  `logit(q) = a + b·logit(m) + g2·(logit(final) − logit(m))`, same
  walk-forward fitting discipline as q1 but on the *deployed* `final`
  probability — the Chong–Hendry encompassing test for the forecast that
  actually trades.  Reported as `q2_vs_q0` plus a `q2_residual_diagnostic`
  (gamma2 > 0 with `q2_vs_q0` PASS = deployed forecast carries incremental
  information beyond the calibrated market).
- **Murphy decomposition** per stage: Brier = Reliability − Resolution +
  Uncertainty over fixed-width probability bins.  Splits the FAIL into
  calibration error (fixable by recalibration) vs discriminative power
  (structural).  Interpretation guide: if Resolution ≈ market's, the model
  adds nothing; if Reliability dominates, isotonic/Platt recalibration is
  the repair.
- **Price-band slices**: 0.10-wide bands on contemporaneous mid
  (`pband_0`..`pband_9`, band_9 inclusive of mid==1.0) — the "by price
  decile" stratification.  The pinned-fav lane lives in the FLB-biased
  85–98c region, so per-band Brier skill matters more than the global
  verdict.  When stratifying for edge claims, apply Šidák/BH-FDR across
  the grid — uncorrected mining will find a lucky cell.

### Jump-robust realized vol (`merid/prediction/realized_vol.py`)

`MERID_REALIZED_VOL_ESTIMATOR` selects the per-second variance estimator:
`rv` (default, unchanged EWMA of squared returns), `bpv` (bipower
variation, `π/2·|r_{t-1}|·|r_t|` scaling), `medrv` (median-of-three absolute
returns — Andersen/Dobrev/Schaumburg 2012; recommended for 1s sampling
because it also steps over zero-return intervals that bias MinRV/bipower
down).  All feed the same EWMA/dt-normalization path; the
`_ANNUALIZED_VOL_BANDS` clamps in `trade_decision.py` still bind every
source.  Verified: a single 0.5% jump triples `rv` (~1.84 ann.) while
`bpv`/`medrv` stay ~0.5–0.6.  `RealizedVolEstimate.estimator` stamps which
variant produced each estimate.

### Settlement-path backtest (`merid/backtesting/rti_path_backtest.py`)

Replays `data/cf_rti_ticks.db` (~1s CF RTI prints, 5 assets, archive spans
2026-11-06 → present but coverage is bursty — long feed gaps are reported
as `no_ticks`/`no_strike`/`low_coverage` skips, never fabricated).  For
each 15-minute expiry it reconstructs the settlement window at configurable
TTE decision points (`--tte-grid`), feeds the real
`compute_settlement_distribution` code path (observed 60-print slots fixed,
remaining variance on the actual elapsed schedule — arithmetic-average
Gaussian is exact under Bachelier, no moment-matching needed), and scores
model vs spot-implied vs constant-0.5 Brier/log-loss by horizon and asset.
Timestamps are precomputed per asset with bisect slicing (no per-decision
O(n) rebuilds).  This is the artifact that makes fee-aware edge claims
possible: it prices the *averaged settlement instrument*, not terminal
spot.  Smoke run (BTC, 2026-11-15 partial coverage): model Brier beat both
baselines at every scored horizon, but n was small — treat as harness
validation, not evidence.

### Deflated Sharpe Ratio (`merid/backtesting/deflated_sharpe.py`)

Bailey & López de Prado (2014) DSR for promotion-gate return series:
`deflated_sharpe_ratio(returns, n_trials, periods_per_year=None)` returns
the probability the true Sharpe exceeds the expected-max-under-null
benchmark given `n_trials` variants tried.  `n_trials` must count *every*
variant screened, not just the winner — that is the whole point.  Use
`passes(threshold=0.95)` as the gate; `to_dict()` for audit records.  N=1
reduces to the Probabilistic Sharpe Ratio.  Companion to (not a
replacement for) CSCV/PBO if parameter grids are ever searched.

### Correlation-mode precondition on exposure-cap lift (`merid/config/live_config.py`)

`_apply_correlation_cap_guard` enforces the review invariant structurally:
the resolved `fixed_exposure_cap_usd` may exceed the audited $11
(`_AUDITED_EXPOSURE_CAP_USD`) **only** when the profile's correlation stack
is actually live — `correlation_tracking.enabled` AND
`correlation_tracking.real_time_monitoring` (the flag the 0.80/3-asset
thresholds hang off; inert while False).  A cap lift without that stack
fails closed to $11 with the rejection recorded in `conflicts_caught`.
Lifting the cap is therefore a two-key change: profile cap AND
`real_time_monitoring: true` — they cannot drift apart.  Note env overrides
can never raise the cap above the profile value anyway (existing
fail-closed rule); this guard covers the profile-edit path.

## 2026-11-19 (pm) DSR promotion gate + first settlement-path results

### Deflated Sharpe now gates `validate_before_lift`

`merid/backtesting/deflated_sharpe.py` was corrected to the canonical
Bailey & López de Prado form: the benchmark `SR0` uses the **empirical
variance of the trial Sharpes** (`trial_sharpes` arg — every variant tried,
winners and losers alike), with `n_trials`-only as a null-variance fallback.
Adds `min_track_record_length` (MinTRL).  `BacktestReport` gained
`n_trials`/`trial_sharpes` fields; `validate_before_lift` now runs the DSR
leg after the legacy checks and fails closed on
`dsr_not_evaluable`/`dsr_below_<thr>`; `MERID_PROMOTION_DSR_MIN` (default
0.95, 0 disables) tunes the floor.  Verified: sharpe=0.8/8760-obs report
with n_trials=500 → DSR 0.638 → **FAIL** where the legacy gate passed —
the selection-inflation catch working.  Callers populate `n_trials`/
`trial_sharpes` honestly or the gate sees N=1 (PSR vs zero).

### Murphy decomposition now uses equal-frequency bins

`_murphy_decomposition` switched from fixed-width to quantile edges
spanning [0,1] (deduped so tied forecasts never split) — forecast
probabilities cluster near the extremes, so fixed bins left most empty.
`identity_residual` still reports the WBV/WBC approximation gap for binned
continuous forecasts (Stephenson-Coelho-Jolliffe caveat, documented).

### First RTI-path backtest run — settlement-model validation

`reports/rti_path_2026-11-07_16.json` (gitignored artifact): 865 expiries,
3,355 scored decisions across all 5 assets over the full tick archive.
Archive coverage is bursty — 23k `no_strike` skips (no tick within 30s of
window open) are honest data gaps, not bugs.  Headline Brier (model vs
terminal-spot Bachelier vs 0.5):

| TTE | model | terminal_spot | 0.5 |
|-----|-------|---------------|-----|
| 900s | 0.2500 | 0.2500 | 0.2500 |
| 600s | 0.1996 | 0.1996 | 0.2500 |
| 300s | 0.1204 | 0.1210 | 0.2500 |
| 120s | 0.0600 | 0.0630 | 0.2500 |
| 60s  | 0.0302 | 0.0366 | 0.2500 |
| 45s  | 0.0185 | 0.0286 | 0.2500 |
| 30s  | 0.0103 | 0.0238 | 0.2500 |

Read: at window open the model is a coin flip (Brier = 0.25 exactly — the
60-print average hasn't diverged from spot yet); the settlement-aware
pricer beats terminal-spot at EVERY horizon and the gap widens as TTE
shrinks (2.3x at 30s) — direct evidence the observed-sample fixing +
discrete variance schedule adds real information.  This measures raw
forecast quality on the settlement instrument, NOT edge over market mid
(book history isn't in the tick DB — the forecast_audit remains the
model-vs-market verdict, currently FAIL overall).

`walk_forward_analysis` now populates the DSR leg honestly: every
(window × param_grid) train evaluation's Sharpe is pooled into
`BacktestReport.trial_sharpes` (annualized→per-period via the module's
sqrt(252) daily convention) with `n_trials=len(param_grid)` — the WFA
param search is exactly the selection process DSR exists to deflate.
Single-run producers (`kalshi_backtest.run_backtest_2y`) honestly report
n_trials=1.

## 2026-11-19 (late) Edge-vs-memory deep audit — verdict + claim-tail finding

Full write-up: `reports/EDGE_AUDIT_2026-11-19.md`; machine artifact
`reports/edge_audit_v2.json`; scripts `scripts/audit_edge_v2.py`,
`scripts/audit_edge_history.py`, `scripts/audit_edge_vs_memory.py`.

**Verdict: the model has real tail-calibration skill; cell memory has
none; the traded book is ~breakeven-to-negative.**

- All-eval pooled edge −1.78¢/contract is a *structural* fee+spread
  floor (YES/NO evals cancel within each market; per-ticker cluster-σ
  only 0.58¢). Do not read it as "no information".
- **Claim tail is real:** model-implied net edge `claim_gap ≥ +2¢` at
  eval → realized **+3.41¢/contract, CI [+1.66,+4.80], positive all 6
  weeks**; ≥+3¢ → +4.71¢; ≥+5¢ → +7.27¢. Monotone dose-response.
  Composition: mid-band 25–89¢, early/final TTE, SOL/DOGE/ETH carry,
  BTC weakest. Within-band claim→realized slopes 0.47–0.88 (all CI>0)
  — claims directionally real, overstated ~25–50%.
- **Decay warning:** the same top-decile at last-minute (TTE<60s)
  snapshot is +0.75¢ CI incl. 0 — the edge is entry-timing, not a
  hold-to-settle anomaly. Eval-price fills also overstate: shadow
  orders at ask+slippage stress are required before sizing.
- **Cell memory fails OOS:** walk-forward trailing-cell-edge → next-day
  realized spread −0.10¢, positive 16/34 days. The 27 BH-significant
  last-minute cells are small-n favorite pockets; no cell promotion
  without a pre-registered grid + held-out time split.
- **Real money (fills ledger, settlement pseudo-fills excluded,
  terminal = residual YES exposure × settlement):** −$36.41 over 957
  markets Sep 14→Nov 18; Sep −$5.35, Oct −$30.68, **Nov −$0.38**
  (162 mkts, post-containment breakeven). ENTER fill cohort n=9,928:
  mean −4.30¢/contract at median entry 96¢ — the pinned_fav band
  (−1.87¢/contract on 4,527 rows) is what the policy actually trades.
- **The gap:** positive-expectancy evals (~8/day, mid-band early/final)
  are not what the gate stack selects for; it selects negative-EV
  favorite probes instead. Next step is shadow-capture of the ≥+2¢
  claim cohort with realistic fill/slippage stress — NOT gate
  relaxation, NOT cell promotion.

Caveats: eval→fill join not yet built (cal log lacks decision_id);
fills-ledger `fee_cost` coverage partial (recorded total $14.97);
`net_ev` sparse in the evidence extract.

### Edge-audit execution addendum (same day, second pass)

- `scripts/audit_fill_slippage.py` joined cal-log evals to
  `kalshi_fills` entries: only **11 of 3,112 claim≥+2¢ eval-keys ever
  produced a fill** (~0.3% harvest) — the +EV tail is essentially
  untraded. Rare high-claim fills slipped +5.2¢ vs eval ask but kept
  +19.5¢ realized (n=5). Actual maker/maker_bid fills ran −5 to −9.5¢
  at fill price — worse than eval-price estimates.
- Decision-spine corroboration (`decision_audit_evidence_outcomes.db`,
  ~40h/309mkts): vetoed FULLY_EXECUTABLE claim≥+2¢ → +0.57¢
  CI[−2.94,+4.47]; fill claim≥+2¢ (pinned_fav) → +4.31¢ (n=68);
  50–74¢ sub-band +18¢ CI>0 (n=55); 01–09¢ claims −1.23¢ (FLB).
- `strategy_decision_side_ev`/`_outcomes` in `decision_audit.db` is the
  authoritative eval→fill spine (per-side expected_net_ev_cents +
  actual_fill_price_cents) but full-table scans are HDD-bound — query
  by decision_ts slices, never bare count(*).
- Next step spec'd in `reports/EDGE_AUDIT_2026-11-19.md` §7: book-
  archive depth replay at claim-tail eval timestamps before any
  shadow-order work.

### Edge-audit third pass — decision spine extracted (2026-11-19 late)

- `data/decision_spine.pkl`: 1,026,130 side_evals / 956,534 settled /
  1,359 mkts / ~4.7d via `scripts/extract_decision_spine.py`
  (6h-sliced reads; **never use `immutable=1`** — it skips the WAL and
  throws "malformed"; `mode=ro` only).
- Spine audit (`scripts/analyze_decision_spine.py` →
  `reports/decision_spine_edge_audit.json`): claim≥+2 → +3.58¢ ns;
  FULLY_EXECUTABLE-only → +2.44¢; **NOT_EXECUTABLE_* statuses inflate
  edge 4-8× (phantom — always filter)**; thin-book depth<1 → +12¢
  fiction vs deep-book +2.4¢ honest; early/final TTE carry.
- **pinned_fav claim inversion:** its own claim≥+2 evals realized
  **−2.05¢ CI[−2.64,−1.26]** — anti-predictive, consistent with FLB
  (model calls favorites underpriced; market is right). Decompose
  claim into model-vs-mid vs mid-vs-price components next.
- In-window actual fills (n=94): capital P&L −$12.41; median edge at
  actual fill −12.7¢/contract.
- Book replay (`scripts/audit_book_replay.py`) built; archive coverage
  bursty (~873 mkts Nov 17-20 with collector gaps) — rerun
  periodically for markouts, don't block on it.
- Literature applied: queue-position fill modeling (never fill-on-
  touch), markout adverse-selection measurement, executable-status
  filtering, BH-FDR/DSR/PBO multiplicity discipline.

### pinned_fav FLB decomposition (decision spine, same night)

Splitting `decision_lane='pinned_fav'` evals by exec price on
`decision_spine.pkl` resolves the "claim≥2 → −2.05¢" finding into
textbook FLB on both tails:

- Cheap side (≤9¢, n=21.7k): model p 4.2% vs realized wr 2.9% —
  longshots OVERSTATED ~1.4×; edge −0.1..−4.7¢ rising with price;
  all selected=0 (diagnostic only). Any cheap-side lane inherits
  this bias — keep `MERID_CHEAP_NO_LANE_ENABLED=0`.
- Favorite side (≥90¢, n=22.6k): model p 95.3% vs realized 97% —
  favorites UNDERSTATED ~1.7pp; eval-edge +4.4¢@90-93, +1.4¢@94-96,
  −0.2¢@97-98. Real pocket, consumed by pin-break tail + slippage.
- The +2.4-3.6¢ executable claim-tail edge lives in
  evidence_escape/unlabeled mid-band early/final admissions — NOT in
  pinned_fav.

### FLB mid-decomposition + 90-93 NO-pocket (decision spine, late 11-19)

`scripts/analyze_flb_decomposition.py` → `reports/flb_decomposition.json`
reconstructs market mid per decision from paired side entry prices
(99.3% coverage; sign of yes+no−100 reveals taker/bid basis) and splits
claim into model_vs_mid / mid_vs_entry / costs. Verified
`calibrated_probability` = P(held side). Findings:

- pinned_fav cheap side (≤9c, n=21.7k): FLB ratio 1.45 — model p 4.2%
  vs wr 2.9%; claim≥2 subset mvm +2.9c but realized −2.05c CI excl 0.
  Longshot-zone model-vs-mid deviations are fiction.
- pinned_fav favorite side: model UNDERSTATES favorites ~1.7pp;
  eval-edge +4.4c@90-93, +1.4c@94-96, −0.2c@97-98; reserve stack
  ~−6.4c means model claim is negative even where realized is +.
- claim≥2 tail (n=3,046): lives in unlabeled lane at px~16.6c —
  mvm +3.66c, wr 20.5%≈p 20.1% (calibrated), +3.85c realized;
  costs only −0.45c. Mid-band model-vs-mid deviations are REAL.
- 90-93c NO-side pinned_fav (n=2,512/118mkts): +5.20c ALL,
  +4.45c FULLY_EXEC CI[+0.85,+7.17], +4.92c depth≥100 — FLB harvested
  from favorite side (cheap-YES overpriced → NO underpriced). Eval
  prices only (3 fills +27c); decays Nov16 +8.2→Nov18 +0.3; band
  excluded by containment. Shadow-capture candidate, NOT a reopen.

### Cal-log decision_id lineage (2026-11-19, audit instrumentation)

`model_calibration_observations.jsonl` records now carry `decision_id`
(optional field, `log_model_observation(decision_id=...)` called from
`_compute_trade_decision_impl`). Fixes the fuzzy ticker+side+ts join
that missed ~99.7% of claim-tail evals in the edge audit. Dedup still
keys on (ticker, side, TTE-minute) — one decision_id per bucket; the
decision spine (`decision_audit.db` side_ev) remains authoritative for
per-decision joins. Lane/depth/model-release are NOT in the cal log
(they are admission outcomes determined after this call site); the
spine already carries them.

Audit scripts (manual/on-demand, not scheduled — spine extract is
HDD-bound ~30-60min, analyze steps ~2-5min on the pkl):
`extract_decision_spine.py` → `analyze_decision_spine.py` →
`analyze_flb_decomposition.py`; `audit_fill_slippage.py`,
`audit_book_replay.py` for execution-side checks.

### Daily P&L deposit/withdrawal netting (2026-11-20, UI fix)

`/api/v1/kalshi/pnl` `daily_pnl_usd` is an equity delta
(`equity_now − data/kalshi_daily_equity_anchor.json` day-start anchor).
External cash movements are not trading P&L — a $25 debit deposit
(net $24.50 after the $0.50 fee) was rendering as +$24.50 "P&L" in the
top bar.  `get_pnl()` now subtracts applied deposits/withdrawals
(`GET /portfolio/deposits` + `/portfolio/withdrawals` via the bankroll
service's `KalshiClientV2`) finalized at/after `anchored_at`:
deposit credit = `amount_cents − fee_cents`, withdrawal debit =
`amount_cents + fee_cents` (fee semantics verified against live balance:
anchor $3.36 + $24.50 net deposit = $27.86 equity).  Only `status ==
"applied"` rows count; pending/failed/returned never moved balance.
New response fields: `daily_pnl_cash_flows_usd` (net flows subtracted,
`null` when unverified), `daily_pnl_deposits_usd`,
`daily_pnl_withdrawals_usd`; `daily_pnl_source` is
`equity_delta_net_flows` when adjusted, plain `equity_delta` when the
flows endpoints fail (raw delta kept — flagged, not silently zeroed).
Flows fetch is TTL-cached (`MERID_PNL_FLOWS_CACHE_S`=60s) with a stale
success window (`MERID_PNL_FLOWS_STALE_S`=600s) since /pnl is polled.
`/kalshi/risk` and grid P&L were already ledger-based and unaffected.
Regression coverage: `tests/api/test_kalshi_pnl_endpoint.py` flow-netting
block (deposit, withdrawal, pre-anchor, pending/failed, unverified).
