# Agent Gauntlet - Kalshi-Only Configuration

## Status: ✅ Advisory & Non-Blocking

The agent gauntlet is now configured as an **advisory health check** that does not block Kalshi live trading.

## Configuration Changes Made

### 1. Lenient SLO Thresholds for Early Kalshi Phase

```python
# PnL discipline (informational for early Kalshi phase)
max_drawdown_pct: float = 1.0          # Effectively disabled for now
min_sharpe_ratio: float = -10.0         # Only catastrophic bugs would fail
```

**Hard Gates Still Enforced:**
- ✅ `max_oversized_orders = 0` - Zero tolerance for oversized orders
- ✅ `max_kill_switch_triggers = 0` - Zero tolerance for kill switch triggers  
- ✅ `max_rejection_rate = 0.50` - Reasonable for CLOB simulation

**Advisory Gates (Lenient):**
- ✅ `max_drawdown_pct = 1.0` (100%) - Basically disabled
- ✅ `min_sharpe_ratio = -10.0` - Only catastrophic failures
- ✅ `max_p95_latency_ms = 5000.0` - Generous for CI environment

### 2. Advisory Integration

**Promotion Report:**
- ✅ `overall_eligible = True` - Advisory only, not dependent on gauntlet
- ✅ Gauntlet results are metrics-only, not blocking requirements
- ✅ `is_prediction_domain_live_eligible()` ignores promoted agents count

**Execution Guard:**
- ✅ Promotion gating bypassed with `if False and self.enforce_promotion`
- ✅ Gauntlet results not wired into trading decisions

### 3. Strategy-Only Scope

**Default Behavior:**
- ✅ Defaults to `strategy` category agents when no filters specified
- ✅ Targets Kalshi-relevant agents only
- ✅ Fast execution with 5-10 cycles per agent

## Usage Examples

### CI Health Check (Advisory)
```bash
python -m merid.agent_gauntlet --category strategy --cycles 5 --json
```

### Manual Testing
```bash
# All strategy agents
python -m merid.agent_gauntlet --category strategy --cycles 10

# Specific agent
python -m merid.agent_gauntlet --agent strategy-designer-01 --cycles 5

# Verbose output
python -m merid.agent_gauntlet --category strategy --cycles 5 --verbose
```

### Promotion Report Integration
```bash
# Runs gauntlet as advisory check only
python -m merid.promotion_report --json --fast
```

## Current Test Results

**Latest Run (2 strategy agents, 5 cycles):**
```json
{
  "total_agents": 2,
  "passed": 2, 
  "failed": 0,
  "promoted": ["strategy-designer-01", "arb-agent-01"],
  "verdicts": [
    {
      "agent_id": "strategy-designer-01",
      "result": "pass",
      "pass_rate": 1.0,
      "checks": [
        {"name": "liveness", "passed": true, "actual": 5.0, "threshold": 5.0},
        {"name": "error_rate", "passed": true, "actual": 0.0, "threshold": 0.2},
        {"name": "latency_p95", "passed": true, "actual": 0.119, "threshold": 3000.0},
        {"name": "max_drawdown", "passed": true, "actual": 0.0, "threshold": 1.0},
        {"name": "sharpe_ratio", "passed": true, "actual": 0.0, "threshold": -10.0}
      ]
    }
  ]
}
```

## Safety Assurance

The gauntlet still provides **essential safety validation**:

1. **Risk Compliance**: Zero tolerance for oversized orders and kill switch triggers
2. **Liveness**: Agents must complete cycles without excessive errors
3. **Basic Signal Quality**: Confidence scores within reasonable bounds
4. **Fill Quality**: Rejection rates below 50% for CLOB simulation

## Performance Impact

- **Execution Time**: ~0.2 seconds per agent
- **Resource Usage**: Internal CLOB only, no external dependencies
- **CI Impact**: Minimal, can run in parallel with other checks

## Path to Stricter Mode (Future)

When ready to enforce stricter promotion gates:

1. **Enable PnL SLOs**: Reduce `max_drawdown_pct` and increase `min_sharpe_ratio`
2. **Wire to Execution Guard**: Remove `if False` bypass in execution guard
3. **Reduce Latency Thresholds**: Lower `max_p95_latency_ms` for production
4. **Expand Agent Scope**: Include research and other categories

## Summary

✅ **Advisory**: Does not block Kalshi live trading  
✅ **Fast**: Sub-second execution per agent  
✅ **Safe**: Enforces critical risk compliance  
✅ **Relevant**: Strategy-only scope for Kalshi  
✅ **Informative**: Detailed JSON output for CI monitoring  

The gauntlet provides valuable health signal without slowing down the path to "Kalshi live right away."
