# MERID LAUNCH CONSOLE
## One-Page Operator Interface for Launch Execution

**Version:** 1.0  
**Date:** January 12, 2026  
**Purpose:** Single-screen reference for operators during launch  

---

## Pre-Launch Setup

### Terminal Windows (4 Required)

**Terminal 1: Command Execution**
```bash
cd c:\Dev\MERID
venv\Scripts\activate
# Execute launch commands here
```

**Terminal 2: Log Monitoring**
```bash
cd c:\Dev\MERID
tail -f logs/merid.log
# Watch for errors, warnings, state changes
```

**Terminal 3: Python Console**
```bash
cd c:\Dev\MERID
venv\Scripts\activate
python
# For interactive queries and verification
```

**Terminal 4: Neo4j Queries**
```bash
# Neo4j Browser: http://localhost:7474
# Or use cypher-shell for CLI queries
```

### Browser Tabs (5 Required)

1. **Trading Dashboard:** `http://localhost:8000/dashboard`
2. **Operator Console:** `http://localhost:8000/operator`
3. **Risk Dashboard:** `http://localhost:8000/risk`
4. **Neo4j Browser:** `http://localhost:7474`
5. **Launch Runbook:** `file:///c:/Dev/MERID/LAUNCH_DAY_RUNBOOK.md`

---

## Stage 0 Launch Commands

### Step 1: Freeze Code (T-0, 09:00)
```bash
# Terminal 1
git log -1 --oneline
git tag merid-prod-v1.0-stage0
git push origin merid-prod-v1.0-stage0
```

### Step 2: Set Stage 0 Config (T+5min, 09:05)
```bash
# Edit .env
DEPLOYMENT_STAGE=STAGE_0_SIMULATION
MAX_CAPITAL=0
KILL_SWITCH_ACTIVE=true

# Verify
grep "DEPLOYMENT_STAGE\|MAX_CAPITAL\|KILL_SWITCH" .env
```

### Step 3: Start Services (T+15min, 09:15)
```bash
# Terminal 1
python startup.py 2>&1 | tee logs/launch_startup_20260112_0915.log

# Expected: ✓ Components Initialized (8)
# Expected: ✓ Health Checks Passed (4)
# Expected: 🚀 MERID IS READY FOR OPERATION
```

### Step 4: Run Tests (T+20min, 09:20)
```bash
# Terminal 1
python run_tests.py 2>&1 | tee logs/launch_tests_20260112_0920.log

# Expected: SUMMARY: 7/7 tests passed (0 failed)
# Expected: 🎉 ALL TESTS PASSED - SYSTEM READY
```

### Step 5: Check Dashboards (T+25min, 09:25)
**Browser Tabs 1-3:**
- Status: "SIMULATION MODE"
- Capital: $0
- Kill Switch: ACTIVE (red)
- Open Incidents: 0

### Step 6: Verify Neo4j (T+35min, 09:35)
```python
# Terminal 3 (Python console)
from core.graph_service import get_graph_service
graph = get_graph_service()
health = graph.get_system_health_summary()
print(f"Proposals: {health['total_proposals']}")
print(f"Executions: {health['total_executions']}")
print(f"Incidents: {health['open_incidents']}")
```

### Step 7: Kill Switch Drill (T+40min, 09:40)
```python
# Terminal 3 (Python console)
from core.execution_controller import get_execution_controller
controller = get_execution_controller()

# Test deactivation
controller.deactivate_kill_switch("Launch test")
print(f"Kill switch: {controller.kill_switch_active}")  # False

# Re-activate
controller.activate_kill_switch("Launch test complete")
print(f"Kill switch: {controller.kill_switch_active}")  # True
```

---

## Stage 1 Launch Commands

### Step 9: Transition Config (Day 4, 09:00)
```bash
# Edit .env
DEPLOYMENT_STAGE=STAGE_1_MICRO
MAX_CAPITAL=100
KILL_SWITCH_ACTIVE=true

# Verify
grep "DEPLOYMENT_STAGE\|MAX_CAPITAL" .env
```

### Step 10: Restart Services (Day 4, 09:15)
```bash
# Terminal 1
pkill -TERM -f merid
# Wait for clean shutdown (watch Terminal 2)

python startup.py 2>&1 | tee logs/stage1_startup_20260116_0915.log
```

### Step 11: Verify Risk Limits (Day 4, 09:25)
```python
# Terminal 3
from core.risk_envelope import get_risk_envelope_manager
risk_mgr = get_risk_envelope_manager()
envelope = risk_mgr.envelope
print(f"Max position: ${envelope.max_position_size_usd}")
print(f"Max leverage: {envelope.max_leverage}x")
print(f"Max drawdown: {envelope.max_drawdown_pct*100}%")
```

### Step 13: Enable Trading (Day 4, 09:45)
```python
# Terminal 3
from core.execution_controller import get_execution_controller
controller = get_execution_controller()
controller.deactivate_kill_switch("Stage 1 launch - Ops Lead approval")
print("🚀 LIVE TRADING ENABLED")
```

---

## Real-Time Monitoring Queries

### System Health
```python
# Terminal 3 - Run every 15 minutes
from core.graph_service import get_graph_service
graph = get_graph_service()
health = graph.get_system_health_summary()
print(f"""
System Health:
  Proposals: {health['total_proposals']}
  Orders: {health['total_orders']}
  Executions: {health['total_executions']}
  Open Incidents: {health['open_incidents']}
  Circuit Breakers (24h): {health['circuit_breakers_24h']}
""")
```

### Wallet Exposure
```python
# Terminal 3 - Run every 30 minutes
from core.graph_service import get_graph_service
graph = get_graph_service()
exposure = graph.get_wallet_exposure("trading_eth_1")
for exp in exposure:
    print(f"{exp['asset']} on {exp['venue']}: ${exp['exposure_usd']:,.2f}")
```

### Recent Trades
```python
# Terminal 3 - After each trade
from core.graph_integration import create_operator_adapter
adapter = create_operator_adapter()
dashboard = adapter.get_system_dashboard()
print(f"Recent executions: {dashboard['health']['total_executions']}")
```

### Trade Lineage
```python
# Terminal 3 - For specific trade
from core.graph_integration import create_operator_adapter
adapter = create_operator_adapter()
lineage = adapter.explain_trade("[execution_id]")
print(f"Proposal: {lineage['proposal']}")
print(f"Order: {lineage['order']}")
print(f"Execution: {lineage['execution']}")
print(f"Assertions: {len(lineage['assertions'])}")
```

---

## Dashboard Monitoring Checklist

### Every 15 Minutes
- [ ] Trading Dashboard: No unexpected positions
- [ ] Risk Dashboard: Utilization within limits
- [ ] Incidents Dashboard: No new incidents
- [ ] Terminal 2 (Logs): No ERROR or CRITICAL messages

### Every Hour
- [ ] Run system health query (above)
- [ ] Check wallet exposure (above)
- [ ] Verify Neo4j query performance (<50ms)
- [ ] Review agent performance metrics

### Every 4 Hours
- [ ] Run `python run_tests.py` (should pass 7/7)
- [ ] Generate agent performance report
- [ ] Review circuit breaker status
- [ ] Check for compliance alerts

---

## Key Metrics to Watch

### Trading Metrics (Dashboard Tab 1)
```
✓ Fill Rate: >90% (green)
⚠ Fill Rate: 80-90% (yellow)
✗ Fill Rate: <80% (red - investigate)

✓ Error Rate: <5% (green)
⚠ Error Rate: 5-10% (yellow)
✗ Error Rate: >10% (red - kill switch)

✓ Slippage: <1.5x (green)
⚠ Slippage: 1.5-2.0x (yellow)
✗ Slippage: >2.0x (red - MEV suspected)
```

### Risk Metrics (Dashboard Tab 3)
```
✓ Position Utilization: <80% of limit (green)
⚠ Position Utilization: 80-95% (yellow)
✗ Position Utilization: >95% (red - approaching limit)

✓ Drawdown: <3% (green)
⚠ Drawdown: 3-5% (yellow)
✗ Drawdown: >5% (red - circuit breaker triggers)
```

### System Metrics (Operator Console Tab 2)
```
✓ Service Uptime: >99% (green)
⚠ Service Uptime: 95-99% (yellow)
✗ Service Uptime: <95% (red - investigate)

✓ Neo4j Latency: <50ms (green)
⚠ Neo4j Latency: 50-100ms (yellow)
✗ Neo4j Latency: >100ms (red - performance issue)
```

---

## Emergency Actions

### EMERGENCY STOP (Any Time)
```python
# Terminal 3 - IMMEDIATE
from core.execution_controller import get_execution_controller
controller = get_execution_controller()
controller.activate_kill_switch("EMERGENCY STOP - [reason]")
print(f"Kill switch: {controller.kill_switch_active}")  # Must be True
```

### Verify Trading Stopped
```bash
# Terminal 2 - Check logs
grep "KILL_SWITCH" logs/merid.log | tail -5

# Dashboard Tab 1 - Verify
# Status should show: "TRADING HALTED - KILL SWITCH ACTIVE"
```

### Escalate
```
Level 2: Technical Lead - [Phone]
Level 3: Executive - [Phone]
Emergency: [Phone]
```

---

## Neo4j Queries (Browser Tab 4)

### Check Proposal Count
```cypher
MATCH (p:TradeProposal)
RETURN count(p) AS total_proposals
```

### Recent Executions
```cypher
MATCH (e:Execution)
WHERE e.timestamp > datetime() - duration({hours: 1})
RETURN e.execution_id, e.size_usd, e.price, e.timestamp
ORDER BY e.timestamp DESC
LIMIT 10
```

### Active Incidents
```cypher
MATCH (inc:Incident {status: 'OPEN'})
RETURN inc.incident_id, inc.type, inc.severity, inc.created_at
ORDER BY inc.created_at DESC
```

### Wallet Exposure
```cypher
MATCH (w:Wallet {wallet_id: 'trading_eth_1'})-[:OWNS_POSITION]->(pos:Position)-[:ON_ASSET]->(a:Asset)
OPTIONAL MATCH (pos)-[:ON_VENUE]->(v:Venue)
RETURN a.asset_id AS asset,
       v.venue_id AS venue,
       sum(pos.net_size_usd) AS exposure_usd
```

### Trade Lineage
```cypher
MATCH (e:Execution {execution_id: $execution_id})
MATCH (e)<-[:FILLED_AS]-(o:Order)<-[:EXECUTED_AS]-(p:TradeProposal)
OPTIONAL MATCH (p)-[:ASSERTED_BY]->(as:Assertion)
OPTIONAL MATCH (ag:Agent)-[:CREATED]->(p)
RETURN p, o, e, collect(as) AS assertions, collect(ag) AS agents
```

---

## Log Patterns to Watch (Terminal 2)

### Good Patterns
```
✓ "Component initialized successfully"
✓ "Health check passed"
✓ "Proposal submitted: [id]"
✓ "Risk check passed"
✓ "Order executed successfully"
✓ "Neo4j query completed in [X]ms"
```

### Warning Patterns
```
⚠ "Proposal rejected: risk limit"
⚠ "High slippage detected"
⚠ "Data feed latency spike"
⚠ "Circuit breaker threshold approaching"
```

### Critical Patterns (Immediate Action)
```
✗ "KILL_SWITCH activated"
✗ "Circuit breaker TRIGGERED"
✗ "Sanctions hit detected"
✗ "Neo4j connection lost"
✗ "CRITICAL: [any message]"
✗ "ERROR: [repeated pattern]"
```

---

## Status Reporting Template

### Every 2 Hours (Day 1)
```
MERID Status Update - [Time]
Stage: [0/1]
Status: [Green/Yellow/Red]

Metrics:
- Trades: [count]
- PnL: $[amount]
- Incidents: [count]
- Uptime: [%]

Issues: [None / List]
Next Update: [Time]
```

### Slack/Email Format
```
#merid-launch
🟢 Stage 0 - Hour 2 - All Systems Normal
📊 0 trades (simulation), 0 incidents, 100% uptime
📈 All metrics green, no issues
⏰ Next update: 13:00
```

---

## Decision Points

### Continue Stage 0?
```
✓ All metrics green → Continue
⚠ Minor issues → Continue with monitoring
✗ Critical issues → Activate kill switch, investigate
```

### Advance to Stage 1?
```
✓ 3-5 days stable, all criteria met → Advance
⚠ Some criteria not met → Extend Stage 0
✗ Critical issues → Do not advance
```

### Continue Stage 1?
```
✓ All metrics green → Continue
⚠ Minor issues → Continue with enhanced monitoring
✗ Critical issues → Rollback to Stage 0
```

---

## Quick Reference Card

### Critical Commands
```bash
# Start
python startup.py

# Test
python run_tests.py

# Emergency Stop
python -c "from core.execution_controller import get_execution_controller; get_execution_controller().activate_kill_switch('Emergency')"

# Status
curl http://localhost:8000/operator/dashboard

# Logs
tail -f logs/merid.log
```

### Critical Contacts
- Lead Operator: [Phone]
- Technical Lead: [Phone]
- On-Call: [Phone]
- Emergency: [Phone]

### Critical URLs
- Dashboard: http://localhost:8000/dashboard
- Operator: http://localhost:8000/operator
- Neo4j: http://localhost:7474
- Runbook: file:///c:/Dev/MERID/LAUNCH_DAY_RUNBOOK.md

---

## Operator Sign-Off

**Pre-Launch Checklist:**
- [ ] All 4 terminals open and configured
- [ ] All 5 browser tabs open
- [ ] Launch runbook reviewed
- [ ] Emergency procedures reviewed
- [ ] Communication channels tested
- [ ] Support operator on standby

**Operator:** _________________ **Time:** _______

**Support:** _________________ **Time:** _______

---

**Remember:** Follow the runbook. Verify every step. When in doubt, activate kill switch.

**Launch Status:** ☐ READY | ☐ IN PROGRESS | ☐ COMPLETE

---

END OF LAUNCH CONSOLE
