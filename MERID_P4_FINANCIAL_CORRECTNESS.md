# P4 — Financial Correctness Workstream (2026-11-02)

Correctness only. No exit-policy changes, no exposure changes, no deletions.
Coordinates with P2 (retry handling) and P3 (ledger→FSM reconciliation): P3
fixes state propagation; P4 verifies that everything downstream of state
computes the right money. Frozen at commit `a18f5d60` + P1 disposition changes.

## 1. Metric dictionary (draft — authoritative definitions)

| Metric | Definition | MERID source field(s) | Open questions |
|---|---|---|---|
| Realized trading P&L | P&L on closed/settled exposure under a documented cost-basis method | `kalshi_fills.proceeds_dollars` (signed cash, **net of fee** per schema line 771 + code comment L4707); episode residual settled at `resolved_yes` | Cost-basis method for multi-entry partial exits — FIFO vs average — must be documented where computed |
| Unrealized P&L | Marked value of remaining inventory − remaining cost basis | `_recompute_unrealized_pnl` in fills_ledger; `unrealized_pnl_cents` on Position | Mark source (own-side bid vs model fair) must be uniform per surface |
| Total trading P&L | realized + unrealized, fees handled once | derived | Verify no consumer adds `fee_cost` again after `proceeds_dollars` |
| Cash balance | Actual cash, not profit | Kalshi `balance_dollars`/`balance_breakdown` (exact strings, never truncated `balance`) | Per-shard vs total — shard 2 only can collateralize |
| Available cash | Cash after reservations | bankroll_service_v2 / risk reservations | Reservation lifecycle audit |
| Account equity | cash + marked positions + other items reconciled | portfolio_pnl_computer / canonical_portfolio | Verify mark method |
| Net contributions | deposits − withdrawals, not trading revenue | venue balance events | Needed to keep transfers out of P&L curves |

**Episode reconciliation (frozen):** `net_episode_pnl = Σ proceeds_dollars (non-settlement rows) + residual canonical_yes_delta_cc × settlement_outcome`. Settlement pseudo-fills (`liquidity_role='settlement'`) carry no cash — excluded from cash, used only to extinguish residual. `proceeds_dollars` already nets fees; subtracting `fee_cost` again double-counts.

## 2. Source-of-truth map

- **Execution truth:** `data/kalshi_fills.db` (`kalshi_fills`) — trusted ledger,
  canonical fields preferred; `TRUSTED_LIVE_V1` canonicalization required for
  accounting fields. `proceeds_dollars` may be repaired post-ingest
  (`FILL-PROCEEDS-REPAIRED`, original preserved at `proceeds_dollars_at_ingest`).
- **FSM ≠ cashflow:** `exit_order_attempts` describes lifecycle only; it must
  never mint P&L (9 FSM-only `any_fill` claims remain unresolved — no cash
  recognized from them).
- **Settlements:** `settlement_outcomes.jsonl` `resolved_yes` per ticker +
  settlement pseudo-fills in ledger.
- **Cash:** Kalshi REST `balance_dollars`/`balance_breakdown` exact strings.
- **Shadow/eval records are not trades:** `exit_evaluations.jsonl`,
  `signal_disposition` records (`observe_only`) carry no financial weight.

## 3. Ingestion completeness (initial findings)

- Pagination is fail-closed: `canonical_portfolio._collect_paginated` raises
  `PaginationIncomplete` on cursor loops/malformed pages; `client.get_fills`
  marks `truncated` on partial failure. ✓
- **FINDING P4-1: no `historical/*` endpoint consumption.** Only
  `/portfolio/fills` + `/portfolio/settlements` are fetched. Kalshi migrates
  older fills to historical storage and `/settlements` does not return
  archived records — fresh backfills and re-verification are bounded to what
  the live endpoints still expose. Durable ledger rows persist, so this
  affects rebuild/re-verify completeness, not existing rows.
- **FINDING P4-2: `proceeds_dollars` is net-of-fee.** Any consumer that adds
  or subtracts `fee_cost` from a proceeds-based sum double-counts. Audit all
  `total_fees += fill.fee_cost` sites for whether their total is then applied
  to a net figure (fills_ledger L4134, L4671, L5108 `net_cost = total_cost +
  fee_cost` — L5108 adds fee to a *gross* cost path; verify each site's base).
- Dedup across WS/poller/backfill/replay keyed by fill identity with
  out-of-order tolerance — ✓ per comments at L2190/L2656.

## 4. Consumer map (by grep density — full verification pending)

| Surface | File | Hits | Risk |
|---|---|---|---|
| Ledger producer | `fills_ledger.py` | 148 | canonical |
| Risk gates | `kalshi_risk.py` | 62 | daily-loss gate correctness is live-risk-critical |
| Kill switches | `risk/kill_switches.py` | 56 | halt thresholds consume P&L |
| Position accounting | `position_cache.py` | 49 | cost basis, unrealized marks |
| Position monitor | `position_monitor.py` | 19 | telemetry + exit evals |
| API/snapshot | `backend_snapshot_fetcher.py`, `loop_15m.py` | 8 | UI feed |
| Decision audit | `decision_audit_ledger.py` | 8 | counterfactual P&L on 88% of settled NO_TRADEs |
| Portfolio P&L | `portfolio_pnl_computer.py`, `portfolio_models.py` | 36 | equity computation |
| Bankroll | `bankroll_service_v2.py`, `unified_risk_manager.py` | 18 | available-cash |
| Reconciliation | `reconciliation.py`, `venue_reconciler.py`, `bankroll_reconciler.py` | 16 | divergence detection |
| Round-trip monitor | `round_trip_monitor.py` | 7 | episode accounting — verify vs audit formula |
| Attribution | `trade_attribution_fact_table.py` | 7 | lane P&L — `legacy_identity_unverified` flag |
| UI/export | post_trade_report, golden_record_rollup, calibration_report | 14 | display semantics |

## 5. Bug register (seeded from audit + this pass)

| ID | Item | Status |
|---|---|---|
| P4-B1 | Long-NO residual sign bug (episode join) | fixed during audit — regression test required |
| P4-B2 | Raw `action` = counterparty side — consumers must use canonical fields | verified in audit; test to lock |
| P4-B3 | Shadow evals misread as trades | fixed (P1 observe_only) |
| P4-B4 | FSM state as execution truth | P3 workstream; no cashflow from FSM-only fills |
| P4-B5 | Settlement payout + residual inventory double-count | fixed in audit join; test needed |
| P4-B6 | Unknown lane attribution presented as confident | `legacy_identity_unverified` on 98% of fills; UI/learning must not force lane names |
| P4-B7 | `historical/*` endpoints unconsumed (P4-1) | open — bound re-verify/backfill completeness |
| P4-B8 | Fee double-subtract risk on `proceeds + fee_cost` consumers | **cleared at L5108** — `net_cost = gross(price×qty) + fee`, export-only column; continue per-consumer audit for other sites |
| P4-B9 | Missing price/fee/outcome → silent zero | open — inventory `or 0`/`or Decimal(0)` coercions on financial fields |
| P4-B10 | `trade_attribution_fact.db` intent spine gap (1 intent row for 581 fills) | open — P5 |
| **P4-B11** | **kill_switches `fills_canonical` fallback counts entry spend as realized loss** — `Σ proceeds_dollars` over ALL of today's live fills (`kill_switches.py:551`), no `closed_markets` filter; open-position cost basis registers as daily loss until close. `summary().daily_realized_pnl` has the correct filter (L4693). Operational effect: **false entry blocks** whenever the session snapshot is unavailable. Role in the 131 `DAILY_LOSS` blocks: **strong hypothesis** — requires replaying fallback activations from logs, not yet proven causal. | confirmed defect; causal role hypothesized |
| **P4-B12** | **Three daily-loss definitions, three windows:** kill_switches session path = realized-pnl since *process start* (restart = mid-day window reset + yesterday's losses vanish); kill_switches fills path = cash-flow since midnight UTC (B11); kalshi_risk = equity-decline from first-call-of-day (`_update_daily_loss_tracking`, restart re-anchors). Operational effects differ per path: missed block, false block, both. | confirmed defect (semantics) |
| **P4-B13** | **Restart re-anchoring — narrowed:** `start_of_day_equity` (kalshi_risk) re-anchors on first call after restart; `session_snapshot` window = process start (restart resets + drops prior-day realized). The `fills_canonical` path does NOT re-anchor: `_daily_loss_start_ts` is recomputed as that day's midnight UTC on each check (kill_switches.py:508), so its historical coverage is restart-independent. | confirmed for session/equity paths only |

## 5a. Daily-loss gate dependency chain (documented 2026-11-02)

Effective state: **all three gates are currently disabled** —
`kalshi_risk._check_daily_loss_limit` skipped by `MERID_LOSS_BRAKES_ENABLED=0`
(tracking only); `kill_switches` DAILY_LOSS `daily_loss_enabled=False`
(profile loader `get_profile_daily_loss_limit()` unconditionally returns
`(None, False)` at kill_switches.py:112 — the "load during startup" path does
not exist); the kalshi_risk `_log_breach("daily_loss_limit")` at 2227 is
inside the same loss-brakes-gated tracking path.

Chain by source:
1. `agent_grid_15m.get_pnl_snapshot().session_realized_pnl_dollars`
   (preferred; `pnl_source="session_snapshot"`) — realized-only via
   `fills_ledger._session_realized_pnl` (`+=` on close/settlement events at
   L6845/6914/7123) — **window = process start, not calendar day** (B12/B13).
2. `ledger.get_canonical_fills(since=_daily_loss_start_ts)` →
   `Σ float(f.proceeds_dollars or 0) for f.is_live` (`pnl_source=
   "fills_canonical"`) — **cash-flow basis, B11**; correct window
   (midnight UTC at kill_switches.py:508); correctly excludes synthetic
   `live_router_*` rows and tracks `unresolved_router_fills` count
   (positive: unresolved ≠ zero-loss).
3. `self._daily_pnl` (manual `record_pnl` accumulator) — silent fallback
   when both live sources fail; an unknown presented as a number (B9-adjacent).
4. `kalshi_risk` gate: `max(0, start_of_day_equity − equity)` + per-order
   `order_worst_case_loss` — equity-decline semantics incl. unrealized marks;
   also exposed to deposit/withdrawal masking if equity isn't adjusted.

`summary().daily_realized_pnl_usd` (API surface) is **correct**: filters to
`closed_markets` (position_cache-derived, Kalshi-REST-synced) before summing
net proceeds (L4690-4724) — open-position spend never counts; day boundary
midnight UTC; strict-mode derived-fill exclusions logged.

## 6. Regression suite (fixture list — to build)

YES/NO win+loss settlement; profitable/losing early exit; multi-entry +
partial exit; residual settling post-partial; close+reopen same market;
fractional cc; varying fees; duplicate/delayed/out-of-order fills;
sibling-attempt fill; FSM-only fill claim; live→historical migration;
midnight boundary; deposit/withdrawal; missing mark/unresolved settlement.
Each asserts: cash, inventory, remaining basis, realized, unrealized, fees,
API result. Benchmark: **−2,802.15¢ over 799 episodes** must reproduce or be
explained event-by-event — never force-matched.

## 7. Acceptance criteria (unchanged from brief)

Metric dictionary + source-of-truth map (this doc, to be finalized);
bug register; reproducible before/after diffs; passing fixtures + ingestion
replay; backend↔UI agreement on same snapshot; risk/learning consumers
migrated; unresolved discrepancies surfaced explicitly — never balanced
away silently.

---

## 8. P4 implementation + rehearsal status (2026-11-02)

### Production-owned shared contract
`merid/event_venues/kalshi/canonical_fill_view.py` � `CANONICAL_CONTRACT_VERSION = "canonical-fill-view/1.0"`.
Classes: `verified_venue | mirror_matched | mirror_partial | side_conflict | unpaired_provisional | non_execution`.
Mirror matching requires: same `order_id`, same market, same subaccount scope, consistent signed position effect,
and full venue quantity coverage � not merely "same order". Trade identity dedups on exchange `trade_id`
(never `order_id`+qty+second: genuine same-second partials are preserved). Side conflicts quarantine ALL rows on
the order. Unpaired provisionals are excluded but reported with explicit coverage status.
`_audit_p4_canonical.py` delegates to the module (audit scripts and production consumers share one code path).

### Patched consumers (all on the shared contract)
1. `fills_ledger._market_fill_totals` � authoritative-only; feeds `get_market_realized_pnl` (cooldown) and
   `get_market_residual_yes_cc` (settlement reconciler). Settlement pseudo-fills are `non_execution`: excluded
   from proceeds+residual (residual�outcome re-derives payout; including their sweep delta erased it � this was
   a second live bug found by the integration check: post-settlement residuals read -held instead of the
   execution residual).
2. `fills_ledger.summary()` � skips excluded/provisional rows for fees and realized PnL; settlement rows still
   count cash. Exposes `canonical_contract_version`, `excluded_fill_count`, `provisional_fill_count`,
   `non_execution_fill_count`, `provisional_fees_usd`.
3. `analysis/calibration_report.load_fill_pnls` � excludes mirror/conflict/unpaired rows + duplicate venue
   trade_ids via the module.
4. `execution/decision_audit_ledger._capital_realized_from_fills_db` � trust-state filter plus canonical
   contract filter (mirror rows carry TRUSTED_LIVE_V1 and previously passed).

### Coverage propagation
New accessor `fills_ledger.get_market_accounting_coverage(ticker)` returns
`verified_record_count / coverage_status / excluded_record_count / provisional_record_count /
non_execution_record_count / exclusion_reasons / canonical_contract_version`.
Statuses: `verified_complete | verified_with_excluded_mirrors | incomplete_coverage | provisional_unverified |
conflict_quarantined`. `settlement_poller` gates `local_history_complete` on coverage status � a computed zero
residual over a quarantined/provisional population can never read as verified-flat.

### Load-path preservation fix (pre-existing destructive behavior found by rehearsal)
`load_from_db` called `_delete_stale_live_router_rows`, which ran `DELETE FROM kalshi_fills` for every matched
live_router_* mirror on every startup � including the d3ae conflict mirror (its order has venue twins). The next
production restart would have permanently deleted 23 raw evidence rows. Now: mirrors are moved to an in-memory
`_superseded_mirror_fills` quarantine (never DB-deleted), kept visible to conflict detection and coverage; the
live ingest suppress path (`_suppress_duplicate_live_router`) also retains suppressed mirrors there.

### Verification results
- `_test_p4_canonical.py`: 29/29 fixtures pass (all 8 required cases + trade_id dedup + settlement exclusion +
  replay idempotence).
- `_audit_p4_integration.py`: 19/19 checks pass � census reconciles (1416/346/22/3/1 = 1788), zero corrected
  residuals on all 22 mirror markets, coverage statuses on ambiguous markets, contract-version + coverage-field
  propagation, live-ledger end-to-end on temp copy (summary counts excluded=25/provisional=1/non_exec=346,
  residuals clean, conflict/provisional statuses correct).
- `_audit_p4_rehearse.py` through the production module: A reproduces -2802.15c/+518.11c exactly; C gives
  -4384.53c/-3301.68c/-1082.85c over 798 episodes.

### Verified-only regression targets (explicit exclusions; NOT complete account truth, NOT a bound)
- Actual P&L: **-4,384.53� (~-$43.85)**; hold benchmark: **-3,301.68� (~-$33.02)**; exit delta: **-1,082.85�
  (~-$10.83)**; episodes: **798**; contract `canonical-fill-view/1.0`.
- Excluded from this snapshot: 22 matched mirrors, 3 side-conflict rows (order `01a0d3ae`, market
  KXXRP15M-26SEP241000-00 � quarantined, both representations held), 1 unpaired provisional (`01a0da6e` /
  intent `cb898835`, market KXXRP15M-26SEP251730-30).
- Complete-historical-accounting target stays pending until d3ae execution/account-position truth and da6e
  real-vs-phantom are resolved.
- Episode partition reconciliation: A={fully_exited 461, partial_exit 25, no_exit 313}=799;
  C={fully_exited 482, partial_exit 4, no_exit 312}=798. The da6e market was a `no_exit` episode under A
  (provisional buy, residual held) � it drops out under C (zero verified rows): **no_exit 313?312**.
- 21 of 25 A-partial_exits were phantom residuals on actually-flat markets; KXSOL15M-26SEP190100 stayed
  no_exit but corrected -64.0c.

### Expected live-decision changes on deployment (policy config unchanged)
- Cooldown inputs (`get_market_realized_pnl`) correct on 22 markets; worst mask: KXXRP15M-26SEP182230 reported
  +157.2c vs true +7.2c; KXSOL15M-26SEP210915 reported +162.4c vs true -29.6c � post-loss re-entry cooldown
  would have fired under corrected values where it did not historically. Behavior change is in INPUT values,
  not thresholds.
- Settlement reconciler: 23 phantom �4�100cc residuals no longer generated ? stops false `settlement_mismatch`
  candidates; conversely d3ae/da6e markets now report `local_history_complete=False` instead of false-flat.
- `summary()` totals: fees -$0.37 (mirror fee double-count), realized PnL removes mirror proceeds.

### Deployment / refresh / rollback (proposed � production held)
- Deploy: code-only read-path patch; no DB migration, no row deletion. Requires a controlled restart because
  `_fills`, `_superseded_mirror_fills`, position cache and every downstream projection hydrate at load � there
  is no live cache-invalidation path. Restart must be scheduled with positions protected (preflight sequence
  unchanged); do NOT restart into unmanaged open positions.
- After restart verify: `_audit_p4_integration.py` ledger checks green; `summary()` contract fields present;
  residuals on the 22 markets = 0; d3ae=conflict_quarantined, da6e=provisional_unverified; cooldown input diffs
  match the rehearsal table.
- Rollback: revert the patch AND restart again � in-memory projections (position cache, summary counters,
  cooldown history) carry values computed under whichever contract loaded them; reverting code alone leaves
  newer-contract values live. The DB is untouched by the patch, so no data rollback is needed; the former
  DELETE behavior is not restored automatically (rows simply remain � harmless, classified as telemetry).

### Remaining blockers before deployment sign-off
1. d3ae: exchange order record / account-position evidence to resolve sell-NO@70-69 venue fills vs
   buy-NO@72 submission. Until then the market is quarantined from authoritative totals.
2. da6e: balance/position evidence for real-vs-phantom (-66� if real).
3. Learning-artifact eligibility manifest + regeneration (14 exit_counterfactuals records, 468
   bankroll settlement-trigger records, per-market calibration on 22 markets, decision-audit capital-realized
   lots) � preserved originals, versioned rebuild; not silently overwritten.
4. API/UI/Prometheus surface verification post-restart (metrics exporter reads `summary()` � new fields flow
   automatically; UI agreement to be confirmed against identical filters).
