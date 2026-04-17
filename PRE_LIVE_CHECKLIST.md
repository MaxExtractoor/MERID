# PRE-LIVE CHECKLIST

**Purpose**: Formal sign-off before entering live trading. All items must be checked before Phase 1 execution.

## Environment Locks

- [ ] **Mode control documented**: Clear procedure for flipping `MERID_TRADE_MODE` and `MERID_ALLOW_LIVE_TRADES`
- [ ] **Rollback procedure**: How to flip back on halt (emergency stop sequence)
- [ ] **Env var verification**: Confirm production env vars are set correctly before start

## Test Suite

- [ ] **Test count**: `37 passed, 3 skipped (aiohttp)` confirmed
- [ ] **No regressions**: All structural tests passing (`test_kalshi_only_profile.py`, `test_ui_backend_contract.py`, `test_sse_smoke.py`)
- [ ] **Coverage**: Core trading paths have regression tests

## Event Loop Health Evidence

> **NOTE — Two distinct gate types exist. They are NOT interchangeable:**
>
> - **Infra gate** (`MERID_VALIDATION_MODE=1`): proves the HTTP path, Kalshi client/catalog, and LoopLagMonitor are healthy. ~15 ms P95 on a stripped server (~10–15 active tasks). Does NOT exercise MeridLoop, trading agents, WebSocket bridge, or any swarm component.
> - **Trading gate** (`MERID_VALIDATION_MODE` unset): proves the full stack (MeridLoop, 35 agents, 8 StreamingAgents, WS bridge, InsightPipeline) meets P95 < 500 ms under real load. Currently fails (historical: 1–9 s P95 with ~90–100 active tasks). ANOMALY-001 is NOT resolved under full load.
>
> All gates below that use `MERID_VALIDATION_MODE=1` are **infra gates only**. Production readiness requires passing trading gates.

- [x] **Infra gate #1**: 10-minute VALIDATION_MODE gate PASS — `fix_history.md` entry: "2026-04-02 Infra Gate #1"
  - Gate ID: `infra_gate_v5_20260402` — JSON: `validation_results/validation_gate_infra_gate_v5_20260402_20260402_143537.json`
  - 20/20 samples passing, P95 max=16ms, degraded=0, high-lag profiles=0
- [x] **Infra gate #2**: 30-minute VALIDATION_MODE gate PASS — `fix_history.md` entry: "2026-04-02 Infra Gate #2"
  - Gate ID: `infra_gate_2_20260402` — JSON: `validation_results/validation_gate_infra_gate_2_20260402_20260402_150902.json`
  - 60/60 samples passing, P95 max=31ms avg=15ms, degraded=0, high-lag profiles=0
- [ ] **Trading gate #1**: 10-minute full-load gate completed — ANOMALY-001 root causes fixed
- [ ] **Trading gate #2**: 30-minute full-load gate completed — P95 < 500 ms all samples
- [x] **Phase 3 Tick Optimization**: Code complete, 19/19 tests passing
  - [x] Tick overlap protection implemented and tested
  - [x] Per-step duration tracking implemented
  - [x] Symbol batching verified (1→2→5 symbols progression)
  - [x] Liquidity parallelization verified (semaphore=2, timeout=2s)
  - [x] Consensus parallelization verified (max 10 symbols, 5 debates)
- [ ] **Paper gate #4 (runner-driven)**: 30-minute gate with `scripts/run_paper_gate.py`, JSON artifact linked below
  - [ ] 5-minute smoke gate completed
  - [ ] 30-minute full gate completed
- [ ] **All TRADING gates PASS**: P95 < 500ms, `degraded=false`, no high-lag profiles under full load

**Gate Evidence JSON**: `validation_results/validation_gate_tick_opt_smoke_20250401_0425.json`

## Anomalies

- [ ] **ANOMALY-001 (Production Event-Loop Lag)**: Status **PARTIALLY MITIGATED / NOT VALIDATED UNDER FULL LOAD** — see `fix_history.md`. Infra gate shows 15 ms P95 on stripped server. Full-load gate (all agents + WS bridge) still fails: 1–9 s P95 historically. Root cause (`StreamingAgent._run_loop`, `KalshiTradingAgent._run_loop` not yielding) not yet fixed.
- [ ] **No unresolved lag anomalies**: All steady-state issues addressed under full load
- [ ] **No open WS/agent anomalies**: WebSocket and agent health confirmed

## Monitoring & Alerts

- [ ] **Telegram wiring**: Alert bot configured and tested
- [ ] **Lag alerts**: Event-loop lag > 500ms triggers alert
- [ ] **Health alerts**: `degraded=true` triggers alert
- [ ] **Kill switch alerts**: Emergency halt triggers alert
- [ ] **Dashboard**: Health telemetry visible in real-time

## Risk Configuration

- [ ] **Kill switch active**: Lag threshold at 300ms (Phase 0) or appropriate level
- [ ] **Position caps**: ≤ $10/market, ≤ $50 global, 5% Kelly (or current phase limits)
- [ ] **Market restriction**: BTC-daily-only wired into config (Phase 0/1)
- [ ] **Auto-halt tested**: Simulated lag > threshold triggers block (verified in Phase 0)

## Sign-Off

**SIGNED**: _________________ **DATE**: _________________ **TIME (UTC)**: _________________

**Role**: Operator / Lead Engineer

**Notes**:

---

*This checklist must be completed before every live gate transition. Do not proceed to live trading without formal sign-off.*
