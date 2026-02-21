# MERID Swarm - Troubleshooting Playbook

**Quick reference for diagnosing and fixing common issues.**

---

## Table of Contents

1. [No Events Flowing](#1-no-events-flowing)
2. [Consensus Not Forming](#2-consensus-not-forming)
3. [Orders Not Executing](#3-orders-not-executing)
4. [Agent Offline/Unhealthy](#4-agent-offlineunhealthy)
5. [High Latency](#5-high-latency)
6. [Watchdog Alerts](#6-watchdog-alerts)
7. [Mode Violations](#7-mode-violations)
8. [UI Not Updating](#8-ui-not-updating)
9. [Memory Leaks](#9-memory-leaks)
10. [Database Issues](#10-database-issues)

---

## 1. No Events Flowing

### Symptoms
- No opinions appearing in logs
- Telemetry shows 0 events
- UI components empty

### Diagnostic Commands

```bash
# Check if event stream is running
python -c "from observability.event_stream import get_event_stream; print(get_event_stream())"

# Check event subscriber count
curl http://localhost:8000/api/v1/swarm/stats | jq '.swarm.active_agents'

# Check agent logs
tail -100 logs/merid.log | grep -i "opinion"
```

### Common Causes & Fixes

**1. Event stream not initialized**
```python
# Verify in startup logs
grep "Event stream" logs/merid.log

# Fix: Ensure web/main.py initializes event stream
```

**2. Agents not emitting**
```bash
# Check agent has SwarmAgentMixin
grep -r "SwarmAgentMixin" agents/

# Fix: Wire agents with mixin (see AGENT_WIRING_GUIDE.md)
```

**3. Heartbeat loop not started**
```python
# Check agent __init__ has:
asyncio.create_task(self.start_heartbeat_loop())

# Fix: Add heartbeat loop startup
```

**4. EventStream publish failing silently**
```bash
# Add debug logging in emit_strategy_opinion
logger.info(f"Emitting opinion: {opinion.to_dict()}")

# Check logs for emission attempts
```

---

## 2. Consensus Not Forming

### Symptoms
- Opinions emitted but no consensus
- Consensus rate = 0
- UI shows pending opinions

### Diagnostic Commands

```bash
# Check consensus subscriber running
grep "Consensus opinion subscriber" logs/merid.log

# Check pending opinions
python -c "from consensus.consensus_coordinator import get_consensus_coordinator; c = get_consensus_coordinator(); print(c._pending_opinions)"

# Check min quorum setting
grep "min_agents_for_quorum" .env
```

### Common Causes & Fixes

**1. Consensus subscriber not started**
```bash
# Check startup logs
grep "start_opinion_subscriber" logs/merid.log

# Fix: Verify web/main.py includes:
await consensus.start_opinion_subscriber()
```

**2. Not enough opinions (< quorum)**
```bash
# Check opinion count per symbol
curl http://localhost:8000/api/v1/swarm/consensus/stats | jq '.pending_opinions'

# Fix: Ensure ≥3 agents emitting for same symbol
```

**3. Opinion handler exception**
```bash
# Check for errors in consensus logs
grep -i "error.*opinion" logs/merid.log

# Fix: Check _handle_opinion_event for exceptions
```

**4. Opinions for different symbols**
```bash
# Verify all agents use same symbol
grep "symbol.*BTC/USDT" logs/merid.log

# Fix: Ensure all test agents target same symbol
```

**5. Votes not being submitted**
```bash
# Add logging in _try_form_consensus
logger.info(f"Submitting {len(opinions)} votes")

# Check if submit_vote is being called
```

---

## 3. Orders Not Executing

### Symptoms
- Consensus formed but no orders
- Trade intent created but no order event
- Order router errors

### Diagnostic Commands

```bash
# Check execution coordinator running
grep "Execution coordinator started" logs/merid.log

# Check order router mode
curl http://localhost:8000/api/v1/swarm/mode | jq

# Check execution stats
curl http://localhost:8000/api/v1/swarm/execution/stats | jq
```

### Common Causes & Fixes

**1. Execution coordinator not started**
```bash
# Check startup
grep "ExecutionCoordinator" logs/merid.log

# Fix: Add to web/main.py startup
await execution.start()
```

**2. Risk checks failing**
```bash
# Check risk check logs
grep "risk check" logs/merid.log

# Fix: Adjust risk thresholds or fix intent parameters
```

**3. Order router mode mismatch**
```bash
# Check mode configuration
cat .env | grep RUN_MODE

# Fix: Ensure TradeIntent.mode matches global RUN_MODE
```

**4. Live mode not authorized**
```bash
# If trying live mode
grep "LIVE_MODE_AUTHORIZED" .env

# Fix: Only set true if intentionally going live
```

**5. Order router not configured**
```bash
# Check OrderRouter initialization
python -c "from execution.order_router import get_order_router; print(get_order_router())"

# Fix: Ensure order router initialized before execution coordinator
```

---

## 4. Agent Offline/Unhealthy

### Symptoms
- Agent heartbeat stopped
- Agent shows as offline in telemetry
- Participation rate dropped

### Diagnostic Commands

```bash
# Check agent heartbeats
grep "heartbeat.*agent-01" logs/merid.log | tail -20

# Check agent health
curl http://localhost:8000/api/v1/swarm/stats | jq '.agents[] | select(.agent_id == "agent-01")'

# Check for agent exceptions
grep -i "error.*agent-01" logs/merid.log
```

### Common Causes & Fixes

**1. Agent process crashed**
```bash
# Check if process running
ps aux | grep agent

# Fix: Restart agent, investigate crash logs
```

**2. Heartbeat loop stopped**
```bash
# Check for heartbeat task cancellation
grep "heartbeat.*stopped" logs/merid.log

# Fix: Ensure stop_heartbeat_loop() only called on shutdown
```

**3. Agent stuck in processing**
```bash
# Check processing latency
grep "processing.*ms" logs/merid.log | tail -20

# Fix: Add timeout to agent.process() calls
```

**4. Network issues**
```bash
# Check connectivity
ping localhost
curl http://localhost:8000/health

# Fix: Check firewall, network configuration
```

---

## 5. High Latency

### Symptoms
- Pipeline latency >10 seconds
- Slow opinion→order execution
- UI updates delayed

### Diagnostic Commands

```bash
# Check pipeline latency
curl http://localhost:8000/api/v1/swarm/stats | jq '.swarm.pipeline_latency_ms'

# Check agent processing latency
grep "latency" logs/merid.log | tail -50

# Check system resources
top
free -m
```

### Common Causes & Fixes

**1. Agent processing slow**
```bash
# Profile agent.process()
import cProfile
cProfile.run('await agent.process(energy)')

# Fix: Optimize expensive operations, add caching
```

**2. Event queue backed up**
```bash
# Check queue sizes
python -c "from observability.event_stream import get_event_stream; print(get_event_stream()._subscribers)"

# Fix: Increase event processing capacity
```

**3. Database queries slow**
```bash
# Enable query logging
# Check slow query log

# Fix: Add indexes, optimize queries
```

**4. Too many subscribers**
```bash
# Check subscriber count
# Each subscriber adds processing overhead

# Fix: Batch updates, reduce polling frequency
```

**5. Blocking I/O operations**
```bash
# Check for sync operations in async code
# Look for non-async API calls

# Fix: Use async versions (httpx, aiohttp)
```

---

## 6. Watchdog Alerts

### Symptoms
- Continuous watchdog alerts
- False positive alerts
- Missing expected alerts

### Diagnostic Commands

```bash
# Check watchdog status
curl http://localhost:8000/api/v1/swarm/watchdog/alerts | jq

# Check watchdog logs
grep "watchdog" logs/merid.log | tail -50

# Check alert thresholds
cat .env | grep WATCHDOG
```

### Alert-Specific Fixes

**Liveness Alerts**
```bash
# If agents are actually online
# Increase heartbeat timeout threshold
WATCHDOG_LIVENESS_THRESHOLD_SECONDS=90

# Or fix agent heartbeats
```

**Staleness Alerts**
```bash
# If state is actually fresh
# Check timestamp comparison logic
# Adjust staleness threshold
WATCHDOG_STALENESS_THRESHOLD_SECONDS=120
```

**Mode Alerts**
```bash
# If mode is correct
# Check mode enforcement in OrderRouter
# Verify TradingMode enum usage
```

**Consensus Alerts**
```bash
# If consensus is actually forming
# Check threshold for "stuck" opinions
# Adjust timeout for consensus formation
```

---

## 7. Mode Violations

### Symptoms
- Mode violation alerts
- Live calls in simulation/paper mode
- Orders rejected with mode error

### Diagnostic Commands

```bash
# Check current mode
curl http://localhost:8000/api/v1/swarm/mode | jq

# Check for violations
grep "mode violation" logs/merid.log

# Check order router mode
python -c "from execution.order_router import get_order_router; print(get_order_router().config.run_mode)"
```

### Common Causes & Fixes

**1. Mode configuration mismatch**
```bash
# Check .env
cat .env | grep RUN_MODE

# Check code
grep "TradingMode" agents/*.py

# Fix: Ensure all components use same mode
```

**2. Direct broker calls bypassing router**
```bash
# Search for direct broker usage
grep -r "alpaca\|ibkr" execution/

# Fix: Route all orders through OrderRouter
```

**3. Agent mode not set**
```bash
# Check agent initialization
grep "set_trading_mode" agents/strategy_agent.py

# Fix: Call agent.set_trading_mode() in __init__
```

**4. Live mode accidentally enabled**
```bash
# Double-check
cat .env | grep LIVE_MODE_AUTHORIZED

# Fix: Set to false unless intentionally going live
```

---

## 8. UI Not Updating

### Symptoms
- SwarmActivityPanel shows stale data
- OpinionFeed not refreshing
- WebSocket disconnected

### Diagnostic Commands

```bash
# Check WebSocket connection (browser console)
# Look for connection errors

# Check backend WebSocket
grep "websocket" logs/merid.log

# Check if events being broadcast
grep "broadcast.*event" logs/merid.log
```

### Common Causes & Fixes

**1. WebSocket not connected**
```javascript
// Check in browser console
// Look for WebSocket connection URL

// Fix: Verify ws://localhost:8000/ws endpoint
```

**2. Events not being broadcast**
```bash
# Check swarm publishers running
grep "Swarm event publishers started" logs/merid.log

# Fix: Ensure swarm_publishers.py is started
```

**3. useSwarmEvents hook not used**
```typescript
// Verify component imports hook
import { useSwarmEvents } from '../hooks/useSwarmEvents';

// And uses it
const { opinions, consensus } = useSwarmEvents();
```

**4. CORS issues**
```bash
# Check CORS configuration
grep "CORS" web/main.py

# Fix: Add appropriate CORS origins
```

**5. Socket.io version mismatch**
```bash
# Check versions match
npm list socket.io-client
pip show python-socketio

# Fix: Update to compatible versions
```

---

## 9. Memory Leaks

### Symptoms
- Memory usage grows over time
- Eventually runs out of memory
- Performance degrades gradually

### Diagnostic Commands

```bash
# Monitor memory usage
watch -n 5 'ps aux | grep uvicorn'

# Python memory profiling
pip install memory_profiler
python -m memory_profiler scripts/start_swarm_system.py

# Check for large objects
import sys
sys.getsizeof(large_object)
```

### Common Causes & Fixes

**1. Event subscribers not cleaned up**
```python
# Check for orphaned subscribers
# Ensure unsubscribe called on shutdown

# Fix: Always cleanup in finally block
try:
    queue = await event_stream.subscribe()
    # ...
finally:
    await event_stream.unsubscribe(queue)
```

**2. Unbounded event history**
```python
# Check event storage limits
# e.g., opinions_received list growing forever

# Fix: Add max size limits
opinions = deque(maxlen=1000)
```

**3. Circular references**
```python
# Check for objects referencing each other

# Fix: Use weak references where appropriate
import weakref
```

**4. Large log files in memory**
```bash
# Check log rotation
ls -lh logs/

# Fix: Configure log rotation
```

---

## 10. Database Issues

### Symptoms
- Database connection errors
- Slow queries
- Data inconsistencies

### Diagnostic Commands

```bash
# Check database connection
# Depends on your database setup

# Check connection pool
# Monitor active connections

# Check slow queries
# Enable slow query logging
```

### Common Causes & Fixes

**1. Connection pool exhausted**
```python
# Increase pool size
SQLALCHEMY_POOL_SIZE=20
SQLALCHEMY_MAX_OVERFLOW=10

# Fix connection leaks
# Always close connections
```

**2. Missing indexes**
```sql
-- Add indexes for frequently queried columns
CREATE INDEX idx_opinions_symbol ON opinions(symbol);
CREATE INDEX idx_consensus_timestamp ON consensus_decisions(timestamp);
```

**3. Lock contention**
```bash
# Check for deadlocks
# Monitor lock wait times

# Fix: Reduce transaction scope
# Use optimistic locking where possible
```

---

## Quick Diagnostic Script

Create `scripts/diagnose.py`:

```python
"""Quick diagnostic script."""

import asyncio
import httpx

async def diagnose():
    """Run quick diagnostics."""
    
    print("MERID Swarm Diagnostics\n")
    
    async with httpx.AsyncClient() as client:
        # Check health
        try:
            health = await client.get("http://localhost:8000/api/v1/swarm/health")
            print(f"✓ Health: {health.json()['status']}")
        except Exception as e:
            print(f"✗ Health check failed: {e}")
        
        # Check stats
        try:
            stats = await client.get("http://localhost:8000/api/v1/swarm/stats")
            data = stats.json()
            swarm = data["swarm"]
            
            print(f"\nSwarm Stats:")
            print(f"  Active agents: {swarm['active_agents']}/{swarm['total_agents']}")
            print(f"  Participation: {swarm['participation_rate']:.1%}")
            print(f"  Opinions/min: {swarm['opinions_per_minute']:.1f}")
            print(f"  Consensus/min: {swarm['consensus_per_minute']:.1f}")
            print(f"  Latency: {swarm['pipeline_latency_ms']:.0f}ms")
            
            # Check for issues
            issues = data.get("health_issues", {})
            if issues:
                print(f"\n⚠ Health Issues:")
                for agent, issue in issues.items():
                    print(f"  - {agent}: {issue}")
            else:
                print(f"\n✓ No health issues")
        
        except Exception as e:
            print(f"✗ Stats check failed: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose())
```

Run: `python scripts/diagnose.py`

---

## Emergency Procedures

### Complete System Reset

```bash
# 1. Stop all processes
pkill -9 -f uvicorn
pkill -9 -f agent

# 2. Clear caches/temp data (if safe)
rm -rf /tmp/merid_*

# 3. Reset database (if needed - CAREFUL)
# python scripts/reset_database.py

# 4. Restart from clean state
python scripts/start_swarm_system.py --mode simulation --verify
python -m uvicorn web.main:app --reload
```

### Data Capture for Bug Report

```bash
# Capture all diagnostic info
mkdir bug_report_$(date +%Y%m%d_%H%M%S)
cd bug_report_*

# Copy logs
cp -r ../logs .

# Capture state
python ../scripts/diagnose.py > diagnostics.txt
curl http://localhost:8000/api/v1/swarm/stats > swarm_stats.json
curl http://localhost:8000/api/v1/swarm/health > swarm_health.json

# System info
uname -a > system_info.txt
python --version >> system_info.txt
pip list > pip_packages.txt

# Compress
cd ..
tar -czf bug_report_*.tar.gz bug_report_*
```

---

## Getting Help

If issue persists:

1. **Check Documentation**
   - TESTING_GUIDE.md
   - QUICKSTART_SWARM.md
   - INTEGRATION_STATUS.md

2. **Run Full Diagnostics**
   ```bash
   python scripts/diagnose.py
   python scripts/swarm_readiness.py
   ```

3. **Collect Debug Info**
   - Recent logs (last 1000 lines)
   - Current configuration (.env)
   - System stats (CPU, memory)
   - Error stack traces

4. **Create Issue**
   - Include bug report archive
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details

---

**Last Updated**: 2026-02-06  
**Version**: 1.0
