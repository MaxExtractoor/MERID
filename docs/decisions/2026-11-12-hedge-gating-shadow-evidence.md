# ADR: Hedge-entry gating, counterfactual shadow evaluation, and reserve evidence health

Date: 2026-11-12
Status: Accepted (implemented)
Scope: `merid/hedging/*`, `merid/event_venues/kalshi/order_router.py`,
`merid/diagnostics/evidence_health_report.py`, `merid/prediction/window_plan.py`,
`merid/prediction/risk/_prediction_risk.py`

## Context

Work packages 1–4 of the sizing/execution control program established that
the audited candidate-entry path (TradeDecision approval + ceiling +
window-plan reservation + fail-closed bankroll) is sound, while other
risk-increasing producers were not equally accounted:

- **Hedge entries** bypassed TradeDecision approval and window-plan
  reservation entirely, ran every loop tick when
  `|net_delta| > threshold`, and on 15m binaries a same-market
  opposite-side pair locks in spread + taker fees rather than reducing
  variance.
- **`_prediction_risk.check_order`** fabricated a $1000 global cap on
  exception and floored bankroll at $50/$1, turning unavailable equity
  into apparent buying power.
- **`loop_15m._mark_reject`** was defined but never bound; every named
  rejection was rewritten as `router_exception`, corrupting telemetry.
- **Hedge TP/SL auto-exit loop** (`run_auto_exit_loop`) is never started;
  residual hedge positions rely on the alpha-close trigger only.

## Decision

1. **Hedge entries are gated OFF by default.**
   `HedgeConfig.entries_enabled` (default `False`, env override
   `MERID_HEDGE_ENTRIES_ENABLED`, YAML `hedging.entries_enabled`) gates
   risk-increasing hedge buys inside `CryptoHedgeEngine.compute_hedge_orders`.
   Hedge *exits* (`auto_exit_hedges`, TP/SL config) are unaffected — they
   are risk-reducing and must stay live for residual positions.

   Re-enable preconditions (all required):
   - shared authorization/reservation accounting covering hedge producers
     (the common order-authorization contract: producer, policy version,
     approved quantity, max cash commitment, reservation id, expiry);
   - hedge sizing in centi-contracts consistent with the alpha path;
   - exposure cells scoped per-window, not per-series;
   - verified exit/recovery behavior for orphaned hedge positions;
   - current-policy shadow evidence (`logs/hedge_shadow.jsonl`) showing
     the hedged book's net-of-cost outcome beats alpha-only.

2. **Counterfactual shadow lane records what gated-off hedges would do.**
   `merid/hedging/shadow_eval.py` + `compute_hedge_orders(shadow=True)`:
   when entries are disabled, the engine computes identical orders and the
   router records each to `logs/hedge_shadow.jsonl` instead of routing.
   Each record carries the *executable ask* for the hedge side (never the
   engine's mid/FVG estimate), side-specific displayed depth, the
   versioned Kalshi taker fee (`kalshi_fee_cents_exact`), fill-ratio
   under a conservative depth-only model, book freshness, and
   `research_eligible` only when a fresh initialized book shows a real
   ask with depth covering the full size.  Write-only, exception-safe,
   cannot self-promote to live.

   Env: `MERID_HEDGE_SHADOW_ENABLED` (default on),
   `MERID_HEDGE_SHADOW_LOG`, `MERID_HEDGE_SHADOW_MAX_BOOK_AGE_S` (5s).

   Grading is offline: join records to settlement/exit outcomes and
   compute alpha-only vs alpha+hedge P&L, variance/CVaR change, and
   cost-as-% of edge.  A price touch is never treated as a fill.

3. **Reserve evidence-health report** (`merid/diagnostics/evidence_health_report.py`)
   answers "is old evidence still driving current policy?" per source:
   bankroll snapshot freshness, slot-allocator reservations, window-plan
   budget/pending TTL, capital sleeve state, scalp return model
   (expected `unvalidated` until Release 2), market-state store
   freshness, hedge policy gate state.  Each source reports sample
   count, oldest/newest observation, last update, effective value,
   fallback reason, and expiry/recheck time.  Collectors never raise;
   broken sources report `unavailable` with reason.

   Distinct from `merid.prediction.evidence_health`, which tiers the
   `live_entry_evidence.json` artifact by age for admission gating.

4. **Fail-closed bankroll everywhere.** `_prediction_risk.check_order`
   rejects `BANKROLL_UNAVAILABLE` on missing/stale/invalid equity — no
   fabricated caps or floors. Hedge sizing already uses
   `get_equity_for_risk_calc()` (freshness-bounded); zero/unknown bankroll
   yields zero hedge orders.

## Consequences

- The only enabled risk-increasing producer on the 15m path is the
  Phase-A-audited candidate path. Market making and arbitrage remain
  disabled by default; arbitrage unpaired-leg fills now emit CRITICAL
  telemetry instead of silently leaving directional exposure.
- Shadow records accumulate evidence for the eventual hedge decision
  without contaminating live P&L or capital accounting.
- Kelly sizing remains shadow-only: `scalp_return_model` has no active
  validated model; live 0.10 fractional-Kelly magnitude is deferred until
  the empirical net-return model is validated under current policy.

## References

- Commits: `76636385`, `a851b26e`, `b272269a`, `6630fa61`, `c28ccd94`,
  `4234014a` (control integrity); this ADR accompanies the evidence-health
  + shadow-lane commit.
- `tests/FAILURE_LEDGER.md` — stale-test classification.
- `tests/hedging/test_shadow_eval.py`, `tests/test_evidence_health_report.py`,
  `tests/test_hedge_entries_gate.py`,
  `tests/test_prediction_risk_bankroll_fail_closed.py`.
