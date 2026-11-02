# P4 Release Notes — canonical-fill contract (controlled deployment)

**Release commit**: `67cec276d3299253f866022904cfce75c4b0e820` (main)
**Canonical contract version**: `canonical-fill-view/1.0`
**Date**: 2026-11-02 ~02:00 local
**Deployed tree note**: working tree = release commit + ~692 lines of pre-existing
uncommitted changes in `order_attempt_store.py`, `settlement_aligned_exit.py`,
`stop_candidate.py`, `loop_15m.py`, `position_monitor.py` (incumbent in-flight code
the previous production instance ran — NOT part of the reviewed release scope).

## Scope

- `merid/event_venues/kalshi/canonical_fill_view.py` — shared classification
  contract. Classes: `verified_venue | mirror_matched | mirror_partial |
  side_conflict | unpaired_provisional | non_execution`.
- `fills_ledger.py` — `_market_fill_totals` + `summary()` filtered to the
  contract; `get_market_accounting_coverage()` added; settlement rows are
  `non_execution`; stale mirrors quarantined to `_superseded_mirror_fills`
  (never DB-deleted); live suppress path retains mirrors as telemetry.
- `settlement_poller.py` — `local_history_complete` gates on coverage status.
- `calibration_report.py`, `decision_audit_ledger.py` — same contract filter.
- Not included: ledger rewrite/deletion, learning rebuild, exit-threshold
  change, stop-loss activation, loss-gate activation, exposure change.

## Settlement accounting distinction (consumer contract)

Settlement pseudo-fills (`liquidity_role='settlement'`, `fill_id` prefix
`settlement:`) are **cashflow records, not executions**:

- `summary()` and cash accounting count their `proceeds_dollars` **once** —
  they are the realized settlement payout.
- `_market_fill_totals` / `get_market_residual_yes_cc` /
  `get_market_round_trip_pnl_dollars` treat them as `non_execution`: their
  `canonical_yes_delta_cc` (a position sweep) is **excluded** from exposure
  reconstruction, and the residual×outcome term re-derives the payout value.
- A consumer MUST NOT combine both treatments: including settlement-row
  proceeds AND the residual-derived payout double-counts the settlement.
  The sweep delta included in residual likewise erases the payout term
  (pre-P4 bug: post-settlement residuals read −held).

## Verified-only benchmark (labeling contract)

Verified-only (contract 1.0, exclusions explicit, NOT complete account truth,
NOT a floor/bound): actual **−4,384.53¢**, hold **−3,301.68¢**, delta
**−1,082.85¢**, 798 episodes, partition {fully 482 / partial 4 / no_exit 312}.
Excluded: 22 mirror_matched, 3 side_conflict (order `01a0d3ae`,
KXXRP15M-26SEP241000-00), 1 unpaired_provisional (`01a0da6e`/`cb898835`,
KXXRP15M-26SEP251730-30). Prior −$28.02/+$5.18 figures are withdrawn as
benchmarks.

**d3ae + da6e RESOLVED 2026-11-02 at exchange settlement truth** (see audit
snapshot §P4-PAIRS addendum): d3ae −13.06c (buy-NO + buy-YES hedge pair, $1.00
payout), da6e −65.62c (real buy-NO execution, YES won → $0; venue fill
`0723b3d4` never ingested — 09-25 fills-poller gap, backfill candidate).
Complete-history realized: **−4,463.21c ≈ −$44.63**.

## Pre-restart checks (recorded)

- Commit `67cec276`, contract `canonical-fill-view/1.0`.
- Backups: `backups/p4_release_2026-11-02/` — kalshi_fills.db,
  kalshi_order_attempts.db, decision_audit.db, position_exit_state.json,
  exit_counterfactuals.jsonl, bankroll_reconciliation.jsonl,
  settlement_outcomes.jsonl, baseline capture.
- Baseline (`_release_baseline_2026-11-02.json`): exchange 0 positions /
  0 open orders / $12.6431 — **verified flat**; ledger census 1788 rows;
  24 live_router rows present; coverage flags verified end-to-end.
- No startup path deletes raw mirror evidence (DELETE removed; mirrors
  quarantine to `_superseded_mirror_fills`).
- Rollback retains evidence preservation: `backups/.../rollback_evidence_
  preservation.patch` reapplies the quarantine-not-delete + suppress-telemetry
  changes onto a reverted tree (`git revert 67cec276 && git apply <patch>`;
  the patch also carries the now-dead `_order_rows_conflict` helper so the
  quarantined-scope scan still works if invoked).

## Restart conditions

Server is DOWN (last process exited ~21:43 local; no supervisor running).
Deployment = cold start via `start_15m.ps1` into a verified-flat account —
the required safe window. `MERID_OBSERVE_ONLY` derives 0 from
auto_execution_mode=1 → entries auto-enable after preflight (unchanged
operating contract). First possible entry is post-preflight, gated normally.

## Post-restart acceptance (before treating deployment as complete)

| Area | Required |
|---|---|
| Raw ledger | 24 live_router rows still in kalshi_fills |
| Contract | consumers report canonical-fill-view/1.0 |
| Coverage | d3ae=conflict_quarantined, da6e=provisional_unverified |
| Residuals | 22 mirror markets read 0; genuine exposure unmasked |
| Reconciliation | local positions == exchange, discrepancies explicit |
| Surfaces | API/UI/Prometheus agree for same scope/timestamp |
| Policy config | exit/stop/loss-gate/exposure env unchanged |
| Execution health | no unexpected orders/cancels/retry bursts |

Verified-only benchmark is reproduced from the FROZEN snapshot (backup DB);
current live totals reconcile separately — never force equal.

## Rollback

1. Pause entries (existing operational control).
2. `git revert 67cec276` (or checkout parent) + `git apply
   backups/p4_release_2026-11-02/rollback_evidence_preservation.patch`.
3. Restart again — in-memory projections carry contract-era values until
   reload; code-revert alone is insufficient.
4. Do NOT restore old DB backups over newer state.
5. Preserve diagnostics; assess positions before another restart.

## Deployment record 2026-11-02

- Deployed commit: `142b5419` (= P4 release `67cec276` + incumbent P2/P3 repairs commit; working tree clean)
- First start attempt (pid 12428) failed closed on dirty-tree gate; in-flight repairs committed as `142b5419` then relaunched (uvicorn pid 9212, 02:12:03 local)
- Preflight PASS 02:15:40 -> LIVE_ENTRIES_ENABLED (auto_enable_after_preflight); env_sha256=0FEBDD2A8B3643B7 identical to baseline (policy unchanged)
- Post-start acceptance: raw ledger 1788 rows preserved (24 live_router + 346 settlement intact in DB); FillsPoller restored 1788; canonical reconciler MATCHED (exchange=ledger=cache=0 pos, 0 orders); no unexpected submissions
- Coverage verified on deployed code + live DB: d3ae conflict_quarantined (resid=100 retained, not zeroed), da6e provisional_unverified (resid=None), mirror market verified_with_excluded_mirrors (resid=0); summary() contract=1.0 excluded=25 provisional=1 non_execution=346
- Post-preflight legitimate activity: first eligible entry executed -- 4 NO @65c KXDOGE15M-26NOV020230-30 (fill 0727f7a4); balance 12.6431 -> ~10.04 available; exposure recon converged -400 exchange/ledger/cache
- Authed API/UI surface agreement check: not verified (session auth fail-closed under live trading; requires operator session)
- Stale log string noted: '[FILLS-LEDGER-BACKFILL] deleted 23 stale live-router rows' still prints 'deleted' though code quarantines in-memory only (DB verified intact)


## Live session 2026-11-02 02:12-02:45 (stopped by operator)

- Trades: 3 entries (DOGE-0230 4NO@65c; XRP-0245 2.69NO@65c; DOGE-0245 3.31NO@96c), 1 partial trail exit (XRP +0.88), 3 NO-win settlements. Balance 12.6431 -> 15.0001 exact reconciliation.
- Settlement path verified live: settlement pseudo-fill (proceeds +4.00, liquidity_role=settlement) ingested; exchange flat at close.
- Exit FSM worked: FILLED / EXCHANGE_CONFIRMED_FLAT / CANCELED / RESOLVING all durable and correct.
- DEFECT (env/lifecycle, not P4): stale decision_audit -wal from prior unclean exit -> WAL-recovery race at boot -> server's audit conns permanently readonly (1529+ writes dropped; schema init + record_* all failed). Fresh conns write fine; WAL checkpointed clean post-stop.
- EXIT-POLICY FINDING: every position born risk_params_state=unknown (REST position poll precedes fill ingestion; no upgrade path) -> EXIT-POLICY-QUARANTINE blocks discretionary exits; profit_only_v1 floor suppresses sub-entry trails -> only profit-trails + derived fallback SL + settlement function. Live mechanism behind the historical 'no-exit losses' concentration. HARD_PROFIT_LOCK_TRIGGER_NO_INTENT P0 alert also observed.

