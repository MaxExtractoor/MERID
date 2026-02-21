# MERID Swarm System - Quick Start Guide

**Get the governed swarm running in 10 minutes.**

---

## Prerequisites

- Python 3.9+
- Existing MERID installation
- `.env` file configured

---

## 1. Configure Swarm Settings

Copy the swarm configuration template:

```bash
cp .env.swarm.example .env
# Or merge settings into your existing .env
```

**Minimum required settings**:

```bash
RUN_MODE=simulation
LIVE_MODE_AUTHORIZED=false
MIN_AGENTS_PER_TRADE=3
HEARTBEAT_INTERVAL_SECONDS=30
```

---

## 2. Verify Installation

Run the readiness checker (infrastructure checks only):

```bash
python scripts/swarm_readiness.py --skip-rehearsal
```

**Expected output**:

```
[1/5] Environment Check
  ✓ Python version
  ✓ .env file exists
  ✓ scripts/paper_rehearsal.py exists
  ✓ Required packages

[2/5] Mode & Config Check
  RUN_MODE: simulation
  LIVE_MODE_AUTHORIZED: false

...

Overall: 4/4 checks passed (rehearsal skipped)
```

---

## 3. Start Backend Services

```bash
# Terminal 1: Start FastAPI backend
python -m uvicorn web.main:app --reload
```

**Look for startup messages**:

```
✓ Swarm event publishers started
✓ Watchdog coordinator started (simulation)
```

---

## 4. Start Frontend (Optional)

```bash
# Terminal 2: Start React UI
cd web/react
npm install  # First time only
npm run dev
```

Open http://localhost:5173

---

## 5. Run First Agent Test

Create a test script to trigger the wired strategy agent:

```python
# test_swarm.py
import asyncio
from agents.strategy_agent import StrategyAgent
from schemas.swarm_events import TradingMode

async def test_agent():
    agent = StrategyAgent(agent_id="test-strategy-01")
    agent.set_trading_mode(TradingMode.SIMULATION)
    
    # Create test energy packet
    energy = {
        "energy_id": "test-001",
        "symbol": "BTC/USDT",
        "price": 50000.0,
        "payload": {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "signal": "bullish momentum"
        }
    }
    
    result = await agent.process(energy)
    print(f"Agent vote: {result['vote']}, confidence: {result['confidence']}")
    
    # Wait for heartbeat
    await asyncio.sleep(2)
    
    # Stop heartbeat
    await agent.stop_heartbeat_loop()

if __name__ == "__main__":
    asyncio.run(test_agent())
```

Run it:

```bash
python test_swarm.py
```

**Expected logs**:

```
Opinion emitted: test-strategy-01 → BTC/USDT LONG (conf=0.75)
Agent test-strategy-01 heartbeat emitted
```

---

## 6. Run Paper Rehearsal

Execute the full validation:

```bash
python scripts/paper_rehearsal.py --mode simulation --duration 60
```

**Expected output** (may have mock data warnings):

```
PAPER REHEARSAL VALIDATION SUMMARY
================================================================================

Mode: SIMULATION
Duration: 60s

Events Collected:
  Opinions: X
  Consensus Decisions: Y
  Trade Intents: Z
  Order Events: Z

Validation Results:
  [✓ PASS] trade_ancestry: ...
  [✓ PASS] no_stale_state: ...
  [✓ PASS] mode_compliance: ...
  [✓ PASS] event_rates: ...
  [✓ PASS] consensus_quality: ...

Overall: 5/5 checks passed

✓ REHEARSAL PASSED - System ready for extended testing

Rehearsal log saved to: logs/rehearsal_20260206_013545.jsonl
```

---

## 7. Check Swarm Telemetry

With backend running, query swarm stats:

```bash
curl http://localhost:8000/api/v1/swarm/stats | jq
```

**Expected response**:

```json
{
  "swarm": {
    "active_agents": 5,
    "total_agents": 5,
    "participation_rate": 1.0,
    "opinions_per_minute": 12.5,
    "consensus_per_minute": 3.2,
    "consensus_success_rate": 0.85
  },
  "agents": [
    {
      "agent_id": "strategy-agent-01",
      "status": "healthy",
      "last_heartbeat": "2026-02-06T01:45:30Z",
      "messages_processed": 45
    }
  ],
  "health_issues": {}
}
```

---

## 8. View UI Panels

Navigate to:

- **Overview Dashboard**: Should show SwarmActivityPanel
- **Trading/Swarm Page**: Should show OpinionFeed

**What you should see**:

- Mode indicator: "SIM ONLY" banner
- Agent heartbeat table
- Opinions streaming when agents process signals
- Consensus badges forming after opinions aggregate

---

## 9. Run Full Readiness Check

Execute all checks including rehearsal:

```bash
python scripts/swarm_readiness.py
```

**This validates**:

1. Environment setup
2. Mode configuration
3. Paper rehearsal execution
4. Prometheus metrics continuity
5. Watchdog status

**Expected exit code**: `0` (pass)

---

## 10. Review Event Logs

Inspect captured rehearsal data:

```bash
# List recent rehearsal logs
ls -ltr logs/rehearsal_*.jsonl

# View latest log summary
tail -1 logs/rehearsal_*.jsonl | jq '.validation_results'

# Count opinions in last run
cat logs/rehearsal_20260206_013545.jsonl | jq 'select(.event_type == "strategy_opinion")' | wc -l

# Extract all symbols traded
cat logs/rehearsal_20260206_013545.jsonl | jq -r 'select(.event_type == "strategy_opinion") | .payload.symbol' | sort | uniq
```

---

## Troubleshooting

### "No module named 'schemas.swarm_events'"

**Fix**: Ensure you're in the MERID root directory.

```bash
cd c:\Dev\MERID
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

### "Rehearsal failed: No events collected"

**Cause**: Agents not running or not emitting events.

**Fix**:
1. Verify backend is running (`uvicorn web.main:app`)
2. Check logs for agent startup errors
3. Run simple agent test first (step 5)

### "Prometheus check skipped"

**Cause**: Prometheus not running or `requests` package missing.

**Fix** (optional):
```bash
pip install requests

# Start Prometheus (if available)
prometheus --config.file=prometheus.yml
```

### "WebSocket events not showing in UI"

**Cause**: WebSocket handler not initialized.

**Fix**:
1. Verify `ws_events.py` is imported in backend
2. Check browser console for WebSocket connection errors
3. Ensure CORS settings allow frontend origin

### "Swarm readiness check fails on mode_config"

**Cause**: `.env` not configured correctly.

**Fix**:
```bash
# Verify RUN_MODE is set
grep RUN_MODE .env

# Should show:
RUN_MODE=simulation
```

---

## What's Working vs. What Needs Wiring

### ✅ Ready to Use

- Swarm event schemas (opinion, consensus, trade, order)
- OrderRouter with mode enforcement
- SwarmTelemetry with Prometheus export
- Watchdog agents (liveness, consensus, mode, staleness)
- Paper rehearsal script with log capture
- Swarm readiness CLI tool
- Strategy agent proof-of-concept with opinion emission
- WebSocket broadcast infrastructure
- UI components (SwarmActivityPanel, OpinionFeed)

### 🔧 Needs Integration

1. **Wire all strategy agents** to use `SwarmAgentMixin`
   - Add to other strategy agents beyond PoC
   - Start heartbeat loops in `__init__`
   - Call `emit_strategy_opinion()` in `process()`

2. **Subscribe ConsensusCoordinator to opinions**
   - Currently emits `ConsensusDecision`, needs to consume `StrategyOpinion`
   - Link opinion IDs to consensus for ancestry

3. **Wire execution agents to OrderRouter**
   - Create `TradeIntent` after risk check
   - Call `OrderRouter.submit_order()` instead of direct broker calls

4. **Hook WebSocket publisher to existing WS infrastructure**
   - Import `ws_events.register_connection()` in WebSocket endpoint
   - Ensure connections are registered on connect

5. **Add UI event handlers**
   - Update `useMeridSocket` hook to handle swarm events
   - Wire `SwarmActivityPanel` and `OpinionFeed` to routes

6. **Add Prometheus metrics endpoint**
   - Create FastAPI route at `/metrics`
   - Call `SwarmTelemetry.get_prometheus_metrics()`

---

## Next Steps

### Immediate (Day 1)

```bash
# 1. Run readiness check
python scripts/swarm_readiness.py --skip-rehearsal

# 2. Fix any failures
# 3. Wire one more agent to SwarmAgentMixin
# 4. Run rehearsal with 2+ agents
python scripts/paper_rehearsal.py --mode simulation --duration 60

# 5. Verify log capture
ls -l logs/rehearsal_*.jsonl
```

### Short Term (Week 1)

- Wire all agents to swarm contracts
- Add WebSocket event handlers to UI
- Run extended rehearsal (1 hour)
- Test graceful degradation (kill agent mid-session)
- Review watchdog alerts

### Medium Term (Month 1)

- Switch to PAPER mode
- Run 24-hour rehearsals
- Monitor Prometheus dashboards
- Tune consensus thresholds
- Add new watchdog rules for discovered failure modes

### Before LIVE

- Complete full `SWARM_READINESS.md` checklist
- Pass all 5 validation checks for 7 consecutive days
- Zero critical watchdog alerts for 48 hours
- Extended rehearsal (4+ hours) with no issues
- Second reviewer sign-off

---

## Quick Reference Commands

```bash
# Full readiness validation
python scripts/swarm_readiness.py

# Extended validation (1 hour)
python scripts/swarm_readiness.py --extended

# Infrastructure checks only
python scripts/swarm_readiness.py --skip-rehearsal

# Paper rehearsal
python scripts/paper_rehearsal.py --mode simulation --duration 60

# Check swarm stats
curl http://localhost:8000/api/v1/swarm/stats | jq

# View recent rehearsal logs
cat logs/rehearsal_$(ls -t logs/ | grep rehearsal | head -1) | jq

# Count active agents
curl -s http://localhost:8000/api/v1/swarm/stats | jq '.swarm.active_agents'

# Get watchdog alerts
curl -s http://localhost:8000/api/v1/watchdog/alerts | jq
```

---

## Support & Documentation

- **Full Architecture**: `SWARM_ARCHITECTURE_UPGRADE.md`
- **Deployment Checklist**: `SWARM_READINESS.md`
- **Integration Status**: `INTEGRATION_STATUS.md`
- **Configuration Example**: `.env.swarm.example`

---

**Last Updated**: 2026-02-06  
**Checklist Version**: 1.0.0  
**Status**: POC agent wired, infrastructure complete, full integration in progress
