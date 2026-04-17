# MERID Kill-Switch & Trading-Disable Control Inventory

> Generated: 2026-04-09  
> Scope: All controls that can halt, pause, simulate, or block real Kalshi order submission.  
> **Bold** = actually blocks Kalshi orders. *Italic* = phantom/dead for Kalshi.

---

## 1. Complete Control Table

| # | Control Name | File : Line | Layer | Type | Trigger | Can Block Kalshi? | Blocks Via | Manual/Auto | Notes |
|---|-------------|-------------|-------|------|---------|-------------------|-----------|------------|-------|
| 1 | `risk_controller._global_kill` | `merid/risk/kill_switches.py:140` | Global | Hard kill | Manual or auto (PnL/error/RTI) | **YES** | `check_execution_gate()` → `kill_switch` reason | Both | Primary kill switch. Persisted to `data/risk_kill_switch.json`. All other paths funnel here. |
| 2 | `ExecutionGateStatus.blocked` | `core/execution_gate.py:79` | Global | Aggregator | Aggregates all 6 check sources | **YES** | Direct: `live_execution_blocked()` | Auto | The single gate all Kalshi-path code must call. Any CRITICAL source → blocked=True. |
| 3 | `VenueGate._mode` (MOCK) | `merid/prediction/venue_gate.py:75` | Venue | Mode gate | Config/env: `MERID_PM_TRADING_MODE` | **YES** | `VenueGate.check_can_trade()` raises `ModeBlockedError` | Config | MOCK mode = no orders sent. Singleton checked by KalshiTradingAgent per cycle. |
| 4 | `VenueGate._live_enabled` (False) | `merid/prediction/venue_gate.py:87` | Venue | Mode gate | `MERID_PM_LIVE_ENABLED=false` | **YES** | `VenueGate.check_can_trade()` raises when mode=LIVE but live_enabled=False | Config | Second latch on top of LIVE mode. |
| 5 | `MERID_ALLOW_LIVE_TRADES` (unset) | `merid/prediction/venue_gate.py:92` | Venue | Mode gate | Missing env var | **YES** | Forces mode → PAPER even if `MERID_PM_TRADING_MODE=live` | Config | Platform-wide latch. Checked in VenueGate constructor, setter, and reload(). |
| 6 | `AgentMode.HALTED` | `merid/event_venues/kalshi/deployment.py:47` | Per-agent | Per-agent halt | `DeploymentController.halt()` | **YES** | `KalshiTradingAgent` checks deployment state before cycle | Manual | Only pauses that specific agent's cycle. Does NOT cancel open orders. |
| 7 | `KalshiTradingAgent.state.enabled` | `merid/prediction/trading_agent.py` | Per-agent | Per-agent pause | `agent.pause()` / `agent.resume()` | **YES** | Agent cycle exits early if `state.enabled=False` | Manual | Per-agent pause. Other agents continue. |
| 8 | `StopLossRules._session_halted` | `merid/event_venues/kalshi/stop_loss.py` | Per-session | Session halt | Intra-session loss cap breached | **YES** | `trading_agent.py:1858` — agent exits cycle if `session_halted` | Auto | Per-agent session halt from stop-loss. Resets on next session start. |
| 9 | `PortfolioRiskAgent._kill_switch_active` | `merid/prediction/portfolio_risk_agent.py` | Portfolio | Risk breaker | Exposure/drawdown auto-trigger | **YES** (indirectly) | PRA refuses to authorize pre-trade checks when active | Auto | Pre-trade check refusal → trade not sized. Does NOT directly block `check_execution_gate()`. |
| 10 | `PredictionMarketRisk` pre-trade check | `merid/prediction/risk.py` | Portfolio | Risk gate | Per-trade: exposure, concentration | **YES** (per-trade) | `PreTradeCheck.approved=False` → agent skips order | Auto | Per-trade sizing gate. Not a kill switch — purely per-decision. |
| 11 | `risk_controller._global_kill` via `reconciliation` | `core/execution_gate.py:204` | Global | Data quality | Kalshi venue reconciliation discrepancy | **YES** | `check_execution_gate()` → `reconciliation` reason (CRITICAL in live mode) | Auto | In demo mode this is a warning only. |
| 12 | `price_feed` staleness gate | `core/execution_gate.py:287` | Global | Data quality | BTC/ETH/SOL/XRP/DOGE/USD > 120s stale | **YES** | `check_execution_gate()` → `price_feed` reason (CRITICAL in live mode) | Auto | All 5 critical-group symbols checked. 120s threshold (env: `KALSHI_PRICE_FEED_CRITICAL_THRESHOLD_S`). |
| 13 | `dependency_health` gate | `core/execution_gate.py:339` | Global | Infrastructure | Critical dependency DOWN | **YES** | `check_execution_gate()` → `dependency_health` CRITICAL reason | Auto | Non-critical deps (Finnhub, Twitter) are warnings only. |
| 14 | `fills_ledger_reconciliation` gate | `core/execution_gate.py:259` | Global | Data quality | Fills ledger status=BROKEN | **YES** | `check_execution_gate()` → `fills_ledger_reconciliation` (CRITICAL in live) | Auto | DEGRADED = warning. BROKEN = critical. |
| 15 | `news_feed` gate | `core/execution_gate.py:372` | Global | Data quality | Finnhub down/stale | NO | Warning only — never blocks | Auto | Never rises to CRITICAL. Conviction only. |
| 16 | `pnl_consistency` gate | `core/execution_gate.py:316` | Global | Data quality | Domain-internal PnL divergence > $5 | WARNING only | `check_execution_gate()` → `pnl_consistency` warning | Auto | Warning-only — gate goes LIMITED, not BLOCKED. |
| 17 | `risk_controller.daily_loss_limit` | `merid/risk/kill_switches.py:112` | Global | Auto kill | Daily PnL < −`daily_loss_limit` | **YES** | Sets `_global_kill=True` → blocks `check_execution_gate()` | Auto | Default $500 loss limit. Override: `MERID_MAX_DAILY_LOSS_USD`. |
| 18 | `risk_controller.error_threshold` | `merid/risk/kill_switches.py:133` | Global | Auto kill | Error count ≥ `error_threshold` per window | **YES** | Sets `_global_kill=True` | Auto | Default 10 errors per window. Override: `MERID_ERROR_THRESHOLD`. |
| 19 | `TradingHaltManager._halt_reasons` | `core/automated_risk_controls.py` | Global | Halt manager | `/api/v1/risk/halt` | NO* | Halt flag NOT read by `check_execution_gate()` — **phantom for Kalshi direct path** | Manual | *The halt-reasons dict affects `PortfolioRiskManager` but NOT `check_execution_gate()`. See §3. |
| 20 | `SessionGuard.is_trading_allowed()` | `merid/prediction/session_guard.py` | Session | Time gate | Kalshi maintenance window (Thu 3–5am ET) | **YES** | `KalshiTradingAgent` calls `get_session_guard()` before each cycle | Auto | Time-based. Agent skips cycle. Open orders NOT canceled. |
| 21 | `MERID_UNIVERSE_CATEGORIES` | `merid/event_venues/kalshi/universe.py:66` | Universe | Scope gate | Env var filters allowed categories | **YES** (indirectly) | Excludes `crypto` category from universe pool → no Kalshi crypto markets discovered | Config | If unset → all categories allowed. Set to exclude crypto → all 30 cells see zero markets. |
| 22 | `UniverseConfig.min_volume/min_open_interest` | `merid/event_venues/kalshi/universe.py:57` | Universe | Liquidity gate | Markets below floor rejected | **YES** (indirectly) | Markets not in universe pool → agent never sees them | Config | Env: `MERID_UNIVERSE_MIN_VOLUME`, `MERID_UNIVERSE_MIN_OI`. |
| 23 | `AgentConfig.enabled` | `merid/prediction/agent_grid_config.py:95` | Per-agent | Config gate | YAML `enabled: false` | **YES** | Agent not instantiated by orchestrator | Config | Startup-only. Rarely used. |
| 24 | `loop_lag` halt counter | `core/execution_gate.py:34` | Global | Performance | (Removed from gate inputs) | NO | `reset_lag_halt_counter()` is a no-op | — | Loop lag is recorded in health APIs but does NOT affect gate state. |
| 25 | `arbitrage.py` kill switch | `web/api/arbitrage.py:299` | Dead | Dead path | `POST /api/v1/arbitrage/kill` | NO | Arbitrage module removed. Router may not be mounted. | — | **DEAD** — `from arbitrage import …` will fail at import (arbitrage/ deleted). |
| 26 | `debate_integration_api.py` kill switch | `web/api/debate_integration_api.py:847` | Per-deployment | Debate deployment | `POST /api/v1/debate/kill-switch` | NO | Affects `DeploymentManager` debate kill flag, NOT `risk_controller._global_kill` | Manual | Separate from main kill switch. Does not flow into `check_execution_gate()`. |
| 27 | `core/automated_risk_controls.py` `PortfolioRiskManager` | `core/automated_risk_controls.py:130` | Portfolio | Risk manager | Internal risk loops | NO* | NOT wired to `check_execution_gate()`. Affects crypto paper-sim, not Kalshi direct path. | Auto | *Phantom for Kalshi: manages crypto sim portfolios. Legacy module. |
| 28 | `KALSHI_USE_DEMO` env var | `core/execution_gate.py:154` | Global | Mode gate | Env at startup | Partially | When `true`, downgrades reconciliation and price_feed from CRITICAL → WARNING | Config | Safe-default mode. Set `KALSHI_USE_DEMO=false` for live mode, CRITICAL blocking. |
| 29 | `pm_spot_hard_gate` | `merid/prediction/trading_agent.py:2392` | Per-agent | MM-specific gate | `MERID_CRYPTO_MM_PM_SPOT_HARD_GATE=0` | **YES** (MM agents) | Blocks QUOTE orders when spot missing/stale | Config | Only applies to market_maker archetype agents with `pm_spot_hard_gate: true`. |
| 30 | `GateState.LIMITED` | `core/execution_gate.py:46` | Global | Soft gate | Warnings only (no CRITICAL sources) | **Reduce-only** | Allows closes/reduces but no new risk entries (enforced per caller) | Auto | Depends on callers checking `allows_reduce()`. |

---

## 2. Path Mappings — Major Controls

### A. Primary Global Kill Switch

```
UI: Mode & Safety panel → "Kill Switch" button
  → API: POST /api/v1/kalshi/kill-switch?activate=true (kalshi_api.py:3745)
  → backend: risk_controller.fire_kill_switch() → risk_controller._global_kill = True
  → persisted: data/risk_kill_switch.json (survives restart)
  → read at: check_execution_gate() → kill_switch reason (severity=CRITICAL)
             → ExecutionGateStatus.blocked = True
  → effect: order_router.py calls check_execution_gate() before every order; BLOCKED → order refused
            trading_agent._run_cycle() calls check_execution_gate() at cycle start
```

**Recovery:** `POST /api/v1/kalshi/kill-switch?activate=false` → `risk_controller.reset_kill_switch()` → clears `data/risk_kill_switch.json` → next `check_execution_gate()` returns CLEAR.

### B. VenueGate / Trading Mode

```
Config: .env → MERID_PM_TRADING_MODE=mock|paper|live + MERID_PM_LIVE_ENABLED=true + MERID_ALLOW_LIVE_TRADES=1
  → startup: VenueGate.__init__() reads settings.MERID_PM_TRADING_MODE
  → singleton: get_venue_gate() (merid/prediction/venue_gate.py:251)
  → read at: trading_agent._execute_signal_body() → gate.check_order("kalshi")
             If MOCK: raises ModeBlockedError → agent logs and skips
  → effect: NO Kalshi order submitted in MOCK mode.
```

**Recovery:** Set `MERID_PM_TRADING_MODE=paper` or `live` + `MERID_PM_LIVE_ENABLED=true` + `MERID_ALLOW_LIVE_TRADES=1`, then `gate.reload()` or restart.

### C. Per-Agent Halt (DeploymentController)

```
UI: Agent Grid panel → "Halt" button per agent
  → API: POST /api/v1/kalshi/deployment/halt (deployment.py)
  → backend: DeploymentController.halt(agent_name) → AgentDeployment.mode = HALTED
  → persisted: data/deployment_state.json
  → read at: KalshiTradingAgent._run_cycle() checks deployment.get_mode(name)
             HALTED → cycle exits early, no order submitted
  → effect: Only that agent is halted. Other agents continue.
```

### D. Automatic Daily Loss Kill

```
trigger: risk_controller.record_pnl(negative_amount) called in trading_agent.py fill handler
  → _daily_pnl < -daily_loss_limit (default $500, env: MERID_MAX_DAILY_LOSS_USD)
  → risk_controller._global_kill = True, _kill_reason = DAILY_LOSS
  → persisted: data/risk_kill_switch.json
  → propagates identically to path A above
```

### E. Session Guard (Time-Based)

```
trigger: Kalshi maintenance window (Thu 3:00–5:00am ET by default)
  → SessionGuard.is_trading_allowed() returns False
  → read at: KalshiTradingAgent._run_cycle() at cycle start
  → effect: cycle body skipped; open orders NOT canceled; gate stays CLEAR
  → auto-clears: when current time is outside maintenance window
```

### F. Price Feed Staleness (Auto-Gate)

```
trigger: BTC/USD, ETH/USD, SOL/USD, XRP/USD, or DOGE/USD price > 120s stale
  → check_execution_gate() → price_feed reason (CRITICAL in live mode)
  → ExecutionGateStatus.blocked = True
  → all Kalshi order paths blocked
  → self-clears: when price feed updates (Coinbase REST poll next cycle)
```

---

## 3. Phantom / Dead Controls for Kalshi

These controls exist in code but do NOT block the Kalshi execution path:

| Control | Why It's Phantom |
|---------|-----------------|
| `TradingHaltManager` (core/automated_risk_controls.py) | Not imported or called by `check_execution_gate()`. Manages crypto sim. |
| `arbitrage.py` kill switch | `arbitrage/` module deleted. Router not mounted in web/main.py (verify: grep shows no arbitrage router mount). |
| `debate_integration_api.py` toggle_kill_switch | Sets `DeploymentManager.kill_switch_active` — separate from `risk_controller._global_kill`. Not checked in Kalshi order path. |
| `loop_lag` halt counter | `reset_lag_halt_counter()` is documented as a no-op. Loop lag recorded for observability only. |
| `pnl_consistency` gate | Warning-only severity. Gate goes LIMITED (reduce-only), not BLOCKED. |
| `news_feed` gate | Always WARNING severity by design. News informs conviction, never blocks. |

---

## 4. Controls That Block Kalshi Orders — Summary Table

| Control | blocks_via | notes |
|---------|-----------|-------|
| `risk_controller._global_kill` | `check_execution_gate()` → kill_switch CRITICAL | Primary. Persisted. |
| `VenueGate` MOCK mode | `ModeBlockedError` in agent cycle | Mode-level block |
| `VenueGate` LIVE + live_enabled=False | `ModeBlockedError` | Second latch |
| `MERID_ALLOW_LIVE_TRADES` unset | Forces PAPER via VenueGate | Platform latch |
| `AgentMode.HALTED` | Agent cycle exits early | Per-agent only |
| `agent.state.enabled=False` | Agent cycle exits early | Per-agent only |
| `StopLossRules.session_halted` | Agent cycle exits early | Per-session, per-agent |
| `PredictionMarketRisk` refusal | `PreTradeCheck.approved=False` | Per-trade sizing gate |
| `SessionGuard` (maintenance window) | Agent cycle exits early | Time-based, auto-clear |
| Reconciliation (live mode) | `check_execution_gate()` → reconciliation CRITICAL | Auto, self-clears |
| Price feed stale (live mode) | `check_execution_gate()` → price_feed CRITICAL | Auto, self-clears |
| Dependency DOWN (critical dep) | `check_execution_gate()` → dependency_health CRITICAL | Auto, self-clears |
| Fills-ledger BROKEN (live mode) | `check_execution_gate()` → fills_ledger_reconciliation CRITICAL | Auto |
| `MERID_UNIVERSE_CATEGORIES` (excludes crypto) | Universe pool empty → no markets found | Config, startup |
| `pm_spot_hard_gate` | Blocks QUOTE in MM agents | MM-only, per-trade |

---

## 5. Duplicate / Conflicting Kill Endpoints

The following endpoints all claim to "kill trading" but affect different state objects:

| Endpoint | State Mutated | Blocks Kalshi? |
|----------|--------------|---------------|
| `POST /api/v1/kalshi/kill-switch` | `risk_controller._global_kill` | **YES** — via `check_execution_gate()` |
| `POST /api/v1/debate/kill-switch` | `DeploymentManager.kill_switch_active` (debate only) | NO — not in Kalshi path |
| `POST /api/v1/arbitrage/kill` (dead) | `ArbitrageGate` (module deleted) | NO — dead path |
| `POST /api/v1/risk/halt` (if mounted) | `TradingHaltManager._halt_reasons` | NO — not in Kalshi path |

**Operator warning:** Only `POST /api/v1/kalshi/kill-switch` and `POST /api/v1/kalshi/deployment/halt/{agent}` reliably affect live Kalshi trading.  The other endpoints are either dead or affect separate subsystems.

---

## 6. Kill-Switch State on Cold Restart

On restart, the kill switch state is re-loaded from `data/risk_kill_switch.json`:
- If the file says `triggered` → trading is blocked from first cycle
- File is written on `emergency_stop()` / `fire_kill_switch()`, cleared on `reset_kill_switch()`
- **To guarantee trading resumes after restart**: ensure `data/risk_kill_switch.json` is cleared OR call `POST /api/v1/kalshi/kill-switch?activate=false` before restarting

---

## 7. Env-Var Reference for All Gate Controls

| Env Var | Default | Effect |
|---------|---------|--------|
| `MERID_PM_TRADING_MODE` | `mock` | `mock`/`paper`/`live` — VenueGate mode |
| `MERID_PM_LIVE_ENABLED` | `false` | Second latch for LIVE mode |
| `MERID_ALLOW_LIVE_TRADES` | (unset) | Platform-wide LIVE trade permission latch |
| `KALSHI_USE_DEMO` | `true` | Downgrades reconciliation/price_feed to WARNING |
| `KALSHI_CONFIRM_LIVE` | `0` | Must be `1` to point at live Kalshi API |
| `MERID_MAX_DAILY_LOSS_USD` | `500` | Auto-kill threshold on daily P&L |
| `MERID_ERROR_THRESHOLD` | `10` | Auto-kill after N errors per window |
| `KALSHI_PRICE_FEED_CRITICAL_THRESHOLD_S` | `120` | Seconds before price feed → CRITICAL |
| `MERID_UNIVERSE_CATEGORIES` | (empty=all) | Comma-separated category whitelist |
| `MERID_UNIVERSE_MIN_VOLUME` | `50` | Min contracts volume for universe |
| `MERID_UNIVERSE_MIN_OI` | `10` | Min open interest for universe |
| `MERID_RISK_KS_FILE` | `data/risk_kill_switch.json` | Kill switch persistence path |
| `MERID_DEPLOYMENT_STATE` | `data/deployment_state.json` | Per-agent deployment state path |
| `MERID_CRYPTO_MM_PM_SPOT_HARD_GATE` | `1` (enabled) | Set `0` to disable PM spot hard gate globally |
