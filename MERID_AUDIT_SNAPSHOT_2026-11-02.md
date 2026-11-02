# MERID System Audit Snapshot — 2026-11-02

Read-only historical audit, closed at commit `a18f5d60` (2026-11-01 21:07 UTC-5).
No live config changes, no restarts, no orders, no deletions. Exit policy and
exposure limits unchanged throughout.

## Reproduction

Audit scripts (repo root, scratch convention): `_audit_scorecard.py`,
`_audit_lanes{2,3,4}.py`, `_audit_exec{,2}.py`, `_audit_pnl.py`,
`_audit_probe_keys.py`, `_audit_final{,2}.py`, `_audit_roundtrip.py`,
`_audit_episode_raw.py`, `_audit_categories.py`, `_audit_obligations.py`,
`_audit_track_a.py`, `_audit_final_join.py`, `_audit_dispatch_gap.py`.

Python: `.venv` interpreter. All DB access read-only (`mode=ro` URIs).

## Sources and coverage windows

| Source | Coverage | Notes |
|---|---|---|
| `data/kalshi_fills.db` (`kalshi_fills`) | 1,788 fills, 2026-09-14→11-02 | trusted ledger; `proceeds_dollars` is signed cash; raw `action` = counterparty side — use `canonical_yes_delta_cc` + `entry_or_exit`; `liquidity_role='settlement'` rows are pseudo-fills (no cash) |
| `data/kalshi_order_attempts.db` (`order_attempts`) | 25,551 rows, from ~2026-10-19 | generic attempt store; `PERSISTED` = pre-submit bookkeeping (0 exchange IDs, 0 updates) |
| `data/kalshi_order_attempts.db` (`exit_order_attempts` + `_events`) | 2,399 attempts, era from ~Sept | exit-obligation FSM; `exit_intent_id` = obligation unit; `position_key` = UUID not ticker:side |
| `logs/exit_evaluations.jsonl` | 25,745 evals, from ~2026-09-21 | per-eval decisions incl. `would_submit`, `decision`, input-quality flags, `policy_version` |
| `logs/settlement_outcomes.jsonl` | 46,024 outcomes | `resolved_yes` per ticker |
| `data/decision_audit.db` | >1M decision rows | `strategy_decisions`/`_outcomes`/`_snapshots`; counterfactual P&L on 88% of settled NO_TRADE |
| `data/trade_attribution_fact.db` | 581 fills, 3,406 orders, 3,648 settlements, **1 intent** | spine gap: intent events unpopulated |
| `.env` / `AGENTS.md` | current | live config + operating contract |

Grouping/precedence rules (documented, frozen): episode = `market_ticker`;
cash = Σ `proceeds_dollars` (non-settlement rows) + residual `canonical_yes_delta_cc`
valued at settlement outcome; category: `fully_exited` (exit fill + zero resid) /
`partial_exit` (exit fill + resid) / `no_exit` (no exit fills); episode primary
obligation class precedence: `any_fill > exchange_rejected > canceled_unfilled >
terminal_unfilled > not_accepted > no_obligation_records` (reporting convention,
not causal attribution).

## Verified results

- **Historical account P&L: −2,802.15¢ (−$28.02)** over 799 settled episodes
  (461 fully_exited +3,381.5¢; 25 partial_exit +2,171.8¢; 313 no_exit −8,355.5¢).
- **Hold-to-settlement counterfactual: −3,320.3¢** → recorded exit policy added
  **+518.1¢ (~+$5.18)** vs holding same entries.
- Exit obligations: 2,399 attempts → **1,224 distinct `exit_intent_id`s** (~1.96×
  retry inflation; max 130 attempts on one `hard_profit_lock` obligation).
- Dispositions (one per obligation): any_fill 330, terminal_unfilled 403,
  not_accepted 312, canceled 96, exchange_rejected 80, other 3.
- `not_accepted` reasons (exact 312): position_closed 262, retry_unknown 32,
  exchange_position_missing 17, market_finalized 1 → **280/312 (89.7%) correctly
  suppressed** (valid-at-creation, obsolete at check: 305/312 created before
  position's last fill).
- **FSM↔ledger reconcile: 379 obligations have ledger-verified exit fills**
  (321 any_fill + 37 not_accepted + 15 canceled + 6 rejected) → **67 obligation-level
  discrepancies**: 58 fills the FSM never propagated + 9 FSM `any_fill` claims
  without ledger fills (preserved unresolved).
- **37 sell-signalled episodes lack linked obligation records** — RESOLVED as
  telemetry misclassification, not dropped dispatch: all are `stop_loss`
  `canonical_reason` evals produced by the explicitly observe-only
  `[EV-EXIT-SHADOW]` call site (`position_monitor._evaluate_stop_loss`), which
  has no consumer by design. `would_submit:true` is the evaluator's verdict,
  not a dispatch approval. Full instrumentation coverage does NOT change this:
  the ~2-3 in-coverage cases are also shadow evals, not live requirements.
  Historical classification: **shadow evaluations signalled hypothetical
  sells; no exit intent was expected from that path.** (The genuine defects
  fixed in P1: shared telemetry indistinguishable from live approvals +
  EDGE_DECAY EV-veto log-only.) Whether an independent *live* candidate
  existed for the same position instance is a separate backfill question —
  match on position+time+identifiers, not ticker alone.
- 164 no-exit episodes have no obligation records (−5,872.1¢): 136 pre-logging
  (unobservable), 26 evals-present-held (−1,818¢, policy-normal), 2-3 in-coverage
  sell-signalled.
- Fees verified exact (`kalshi_fee_cents_exact`, 0.01¢): maker 0.09¢ @95¢,
  taker 0.34¢ @95¢. Bankroll $12.64; 35% stake cap ≈$4.43 < 6×95¢ cost;
  daily-loss limit $1.77 < one pin-break — both calibrated below one order's
  worst case (misalignment, not corruption).
- Tail calibration artifact `tail_pava:n10220` structurally sound (non-dual NO
  curve, market-dedup, per-asset shrinkage) but fit 2026-10-15 — predates floor
  raises (90→92→94) and ETH quarantine.
- `MERID_LOSS_EXITS_ENABLED=0` (profit-only), `MERID_ENABLE_EV_EXIT_GATE=1`,
  envelope bid≥85¢/TTE≤120s; yet 43 `LOSS_CAP`/`HARD_STOP` attempts 10-16→29 —
  version-path unverified.
- Lane names observed: pinned_fav, window_quota, drift_fav, maker_bid,
  cheap_no_settle, settlement_convergence, evidence_cell_escape, threshold_cell,
  current_build_provisional, canary_maker, taker, maker. User labels
  `moneyness`/`mband` produced zero attributed fills — role unfmapped.
- Pinned-fav-taker: not a strategy label; a route inside `pinned_fav`
  (`MERID_PINNED_FAV_MAKER_MODE=1` active); taker economics at 94-98¢ cannot
  clear net-of-cost (~1.4¢ cost vs ~0-0.3¢ measured edge).

## NOT established by this audit

Current-build healthy profitability; recoverable-dollar shortfall; freeze
dating (watchdog logs untapped); whether suppressed exits were optimal at first
signal; `BYPASS_EMERGENCY` branch ownership (45% of evals); cause classification
for 80 exchange rejections; `moneyness`/`mband` roles.

## Learning eligibility manifest (spec)

Per-record flags (multi-code): `legacy_identity_unverified` (1,751/1,788 fills),
`pre_logging_coverage`, `data_quality_blocked`, `incident_overlap`,
`attempt_outcome_unknown`, `join_ambiguous`, `fsm_fill_unpropagated`,
`retry_amplification`. Task-scoped eligibility: account P&L keeps all verified
cashflows; lane learning excludes unverifiable attribution; reliability excludes
uninstrumented periods; current-build cohort requires version+inputs+coverage+
incident-clean; healthy no-exit losses retained alongside wins. Flags are
evidence, not universal exclusions. Rebuild as versioned state with old state
preserved.

## Repair log

**P1 (partial) — stop-candidate signal dispositions, landed 2026-11-02:**
`stop_candidate.py` — `maybe_submit_stop_candidate` is now a thin observability
wrapper over `_maybe_submit_stop_candidate_impl`. Every return path (17 gate
rejections, arbiter denial, router result, route timeout/exception, raised
exception, sync no-event-loop) appends exactly one `record_type:"signal_disposition"`
row to `logs/stop_candidates.jsonl` carrying `candidate_id`, deterministic
`intent_id`/`client_order_id` (joins `exit_order_attempts.exit_intent_id`),
disposition class (`approved`/`suppressed`/`unresolved`/`error`), result status,
reason, and the suppression inputs (exec bid, entry, fair value, TTE).
Behavior-neutral: never raises, exceptions still propagate after the error
record lands. Verified by `_test_disposition.py` (stubbed impl per status).
**P1 (completed) — same day:** root cause of the "no candidate" class found at
`position_monitor.py:~6484` — the `canonical_reason="stop_loss"` evals are an
explicitly observe-only shadow evaluation (`[EV-EXIT-SHADOW]`) that never
dispatches by design; their `would_submit=true` records were indistinguishable
from live-gate approvals. Repairs: (a) `record_signal_disposition` accepts
candidate-less dispositions; (b) SELL-signalled shadow evals now emit
`disposition:"observe_only"` records keyed by `evaluation_id` — signal→outcome
joins now classify them correctly instead of as dropped handoffs; (c) the
EDGE_DECAY EV-gate veto (`STOP-LOSS-EDGE-DECAY-EV-VETO`, previously log-only)
now emits `disposition:"suppressed"` + `reason:"ev_gate_veto:<decision>:<detail>"`
on the recorded candidate. Disposition vocabulary: `approved` / `suppressed` /
`unresolved` / `error` / `observe_only`. `_emit_exit_intent` suppressions were
already durable via `_log_exit_eval` (EXIT_BLOCKED/EXIT_INTENT_CREATED).

## P2 reconstruction — the 130-attempt obligation (2026-10-24)

Obligation: `intent_exit_0a0c4037960942fe0f23`, ticker
`KXETH15M-26OCT240000-00`, reason `hard_profit_lock`, req 102cc @ 88c.
Measured from `data/kalshi_order_attempts.db` + `data/kalshi_fills.db`.

Ordered timeline (single obligation):

```
03:49:23  entry fill (yes/sell 102cc, -$0.89) — position opens, long NO
03:50:16  eval tick: bid >= latched lock threshold -> _emit_exit_intent
          attempt#1 INTENT_PERSISTED -> SUBMITTING (hard_profit_lock)
03:50:17+ submission outcome unprovable; no ack stored
          attempt#1 -> NOT_ACCEPTED_CONFIRMED (reason: retry_unknown_submission)
          next eval tick: prior attempt terminal -> superseded_for_rearm
          -> fresh coid (exit_<sha>:superseded:<attid>) -> attempt#2 -> ...
          (repeats every eval tick ~0.95s median; 128x the same 3-state cycle)
03:51-53  2/130 attempts took RESOLVING_ON_EXCHANGE; one verdict:
          position_closed -> NOT_ACCEPTED_CONFIRMED (rearm continued anyway)
          1x intent_timeout_submission_unknown round-trip
03:53:47  last attempt (#130) — obligation went quiet
          (lock pending record terminalized / bid left threshold band)
04:00:03  settlement fill no/sell 102cc +$1.02 -> position flat, net +$0.13
```

State tally: 65x NOT_ACCEPTED_CONFIRMED + 65x SUPERSEDED_AFTER_CONFIRMED_TERMINAL.
All 130 attempts: **0 exchange_order_ids, 0 fills, 0/329 events carrying
raw_exchange_payload**. Sibling clusters (same shape, all `hard_profit_lock`):
SOL 71 att / DOGE 69 / ETH 68 (1 attempt got an oid, still rearmed 67x) /
XRP 66 — mixed REJECTED_EXCHANGE + NOT_ACCEPTED + superseded.

Answers to the four reconstruction questions:

1. **What triggered the first retry?** Not a retry decision — an *obligation
   re-emission*. Attempt #1's submission outcome was unprovable; the
   then-current build classified it `NOT_ACCEPTED_CONFIRMED`
   (`retry_unknown_submission`, a lookup-based inference — no exchange
   evidence stored). The next eval tick saw a terminal attempt and
   `superseded_for_rearm` minted a fresh coid. Loop repeats at eval cadence.
2. **Evidence before each later retry?** None recorded. Every terminal
   verdict was inference without stored exchange payload; the real
   evidence-path (`RESOLVING_ON_EXCHANGE`) ran on only 2/130 attempts.
3. **Was an existing order/fill covering the requirement?** Never. Zero
   exchange orders, zero fills. The requirement stayed uncovered until the
   market settled the position at 04:00:03. One reconcile verdict
   (`position_closed`) was false vs exchange-truth fills — the position was
   still live — yet rearm continued regardless.
4. **What should have stopped the loop?** In order of where the check fails
   today:
   a. `position_closed` verdict → position-level verification before rearm
      (recorded `hard_lock_pending.state=FILLED`, which only disables the
      *below-threshold chase* path, not the ≥threshold re-fire path).
   b. A per-obligation durable-attempt bound. `MERID_HARD_LOCK_CHASE_MAX_ATTEMPTS`
      (default 3) caps only the salvage-chase emissions (`_lock_bid <
      _lock_threshold`); the ≥threshold re-fire path has no durable ceiling.
   c. Evidence requirement for terminalization: "unknown" → "CONFIRMED
      not-accepted" without stored exchange evidence over-claims the verdict.
      (Oct-26 ack-payload capture partially addressed this going forward.)
   d. Structural vs price-failure discrimination: `limit_not_executable`
      reprice-retry is correct; an IOC that never reached the exchange is an
      infra/connectivity failure — resubmitting a fresh coid at eval cadence
      is spam, not retry (the deterministic coid exists precisely so an
      *unproven* outcome resubmits under the same idempotent key).

Deployed-commit correction (2026-11-02): the storm ran on code that
already contained the 2026-10-18 route-timeout->SUBMISSION_UNKNOWN fixes
(`09517e96`, `f743bf02`, `3c1d04fb`) — the build at 03:50 UTC was >= the
2026-10-21 chase-ladder commit `58f0e0c5` (attempt payload carried no
build_sha, so the exact head is bounded, not pinned).  The unbounded path
was therefore *not* "predated fix"; it was the 2026-10-20 `c28128a5`
reconcile un-wedge — terminal-status coid lookup + bounded-IOC inference —
which terminalized unproven unfindable-IOC submissions as
NOT_ACCEPTED_CONFIRMED (`retry_unknown_submission`) and authorized rearm,
plus the startup cleanup that terminalized stale unknowns.  That producer
was removed by `6f5e748c` (2026-11-01, "Retain unknown exit orders until
verified"): the reason map now refuses non-evidence-backed verdicts
(`position_closed`, `size_zero`, `flat` are refused), empty order lookups
retain SUBMISSION_UNKNOWN, filled/executed orders retain until fills
reconcile, and canceled/rejected requires zero-fill proof.  `git -S` shows
`retry_unknown_submission` existed only in the removed path.

Current-build residual surface: any *terminal* verdict (REJECTED_EXCHANGE /
NOT_ACCEPTED_CONFIRMED / TERMINAL_UNFILLED / EXPIRED / CANCELED) →
unconditional supersede + fresh coid on the next eval — no per-obligation
ceiling, no flat-check, no structural-vs-price discrimination.  Held for
separate review (can alter which eligible exits are delivered).

P2 in-scope repairs applied 2026-11-02 (implementation correctness only —
no exit-eligibility, pricing, or policy change):

- `EXCHANGE_CONFIRMED_FLAT` state existed (2026-11-01) with zero inbound
  FSM edges and zero producers — unreachable.  Wired: edge from every
  nonterminal state (inventory evidence is orthogonal to the order
  lifecycle, same shape as the authoritative-fill edge), and producer
  `_resolve_exchange_confirmed_flat` inside `_reconcile_exit_intent`:
  queries `/portfolio/positions?market_ticker=<mkt>` (+subaccount when
  present); resolves the intent as EXCHANGE_CONFIRMED_FLAT with stored
  evidence only when the request succeeds AND shows no nonzero market
  position.  Errored/unverifiable/still-open lookups retain unresolved —
  uncertainty is never translated into flat or into a rearm.
- Reached from all three previously-terminal-stuck retain branches:
  position missing from cache (ticker from durable attempt), cached
  size==0, and inconclusive order lookup.  Verified-flat clears the
  in-flight lock but retains `exit_triggered` (position-cache/fills owns
  retiring the record) — a locally-stale open position cannot re-emit.
- Hard-lock bookkeeping: `exchange_confirmed_flat` now records
  `HARD_LOCK_RECONCILED_FLAT` + pending state `RECONCILED_FLAT` instead of
  falling into the `*flat*` -> `HARD_LOCK_FILLED` branch — a
  position-closed inference no longer claims fill evidence it lacks.
- Visibility: `OrderAttemptStore.count_exit_attempts_for_intent` +
  `[EXIT-OBLIGATION-RETRY]` log at supersede (info <5, warn >=5, error
  >=25, critical >=50 siblings).  Log-only.
- Verified concurrently: active-attempt-per-position conflict already
  serializes replacements (BEGIN IMMEDIATE + nonterminal check ->
  ExitOrderAttemptConflict).
- Acceptance harness `_test_flat_resolve.py`: 21/21 — verified-flat
  resolves with evidence; still-open/failed lookups retain;
  missing-position resolves via attempt ticker; unproven position_closed
  refused; no-coid retain; conflict-on-second-active; flat edge complete;
  exit_triggered retained on flat resolution.

Repair targets HELD for separate review (can alter which eligible exits
are delivered — withdrawn from this pass on operator instruction):
- Per-obligation durable-attempt bound / `EXIT_EXHAUSTED` terminal.
- Rejection-reason→action table (structural rejections stop rearm; only
  price rejections reprice-and-rearm).
- Evidence requirement for terminalization beyond the 2026-11-01 map.

## P3 ledger→FSM reconciliation (2026-11-02, implementation)

**Refined dry-run classification** (`_audit_p3_dryrun.py` + decompose scripts;
earlier "58 + 9" reconciled by multi-key joins — coid, tombstone coid,
exchange_order_id, intent_id):

| Class | Count | Disposition |
|---|---|---|
| Late fills on terminal-nonfilled attempts | **37** | CANCELED 13, NOT_ACCEPTED 13, REJECTED 5, TERMINAL_UNFILLED 6 → `apply_exit_fill` (late-fill edges already existed) |
| Fills on *superseded* attempts' original coids | **36** | Fill falsifies the confirmed-terminal verdict that authorized supersede → `SUPERSEDED→FILLED/PARTIALLY_FILLED` (new edges) |
| Already-FILLED attempts, `confirmed_quantity` NULL | **355 fill applications** | cq backfill + `fill_linked:` evidence events |
| 9 "FSM-only" claims → resolved | 5 | Real fills present with `client_order_id` NULL at ingest; joinable by `exchange_order_id` or `intent_id` — claims true, linkage missing |
|  | 2 | Verified misattribution → `FILLED→EXCHANGE_CONFIRMED_FLAT` |
|  | 2 | Test-era rows (fake tickers `KXBTC15M-T/-X`, coids `exit_test2`/`exit_abc123`) — documented, excluded |
| 505 "no attempt" → **469** after tombstone-prefix join (36 fills sat under `:superseded:` coids, moved to the SUPERSEDED apply class) | 346 | `settlement:` pseudo-fills — correct by design |
|  | 123 | Canonical `order_attempts` coid coverage only (pre-exit-FSM era + stopcand + **all 11 `live_router_` ids ⊂ this bucket**) — coverage-era, mutually exclusive |
| **Genuinely unlinked exit fills** | **0** | — |

**Plan (final, `_audit_p3_repair.py` + `_p3_apply_detail.csv`):**
416 applications (416 unique fills / 391 attempts / 391 obligations):
FILLED 342 (cq backfill), SUPERSEDED 37, NOT_ACCEPTED 16, CANCELED 10,
TERMINAL_UNFILLED 6, REJECTED 5. Corrections: 2 (misattribution →
EXCHANGE_CONFIRMED_FLAT). Flagged review-only: 5 ambiguous-intent
(multi-attempt, owner undeterminable), 19 representation-pair rows,
6 empty-`ticker` attempt rows.

**Dual-representation pairs (upstream flag for P4):** ~19 exits exist as two
ledger rows — legacy `live_router_*` (schema v0) + canonical uuid (schema v3)
with identical `order_id`+qty+signed delta. One order cannot fill twice its
size; the repair applies the canonical row once. If position replay sums both
rows' `canonical_yes_delta_cc`, those exits double-count — check before
trusting per-market deltas on Sep-era markets.

**Mutation semantics (verified, not intended):** appends
`exit_order_attempt_events` rows + UPDATEs `state`/`confirmed_quantity`/
`exchange_order_id`/`updated_at`/`state_version` on existing rows. No DELETE,
no fills-ledger writes, no exchange calls — `order_attempt_store.py` imports
stdlib only (sqlite3/json/uuid/…); `_audit_p3_repair.py` references no
client/router path. Backup: `VACUUM INTO` pre-apply (WAL-safe, live-reader
compatible); restore verified (restored copy = pre-apply state exactly).

**Live-consumer review (the important check):**
- `confirmed_quantity` write-path added in `apply_exit_fill` (exactly-once per
  fill_id, dedup durable in events — `fill:`/`fill_linked:` reasons — not
  in-memory). `fills_poller` expired-sweep can now fire — intended; it gates
  on nonterminal attempts only, and the backfill produces **zero** new
  nonterminal records (post-check enforced).
- Terminal-resurrection guard: a terminal attempt can never fill again, so a
  partial fill on one records `fill_linked` + cq without state change —
  prevents zombie in-flight locks via `_rehydrate_exit_intent_in_flight_from_store`
  (PARTIALLY_FILLED→SUBMITTED) and `get_active_exit_attempt_for_position`
  conflicts. Verified: 0 nonterminal results post-apply; the 3 partials land
  as terminal+cq (CANCELED cq_set=3, REJECTED cq_set=1).
- In-memory state: the script instantiates its own store on the DB path —
  position_cache, fills_ledger, and resolver maps are untouched. Concurrent
  live writes are safe: `BEGIN IMMEDIATE` + dedup inside one tx; WAL +
  `busy_timeout=5000` already configured.
- Stop-loss/stop-candidate submission paths are unreachable from the repair
  (no route calls in the call graph; `MERID_LOSS_EXITS_ENABLED=0` unchanged).

**Root causes found and repaired (mechanism, not just backfill):**

1. **`confirmed_quantity` never written** — schema column + `fills_poller`
   completion check (`cq >= rq`, line ~610) existed, but no code path ever set
   it: 0/2,399 attempts had it. The expired-market sweep could therefore never
   fire. Fixed via `OrderAttemptStore.apply_exit_fill()` — exactly-once per
   `fill_id` (dedup by `fill:`/`fill_linked:` event reason, global across
   attempts → cross-attempt double-claim refused with warning), cumulative cq,
   FILLED at/above `requested_quantity` else PARTIALLY_FILLED, evidence in
   `raw_exchange_payload`. Harness `_test_p3_apply_fill.py`: 11/11.
2. **Resolver sole-open-attempt market fallback** (`ExitAttemptResolver._find_attempt`):
   a fill carrying a coid/oid matching no *open* attempt was attributed to the
   sole open attempt on the market — producing the 2 verified misattributions
   (a32e28f9 claimed an entry-leg sell `0727d565`; df9c7282 claimed a
   `live_router_` id absent from the ledger). Fallback now requires the fill
   to carry **no** identity keys.
3. **Terminal attempts unreachable for fills**: `note_fill` searched only
   PENDING/ACKED in-memory attempts; fills on terminalized/never-registered
   attempts quarantined as `[EV-EXIT-FILL-UNMATCHED]` with no durable update.
   `note_fill` now does a durable lookup (wire coid incl. `:superseded:`
   tombstone prefix, then exchange_order_id) → `apply_exit_fill` before
   quarantining. Live fills also flow through `apply_exit_fill` (cq now set).

**PRODUCTION APPLIED 2026-11-02** (operator-approved scoped reconciliation;
backup `data/kalshi_order_attempts.db.p3pre_20261102T005449Z`, integrity ok):
414 applications + 2 attribution corrections + 2 dup-skips. Second run: **0
mutations** (416 dedup-skipped). Post-state: FILLED 330→392,
EXCHANGE_CONFIRMED_FLAT 2, cq populated on 389 attempts (was 0), events
6315→6731, `cq>rq` 0, nonterminal results 0, unresolved FILLED claims 0
under reviewed matching. 7 FILLED attempts remain cq-NULL by design (5
ambiguous-intent multi-attempt intents + 2 test-era rows — flagged, not
mutated). Reports: `_p3_apply_prod1.txt`, `_p3_apply_prod2.txt`,
`_p3_plan_pre.txt`, `_p3_apply_detail.csv`.

## Repair queue (frozen policy)

1. Decision→disposition traceability: every sell signal gets a durable
   disposition (approved/suppressed+reason/superseded/error); signals link to
   existing obligations, not new ones per tick.
2. Retry storms + uncertain submissions (bounded retries, tracked unknowns).
3. Ledger→FSM fill back-propagation (replay-safe, exactly-once completion).
4. The 9 FSM-only fill claims (verify or reclassify).
5. Attribution spine (decision→intent→order→fill→episode).
Acceptance: suppression visibility, approved-signal obligation linkage,
sibling-fill exactly-once, replay idempotence, restart reconcile of open
obligations. Historical backfill = dry-run discrepancy report first; corrections
traceable, original events preserved.

## Errata log (for future readers)

- v1 scorecard priced entries at settlement → superseded by round-trip
  accounting (episodes).
- Leg-price misread (episodes keyed by traded leg) split round-trips → fixed
  via `proceeds_dollars` + signed-YES residual.
- Settlement pseudo-fill `pro` double-counted → excluded.
- Long-NO residual sign bug → `abs(resid)`; totals reconciled to the cent.
- `-` attempt lane = exits; `-` episode lane = unverifiable provenance — different
  meanings, do not conflate.
- PERSISTED ≠ lost orders (0 exchange IDs, 0 updates, ~4.3× row inflation).
- Attempt counts ≠ obligations (1.96× on exit FSM; up to 130× on one).
- Suppressed-share 92%→89.7% after exact primary-disposition selection.
- Sell-signalled-no-obligation count 2→37 after coverage-era correction;
  most are pre-FSM-logging (unobservable), not verified dropped signals.

## P4-PAIRS � dual-representation ledger rows (read-only, 2026-11-02)

Population: 24 `live_router_*` rows (schema v0, `trade_id=None`, `ingestion_source=order_router`,
fill_id = `live_router_<order_id>_N` � router-minted provisional mirrors, not exchange identity).

### Economic-event identity (exchange trade_id is the discriminator)

| Class | Rows | Evidence |
|---|---|---|
| Confirmed duplicate � same-second twin | 18 | venue twin on same order_id, same qty/second/delta |
| Confirmed duplicate � aggregate mirror | 4 | canonical partials sum to mirror qty (98+1+1=100; 90+10=100), <=2s apart |
| Ambiguous � side-conflict | 1 | `live_router_01a0d3ae-a040-70bf` (XRP-241000): venue `sell no` +90/+10 vs mirror `buy no` -100; direction contested, needs order submission payload |
| Unpaired provisional | 1 | `live_router_01a0da6e-97a0-7c36` (XRP-251730): `unmatched=1`, no venue twin |

Same-second canonical+canonical groups (13) are GENUINE partial fills �
distinct exchange trade_ids, ms-distinct created_time. trade_id, not
(order_id,qty,second), is the correct economic key.

### Consumer trace

CLEAN: `_replay_market_position`, `_prior_signed_yes_cc`, `_closing_segment_pnl`,
`get_canonical_fills` + `unresolved_router_fills` consumers (fills_poller /
kill_switches / order_intent_contract) � all gate on `_fill_position_effective` /
`_is_superseded_live_router_fill`.

POLLUTED (no superseded filter):
- `_market_fill_totals` -> `get_market_realized_pnl` (post-loss cooldown input)
  and `get_market_residual_yes_cc` (settlement_poller residual vs exchange).
- `summary()` -> kalshi_ledger_metrics -> JSON/API/Prometheus; kalshi_risk,
  risk_guard, kill_switches, loop, portfolio_reconciliation, status_snapshot.
  Fees +$0.36 total; realized PnL + mirror proceeds on the 22 markets.
- `analysis/calibration_report.py` � raw GROUP BY market_ticker.
- `decision_audit_ledger._capital_realized_from_fills_db` � trust-state filter
  passes the mirrors (they carry TRUSTED_LIVE_V1).
- `logs/exit_counterfactuals.jsonl` � e.g. cf-747d51e46919: exited_qty 1.99 vs
  true 1.00, exit_proceeds 197c vs true ~99c, delta +196c vs true ~+99c.
- `logs/bankroll_reconciliation.jsonl` settlement triggers (e.g. XRP-182230
  realized_pnl -137/-256c vs true market rt +7.2c).
- Audit episode assembly (`_audit_categories`, `_audit_final_join`).

### Benchmark bridge (799 settled episodes, cents)

| Metric | A as-reported | B canonical-only | delta |
|---|---|---|---|
| Actual net P&L | -2802.1 | -4554.1 | -1752.0 |
| Hold-to-settlement | -3320.3 | -3471.3 | -151.0 |
| Exit-policy delta | +518.1 | -1082.9 | sign flip |
| fully_exited | 461 | 482 | +21 |
| partial_exit | 25 | 4 | -21 |
| no_exit | 313 | 313 | 0 |

The reported "+5.18 exits beat holding" was a mirror-row artifact: exit-side
mirrors added phantom proceeds AND phantom residual settlement payouts
(+100cc sval on winning markets) to the actuals side only. Deduped, recorded
exits underperformed hold-to-settlement by ~$10.83 over the window. The -$28.02
and +$5.18 remain the "as-reported" figures; corrected figures are
-$45.54 / -$34.71 / -$10.83 pending the two flagged rows (d3ae, cb89).

### Selection rule + correction boundary (proposed, not applied)

Economic event = authoritative venue row. A `live_router_*`/`order_router` row
is observability-only iff its order_id has >=1 non-mirror fill (existing
`_is_superseded_live_router_fill` semantics); aggregate mirrors match when
canonical partials sum to mirror qty. Retains all genuine partials (13
retracted groups prove). Correction = consumer-side canonical-view filtering,
NOT row deletion; `_market_fill_totals` + `summary()` + calibration_report +
decision_audit capital-realized are the required fix sites. Regression
fixtures: canonical-view exclusion test; 22-market episode fixture asserting
resid=0; `_market_fill_totals` superseded-exclusion test; exit_counterfactuals
schema fixture asserting exited_qty/proceeds canonical-only.

### P4-PAIRS addendum � identity resolutions + contract rehearsal (2026-11-02)

- `cb89` = `da6e`: same record (`live_router_01a0da6e-97a0-7c36`, intent
  `intent_cb8988351ed54f3b96aa4f23dbf8714a`). Label collision only � one record.
- `d3ae` RESOLVED to side-conflict, quarantined BOTH sides: bankroll_reconciliation
  order-ack records show order `01a0d3ae` was submitted **buy no @72c** (mirror
  direction correct); venue fills `07239d14-*` recorded `sell no @70/69` with
  complement-priced cash (-31.58c ~ YES-leg prices). Canon rows are corrupt on
  side, delta sign, and cash for this order. Market rt ranges: as-reported -45.3c /
  canon-only +58.3c / order-ack truth ~ -12.6c. Pending order-ack-level truth.
- `da6e` (XRP-251730): unpaired provisional stays REPORTED-SEPARATELY � market
  has zero verified rows; -66c if execution was real, 0 if phantom.
- Contract classification reconciles: 1416 verified_venue + 346 non_execution
  (settlement) + 22 mirror_matched + 3 side_conflict + 1 unpaired = 1788 rows.
  ingestion_source census: http_poller 1417, settlement_rest 346, order_router 24
  (all live_router_*), websocket 1. Zero duplicate venue trade_ids.
- P3 cross-check: applied fill_ids on every pair market are canonical venue ids;
  mirror ids appear only as sibling flags. P3 stays closed.

**Final bridge (strict contract view, unrounded):**
  rt -2802.15c -> -4384.53c; hold -3320.26c -> -3301.68c;
  exit delta +518.11c -> -1082.85c; partial_exit 25 -> 4; fully_exited 461 -> 482;
  eps 799 -> 798 (da6e market has no verified rows).
  Resolution range: -$43.85 floor; ~-$44.6 if d3ae settles at order-ack truth;
  ~-$45.2 if da6e execution was also real.

**Fixtures**: `_test_p4_canonical.py` 29/29 pass (mirror-twin, aggregate partials,
partial coverage, genuine same-second fills, trade_id dedup, side-conflict
quarantine, unpaired provisional, late supersession, replay idempotence,
settlement exclusion).
**Patch draft**: `_p4_patch_draft.md` (4 sites + downstream trace; not applied).

### P4-PAIRS exchange-settlement resolution (2026-11-02, post-5a227a0c)

`GET /portfolio/settlements` records pulled for both flagged markets (exchange
order records 404 — expired orders are purged; the settlements feed retains the
position/cost-basis snapshot). Both episodes are now RESOLVED at exchange truth:

- **`d3ae` (`KXXRP15M-26SEP241000-00`)** — settlement 14:00:08Z:
  `market_result=yes`, `yes_count_fp=1.00` cost $0.40, **`no_count_fp=1.00` cost
  $0.699**, fees $0.0316, payout $1.00, revenue 0. The account held a fully
  hedged 1-YES + 1-NO pair at settle. Cost basis confirms the entry fills were
  economically **buy-NO 0.9@70 + 0.1@69 = $0.699** — the order-ack (`buy no
  @72c`) and the `live_router_*` mirror were directionally correct; the venue
  fills' `action`/`side` labels were inverted and the local proceeds were
  complement-priced (−31.58c booked vs −69.9c true). The second fill
  (`buy yes 1.0@40c`, −41.68c) was a hedge-add, not a close. **Episode P&L at
  exchange truth: −13.06c** (paid $1.099 + $0.0316 fees, received $1.00).
  Note: net-delta canonical model cannot represent a hedged pair (resid=0 while
  the pair paid $1.00) — this episode requires explicit settlement-evidence
  payout, recorded here.
- **`da6e` (`KXXRP15M-26SEP251730-30`)** — settlement 21:30:08Z:
  `market_result=yes`, `yes_count_fp=0`, **`no_count_fp=1.00` cost $0.64**,
  fees $0.0162, payout $0. Held 1.0 NO into a YES resolution. Exchange fills
  feed contains the missing venue fill `0723b3d4` (`order 01a0da6e`,
  `sell no 1.0@64c` — same inverted-label family; economically buy-NO @64c,
  matching the mirror). The venue fill was **never ingested locally**
  (2026-09-25 fills-poller gap). **Episode P&L at exchange truth: −65.62c**
  realized loss — the execution was real, not phantom. The local zero-payout
  settlement sweep was consistent with venue view.

**Verified cohort plus two resolved episodes (not complete account truth):**
−4384.53c −13.06c −65.62c = **−4463.21c ≈ −$44.63** vs prior verified-only
−$43.85 and the pre-contract polluted figure −$28.02. This arithmetic does not
resolve the other exclusions or coverage gaps and is not a bound on the full
account result. Both were buy-NO entries
that lost (one via hedge-lock, one at settlement) — consistent with the
losses-in-NO-side/no-exit concentration finding.

Systemic finding: **September-era venue fill records can carry inverted
`action`/`side` labels.** Settlement cost basis + order-ack payload + mirror
direction are the tiebreakers. The side-conflict quarantine caught exactly this
class. Backfill candidates (evidence-preserving, marked
`ingestion_source=fills_poller_gap_backfill`): da6e venue fill `0723b3d4`;
d3ae entry fills' delta/proceeds correction remains a projection-layer concern,
not a raw-row rewrite — raw rows stay as ingested, truth lives in this record +
the versioned canonical rebuild manifest.

## Runtime-state test contamination (2026-11-02)

An exit-regression pytest run at 10:26:33 ET passed string paths to
Path-based temporary stores. Their error handlers wrote test-generated
`EXIT_STATE_CORRUPT` and `EXIT_ATTEMPTS_CORRUPT` halt events to the production
`data/live_runtime_state.json`. Its bounded recent transition history was
overwritten. The server had already halted entries at 09:54:47 ET after a
reconciliation failure; that transition remains in the server log. Production
exit-state and exit-attempt JSON files parsed successfully, and the server log
did not show the test-generated corruption events.

The persisted runtime-state file was not restored or cleared. The test
fixtures now use Path objects and isolated runtime-state files; subsequent
focused tests verified that the production runtime-state file did not change.
These observations do not establish that all recovery prerequisites are met.

At 10:40:28 ET the running process repersisted its own in-memory halted state,
replacing the test-generated on-disk reasons with reconciliation-failure
reasons. This does not establish that every earlier transition was recovered.

## Live audit maintenance and log lag (2026-11-02)

The old running build attempted automatic audit-ledger pruning at 05:20,
08:20, 09:20, and 10:20 ET; each attempt logged `interrupted`. No successful
batch-removal message was found in that server log, but these logs alone do not
prove historical completeness or exclude earlier deletion. The live writer
scheduled pruning by default; commit `ddbba3c8` removes that schedule and uses
non-waiting PASSIVE checkpoints. It does not delete or restore any records and
is not deployed to the old process. A further 11:20:33 ET attempt also logged
`interrupted`; the old process can attempt pruning again.

At 11:10 ET the asynchronous log writer reported a queue depth of 9,712 and
zero recorded drops, while a recent record showed 164 seconds of drain lag.
Event timestamps, not file modification or drain times, must be used when
judging freshness. Disk free space was approximately 448 GiB at that time;
PASSIVE checkpoints may retain the WAL file's high-water size and continued
disk monitoring is required.

## WebSocket snapshot and precision findings (2026-11-02)

The old running build drops Kalshi's documented nested
`yes_dollars_fp`/`no_dollars_fp` orderbook snapshots in its parser. Commit
`d1d14650` accepts those snapshots, applies their subscription sequence,
invalidates sibling books on gaps, and rejects stale replay. An empty or
one-sided WS snapshot cannot be replaced by an older REST quote. The new build
is not deployed and does not establish that the feed storm is resolved.

The local book stores whole-cent prices and whole-contract depth; fractional
prices or quantities are not safely represented. The committed safety gate
blocks entries for an affected ticker until a representable WS snapshot
arrives; exact fractional book support remains necessary. This is not a
complete feed solution.

The old running build treats a local state as `ws_subscribed` and discards
sequenced `ok` frames. Commits `2aba0f72` and `6db3637f` forward sequenced
controls, require a current-connection SID acknowledgement and per-ticker
orderbook traffic for subscription readiness, and recheck that evidence for
live entries at the router. These changes are not deployed. A single matched
snapshot does not prove live subscription health or runtime recovery.

## Test log contamination (2026-11-02)

Test subprocesses run during this audit used isolated runtime-state and
database paths but the shared logger still appended to the running server's
`logs/full.log` and `server_output.log`. For example, the
`NOT_ACCEPTED_CONFIRMED -> RESTING` transition for synthetic `attempt-1`
logged at 12:03:35 ET came from a test, not a production exit. Other synthetic
records may be interleaved, including records with test-clock timestamps;
the affected range is not fully enumerated. Neither shared log was edited or
removed. Exclude identifiable test events from operational counts, but do not
assume every event in the interval is synthetic: the server continued logging.

The logger now supports an explicit `MERID_LOG_DIR` override for both log
handlers; further tests should set it before importing application modules.
The running process was not restarted. At 12:06 ET it remained halted on
reconciliation failure while the Kalshi circuit was open.

## Order recovery follow-up (2026-11-02)

Local commits `5136b2e3`, `633edf92`, `159f9069`, and `a1c4e812` retain
uncertain order outcomes and reservations, prevent an unresolved or working
order from being ignored merely because it is old, and preserve working
partial-fill ownership. They are not deployed. A 120-test isolated subset and
two end-to-end simulator cases for 503/transport exceptions passed with
external networking blocked and logs/databases redirected.

The larger simulator and legacy IOC run did not pass: test cases reused
durable order identities across cases, and several assertions expect the old
partial-fill or zero-fill IOC classifications. A separate older test file
still uses the removed whole-contract dedup API and assumes a one-contract
limit that is not the current configuration. These failed runs must not be
reported as passing.

An unresolved safety issue remains in the post-only reprice and maker-to-taker
retry paths: their new wire client-order IDs are not durably bound to their
own attempt before dispatch, and the conversion path can discard its retry
failure result. A later ambiguous retry must not be reconciled using only the
original ID. This requires repair and independent validation before deployment.
The resting-order monitor also has whole-contract fields, so fractional working
remainders require further end-to-end review. The running old process remained
halted at 12:37 ET on a Kalshi circuit-open reconciliation error.

### Subsequent local retry repair

Commits `7a9c1e0a`, `562a27ab`, and `0da71e0b` add durable replacement
chains, route retries with freshly claimed wire IDs, preserve failed retry
responses, and reconcile/attribute by the actual child ID. The 109-test
isolated subset includes a simulated exit conversion followed by either a
503 or a transport exception. It does not yet cover every entry-reprice,
successful-conversion, duplicate-ID, cancellation, or crash window; do not
deploy until those cases and the broader suites are independently validated.

Further audit finding: `_resolve_exchange_confirmed_flat` accepts a successful
position response without verifying all pagination/provenance and currently
coerces invalid quantities to zero. Flat inventory alone also does not prove
that an unresolved live order cannot subsequently execute. Replacement
attempts with unresolved wire status now retain their lock rather than use
that flat shortcut, but the general flat-resolution path needs a fail-closed
repair and dedicated tests before restart.

Follow-up commits `9b8f441b` and `c95bd070` address those findings locally:
filtered position pagination now fails on partial or malformed responses, and
flat resolution requires an authoritative terminal-market response plus a
complete, valid zero-position snapshot. Fifty-one isolated tests passed.
These fixes have not been deployed or verified against a fresh live snapshot.

The separately isolated exit-order simulator suite now passes after its
per-test durable store was isolated and obsolete assumptions were corrected:
a working partial order is not fully filled, an empty post-timeout lookup is
inconclusive, and a terminal IOC must have explicit cancellation evidence.
The focused simulator, fractional-ownership, and submission-certainty run
passed 40 tests. The previously failed broad router/repricing run has not yet
been rerun cleanly and must not be counted as a pass.

Further local commits `d3e6d091` and `10347cdf` retain the logical gate on
duplicate responses, preserve exact fractional working fills, reject
unsupported quantity precision without releasing ownership, and preserve the
original requested quantity when IOC remainders are canceled. The resting
order monitor still uses whole-contract fields; fractional working remainders
need a separate repair and end-to-end tests.
