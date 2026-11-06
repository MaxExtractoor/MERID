# cheap_no_settle Maker-Fill Counterfactual — Scope — 2026-11-06

Scope order (operator): counterfactual design and execution-identifiability
verdict only. No implementation, restart, live expansion, or threshold change
authorized. Core question:

> Among distinct, eligible cheap_no opportunities on B4-clean books, what
> would the actual post-only quoting policy have filled, at what cost, and
> with what settlement P&L and capital occupancy?

## 1. Frozen cohort and policy

### 1a. Live lane contract (drift_lane.py:255–292 + `.env`)

| gate | value | source |
|---|---|---|
| side | `no` only (`cheap_no_side`) | `cheap_no_block` |
| price band | 25–40¢ | `MERID_CHEAP_NO_PRICE_LO/HI` |
| complement | yes-side ask ≥55¢ | `MERID_CHEAP_NO_COMPLEMENT_MIN=55` |
| TTE | ≥240s | `MERID_CHEAP_NO_TTE_MIN_S=240` |
| net EV | ≥ −10¢ | `.env` overrides code default −6 |
| p_selected | ≥0.12 | `MERID_CHEAP_NO_MIN_P` |
| entry basis | **bid only** (`cheap_no_basis_not_bid`) — post-only maker | `cheap_no_block` |
| size | ≤6.0 contracts fp | `MERID_CHEAP_NO_MAX_CONTRACTS=6` |
| per-ticker | 1 attempt slot (durable counter) | `MAX_PER_TICKER=1`, `lane_attempts_exhausted` |
| daily | 96 (.env; code default 24) | `MERID_CHEAP_NO_DAILY_MAX` |
| route | BOUNDED_POST_ONLY_LANES member (trade_decision.py:800) | attempt `oa_a6fab…`: `buy_no 6.0@30¢ GTC` confirmed |

Quote-lifecycle policy inputs to pin verbatim from the build under replay:
`MERID_POST_ONLY_BUFFER_CENTS=1`, `MERID_ENTRY_MAX_CHASE_CENTS=2`,
`MERID_ENTRY_CHASE_REST_S=75`, `MERID_ENTRY_MAX_REST_S=15`,
`MERID_RESTING_RECHECK_SECONDS=5`, `MERID_REST_ENTRY_TTL_MS=8000`,
`MERID_WINDOW_PLAN_PENDING_TTL_S=45`, stake cap
`MERID_MAX_STAKE_PCT_SHARD_CASH=0.35` (code default), and window-end
cancel-at-expiry. Verify per-lane overrides at replay build; do not assume
the maker_bid/pf chase semantics transfer unmodified.

### 1b. B4-clean definition

A candidate observation is B4-clean iff BOTH:

1. Decision-time book integrity passed: `confidence_valid` true with
   `confidence_reasons` free of `orderbook_sequence_gap`,
   `orderbook_not_initialized`, `orderbook_stale`, `rti_book_skew`,
   `no_executable_depth`, `data_state_not_healthy` (snapshot table
   `confidence_reasons`; surfaced as PRC `DATA_QUALITY_VETO` when failed).
2. When archive coverage exists for (ticker, interval): `archive_coverage`
   row for that (connection,sid,ticker) shows no seq-gap/awaiting-snapshot
   interval intersecting the quote lifetime
   (`data/kalshi_book_archive.db` — 4.36 GB, live-collected until
   ~Nov 5 00:29, ~24h retention).

When (2) is unavailable (pre-archive window), records are labeled
`b4_clean_by_decision_state_only` — never silently upgraded to clean.

### 1c. Domains and partitions (no pooling across these without a test)

- **Existing domain**: 25–40¢, the live lane band.
- **Expansion pocket**: 20–25¢ — partially covered by the research shadow
  (`cheap_no_research.jsonl` band 10–24¢, assets ETH,SOL,DOGE,XRP,
  TTE 300–600s) — note the research band's TTE floor (300s) differs from
  the lane's (240s); do not splice them without an explicit TTE partition.
- Partitions: asset × TTE bucket × price bucket × config epoch (C1–C4 per
  `MERID_EVIDENCE_PROVENANCE_AUDIT_2026-11-05.md`: stake-cap 10-30,
  floor epochs, B3 exec fixes 11-02, Stage-B clip deploy).
- Replay unit: **distinct quote opportunity** — dedupe polling rows to
  (ticker, side, quoting episode) consistent with the actual reprice/TTL
  policy; never "all cheap NO quotes."

## 2. Execution-evidence inventory (what the data can/can't establish)

| datum | source | status |
|---|---|---|
| decision-time book (bid/ask/depth/spread, quote_age, book_is_executable) | `decision_audit.db` gate JSON, `rejected_candidates.jsonl`, `cheap_no_research.jsonl` | **available** full window |
| candidate settlement outcome | `settlement_outcomes.jsonl` (47,814 tickers) | **available** |
| book trajectory after decision (level depletion, reprices, adverse moves) | `data/kalshi_book_archive.db` raw `orderbook_delta` frames + coverage | **trailing ~24h only** — retention-bound; the Oct 25–Nov 3 attempt cohort is NOT reconstructable |
| counterparty trade prints | none — archiver captures `orderbook_delta` only | **unavailable** — cannot distinguish level depletion = fills vs cancels |
| queue position at own bid | Kalshi never publishes; only level depth (`depth_at_own_bid_cc` in pf shadow) | **unavailable** — queue is scenario-bound at best |
| own-order lifecycle | `data/kalshi_order_attempts.db` (status + `replaces_order_attempt_id` chain), server `RESTING_ORDER_*` events | **available** (lane-attributed post ~Oct; `decision_lane` absent on 23,538 legacy rows) |
| realized fills + fees | `data/kalshi_fills.db` (1,844 rows; `liquidity_role` NULL — role must be inferred from order side/route, not trusted from the fill row) | **available**; settlement rows included |

**Observed cheap_no lifecycle (validation set):** 15 lane-attributed
attempts, all `buy_no` 25–37¢, ETH/SOL only. Status column distribution:
1 FILLED, 7 ACKNOWLEDGED, 7 REJECTED — **status is the row's latest
state, not a proven terminality**: each ACKNOWLEDGED row must be resolved
to a terminal outcome (fill | cancel | expire | still-resting) via
order-id joins + cancel events before it counts as "expired unfilled."
The 1 FILLED (ETH 10-26, coid `merid_e9cdfe8ad2614c…`): observed entry
(buy_no ×2.0 @~26–27¢, `fee_cost=0.0`, canonicalized as yes-sell) and
observed exit (no-sell@49¢ ~90s later, fee 3.5¢, ~+22¢/contract realized)
— **an actual exit-policy result, NOT a hold-to-settlement outcome**;
its settlement counterfactual is reported separately (would have been
payout-vs-settled-price). Plus 31 ENTER episodes Oct 25–26 per the
all-lanes audit (engine-level ENTER ≠ submission).

**Fill-claim tiers the data support:**
- T0 — candidate settlement P&L (no fill model): **supported** today.
- T1 — **scenario-bounded** fills within archive window (level-depletion
  events around the hypothetical quote): **supported ~24h**, labeled
  scenarios only — `fill_optimistic` (depletion = fill), `fill_conservative`
  (depletion = cancels; fill only on trade-through), `fill_impossible`
  (level never reached / quote cancelled first by policy). Archive deltas
  do not remove the fill-vs-cancel ambiguity — T1 is never promoted to T2.
- T2 — queue-aware fill probability: **not supported** (no queue data,
  no prints); report scenario bounds, never a single "verified maker fill."
- T3 — pre-archive cohort fill claims: **not supported** — decision-time
  quotes exist but post-decision book trajectory does not; T0-only.

## 3. Required outputs (opportunity vs fill economics, separated)

1. **Candidate settlement P&L** (T0): P&L = count·(Y−P_fill)−F on lane-
   eligible candidates; report the 25–40¢ and 20–25¢ domains separately;
   per asset/epoch/TTE.
2. **Modeled fill rate / partial fills** per stated scenario (T1 window
   only) — quote price reached? size consumed? policy TTL/cancel
   interactions (max 1/ticker, rest-until-window-end) honored.
3. **P&L conditional on modeled fills** — does the filled subset retain
   the edge (adverse-selection test; never multiply T0 expectancy by an
   average fill rate).
4. **Net P&L per submitted opportunity** — expected value of the whole
   quoting policy including unfilled orders.
5. **Reserved-dollar time** — stake × time-in-book per quote; the lane is
   hold-to-settlement, so locked capital ≈ stake × remaining TTE≥240s per
   fill; express as window-share of the $6 plan budget and 35% stake cap.
6. **Portfolio replay** — which opportunities remained feasible under
   window_plan cells ($6 budget, 0.35/0.45/0.20 shares), basket same-side
   ≤2, pending-order exposure, and existing-position blocks.
7. **Exclusion ledger** — every candidate → drop reason (B4-dirty,
   lane-gate fail, policy-block, dedup) with counts per partition.

## 4. Reconciliation against observed lifecycles

- Validation set: the 15 cheap_no attempts (+ future ones during replay).
  For each: replay-predicted fill vs actual (FILLED/rested-expired/
  rejected); report agreement, disagreement, unresolvable.
- Fee reconciliation: exact parabolic formula vs recorded `fee_cost` at
  $0.0001 granularity. The one observed maker fill shows `fee_cost=0.0`
  while the pf audit reports ~2.3¢/fill-event avg — reconcile per series/
  account/role before trusting any fee assumption (Kalshi's documented
  rounding is multi-step, not a single ceil).
- Lifecycle provenance: amendments via `replaces_order_attempt_id`,
  partial fills via `count_fp` deltas on the same `client_order_id`;
  settlement rows (`liquidity_role='settlement'`) separate from exits.

## 5. Bounded verdict — evidence requirements

| outcome | required evidence |
|---|---|
| **Insufficient execution evidence** | archive coverage < target window share, or fill-rate CI spans the decision boundary → continue instrumentation/shadow only |
| **Existing 25–40¢ supported** | T0 positive + T1 filled-conditional P&L positive across ≥2 epochs, fill model robustness within labeled scenario bounds, validation-set agreement, portfolio replay feasible — then a **separately authorized** bounded test |
| **20–25¢ expansion supported** | all of the above on the expansion partition alone (its own fillability — deeper-OTM quotes rest differently), as a **separate decision** |

Hard rules: no inherited positive verdict from settlement-only replay;
`MIN_NET_EV=−10¢` is an input to be tested, not a justified default;
no pooling of 20–25¢ with 25–40¢, maker with taker, or B4-clean with
decision-state-only cohorts. Observed exits (actual exit-policy results)
are reported separately from settlement counterfactuals — an exit fill
never validates a hold-to-settlement claim.
