# 🚨 CRITICAL ISSUE IDENTIFIED: 7% Bankroll Allocation Bug

## ROOT CAUSE

**The `Top3EdgeAllocator` is ONLY used in `kalshi_continuous_trader.py`, NOT in the main `AgentGrid` execution path!**

### Current Broken Flow:
```
AgentGrid (35 agents)
  ↓ Each agent runs independently
KalshiTradingAgent._run_cycle()
  ↓ Generates signal independently
_strategy.generate_signals()
  ↓ Calculates size using Kelly criterion
signal.contracts = sized based on edge
  ↓ No cross-agent coordination!
_execute_signal()
  ↓ Order placed
Kalshi API
```

**Problems:**
1. ✅ NO top-3 edge selection across agents
2. ✅ NO 1-2% bankroll cap enforcement at grid level
3. ✅ Each agent independently sizes trades (can sum to 7%+)
4. ✅ NO batch gating between cycles
5. ✅ NO anti-churn at grid level

### Where Top3 IS Used (Correctly):
- `kalshi_continuous_trader.py` - Legacy CT loop

### Where Top3 is NOT Used (The Bug):
- `agent_grid.py` - Main production trading grid (35 agents)
- `trading_agent.py` - Individual agent execution
- `merid/loop.py` - Main MeridLoop

## THE FIX NEEDED

Add top3 edge allocation and bankroll cap enforcement to the AgentGrid execution path.

### Options:

**Option 1: Hook into trading_agent.py _execute_signal()**
- Before placing order, check with Top3BatchManager
- If not in top3 batch, block execution
- If batch ACTIVE and not allocated, block

**Option 2: Hook into agent_grid.py cycle**
- Collect all signals from all agents
- Run top3 selection at grid level
- Only allow top3 to execute

**Option 3: Emergency guard in _prediction_risk.py**
- Add hard cap check before any order
- Fail-safe: if total would exceed 2%, reject

## IMMEDIATE EMERGENCY FIX

Add a hard bankroll cap check in `_prediction_risk.py` that:
1. Tracks total notional exposure across all agents
2. Rejects orders that would exceed 2% bankroll
3. Logs [EMERGENCY_CAP] violations

This is fail-safe and can be deployed immediately.
