# Exit Reliability & Fill Accounting Repair — 15m Kalshi Scalper

**Date:** 2026-10-09 — **Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute scalping stack.
Exit chain (monitor → stop candidate → intent contract → router) and fills-ledger
proceeds accounting.
**Companions:** `AUDIT_2026_10_09_EVIDENCE_POLICY.md`,
`AUDIT_2026_10_09_SUSPENSION_PROBATION.md`,
`AUDIT_2026_10_08_EXPECTANCY_LOSS_CONTAINMENT.md`.

This release is scoped as an **exit-reliability and accounting repair** — not a
threshold-tuning release. Three-contract scaling and broader entry relaxation
remain deferred until the repaired paths pass under live data.

---

## 1. Session reconciliation

Eight episodes in the audited window, all five assets represented. Actual
episode P&L (corrected): **−109.0¢**; bankroll equity delta **−103.5¢**.
The ~5¢ residual is per-fill fees vs. bankroll rounding — reconciled.

| Episode | Side | Entry¢ | Actual¢ | Settled | Hold-to-settle¢ | Loss class |
|---|---:|---:|---:|---|---:|---|
| BTC 082115 | NO | ~60 | **+39.5** | no ✓ | ~+40 | — |
| XRP 082345 | YES | 73 | **+4.4** | yes ✓ | ~+27 | truncated winner |
| BTC 090445 | NO | 70 | **−71.5** | yes ✗ | ~−72 | exit-chain cascade failure |
| SOL 090745 | NO | 30 | **−23.1** | yes ✗ | ~−30 | adverse selection via escape lane |
| SOL 090815 | NO | 60 | **+8.5** | no ✓ | ~+40 | truncated winner |
| XRP 091015 | NO | ~58 | **−27.3** | yes ✗ | ~−58 | chase-to-cap entry, shallow stop |
| ETH 091045 | NO | 72 | **+10.0** | no ✓ | ~+28 | ledger recorded −18 (repaired) |
| DOGE 091130 | NO | ~64 | **−49.5** | yes ✗ | ~−64 | gapping book; stop needed 2 attempts |

7 of 8 entries were NO-side. Fill-based −109.0¢ vs equity −103.5¢ reconciles
after the ETH proceeds repair (−0.18 → +0.82 recorded, a full $1/contract
inversion).

**Payoff asymmetry confirmed but decomposed:** it is not one mechanism.
(a) TP exits truncated three positions that settled at 100 (SOL-0815 +8.5 vs
~+40 hold; ETH +10 vs ~+28; XRP-2345 +4.4 vs ~+27 — entry-side, exits sold a
YES that settled). (b) One loss (BTC-090445) ran past every protective layer
to −71.5¢ through five independent defects. (c) Stop exits on the other
losers recovered real value (SOL sold at ~7 before 0; DOGE recovered ~14;
XRP ~23) — stops are *working*, just shallow.

## 2. BTC-090445 — the cascade, layer by layer

Entry NO @70 at 08:40:32 UTC. Timeline (local UTC−4):

| t | Event |
|---|---|
| 04:41:50 | Bid hits 81 — TAKE_PROFIT triggers (target 80) |
| 04:42:04 | Order `limit=81` arrives; book bid now 79 → firewall `rejected` |
| 04:42:06 | Reconciler re-arms: `exit_retry_count=1` — **retry obligation outstanding** |
| 04:42:06+ | Every subsequent eval: `TAKE-PROFIT suppressed (below overpay floor): price=79 fair=77 floor=80` — the retried obligation was vetoed by a discretionary EV rule even though the configured TP condition still held |
| 04:42:34 | Bid collapses 56 → 54 → 46 → 38. Trail armed at +6 earlier but activation was gated on (a) current-tick profit ≥ min AND (b) an unconditional 30s delay — the profitable window had already closed |
| ~04:43 | Two HARD_STOP candidates emitted, both died pre-submission: `fetch_fresh_signed_yes_exposure` timed out (1s REST), returned `None`, and the position was treated as **flat** (fail-open) → stop silently skipped |
| 04:43–45 | 13 expiry-liquidation evals all decided BYPASS_EMERGENCY → proceed; zero orders. Settlement-guard EV hold (`net_sell ≤ p_cal`) intentionally rode to settlement — by design, and `hold_to_settlement=True` under profit_only_v1 |
| 04:45 | Market settles YES; position pays 0. −71.5¢. |

Five independent layers each failed: (1) firewall limit-vs-book race,
(2) retry obligation vetoed by the overpay floor, (3) trail dead zone,
(4) fail-open position check, (5) stop submission exceptions unobserved
(scheduled task result discarded).

## 3. Defects repaired (this release)

### `fills_ledger.py` — ingestion-order-independent proceeds
ETH-091045 entry fill ingested **115s late** (http_poller lag) while its exit
arrived in 1.4s. `_prior_signed_yes_cc` saw zero prior exposure → a covered
close was priced as a fresh mint: **−18¢ recorded for a +82¢ close**.
Attribution then cemented it as a −90¢ settlement row.

Fix: `_repair_stale_proceeds_for_market()` runs inside `_index_fill` (the
single funnel for every insert, including DB restore). For each trusted,
priced fill of the market it recomputes signed proceeds under the now-complete
fill set using canonical side/action + leg prices + replayed prior exposure,
rewrites divergent rows, stores `proceeds_dollars_at_ingest` +
`proceeds_repaired_reason` in `raw_payload`, and recomputes session P&L.
SQLite `INSERT OR REPLACE` persists repairs; restore re-indexes through the
same funnel so repairs are idempotent. (Postgres writer is a write-only
archive here — production runs SQLite; no `POSTGRES_PASSWORD` in `.env`.)

Verified: bankroll snapshots show `positions=$0.00` 1.7s after the ETH exit
fill — the venue netted the NO at 83¢; the ledger was the only thing wrong.

### `order_intent_contract.py` — verified-flat vs unknown
`fetch_fresh_signed_yes_exposure` now uses the result-typed
`get_positions_result()`: a successful complete list with the ticker absent
returns `(0, None, None)` = *verified flat*; a failed fetch leaves `None` =
*unknown*. Previously `None` conflated both and downstream `None→0` made an
unverifiable position look flat.

All callers audited: firewall returns no snapshot on `None`; the router's
exit path skips cache fallback only on verified values; the loop's reconcile
treats `abs(0)` as confirmed flat.

### `stop_candidate.py` — mandatory precedence + fail-closed
- **Fail closed:** `exchange_position_cc is None` → reject the candidate and
  log; never coerced to flat. (BTC's two HARD_STOPs died exactly here.)
- **Mandatory triggers** (`HARD_STOP`, `LOSS_CAP`, `HARD_RISK`, `EMERGENCY`,
  `EXPIRY_LIQUIDATION`, `MARKET_EXPIRED`, `HARD_PROFIT_LOCK`) bypass the
  fair-value hold — a model that thinks the contract is underpriced must not
  veto a risk obligation. `SETTLEMENT_GUARD` and `AUTO_EXIT_99C` deliberately
  remain EV-sensitive (sell-if-premium is their semantics).
- Mandatory paths still honor fresh-book, VWAP-divergence, attempt-budget,
  settlement-window, and reduce-only checks — only the EV hold is bypassed.

### `position_monitor.py` — retry obligation, trail dead zone, task observability
- **TP retry obligation:** `position.exit_retry_count > 0` (set by
  `_rearm_position_after_failed_exit`, bounded at 3 non-emergency retries)
  marks an outstanding exit obligation. While the TP condition still holds,
  the retry bypasses *only* the discretionary overpay/fair floor and is
  repriced by `_emit_exit_intent` to the **current executable own-side bid**
  — the BTC retry sells at 79 instead of dying at floor=80.
- **Trail dead zone removed:** activation is now immediate on a validated
  executable-bid crossing (the executable bid is itself the noise filter);
  armed state persists through pullbacks below the activation threshold.
  The unconditional 30s delay — which spanned BTC's entire profitable window —
  is gone.
- **Exception observability:** done callbacks on scheduled
  `maybe_submit_stop_candidate` tasks / `run_coroutine_threadsafe` futures
  log exceptions instead of dropping them as "exception was never retrieved".

### Tests
- New `tests/test_fills_ledger_late_arrival_proceeds_repair.py`: ETH inversion
  scenario (exit before entry), idempotence, lifecycle P&L after repair.
- `tests/event_venues/kalshi/test_stop_candidate.py`: mandatory bypass per
  trigger class, verified-flat vs unknown distinction, exception logging —
  one pre-existing test updated to stub the client (real creds in env made
  REST succeed and return verified-flat) and one hold test moved to a
  non-mandatory trigger.
- New monitor tests: TP reject→re-arm→repriced-retry; trail
  immediate-activation + pullback persistence.
- Three stale tests updated to the new trailing contract
  (`test_trailing_state_transitions`, `test_trailing_activation_delay`,
  `test_trailing_activation_r_from_exit_policy`) and two stale config
  assertions corrected to committed YAML (`fixed_exposure_cap_usd=3.00`,
  `max_contracts=3`) — both pre-dated this diff.

## 4. Entry-side findings (audit only — no relaxations)

| Episode | Admission | Finding |
|---|---|---|
| SOL-0745 | `evidence_cell_escape` | Maker GTC@32 filled passively 3s before collapse → adverse selection *through the escape lane* |
| XRP-1015 | taker retry | IOC@54 canceled unfilled → retry chased to ~63 under `economic_cap:64` (`marketable_posture_overrides_maker_policy`) → stopped at 23 |
| DOGE-1130 | `current_build_provisional` | Maker@68 filled 63.65 → collapse; post-flat stragglers below |

**DOGE post-flat stragglers:** the monitor kept emitting repriced exit intents
while the in-flight stop resolved. Two landed after the fill: `sell_no@7`
timed out (`route_timeout:25s` → `submission_unknown` → swept CANCELED) and
`sell_no@14` was rejected by the `price_repeat` gate. Harmless here, but a
live straggler could sell a contract the system no longer owns. Mitigation
exists (per-submit verified exposure check) but intent-level dedup on
position-exit-in-flight is the durable fix — **tracked, not yet implemented**.

## 5. Counterfactual replay — selected cohort, sparse ticks

Chronological replay over extracted monitor-audit ticks (22–30 per episode
where present; BTC-082115 has none). Fees modeled; floor IOC fills use
observed price improvement; residuals settle at outcome.

| Policy | Total¢ | Δ vs actual |
|---|---:|---:|
| actual | −109.0 | — |
| tp_first (exit at first TP touch) | −72.6 | +36.4 |
| tp_retry (this release's obligation fix) | −72.6 | +36.4 |
| tp_plus_10 (deeper target) | −78.8 | +30.2 |
| profit-armed runner | −0.9 | +108.1 |
| partial_50 scale-out | −36.7 | +72.3 |
| hold-to-settlement | −78.8 | +30.2 |

**Limits — this is selected-cohort evidence, not an unbiased experiment:**
monitor ticks exist only while positions are open (sparse after collapse),
post-exit paths unobserved, no depth history (fills assumed at bid for small
size), runner/partial credit assumes settlement on residuals, and the BTC
fix is credited inside its own incident window. The honest claim: **the
retry-obligation fix plausibly converts the BTC −71.5¢ into ≈−60¢ at the
observed 79¢ bid**, and runner-style captures look materially better on this
cohort — hypothesis-generating, not validated. Promotion requires a real
out-of-sample shadow run.

## 6. Verification status

| Suite | Result |
|---|---|
| Consolidated changed-module gate (stop_candidate + degraded_exit + fills repair + order_intent_contract + incident_replay) | **84 passed / 0 failed** |
| tests/position_management/ (whole dir) | **436 passed / 0 failed** |
| tests/kalshi_15m/ -m kalshi_15m | 92 passed, 1 pre-existing failure* |
| tests/15m_trade_path_tests/ | passed (stale config assertions corrected) |
| root fills-ledger suite | 129 passed, 1 pre-existing failure* |

\* `test_allowed_modules_do_not_trigger_error` fails on conftest-chain module
state (this diff adds zero module-level imports); `test_total_open_increments…`
is a source-grep test asserting patterns in `merid/trading/` files absent from
this workspace. `kalshi_core`/`kalshi_risk` markers deselect everything locally
— the markers are not applied in those dirs, so those CI jobs are degenerate.

The unrestricted whole-tree run is not a valid gate here: it repeatedly stalls
in an `os.walk`-based test under filesystem contention (11.7GB decision DB,
live process running). The canonical gate is the sliced CI workflow in
`.github/workflows/kalshi-15m-ci.yml`.

## 7. Deferred / not promoted

- Three-contract scaling and entry relaxation — deferred until repaired paths
  prove out live.
- Runner / partial scale-out policies — replay is selected-cohort only;
  requires depth-aware shadow before any promotion.
- Intent-level dedup for post-flat exit stragglers (DOGE-1130 finding).
- Explicit retry-reason tagging (a stop retry technically also bypasses the
  TP floor today; harmless at the current retry cap but worth tightening).
- Postgres writer does not persist `proceeds_dollars` — pre-existing gap,
  irrelevant while production is SQLite; fix before any PG migration.
