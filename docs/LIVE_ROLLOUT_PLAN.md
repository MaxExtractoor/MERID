# MERID Incremental Live Rollout Plan

> **Status**: 📋 PLAN ONLY — live flags are NOT flipped.  
> **Prerequisite**: All items in `docs/PRE_LIVE_CHECKLIST.md` must be ✅.  
> **Current mode**: `MERID_TRADE_MODE=paper` · `MERID_ALLOW_LIVE_TRADES=false`

This document specifies the concrete, step-by-step process for transitioning
MERID from paper mode to live trading.  Each phase is strictly bounded,
independently revertible, and requires an explicit go/no-go decision before
proceeding.

**DO NOT execute any step** until `docs/PRE_LIVE_CHECKLIST.md` is fully
signed off by all four roles.

---

## Guiding Principles

1. **Conservative first** — start with the smallest possible live exposure.
2. **Independently revertible** — every phase has a defined rollback procedure.
3. **Monitoring-driven** — automated kill-switch fires before humans need to intervene.
4. **Evidence-gated** — each phase advancement requires documented evidence from the previous phase.
5. **No surprises** — all thresholds, markets, and capital limits are specified in advance.

---

## Phase 0 — Pre-Live Hardening (paper mode, before any live flip)

### 0.1 Tighten kill-switch thresholds

Before flipping to live, lower the auto-halt thresholds to be more sensitive
than the paper-gate criteria.  These tighter thresholds stay in place for all
of Phase 1 and are relaxed only after Phase 1 evidence is reviewed.

| Threshold | Paper-gate value | Phase 1 live value |
|-----------|-----------------|-------------------|
| P95 lag warn | 200 ms | 150 ms |
| P95 lag block | 500 ms | **300 ms** |
| Degraded → halt | any `degraded=true` | any `degraded=true` |
| Sustained lag count (block) | 5 samples | **3 samples** |
| Cooloff after block | 10 s | **30 s** |

Update `core/execution_gate.py` `LoopLagConfig` before the live flip:

```python
LoopLagConfig(
    warn_ms=150.0,
    block_ms=300.0,
    sustained_count=3,
    cooloff_s=30.0,
)
```

### 0.2 Set conservative risk parameters

Configure the following **before** flipping live; do not rely on defaults.

| Parameter | Phase 1 live value | Normal paper value |
|-----------|-------------------|-------------------|
| Kelly fraction (all assets) | ≤ 5 % of normal | 100 % |
| Notional cap per market | $10 | uncapped (paper) |
| Global notional cap per run | $50 | N/A |
| Max open positions | 3 | 35 |
| Allowed markets | BTC-daily only | all 25 |

### 0.3 Define allowed markets for Phase 1

Phase 1 live trading is restricted to **one market only**:

- **Asset**: BTC  
- **Timeframe**: daily  
- **Venue**: Kalshi  

All other `KalshiTradingAgent` instances remain in paper mode during Phase 1.

### 0.4 Verify automatic fallback is wired

The system must automatically revert `MERID_TRADE_MODE` from `live` back to
`paper` if any of the following conditions are triggered:

- `degraded=true` on `/health/event_loop`
- P95 lag ≥ 300 ms (sustained for ≥ 3 consecutive samples)
- Kill-switch fires (any reason)
- Unhandled exception in `KalshiTradingAgent._run_loop`

Verify this in staging before the live flip.

---

## Phase 1 — First Live Gate (15–30 minutes)

### Preconditions (all must be ✅)

- [ ] `docs/PRE_LIVE_CHECKLIST.md` fully signed
- [ ] Phase 0 hardening applied and verified in staging
- [ ] Tightened `LoopLagConfig` deployed (block at 300 ms, 3-sample sustain)
- [ ] Conservative risk parameters in place (≤ $10/market, ≤ $50 global)
- [ ] Allowed market = BTC-daily only
- [ ] Automatic fallback wired and integration-tested
- [ ] Telegram alerts confirmed working (test alert received)
- [ ] On-call engineer active and monitoring dashboards open
- [ ] Paper-mode snapshot saved (positions, P&L, agent state) for rollback reference

### 1.1 Flip to live

```bash
# Only execute after all preconditions above are checked
export MERID_TRADE_MODE=live
export MERID_ALLOW_LIVE_TRADES=true
# Restart the backend — do NOT hot-reload
```

### 1.2 Immediate verification (first 5 minutes)

Poll continuously for the first 5 minutes:

```bash
watch -n 10 'curl -s http://localhost:8000/health/event_loop | jq "{degraded, p95_ms: .stats_1m.p95_ms}"'
```

Confirm:
- `degraded=false`
- P95 < 150 ms (warn threshold)
- Orders are being created in Kalshi for BTC-daily only
- No ERROR logs in `KalshiTradingAgent`

**If anything is wrong in the first 5 minutes → immediate rollback (see §1.5).**

### 1.3 Run the 15–30 minute live gate

```bash
python scripts/run_paper_gate.py \
  --duration 15 \
  --poll-interval 30 \
  --gate-id live-gate-001 \
  --output reports/live_gate_001.json
```

Note: `run_paper_gate.py` polls `/health/event_loop` — this works in live mode
too since the health endpoint is mode-agnostic.

Monitoring cadence during the gate:
- Every 30 s: `/health/event_loop` (automated by the runner)
- Every 5 min: manual review of Telegram alerts and Kalshi position summary
- Every 10 min: review `GET /api/v1/reconciliation/status`

### 1.4 Phase 1 pass criteria

All of the following must hold for the full gate duration:

| Criterion | Threshold |
|-----------|----------|
| P95 lag | < 300 ms throughout (tighter than paper gate) |
| `degraded=false` | on every sample |
| Critical-lag samples | 0 |
| Failed polls | 0 |
| Realised loss | < $20 (paper-level equivalent) |
| Reconciliation drift | < 1 % |
| BTC-daily only | no orders on other assets/timeframes |

### 1.5 Rollback procedure

**Trigger rollback immediately if**:
- Any criterion in §1.4 is violated
- Kill-switch fires automatically
- Manual decision by on-call engineer

**Steps**:
```bash
# 1. Revert environment
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

# 2. Restart backend
# 3. Cancel any open Kalshi orders manually via Kalshi dashboard
# 4. Document in fix_history.md with ANOMALY entry
# 5. Root-cause before any retry
```

### 1.6 Document Phase 1 results

Append an entry to `fix_history.md` in the same format as the paper gate
entries (§ Phase 1 in fix_history.md), including:

- Gate ID and timestamp
- P50/P95/P99 means and maxima
- Any violations or anomalies
- Whether Phase 1 criteria were met
- Decision: proceed to Phase 2 or re-gate

---

## Phase 2 — Expanded Live Gate (single session, 2–4 hours)

### Preconditions

- [ ] Phase 1 gate PASSED with no violations
- [ ] Phase 1 results documented in fix_history.md
- [ ] Engineering Lead reviewed Phase 1 gate JSON (reports/live_gate_001.json)
- [ ] Risk Manager confirmed Phase 1 P&L and reconciliation

### Changes vs Phase 1

| Parameter | Phase 1 | Phase 2 |
|-----------|---------|---------|
| Duration | 15–30 min | 2–4 hours |
| Allowed markets | BTC-daily only | BTC + ETH, daily only |
| Max positions | 3 | 6 |
| Notional cap per market | $10 | $25 |
| Global notional cap | $50 | $150 |
| Kelly fraction | 5 % | 10 % |
| P95 lag block | 300 ms | 400 ms |

Everything else (automatic fallback, Telegram alerts, monitoring cadence) remains
identical to Phase 1.

### Pass criteria for Phase 2

Same as Phase 1 §1.4, with the following adjustments:

| Criterion | Phase 2 threshold |
|-----------|-----------------|
| P95 lag | < 400 ms throughout |
| Realised loss | < $100 |
| BTC + ETH daily only | no orders on other assets/timeframes |

---

## Phase 3 — Steady-State Live (ongoing)

### Preconditions

- [ ] Phase 2 gate PASSED across at least 2 independent sessions
- [ ] No open ANOMALY entries in fix_history.md
- [ ] Risk Manager signed off on full risk parameter set

### Changes vs Phase 2

| Parameter | Phase 2 | Phase 3 |
|-----------|---------|---------|
| Allowed markets | BTC + ETH daily | All 25 (5 assets × 5 timeframes) |
| Max positions | 6 | 35 (full agent set) |
| Notional cap per market | $25 | Per risk profile in crypto_kalshi_risk.py |
| Global notional cap | $150 | Per portfolio risk manager |
| Kelly fraction | 10 % | Normal (per strategy) |
| P95 lag block | 400 ms | 500 ms (back to paper-gate threshold) |

### Ongoing monitoring requirements

| Signal | Cadence | Action on breach |
|--------|---------|-----------------|
| `/health/event_loop` P95 | every 30 s (automated) | Page on-call if > 400 ms for 5 min |
| `degraded=true` | immediate (automated) | Auto-halt + page on-call |
| Daily P&L vs. expectation | daily | Risk review |
| Reconciliation drift | every 15 min | Alert if > 0.5 % |
| Weekly paper gate re-run | weekly | Confirm baseline still clean |

---

## Rollout Schedule (placeholder dates)

> Dates are placeholders.  Replace with actual dates once Phase 0 is verified.

| Milestone | Planned date | Actual date | Status |
|-----------|-------------|-------------|--------|
| Phase 0 hardening complete | TBD | — | ⬜ |
| Pre-live checklist signed | TBD | — | ⬜ |
| Phase 1 live gate | TBD | — | ⬜ |
| Phase 1 results reviewed | TBD | — | ⬜ |
| Phase 2 live gate (session 1) | TBD | — | ⬜ |
| Phase 2 live gate (session 2) | TBD | — | ⬜ |
| Phase 3 steady-state | TBD | — | ⬜ |

---

## Stop Conditions (any triggers immediate halt and reversion to paper)

The following conditions trigger an **automatic or manual emergency halt** at
any phase.  After halting, treat as a new ANOMALY: investigate, document in
fix_history.md, and restart the rollout from Phase 0.

| Condition | Trigger | Response |
|-----------|---------|----------|
| `degraded=true` | automatic | Revert to paper, page on-call |
| P95 lag ≥ phase threshold (sustained) | automatic | Revert to paper, page on-call |
| Kill-switch fires | automatic | Revert to paper, page on-call |
| Reconciliation drift > 1 % | alert | Manual halt within 15 min |
| Realised loss > phase cap | alert | Manual halt immediately |
| Unhandled exception in core loop | automatic | Revert to paper, page on-call |
| Orders appearing on non-allowed markets | alert | Manual halt immediately |
| Telegram alerts stop delivering | manual check | Pause live trading until resolved |

---

## References

- [fix_history.md](../fix_history.md) — event loop lag fix history and paper gate evidence
- [docs/PRE_LIVE_CHECKLIST.md](PRE_LIVE_CHECKLIST.md) — pre-live sign-off checklist
- [VALIDATION_GUIDE.md](../VALIDATION_GUIDE.md) — 30-minute paper gate procedures
- [scripts/run_paper_gate.py](../scripts/run_paper_gate.py) — automated gate runner
- [core/execution_gate.py](../core/execution_gate.py) — loop-lag execution gate (LoopLagConfig)
- [observability/event_loop_monitor.py](../observability/event_loop_monitor.py) — EventLoopMonitor
- [docs/runbooks/RB-RISK-002-emergency-lockdown.md](runbooks/RB-RISK-002-emergency-lockdown.md) — emergency lockdown runbook
- [Detecting blocking tasks in asyncio](https://mergify.com/blog/detecting-blocking-tasks-in-asyncio-by-measuring-event-loop-latency)
- [P50 vs P95 vs P99 latency percentiles](https://oneuptime.com/blog/post/2025-09-15-p50-vs-p95-vs-p99-latency-percentiles/view)
