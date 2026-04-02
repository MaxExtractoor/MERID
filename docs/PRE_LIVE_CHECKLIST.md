# MERID Pre-Live Checklist

> **Status**: 🟡 READY FOR REVIEW — paper gates passed; live flags remain OFF.  
> **Last updated**: 2026-04-01  
> **Live flags**: `MERID_TRADE_MODE=paper` · `MERID_ALLOW_LIVE_TRADES=false` (unchanged)

This checklist **must be fully satisfied** — every item ticked — before
switching MERID from paper mode to live trading.  It consolidates the
diagnostic runbook (`/diagnostic-runbook`), `VALIDATION_GUIDE.md`, and
`fix_history.md` into a single gating document.

---

## Section 1 — Environment & Safety Locks

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 1.1 | `MERID_TRADE_MODE=paper` is set in the running environment | `echo $MERID_TRADE_MODE` → `paper` | ✅ |
| 1.2 | `MERID_ALLOW_LIVE_TRADES=false` is set | `echo $MERID_ALLOW_LIVE_TRADES` → `false` | ✅ |
| 1.3 | `.env` file does NOT contain `MERID_TRADE_MODE=live` or `MERID_PM_LIVE_ENABLED=true` | `grep -i live .env` shows only paper references | ✅ |
| 1.4 | Kill-switch is **armed** (live trading locked) | `GET /api/kill_switch` → `active=true` | ✅ |
| 1.5 | `scripts/go_live_preflight.py` **passes all gates** (except the live-flip gates which should remain blocked) | Run `python scripts/go_live_preflight.py` and confirm gates 1–3 say FAIL (as expected while in paper) and gates 4–8 say PASS | ⬜ |

---

## Section 2 — Test Suite

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 2.1 | Backend golden-path tests pass: 37 tests, 3 aiohttp tests skipped | `python -m pytest tests/test_e2e_golden_path.py tests/test_signal_layer.py tests/test_live_feeds.py tests/test_prediction_markets.py tests/test_unified_pipeline.py tests/test_canonical_agents.py tests/test_hardening.py -v` | ✅ |
| 2.2 | Paper gate runner tests all pass (23 tests) | `python -m pytest tests/test_paper_gate_runner.py -v` | ✅ |
| 2.3 | No new test failures vs. baseline (baseline: 37 pass, 3 skip, 0 unexplained failures) | Run full CI and compare | ⬜ |
| 2.4 | Ruff lint passes on changed modules | `ruff check . --select E9,F63,F7,F82` | ✅ |

---

## Section 3 — Event Loop Health

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 3.1 | `/api/health` returns `status=healthy` and `degraded=false` | `curl http://localhost:8000/api/health \| jq .` | ✅ |
| 3.2 | `/api/health` response includes `event_loop` block with P50/P95/P99 | Check JSON response for `checks.event_loop` key | ✅ |
| 3.3 | `/health/event_loop` returns `running=true` and `degraded=false` | `curl http://localhost:8000/health/event_loop \| jq .` | ✅ |
| 3.4 | P95 lag < 500 ms at time of check | `curl http://localhost:8000/health/event_loop \| jq '.stats_1m.p95_ms'` → < 500 | ✅ |
| 3.5 | Event Loop Monitor logs startup banner: `✅ Event Loop Monitor started` | Check app startup logs | ✅ |

---

## Section 4 — Paper Gate Evidence

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 4.1 | **≥ 3 independent 30-minute paper gates passed** | Check `fix_history.md` Phase 1 section | ✅ |
| 4.2 | All gates had P95 < 500 ms throughout | See fix_history.md: max P95 = 0.44 ms across all three gates | ✅ |
| 4.3 | All gates had `degraded=false` on every sample | fix_history.md: degraded_samples = 0 for all three | ✅ |
| 4.4 | No critical-lag profiles captured in any gate | fix_history.md: critical_lag_samples = 0 for all three | ✅ |
| 4.5 | No crashes, no missed heartbeats across all gates | fix_history.md: failed_polls = 0 for all three | ✅ |
| 4.6 | Gates ran with full agent/pipeline set (35 agents + 11 pipelines) | fix_history.md confirms full load | ✅ |

---

## Section 4A — Staging Full Trading Mode Validation

> **Critical**: These gates must be run in staging environment with `VALIDATION_MODE=0` (full trading mode), not in CI.
> See [STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md](STAGING_FULL_TRADING_VALIDATION_RUNBOOK.md) for complete procedures.

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 4A.1 | **10-minute gate passed in staging** | Run `python scripts/run_trading_gate.py --duration 10` and analyze results with `--highlight-5min` | ⬜ |
| 4A.2 | 10-minute gate shows P95 < 500ms for all samples including T+5min windows | Check analyzer output: all samples show ✅ | ⬜ |
| 4A.3 | **30-minute gate passed in staging** | Run `python scripts/run_trading_gate.py --duration 30` and analyze results | ⬜ |
| 4A.4 | 30-minute gate meets all 5 go/no-go criteria | P95<500ms, P99<800ms, Max<1000ms, degraded=0, failed_polls=0 | ⬜ |
| 4A.5 | Gate results archived with analyzer output | Copy gate JSON + analyzer output to `reports/LIVE_READY_*` and commit/upload | ⬜ |

**Go/No-Go Decision**: If **any** criterion in 4A.1-4A.4 fails, **DO NOT go live**. Fix issues and re-run gates.

---

## Section 5 — Unresolved Anomalies

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 5.1 | No open `ANOMALY-*` entries in `fix_history.md` related to lag | Review fix_history.md ANOMALY-1 and ANOMALY-2 — both RESOLVED | ✅ |
| 5.2 | No new anomalies discovered during paper gates | fix_history.md Phase 1: "Anomalies: None" for all three gates | ✅ |
| 5.3 | No unresolved circuit-breaker events or reconciliation failures | Review recent logs and `GET /api/v1/reconciliation/status` | ⬜ |
| 5.4 | No WebSocket feed disconnections or gap-detection alerts in the last 24 h | Review logs for `[WARN]` / `[ERROR]` in feed modules | ⬜ |

---

## Section 6 — Risk & Execution Gate

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 6.1 | Execution gate `loop_lag` check is enabled and configured | `core/execution_gate.py` — `LoopLagConfig(warn=200ms, block=500ms)` | ✅ |
| 6.2 | Kill-switch thresholds tightened for first live gate (P95 ≥ 300 ms triggers halt) | See `docs/LIVE_ROLLOUT_PLAN.md` Phase 1 — configure before live flip | ⬜ |
| 6.3 | Kelly fractions set to conservative initial values (≤ 10% of normal) | Confirm in risk config before live flip | ⬜ |
| 6.4 | Notional caps per market and globally set to minimal values | Confirm in risk config before live flip | ⬜ |
| 6.5 | Automatic fallback to paper triggers on `degraded=true` or P95 ≥ 300 ms | Verify fallback hook is wired; see `docs/LIVE_ROLLOUT_PLAN.md` | ⬜ |

---

## Section 7 — Monitoring & Alerting

| # | Check | How to verify | Status |
|---|-------|--------------|--------|
| 7.1 | Telegram alerts are configured and delivering | Send test alert; confirm receipt | ⬜ |
| 7.2 | `/health/event_loop` is polled in production monitoring (Grafana / OneUptime) | Confirm dashboard exists and is green | ⬜ |
| 7.3 | Alert for `degraded=true` is wired to on-call escalation | Review alert rules in `web/api/system_observability.py` | ⬜ |
| 7.4 | Alert for P95 lag > 300 ms (pre-live) fires correctly (integration-tested) | Send synthetic high-lag event in staging | ⬜ |

---

## Section 8 — Sign-off

All sections above must show ✅ before sign-off.  Items marked ⬜ must be
completed immediately before the live flip (not ahead of time, since environment
state may drift).

```
Engineering Lead:  ________________________________  Date: __________
Risk Manager:      ________________________________  Date: __________
Trading Lead:      ________________________________  Date: __________
SRE Lead:          ________________________________  Date: __________
```

> **DO NOT flip live flags until this form is fully signed.**  
> Flip procedure: see `docs/LIVE_ROLLOUT_PLAN.md` Step 4.

---

## Quick-reference gate commands

```bash
# 1. Confirm environment
echo "Trade mode: $MERID_TRADE_MODE"        # must be 'paper'
echo "Live trades: $MERID_ALLOW_LIVE_TRADES" # must be 'false'

# 2. Health endpoints
curl -s http://localhost:8000/api/health | jq '{status,degraded}'
curl -s http://localhost:8000/health/event_loop | jq '{degraded, p95_ms: .stats_1m.p95_ms}'

# 3. Run test suite (CI golden path)
python -m pytest tests/test_e2e_golden_path.py tests/test_signal_layer.py \
  tests/test_live_feeds.py tests/test_prediction_markets.py \
  tests/test_unified_pipeline.py tests/test_canonical_agents.py \
  tests/test_hardening.py tests/test_paper_gate_runner.py -v --tb=short

# 4. Run paper gate (5-minute smoke gate)
python scripts/run_paper_gate.py --duration 5 --poll-interval 30

# 5. Preflight checks
python scripts/go_live_preflight.py
```
