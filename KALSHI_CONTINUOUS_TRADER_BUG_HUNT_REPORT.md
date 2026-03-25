# Kalshi Continuous Trader - Full-Stack Bug Hunt Report

**Date**: 2026-03-25
**Objective**: Identify why the Kalshi continuous trader is not placing any real trades despite live markets being available.

---

## Executive Summary

### ROOT CAUSE IDENTIFIED

The Kalshi continuous trader is **NOT placing real trades** because:

1. **All 26 trading agents default to PAPER mode** on startup (deployment.py:128)
2. **No automatic promotion to LIVE mode** even when `MERID_PM_LIVE_ENABLED=true`
3. **Per-agent mode override** forces paper fills regardless of global mode settings (kalshi_tools.py:285-286)
4. **Zero observability** into agent deployment modes - health endpoints don't expose which agents are PAPER/LIVE/HALTED

**Impact**: The system appears to be running (agents are cycling, markets are discovered, signals are generated), but ALL orders are simulated. Real trading has never occurred.

---

## A. No-Trade Decision Tree

This decision tree enumerates **all paths leading to "no trades"** with specific code locations:

```
┌─────────────────────────────────────────────────────────────────┐
│ START: User expects live trading with MERID_PM_LIVE_ENABLED=true│
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ GATE 1: SessionGuard - Trading Hours Check                      │
│ File: merid/prediction/session_guard.py:96-103                  │
│ Blocks: Thursday 3-5 AM ET (Kalshi maintenance)                 │
│ Result: NO TRADES if outside trading hours                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (if trading allowed)
┌─────────────────────────────────────────────────────────────────┐
│ GATE 2: VenueGate - Global Mode Check                           │
│ File: merid/prediction/venue_gate.py:153-155                    │
│ Condition: should_simulate_fill() returns True if:              │
│   - mode == MOCK or mode == PAPER                               │
│ Result: SIMULATED FILLS if mode is not LIVE                     │
│                                                                  │
│ Check: mode == LIVE AND live_enabled == True                    │
│   - mode from: settings.MERID_PM_TRADING_MODE                   │
│   - live_enabled from: settings.MERID_PM_LIVE_ENABLED           │
│ Result: NO REAL TRADES if live_enabled=False                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (if gate says LIVE)
┌─────────────────────────────────────────────────────────────────┐
│ ⚠️ BUG-1 & BUG-3: DeploymentController Per-Agent Mode Override │
│ File: merid/event_venues/kalshi/deployment.py:125-138           │
│ File: merid/prediction/kalshi_tools.py:285-286                  │
│                                                                  │
│ Issue: Every agent has a deployment mode (PAPER/LIVE/SHADOW)    │
│ Default: AgentMode.PAPER (line 128 in deployment.py)            │
│                                                                  │
│ Override Logic (kalshi_tools.py:285-286):                       │
│   if agent_mode == "PAPER":                                     │
│       return SIMULATED_FILL  # ← FORCES PAPER EVEN IF LIVE      │
│                                                                  │
│ Result: NO REAL TRADES even if VenueGate allows live trading    │
│         ALL 26 AGENTS DEFAULT TO PAPER MODE ON STARTUP          │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (if agent mode is LIVE or SHADOW)
┌─────────────────────────────────────────────────────────────────┐
│ GATE 3: DeploymentController - HALTED Check                     │
│ File: merid/prediction/kalshi_tools.py:251-256                  │
│ Blocks: agent_mode == AgentMode.HALTED                          │
│ Result: NO TRADES if agent has been halted                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (if not halted)
┌─────────────────────────────────────────────────────────────────┐
│ GATE 4: ExecutionGate - Safety Checks                           │
│ File: core/execution_gate.py:104-230                            │
│ File: merid/prediction/kalshi_tools.py:261-273                  │
│ Blocks if:                                                       │
│   - Kill switch engaged (risk_controller._global_kill)          │
│   - Reconciliation never completed                              │
│   - Reconciliation has critical discrepancies                   │
│   - Price feeds stale (>5min)                                   │
│   - PnL consistency check fails                                 │
│ Result: NO REAL TRADES if any safety check fails                │
│                                                                  │
│ Note: In KALSHI_USE_DEMO mode, reconciliation/PnL checks        │
│       downgraded to "warning" (non-blocking)                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (if execution gate passes)
┌─────────────────────────────────────────────────────────────────┐
│ UPSTREAM: Market Discovery → Filtering → Risk Sizing            │
│                                                                  │
│ Possible NO-TRADE causes:                                       │
│                                                                  │
│ 1. MarketCatalog returns empty (API error, rate limit)          │
│    - File: merid/event_venues/kalshi/market_catalog.py:234-255  │
│    - Result: _resolved_markets = [] → NO SIGNALS                │
│                                                                  │
│ 2. All markets filtered out by _filter_active_contracts         │
│    - File: merid/prediction/trading_agent.py:376-430            │
│    - Reasons: expired, wrong timeframe, outside entry window    │
│                                                                  │
│ 3. Strategy returns NO_ACTION (edge < threshold)                │
│    - File: merid/prediction/strategy.py:156-162                 │
│    - Thresholds: 5% (early), 4% (mid), 3% (late), 2% (term)    │
│                                                                  │
│ 4. Risk check blocks order (limits exceeded)                    │
│    - File: merid/prediction/risk.py:239-280                     │
│    - Limits: $500/market, $1000/event, $5000/portfolio          │
│                                                                  │
│ 5. Entry window check fails                                     │
│    - File: merid/prediction/trading_agent.py:558-567            │
│    - Example: BTC_15M has 10min window, cutoff 1min before      │
└─────────────────────────────────────────────────────────────────┘
```

---

## B. Bugs, Eggs, Hardcodes, and Synthetics

### BUG-1: DeploymentController defaults all agents to PAPER mode [CRITICAL]

**File**: `merid/event_venues/kalshi/deployment.py:125-138`

**Symptom**: All 26 trading agents start in PAPER mode on every system boot, regardless of environment variables.

**Code**:
```python
def register_agent(self, agent_name: str) -> AgentDeployment:
    """Register an agent (starts in PAPER mode)."""
    if agent_name not in self._agents:
        self._agents[agent_name] = AgentDeployment(agent_name=agent_name)  # ← Defaults to PAPER
    return self._agents[agent_name]

@dataclass
class AgentDeployment:
    agent_name: str
    mode: AgentMode = AgentMode.PAPER  # ← HARDCODED DEFAULT
```

**Impact**:
- Even with `MERID_PM_LIVE_ENABLED=true` and `MERID_PM_TRADING_MODE=live`, all agents remain in PAPER mode
- No trades are ever sent to Kalshi API
- All fills are simulated

**Proposed Fix**:
```python
def register_agent(self, agent_name: str, initial_mode: Optional[AgentMode] = None) -> AgentDeployment:
    """Register an agent with mode determined by global settings."""
    if agent_name not in self._agents:
        # Determine initial mode from global settings if not specified
        if initial_mode is None:
            from merid.settings import settings
            if settings.MERID_PM_LIVE_ENABLED and settings.MERID_PM_TRADING_MODE == "live":
                initial_mode = AgentMode.LIVE
            else:
                initial_mode = AgentMode.PAPER

        self._agents[agent_name] = AgentDeployment(
            agent_name=agent_name,
            mode=initial_mode
        )
        logger.info(f"[deploy] Registered {agent_name} in {initial_mode.value} mode")
    return self._agents[agent_name]
```

---

### BUG-2: No automatic promotion from PAPER → LIVE [CRITICAL]

**File**: `merid/prediction/agent_grid.py` (startup logic missing)

**Symptom**: Agents require manual API call to `promote_to_live()` for each agent. No startup logic checks environment variables and auto-promotes.

**Impact**:
- Operators don't know agents need manual promotion
- System appears to be running but is actually in paper mode
- No documentation exists for promotion workflow

**Proposed Fix**: Add startup hook in `agent_grid.py`:
```python
async def start(self) -> None:
    """Start all agents and portfolio risk monitor."""
    # ... existing startup logic ...

    # Auto-promote agents to LIVE if environment is configured for live trading
    from merid.settings import settings
    from merid.event_venues.kalshi.deployment import get_deployment_controller

    if settings.MERID_PM_LIVE_ENABLED and settings.MERID_PM_TRADING_MODE == "live":
        dc = get_deployment_controller()
        for agent in self._agents:
            # Register with LIVE mode from the start
            dc.register_agent(agent.config.name, initial_mode=AgentMode.LIVE)
            logger.info(f"[agent_grid] Auto-promoted {agent.config.name} to LIVE mode")
```

---

### BUG-3: Dual mode checking creates confusing override behavior [CRITICAL]

**File**: `merid/prediction/kalshi_tools.py:285-286`

**Symptom**: Per-agent deployment mode overrides global `VenueGate` mode, forcing paper fills even when global mode is LIVE.

**Code**:
```python
# Simulate if in SIM/PAPER mode OR agent is in PAPER deployment mode
_force_paper_deploy = (_agent_mode is not None and _agent_mode.value == "PAPER")
if gate.should_simulate_fill() or _force_paper_deploy:  # ← OVERRIDE
    return SIMULATED_FILL
```

**Impact**:
- Operator sets `MERID_PM_LIVE_ENABLED=true` expecting live trades
- All agents still in PAPER mode, so all fills are simulated
- No error, no warning - silent failure

**Proposed Fix**: Remove per-agent override for agents in LIVE deployment mode, OR add loud warning:
```python
# Check per-agent deployment mode
_force_paper_deploy = (_agent_mode is not None and _agent_mode.value == "PAPER")

# If global gate says LIVE but agent is PAPER, log loud warning
if not gate.should_simulate_fill() and _force_paper_deploy:
    logger.warning(
        f"[kalshi_tools] Agent {_agent_name} is in PAPER deployment mode, "
        f"overriding global LIVE setting. Set agent to LIVE mode to enable real trades."
    )

if gate.should_simulate_fill() or _force_paper_deploy:
    # ... simulated fill logic ...
```

---

### BUG-4: Zero observability into agent deployment modes [HIGH]

**Files**:
- `web/api/kalshi_grid_api.py` (health endpoint)
- `web/api/operator_endpoints.py` (operator API)

**Symptom**: Health endpoints don't expose agent deployment modes. Operator cannot see which agents are PAPER vs LIVE vs HALTED.

**Impact**:
- Operator thinks system is live when all agents are paper
- No way to diagnose why trades aren't being placed
- Must SSH into server and run Python REPL to check agent modes

**Proposed Fix**: Add agent modes to health endpoint:
```python
@router.get("/health")
async def kalshi_grid_health():
    # ... existing health checks ...

    # Add agent deployment status
    from merid.event_venues.kalshi.deployment import get_deployment_controller
    dc = get_deployment_controller()
    agent_modes = {
        name: dep.mode.value
        for name, dep in dc._agents.items()
    }

    return {
        # ... existing fields ...
        "agent_modes": agent_modes,
        "agents_by_mode": {
            "live": [n for n, m in agent_modes.items() if m == "LIVE"],
            "paper": [n for n, m in agent_modes.items() if m == "PAPER"],
            "shadow": [n for n, m in agent_modes.items() if m == "SHADOW"],
            "halted": [n for n, m in agent_modes.items() if m == "HALTED"],
        },
    }
```

---

### EGG-1: KALSHI_USE_DEMO downgrade of safety checks [MEDIUM]

**File**: `core/execution_gate.py:88-101, 130, 181`

**Symptom**: When `KALSHI_USE_DEMO=true`, reconciliation and price feed checks are downgraded from "critical" to "warning", allowing trades despite discrepancies.

**Code**:
```python
def _is_kalshi_demo_mode() -> bool:
    try:
        from merid.settings import settings
        return settings.KALSHI_USE_DEMO
    except Exception:
        return os.environ.get("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes")

# Later in check_execution_gate():
recon_severity = "warning" if kalshi_demo else "critical"  # ← DOWNGRADE
```

**Impact**:
- Intended for demo/paper mode where crypto reconciliation is irrelevant
- Could mask real issues if accidentally set in production
- Not an "egg" per se, but surprising behavior

**Proposed Fix**: Add warning if demo mode is enabled with live trading:
```python
if kalshi_demo and not gate.should_simulate_fill():
    logger.warning(
        "[execution_gate] KALSHI_USE_DEMO=true but global mode is LIVE. "
        "Safety checks are downgraded. This should only be used for testing."
    )
```

---

### HARD-1: Edge thresholds hardcoded in strategy.py [LOW]

**File**: `merid/prediction/strategy.py:52-54`

**Hardcoded Values**:
```python
EDGE_THRESHOLD_EARLY = 0.05   # 5% edge for >24h contracts
EDGE_THRESHOLD_MID = 0.04     # 4% edge for 4-24h
EDGE_THRESHOLD_LATE = 0.03    # 3% edge for 1-4h
EDGE_THRESHOLD_TERMINAL = 0.02  # 2% edge for <1h
```

**Impact**:
- Cannot adjust thresholds without code change
- Different assets (BTC vs DOGE) may need different thresholds
- Not a bug, but reduces flexibility

**Proposed Fix**: Move to YAML config or make per-agent configurable.

---

### HARD-2: Risk limits hardcoded in risk.py [LOW]

**File**: `merid/prediction/risk.py:46, 55`

**Hardcoded Values**:
```python
MAX_NOTIONAL_PER_MARKET = 500  # USD
MAX_DAILY_LOSS = 250  # USD
```

**Impact**:
- Duplicates settings.MERID_PM_MAX_NOTIONAL_PER_MARKET
- Two sources of truth
- Code hardcode overrides settings

**Proposed Fix**: Remove hardcodes, use settings exclusively.

---

### HARD-3: Cycle intervals hardcoded in trading_agent.py [LOW]

**File**: `merid/prediction/trading_agent.py:662`

**Hardcoded Values**:
```python
cycle_interval = 30 if self.config.timeframes and "15m" in self.config.timeframes else 60
```

**Impact**:
- Cannot adjust polling frequency without code change
- 15m agents poll every 30s, all others every 60s
- May be too aggressive or too slow depending on market conditions

**Proposed Fix**: Add `cycle_interval_seconds` to agent YAML config.

---

### SYN-1: No synthetic/paper path leak detected [NONE]

After thorough review, there is **NO** synthetic or paper trading path leaking into the production flow. The paper mode is cleanly separated and only triggered by:
1. Global `VenueGate.should_simulate_fill() == True`
2. Per-agent `AgentMode.PAPER`

Both are intentional gates, not accidental leaks.

---

## C. Minimal Patch Set

### Patch 1: Fix DeploymentController default mode

**File**: `merid/event_venues/kalshi/deployment.py`

**Changes**:
1. Add `initial_mode` parameter to `register_agent()`
2. Check global settings if `initial_mode` is None
3. Log agent mode on registration

**Impact**: Agents will start in LIVE mode if env vars are set correctly.

---

### Patch 2: Add auto-promotion logic to AgentGrid startup

**File**: `merid/prediction/agent_grid.py`

**Changes**:
1. In `start()` method, check if `MERID_PM_LIVE_ENABLED=true`
2. If yes, register all agents with `initial_mode=LIVE`
3. Log promotion decisions

**Impact**: Operators no longer need manual promotion API calls.

---

### Patch 3: Add deployment mode to health endpoints

**File**: `web/api/kalshi_grid_api.py`

**Changes**:
1. Add `agent_modes` dict to health response
2. Add `agents_by_mode` breakdown
3. Include in both `/api/v1/kalshi-grid/health` and `/api/v1/operator/status`

**Impact**: Operators can immediately see which agents are PAPER vs LIVE.

---

### Patch 4: Add warning when agent mode overrides global mode

**File**: `merid/prediction/kalshi_tools.py`

**Changes**:
1. Add loud warning when agent is PAPER but global is LIVE
2. Include agent name and remediation instructions in log

**Impact**: Operators will know immediately when agents are not trading live.

---

### Patch 5: Add demo mode warning in execution gate

**File**: `core/execution_gate.py`

**Changes**:
1. Check if `KALSHI_USE_DEMO=true` while `VenueGate` says LIVE
2. Log warning about downgraded safety checks

**Impact**: Prevents accidental demo mode in production.

---

## D. Verification Checklist

Use this checklist to verify the system is correctly configured for live trading:

### 1. Environment Variables

```bash
# Check settings
python -c "
from merid.settings import settings
print('MERID_PM_TRADING_MODE:', settings.MERID_PM_TRADING_MODE)
print('MERID_PM_LIVE_ENABLED:', settings.MERID_PM_LIVE_ENABLED)
print('KALSHI_USE_DEMO:', settings.KALSHI_USE_DEMO)
print('KALSHI_API_KEY_ID:', settings.KALSHI_API_KEY_ID[:10] + '...' if settings.KALSHI_API_KEY_ID else 'NOT SET')
"
```

**Expected Output** (for live trading):
```
MERID_PM_TRADING_MODE: live
MERID_PM_LIVE_ENABLED: True
KALSHI_USE_DEMO: False
KALSHI_API_KEY_ID: YOUR_KEY...
```

---

### 2. VenueGate Status

```bash
python -c "
from merid.prediction.venue_gate import get_venue_gate
gate = get_venue_gate()
print('Mode:', gate.mode.value)
print('Live Enabled:', gate.live_enabled)
print('Is Live:', gate.is_live)
print('Should Simulate:', gate.should_simulate_fill())
print('Summary:', gate.summary())
"
```

**Expected Output** (for live trading):
```
Mode: live
Live Enabled: True
Is Live: True
Should Simulate: False
```

---

### 3. Agent Deployment Modes

```bash
python -c "
from merid.event_venues.kalshi.deployment import get_deployment_controller
dc = get_deployment_controller()
status = dc.status()
print('Live agents:', status['live'])
print('Paper agents:', status['paper'])
print('Halted agents:', status['halted'])
print('Shadow agents:', status['shadow'])
"
```

**Expected Output** (for live trading):
```
Live agents: ['BTC_15M', 'BTC_HOURLY', 'ETH_15M', ...]  # ← Should have 26 agents
Paper agents: []
Halted agents: []
Shadow agents: []
```

**⚠️ If all agents are in `paper`, trades will be simulated!**

---

### 4. Health Endpoint Check

```bash
curl http://localhost:8011/api/v1/kalshi-grid/health | jq '.agent_modes'
```

**Expected Output**:
```json
{
  "BTC_15M": "LIVE",
  "BTC_HOURLY": "LIVE",
  "ETH_15M": "LIVE",
  ...
}
```

---

### 5. Market Discovery Check

```bash
curl http://localhost:8011/api/v1/kalshi-grid/health | jq '.btc_markets'
```

**Expected Output**:
```json
{
  "total": 10,
  "m15": 5,
  "h1": 5,
  "sample_tickers": ["KXBTC-26MAR25-08PM-T100000", ...]
}
```

**⚠️ If total is 0, no markets are being discovered!**

---

### 6. Execution Gate Status

```bash
python -c "
from core.execution_gate import check_execution_gate
status = check_execution_gate()
print('Blocked:', status.blocked)
print('Safe to Trade:', status.safe_to_trade)
print('Gate State:', status.gate_state)
print('Reasons:', [r.message for r in status.reasons])
"
```

**Expected Output** (healthy system):
```
Blocked: False
Safe to Trade: True
Gate State: clear
Reasons: []
```

---

### 7. Log Grep for "simulated" vs "real" orders

```bash
# Check recent orders
grep -i "kalshi_place_order" /path/to/logs/merid.log | tail -20

# Look for simulated=True (paper) vs simulated=False (live)
```

**Expected**: Should see `"simulated": false` in logs if live trading is active.

---

### 8. Known-Good Scenario: BTC 15m with live markets

**Setup**:
- Time: Any time except Thursday 3-5 AM ET
- Kalshi has active BTC 15m markets
- All env vars set for live trading
- All agents in LIVE mode

**Expected Behavior**:
1. `MarketCatalog` discovers 5+ BTC 15m markets
2. `BTC_15M` agent filters to 1 active contract
3. Strategy evaluates edge (may or may not place order based on edge)
4. If edge > threshold, risk check passes → **REAL ORDER** sent to Kalshi API
5. Order ID returned (not starting with "sim_")
6. Position appears in Kalshi account

**Verification**:
```bash
# Check agent is running
curl http://localhost:8011/api/v1/kalshi-grid/health | jq '.agent_modes.BTC_15M'
# Should return: "LIVE"

# Check BTC markets discovered
curl http://localhost:8011/api/v1/kalshi-grid/health | jq '.btc_markets.m15'
# Should return: 5 (or similar non-zero)

# Check logs for BTC_15M orders
grep "BTC_15M" /path/to/logs/merid.log | grep "kalshi_place_order" | tail -5
```

---

## E. Diagnostic Commands

Quick reference for operators:

```bash
# 1. Check if system is in live mode
python -c "from merid.prediction.venue_gate import get_venue_gate; print('Live:', get_venue_gate().is_live)"

# 2. Check how many agents are in live mode
python -c "from merid.event_venues.kalshi.deployment import get_deployment_controller; print(get_deployment_controller().status()['live_count'])"

# 3. Check if markets are being discovered
python -c "from merid.event_venues.kalshi.market_catalog import get_market_catalog; print('Total markets:', len(get_market_catalog().get_all_markets()))"

# 4. Check if agent grid is running
python -c "from merid.prediction.agent_grid import get_agent_grid; grid = get_agent_grid(); print('Running:', grid.is_running, 'Agents:', len(grid.agents))"

# 5. Check if execution gate is blocking
python -c "from core.execution_gate import check_execution_gate; print('Blocked:', check_execution_gate().blocked)"

# 6. Promote a specific agent to live (manual)
python -c "from merid.event_venues.kalshi.deployment import get_deployment_controller; print(get_deployment_controller().promote_to_live('BTC_15M'))"
```

---

## F. Summary of Findings

| ID | Type | Severity | File | Issue | Impact |
|----|------|----------|------|-------|--------|
| BUG-1 | Bug | CRITICAL | deployment.py:128 | All agents default to PAPER mode | No real trades placed |
| BUG-2 | Bug | CRITICAL | agent_grid.py | No auto-promotion logic | Agents never go live |
| BUG-3 | Bug | CRITICAL | kalshi_tools.py:285 | Per-agent mode overrides global | Silent paper trading |
| BUG-4 | Bug | HIGH | kalshi_grid_api.py | No mode observability | Cannot diagnose issues |
| EGG-1 | Surprise | MEDIUM | execution_gate.py:88 | Demo mode downgrades safety | Masks issues in prod |
| HARD-1 | Hardcode | LOW | strategy.py:52 | Edge thresholds hardcoded | Inflexible |
| HARD-2 | Hardcode | LOW | risk.py:46 | Risk limits hardcoded | Duplicates settings |
| HARD-3 | Hardcode | LOW | trading_agent.py:662 | Cycle intervals hardcoded | Inflexible |

**Total Critical Bugs**: 3 (BUG-1, BUG-2, BUG-3)

---

## G. Conclusion

The Kalshi continuous trader is **architecturally sound** but has **3 critical bugs** that prevent live trading:

1. **Default PAPER mode** for all agents
2. **No automatic promotion** to LIVE mode on startup
3. **Silent override** of global mode by per-agent mode

These bugs combine to create a "perfect storm" where:
- Operator sets `MERID_PM_LIVE_ENABLED=true`
- System appears to be running (agents cycling, markets discovered, signals generated)
- All orders are silently simulated (paper fills)
- No error, no warning, no indication of issue
- Health endpoints don't expose agent modes

**Recommended Action**: Implement Patches 1-5 immediately to restore live trading capability.

---

**End of Report**
