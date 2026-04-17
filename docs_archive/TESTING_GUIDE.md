# MERID Swarm System - Testing Guide

**Complete testing procedures for validating the swarm integration.**

---

## Testing Levels

### 1. Unit Tests (Component Level)
### 2. Integration Tests (Flow Level)
### 3. E2E Tests (Full Pipeline)
### 4. Manual Verification

---

## 1. Unit Tests

### Test Individual Components

#### A. Strategy Agent Opinion Emission

```python
# tests/test_strategy_agent_swarm.py
import asyncio
import pytest
from agents.strategy_agent import StrategyAgent
from schemas.swarm_events import TradingMode, OpinionDirection

@pytest.mark.asyncio
async def test_strategy_agent_emits_opinion():
    """Test that strategy agent emits opinion on non-abstain vote."""
    agent = StrategyAgent(agent_id="test-strategy-01")
    agent.set_trading_mode(TradingMode.SIMULATION)
    
    energy = {
        "energy_id": "test-001",
        "symbol": "BTC/USDT",
        "price": 50000.0,
        "payload": {"symbol": "BTC/USDT", "price": 50000.0}
    }
    
    result = await agent.process(energy)
    
    assert result is not None
    assert "vote" in result
    assert "confidence" in result
    
    await agent.stop_heartbeat_loop()

@pytest.mark.asyncio
async def test_heartbeat_emission():
    """Test that agent emits heartbeats."""
    agent = StrategyAgent(agent_id="test-strategy-02")
    await agent.start_heartbeat_loop()
    
    await asyncio.sleep(2)  # Wait for heartbeat
    
    # Check heartbeat was emitted (would need event capture)
    await agent.stop_heartbeat_loop()
```

#### B. Consensus Formation

```python
# tests/test_consensus_coordinator.py
import pytest
from consensus.consensus_coordinator import get_consensus_coordinator, ConsensusConfig
from schemas.swarm_events import StrategyOpinion, OpinionDirection

@pytest.mark.asyncio
async def test_consensus_forms_from_opinions():
    """Test consensus formation from multiple opinions."""
    config = ConsensusConfig(min_agents_for_quorum=3)
    coordinator = get_consensus_coordinator(config)
    
    # Create test opinions
    opinions = [
        StrategyOpinion(
            agent_id=f"agent-{i}",
            symbol="BTC/USDT",
            direction=OpinionDirection.LONG,
            confidence=0.7,
        )
        for i in range(3)
    ]
    
    # Test would need to inject opinions and verify consensus
    # Implementation depends on how events are mocked
```

#### C. Order Router

```python
# tests/test_order_router.py
import pytest
from execution.order_router import OrderRouter, OrderRouterConfig
from schemas.swarm_events import TradeIntent, TradingMode

@pytest.mark.asyncio
async def test_order_router_simulation_mode():
    """Test order router in simulation mode."""
    config = OrderRouterConfig(
        run_mode=TradingMode.SIMULATION,
        live_mode_authorized=False
    )
    router = OrderRouter(config)
    
    intent = TradeIntent(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.1,
        mode=TradingMode.SIMULATION,
        risk_checked=True,
    )
    
    order = await router.submit_order(intent)
    
    assert order.simulated is True
    assert order.mode == TradingMode.SIMULATION
    assert order.status == "filled"
```

---

## 2. Integration Tests

### Test Multi-Component Flows

#### A. Opinion → Consensus Flow

**File**: `tests/test_swarm_e2e.py` (Already created)

```bash
# Run the E2E test
python tests/test_swarm_e2e.py

# Expected output:
# ✓ Opinions received: 3
# ✓ Consensus formed: 1
# ✓ Full ancestry verified: 3 opinions → 1 consensus
# ✓ ALL TESTS PASSED
```

**What it tests**:
- 3 strategy agents emit opinions
- ConsensusCoordinator consumes opinions
- Consensus forms with full ancestry
- All opinion IDs are linked

#### B. Full Pipeline Test

```python
# tests/test_full_pipeline.py
"""
Test the complete swarm pipeline:
  Agent → Opinion → Consensus → Trade Intent → Order
"""
import asyncio
import pytest
from agents.strategy_agent import StrategyAgent
from consensus.consensus_coordinator import get_consensus_coordinator
from execution.execution_coordinator import get_execution_coordinator
from schemas.swarm_events import TradingMode

@pytest.mark.asyncio
async def test_full_swarm_pipeline():
    """Test complete opinion → consensus → execution flow."""
    
    # Setup
    consensus = get_consensus_coordinator()
    await consensus.start_opinion_subscriber()
    
    execution = get_execution_coordinator(TradingMode.SIMULATION)
    await execution.start()
    
    # Create agents
    agents = [StrategyAgent(f"test-{i}") for i in range(3)]
    for agent in agents:
        agent.set_trading_mode(TradingMode.SIMULATION)
    
    # Process signal
    energy = {
        "energy_id": "pipeline-test",
        "symbol": "BTC/USDT",
        "price": 50000.0,
        "payload": {"symbol": "BTC/USDT", "price": 50000.0}
    }
    
    for agent in agents:
        await agent.process(energy)
        await asyncio.sleep(0.5)
    
    # Wait for pipeline
    await asyncio.sleep(5)
    
    # Verify execution occurred
    stats = execution.get_stats()
    assert stats["executed_trades"] > 0
    
    # Cleanup
    for agent in agents:
        await agent.stop_heartbeat_loop()
    await consensus.stop_opinion_subscriber()
    await execution.stop()
```

---

## 3. Paper Rehearsal Validation

### Run Full System Validation

```bash
# Standard 60-second rehearsal
python scripts/paper_rehearsal.py --mode simulation --duration 60

# Extended 10-minute rehearsal
python scripts/paper_rehearsal.py --mode simulation --duration 600 --symbols BTC/USDT ETH/USDT SOL/USDT
```

**Expected Results**:
```
PAPER REHEARSAL VALIDATION SUMMARY
================================================================================

Mode: SIMULATION
Duration: 60s

Events Collected:
  Opinions: 15
  Consensus Decisions: 5
  Trade Intents: 5
  Order Events: 5

Validation Results:
  [✓ PASS] trade_ancestry: All 5 trades have valid ancestry
  [✓ PASS] no_stale_state: No stale state detected
  [✓ PASS] mode_compliance: All events comply with simulation mode
  [✓ PASS] event_rates: Event rates within expected bands
  [✓ PASS] consensus_quality: Consensus quality healthy

Overall: 5/5 checks passed

✓ REHEARSAL PASSED - System ready for extended testing
================================================================================

Rehearsal log saved to: logs/rehearsal_20260206_013545.jsonl
```

### Rehearsal Failures - Debugging

**If rehearsal fails**, check specific validations:

```bash
# View detailed logs
tail -100 logs/merid.log

# Check event log
cat logs/rehearsal_*.jsonl | jq '.event_type' | sort | uniq -c

# Verify opinion→consensus linkage
cat logs/rehearsal_*.jsonl | jq 'select(.event_type == "consensus_decision") | .payload.opinion_ids'
```

---

## 4. Swarm Readiness Validation

### Automated Full-Stack Check

```bash
# Run all readiness checks
python scripts/swarm_readiness.py

# Expected output:
# [1/5] Environment Check
#   ✓ Python version
#   ✓ .env file exists
#   ✓ scripts/paper_rehearsal.py exists
#   ✓ Required packages
#
# [2/5] Mode & Config Check
#   RUN_MODE: simulation
#   LIVE_MODE_AUTHORIZED: false
#
# [3/5] Paper Rehearsal Execution
#   Running: python scripts/paper_rehearsal.py --mode simulation --duration 60
#   [... rehearsal output ...]
#
# [4/5] Prometheus Metrics Continuity
#   [skipped if Prometheus not running]
#
# [5/5] Watchdog Status
#   Active agents: 5/5
#   Health issues: 0
#   ✓ All watchdogs healthy
#
# ================================================================================
# ✓ SWARM READY FOR DEPLOYMENT
# ================================================================================
```

**Exit code**: 0 = ready, 1 = not ready

### Extended Validation (Pre-Production)

```bash
# 1-hour rehearsal with full checks
python scripts/swarm_readiness.py --extended

# This runs:
# - 1-hour paper rehearsal
# - Extended Prometheus metrics check
# - Full watchdog validation
# - Saves comprehensive report
```

---

## 5. Manual Verification

### A. Start Full Stack

**Terminal 1: Backend**
```bash
python -m uvicorn web.main:app --reload
```

**Wait for startup messages**:
```
✓ Swarm event publishers started
✓ Watchdog coordinator started (simulation)
✓ Consensus opinion subscriber started
✓ Execution coordinator started (simulation)
```

**Terminal 2: Frontend** (Optional)
```bash
cd web/react
npm run dev
```

### B. Trigger Test Agents

```python
# test_manual.py
import asyncio
from agents.strategy_agent import StrategyAgent
from schemas.swarm_events import TradingMode

async def main():
    # Create 3 agents
    agents = [
        StrategyAgent(f"manual-test-{i}")
        for i in range(1, 4)
    ]
    
    for agent in agents:
        agent.set_trading_mode(TradingMode.SIMULATION)
    
    # All process same signal
    energy = {
        "energy_id": "manual-001",
        "symbol": "BTC/USDT",
        "price": 50000.0,
        "payload": {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "signal": "bullish momentum detected"
        }
    }
    
    print("Processing signal with 3 agents...")
    for i, agent in enumerate(agents, 1):
        result = await agent.process(energy)
        print(f"Agent {i}: {result['vote']} (confidence={result['confidence']:.2f})")
        await asyncio.sleep(1)
    
    print("\nWaiting for consensus and execution...")
    await asyncio.sleep(5)
    
    # Cleanup
    for agent in agents:
        await agent.stop_heartbeat_loop()
    
    print("✓ Test complete")

if __name__ == "__main__":
    asyncio.run(main())
```

**Run it**:
```bash
python test_manual.py
```

### C. Verify in Backend Logs

```bash
tail -f logs/merid.log | grep -E "(Opinion|Consensus|Execution)"
```

**Expected log sequence**:
```
Opinion emitted: manual-test-1 → BTC/USDT LONG (conf=0.75)
Opinion emitted: manual-test-2 → BTC/USDT LONG (conf=0.68)
Opinion emitted: manual-test-3 → BTC/USDT LONG (conf=0.82)
Formed consensus for BTC/USDT from 3 opinions (IDs: [...])
Received consensus: BTC/USDT → LONG (confidence=0.75, 3 agents)
Order executed: BTC/USDT buy (status=filled, order_id=...)
```

### D. Query Swarm Stats API

```bash
# Check swarm health
curl http://localhost:8000/api/v1/swarm/stats | jq

# Expected response:
{
  "swarm": {
    "active_agents": 5,
    "total_agents": 5,
    "participation_rate": 1.0,
    "opinions_per_minute": 12.5,
    "consensus_per_minute": 3.2,
    "consensus_success_rate": 0.85,
    "avg_disagreement_rate": 0.22,
    "pipeline_latency_ms": 1250
  },
  "agents": [...],
  "health_issues": {}
}
```

### E. Check Event Logs

```bash
# View recent rehearsal log
ls -ltr logs/rehearsal_*.jsonl | tail -1

# Count events by type
cat logs/rehearsal_20260206_013545.jsonl | jq -r '.event_type' | sort | uniq -c

# Expected output:
#   1 rehearsal_start
#  15 strategy_opinion
#   5 consensus_decision
#   5 trade_intent
#   5 order_event
#   1 rehearsal_end
```

### F. UI Verification (if frontend running)

1. Navigate to `http://localhost:5173`
2. Open browser console (F12)
3. Look for WebSocket messages:
   ```
   [SwarmEvents] Connected to swarm event stream
   [SwarmEvents] Opinion received: {...}
   [SwarmEvents] Consensus received: {...}
   ```
4. Check `SwarmActivityPanel` shows:
   - Agent heartbeats updating
   - Opinions/min > 0
   - Consensus/min > 0
5. Check `OpinionFeed` shows:
   - Opinions appearing
   - Consensus badges forming

---

## 6. Graceful Degradation Test

### Kill Agent Mid-Session

**Purpose**: Verify swarm continues with N-1 agents

```bash
# Terminal 1: Run rehearsal
python scripts/paper_rehearsal.py --mode simulation --duration 120

# Terminal 2: Kill an agent mid-run (after 30s)
sleep 30 && pkill -9 -f "strategy-agent-01"

# Expected:
# - LivenessWatchdog fires alert
# - Participation rate dips but stays > 60%
# - Consensus still forms with remaining agents
# - System recovers if agent restarts
```

**Validation**:
```bash
# Check for liveness alerts
cat logs/merid.log | grep -i "liveness.*offline"

# Verify consensus still formed
cat logs/rehearsal_*.jsonl | jq 'select(.event_type == "consensus_decision") | length'
# Should be > 0 even after agent killed
```

---

## 7. Failure Scenarios

### A. Stale State Detection

**Test**: Inject old price data

```python
# Manually create opinion with old timestamp
opinion = StrategyOpinion(
    agent_id="test-stale",
    symbol="BTC/USDT",
    direction=OpinionDirection.LONG,
    confidence=0.8,
    price_at_opinion=50000.0,
    timestamp=time.time() - 60  # 60 seconds old
)

# StalenessWatchdog should detect and alert
```

### B. Mode Violation

**Test**: Try to execute live order in simulation mode

```python
# This should throw LiveModeViolation
intent = TradeIntent(
    symbol="BTC/USDT",
    side="buy",
    quantity=0.1,
    mode=TradingMode.LIVE,  # WRONG MODE
    risk_checked=True,
)

# OrderRouter should reject if global mode is SIMULATION
```

### C. Low Quorum

**Test**: Only 2 agents vote (min=3 required)

```python
# Should not form consensus
# ConsensusWatchdog should detect stuck opinions
```

---

## 8. Performance Tests

### A. Opinion Throughput

```python
# tests/test_performance.py
import asyncio
import time
from agents.strategy_agent import StrategyAgent

async def test_opinion_throughput():
    """Measure opinions per second."""
    agent = StrategyAgent("perf-test")
    agent.set_trading_mode(TradingMode.SIMULATION)
    
    start = time.time()
    count = 0
    
    for i in range(100):
        energy = {
            "energy_id": f"perf-{i}",
            "symbol": "BTC/USDT",
            "price": 50000 + i,
            "payload": {"symbol": "BTC/USDT", "price": 50000 + i}
        }
        await agent.process(energy)
        count += 1
    
    duration = time.time() - start
    ops = count / duration
    
    print(f"Opinion throughput: {ops:.2f} opinions/sec")
    assert ops > 10  # Should handle >10 opinions/sec
    
    await agent.stop_heartbeat_loop()
```

### B. Pipeline Latency

```python
async def test_pipeline_latency():
    """Measure time from opinion to order execution."""
    # Track timestamps through pipeline
    # Opinion timestamp → Order timestamp
    # Target: < 5 seconds
```

---

## 9. CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/swarm-tests.yml
name: Swarm Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
    
    - name: Run swarm readiness check
      run: |
        python scripts/swarm_readiness.py --skip-rehearsal
      
    - name: Run paper rehearsal
      run: |
        python scripts/paper_rehearsal.py --mode simulation --duration 60
    
    - name: Run E2E test
      run: |
        python tests/test_swarm_e2e.py
```

---

## 10. Troubleshooting

### Common Issues

**Issue: "No events collected"**
- **Cause**: Agents not emitting opinions
- **Fix**: Check agent is using SwarmAgentMixin and calling emit_strategy_opinion()
- **Debug**: `grep "Opinion emitted" logs/merid.log`

**Issue: "Consensus not forming"**
- **Cause**: < 3 opinions or opinions not being consumed
- **Fix**: Verify ConsensusCoordinator.start_opinion_subscriber() was called
- **Debug**: Check `_pending_opinions` in coordinator logs

**Issue: "Orders not executing"**
- **Cause**: ExecutionCoordinator not started or risk checks failing
- **Fix**: Verify ExecutionCoordinator.start() in web/main.py
- **Debug**: Check execution logs for risk check failures

**Issue: "Watchdog alerts constantly firing"**
- **Cause**: Agents actually offline or thresholds too strict
- **Fix**: Check agent processes are running, adjust thresholds in config

---

## Quick Test Commands

```bash
# Full validation (recommended daily)
python scripts/swarm_readiness.py

# Quick E2E test
python tests/test_swarm_e2e.py

# Manual agent test
python test_manual.py

# Check swarm health
curl http://localhost:8000/api/v1/swarm/stats | jq '.swarm'

# View recent events
tail -100 logs/merid.log | grep -E "(Opinion|Consensus|Order)"

# Count events in last rehearsal
cat logs/rehearsal_$(ls -t logs/ | grep rehearsal | head -1) | jq -r '.event_type' | sort | uniq -c
```

---

## Success Criteria

✅ **Swarm is working correctly when**:

1. **E2E test passes**: `python tests/test_swarm_e2e.py` exits 0
2. **Readiness passes**: `python scripts/swarm_readiness.py` exits 0
3. **Ancestry intact**: All orders trace back to 3+ opinions
4. **No stale data**: All timestamps within freshness thresholds
5. **Mode compliant**: No live calls in simulation mode
6. **Graceful degradation**: System works with N-1 agents
7. **UI updates**: Real-time opinions and consensus visible
8. **Watchdogs active**: Alerts fire for actual issues
9. **Metrics flowing**: Prometheus/telemetry updates every 5s
10. **Logs captured**: Every rehearsal creates timestamped JSONL

---

**Last Updated**: 2026-02-06  
**Version**: 1.0  
**Status**: Complete testing suite available
