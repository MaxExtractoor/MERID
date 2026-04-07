# AgentGrid Live Trading Operator Checklist

This checklist ensures AgentGrid is properly configured for live trading before startup.

## Pre-Startup Checklist

### 1. Check Trading Mode Configuration

```bash
# Check environment variables
echo "MERID_PM_TRADING_MODE: $MERID_PM_TRADING_MODE"
echo "MERID_PM_LIVE_ENABLED: $MERID_PM_LIVE_ENABLED"
```

**Expected for live trading:**
- `MERID_PM_TRADING_MODE=live`
- `MERID_PM_LIVE_ENABLED=true`

**If mode is `mock`:** No orders will be submitted (test mode only)
**If mode is `paper`:** Orders will be simulated but not sent to Kalshi

### 2. Run Live Readiness Check Script

```bash
cd /home/runner/work/MERID/MERID
python scripts/check_live_readiness.py
```

This script validates:
- ✓ VenueGate mode and live_enabled flag
- ✓ At least some agents are enabled
- ✓ PortfolioRiskAgent is not halted
- ✓ Sufficient account balance
- ✓ Min edge thresholds are realistic (not too high)
- ✓ Hypothetical trade would get approved

**Action:** Fix any ✗ FAIL items before proceeding.

### 3. Review Strategy Catalog Edge Thresholds

```bash
# Check min_edge_bps for each enabled cell
cat config/strategy_catalog.yaml | grep -A 1 "enabled: true" | grep min_edge_bps
```

**Realistic edge thresholds:**
- 15m/1h: 50-200 bps (0.5-2%)
- Daily: 100-300 bps (1-3%)
- Weekly/Monthly: 150-400 bps (1.5-4%)
- Annual: 200-600 bps (2-6%)

**If min_edge > 800 bps (8%):** Very few trades will occur. Lower thresholds in `config/strategy_catalog.yaml` if needed.

### 4. Check Kalshi API Connectivity

```bash
# Test Kalshi API connection
python -c "
from merid.prediction.kalshi_tools import _kalshi_get_balance
import asyncio
result = asyncio.run(_kalshi_get_balance())
print(f'Success: {result.success}')
print(f'Balance: {result.payload if result.success else result.error}')
"
```

**Expected:** `Success: True` with balance data

### 5. Verify No Kill Switch Active

Check PortfolioRiskAgent is not halted:

```bash
# In Python shell or script
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
print(f"Portfolio risk halted: {grid._portfolio_risk._halted}")
print(f"Halt reason: {grid._portfolio_risk._halt_reason}")
```

**Expected:** `halted: False`

**If halted:** Call `grid._portfolio_risk.resume()` to clear the kill switch.

### 6. Review Agent Configuration

```bash
# Count enabled agents
cat config/kalshi_agent_grid.yaml | grep -c "name:"
```

**Expected:** 30+ agents (5 assets × 6 timeframes)

**Verify at least some agents are enabled** (not all paused)

### 7. Check Log Output After Startup

After starting the system, watch logs for:

```bash
# Look for startup validation summary
tail -f logs/merid.log | grep "\[GRID-START\]"
```

**Expected output:**
```
[GRID-START] live_agents=30 mode=live live_enabled=True risk_halted=False
```

**If you see CRITICAL warnings:** Review and fix the issues listed.

### 8. Monitor First Cycle Activity

After startup, monitor the first few agent cycles:

```bash
# Watch for agent cycle summaries
tail -f logs/merid.log | grep "\[AGENT-CYCLE\]"
```

**Expected output (per agent, per cycle):**
```
[AGENT-CYCLE] agent=BTC_15M candidates=5 orders=0 vetoes=5 (session_guard=0 no_markets=0 entry_window=2 order_limit=0 no_action=3 consensus=0 risk=0 degraded=0)
```

**Diagnose zero trades:**
- **`veto_session_guard > 0`:** Kalshi maintenance window (Thu 3-5AM ET)
- **`veto_no_markets > 0`:** No markets available (check market catalog)
- **`veto_entry_window > 0`:** Markets not in entry window (check `entry_window` config)
- **`veto_no_action > 0`:** Strategy returned NO_ACTION (edge too low or no signal)
- **`veto_consensus > 0`:** Swarm consensus blocked (conflicted or forming)
- **`veto_risk > 0`:** Risk checks failed (check logs for `[RISK-VETO]` details)
- **`veto_order_limit > 0`:** Hit max_orders_per_window

## Common Issues and Fixes

### Issue: "All agents disabled"

**Cause:** All agents in paused state
**Fix:**
```python
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
for agent in grid.agents:
    agent.resume()
```

### Issue: "VenueGate mode=MOCK"

**Cause:** Environment variable not set
**Fix:** Set `MERID_PM_TRADING_MODE=live` and restart

### Issue: "min_edge too high, zero trades for 10+ hours"

**Cause:** Strategy catalog edge thresholds unrealistic
**Fix:** Edit `config/strategy_catalog.yaml`, lower `min_edge_bps` values to 50-200 for 15m/1h

### Issue: "PortfolioRiskAgent halted"

**Cause:** Daily loss limit or drawdown exceeded
**Fix:**
```python
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
grid._portfolio_risk.resume()
```

### Issue: "Swarm consensus always conflicted"

**Cause:** Swarm agents disagreeing on direction
**Fix:** Check swarm proposal logs or allow degraded mode (up to 3 solo trades)

## Post-Startup Verification

Within first 30 minutes, verify:

1. **At least one `[AGENT-CYCLE]` log per agent** → Agents are running
2. **`candidates > 0` for at least some agents** → Market discovery working
3. **`orders > 0` within first hour if edge exists** → Trading pipeline working end-to-end

If `orders=0` for 1+ hours AND `candidates > 0`:
- Check `[AGENT-VETO]` and `[RISK-VETO]` logs for dominant veto reason
- Verify edge thresholds are realistic
- Confirm VenueGate is not in MOCK mode

## Emergency Stop

To halt all trading immediately:

```python
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
grid._portfolio_risk.halt("Manual emergency stop by operator")
```

This activates the kill switch and blocks all new orders until `.resume()` is called.
