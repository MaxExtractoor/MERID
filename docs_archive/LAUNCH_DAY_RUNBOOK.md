# MERID LAUNCH DAY RUNBOOK
## Stage 0 (Simulation) → Stage 1 (Micro Capital) Deployment

**Version:** 1.0  
**Date:** January 11, 2026  
**Environment:** Production  
**Operators Required:** 2 minimum (Lead + Support)  

---

## Pre-Launch Checklist

### T-24 Hours Before Launch

- [ ] **Code Freeze**
  - [ ] Git commit/tag identified: `________________`
  - [ ] CI/CD pipeline: GREEN ✅
  - [ ] All tests passing (7/7)
  - [ ] No critical issues in backlog
  - [ ] Code review completed

- [ ] **Team Readiness**
  - [ ] Lead operator on-site: `________________`
  - [ ] Support operator on-site: `________________`
  - [ ] Technical lead on-call: `________________`
  - [ ] Compliance officer notified
  - [ ] Emergency contacts verified

- [ ] **Environment Preparation**
  - [ ] Production environment provisioned
  - [ ] Neo4j Aura instance ready
  - [ ] Credentials stored in secure vault
  - [ ] Backup/rollback plan documented
  - [ ] Communication channels tested

- [ ] **Documentation Review**
  - [ ] Deployment checklist reviewed
  - [ ] Emergency procedures reviewed
  - [ ] Kill switch procedure rehearsed
  - [ ] Escalation matrix confirmed

---

## Launch Sequence: Stage 0 (Simulation)

**Duration:** 3-5 days  
**Capital:** $0 (Simulation only)  
**Objective:** Validate all systems with zero risk  

### Step 1: Freeze Code Version (T-0, 09:00)

**Actions:**
```bash
# Verify Git commit
git log -1 --oneline
# Record: ________________

# Verify CI status
# Check: https://github.com/[org]/merid/actions
# Status: ________________
```

**Verification:**
- [ ] Commit hash recorded
- [ ] CI pipeline GREEN
- [ ] No pending changes

**Duration:** 5 minutes  
**Responsible:** Lead Operator  

---

### Step 2: Set Stage 0 Configuration (T+5min, 09:05)

**Actions:**
```bash
# Edit .env or config file
DEPLOYMENT_STAGE=STAGE_0_SIMULATION
MAX_CAPITAL=0
KILL_SWITCH_ACTIVE=true

# Verify no real API keys
grep -i "api_key" .env | grep -v "sandbox"
# Should return: No matches or only sandbox keys
```

**Verification:**
- [ ] `DEPLOYMENT_STAGE=STAGE_0_SIMULATION`
- [ ] `MAX_CAPITAL=0`
- [ ] `KILL_SWITCH_ACTIVE=true`
- [ ] No production API keys present
- [ ] Only sandbox/testnet credentials

**Duration:** 10 minutes  
**Responsible:** Lead Operator  
**Reviewer:** Support Operator  

---

### Step 3: Start Core Services (T+15min, 09:15)

**Actions:**
```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Start MERID
python startup.py 2>&1 | tee logs/launch_startup_$(date +%Y%m%d_%H%M%S).log
```

**Expected Output:**
```
✓ Components Initialized (8)
  - GraphService
  - RealityRegistry
  - ExecutionController
  - RiskEnvelopeManager
  - EnhancedThreatMonitor
  - ModelInventory
  - ObservabilityDashboard
  - ProgrammableComplianceEngine

✓ Health Checks Passed (4)
  - Neo4j connectivity
  - Reality Registry
  - Execution Controller
  - Risk Envelope

🚀 MERID IS READY FOR OPERATION
```

**Verification:**
- [ ] All 8 components initialized
- [ ] All 4 health checks passed
- [ ] Neo4j connection confirmed
- [ ] Kill switch status: ACTIVE
- [ ] No critical errors in output
- [ ] Startup log saved

**Duration:** 5 minutes  
**Responsible:** Lead Operator  

**If Failures:**
1. Review error messages in output
2. Check logs: `tail -100 logs/merid.log`
3. Verify Neo4j connectivity
4. Verify environment variables
5. Fix issues and restart
6. **DO NOT PROCEED** until all checks pass

---

### Step 4: Run Full Test Suite (T+20min, 09:20)

**Actions:**
```bash
# Run comprehensive tests
python run_tests.py 2>&1 | tee logs/launch_tests_$(date +%Y%m%d_%H%M%S).log
```

**Expected Output:**
```
✓ PASS | T001 | Neo4j Integration (2.3s)
✓ PASS | T002 | Reality Registry (1.8s)
✓ PASS | T003 | Execution Controller (1.2s)
✓ PASS | T004 | Risk Envelope Manager (1.5s)
✓ PASS | T005 | Enhanced Threat Monitor (1.9s)
✓ PASS | T006 | Model Inventory (2.1s)
✓ PASS | T007 | Programmable Compliance Engine (1.7s)

SUMMARY: 7/7 tests passed (0 failed)
Total duration: 12.5 seconds

🎉 ALL TESTS PASSED - SYSTEM READY
```

**Verification:**
- [ ] All 7 tests PASSED
- [ ] No failures or errors
- [ ] Test log saved
- [ ] Duration reasonable (<30s)

**Duration:** 5 minutes  
**Responsible:** Support Operator  

**If Any Test Fails:**
1. **ABORT LAUNCH IMMEDIATELY**
2. Review failure details
3. Investigate root cause
4. Fix issue
5. Re-run full test suite
6. Repeat until 100% pass
7. Document delay and resolution

---

### Step 5: Check Dashboards (T+25min, 09:25)

**Actions:**
```bash
# Open dashboards in browser
# Trading Dashboard: http://localhost:8000/dashboard
# Operator Console: http://localhost:8000/operator
# Neo4j Browser: http://localhost:7474
```

**Verification - Trading Dashboard:**
- [ ] Status: "SIMULATION MODE"
- [ ] Capital: $0
- [ ] Positions: 0
- [ ] Open orders: 0
- [ ] PnL: $0.00
- [ ] Kill switch: ACTIVE (red indicator)

**Verification - Risk Dashboard:**
- [ ] Max position size: $10,000
- [ ] Max leverage: 2x
- [ ] Max drawdown: 5%
- [ ] Current utilization: 0%
- [ ] No active violations

**Verification - Incidents Dashboard:**
- [ ] Open incidents: 0
- [ ] Circuit breakers: None triggered
- [ ] Threat monitor: Active
- [ ] All services: Healthy

**Duration:** 10 minutes  
**Responsible:** Lead Operator  

---

### Step 6: Verify Neo4j Lineage Queries (T+35min, 09:35)

**Actions:**
```python
# In Python console or script
from core.graph_service import get_graph_service

graph = get_graph_service()

# Check system health
health = graph.get_system_health_summary()
print(f"Total proposals: {health['total_proposals']}")
print(f"Total executions: {health['total_executions']}")
print(f"Open incidents: {health['open_incidents']}")

# Test lineage query (use test proposal from startup)
lineage = graph.get_proposal_lineage("test_001")
if lineage:
    print("✓ Lineage query successful")
    print(f"  Proposal: {lineage['proposal']}")
    print(f"  Assertions: {len(lineage['assertions'])}")
else:
    print("✗ Lineage query failed")
```

**Verification:**
- [ ] System health query returns data
- [ ] Lineage query successful
- [ ] Test proposal found in graph
- [ ] Assertions linked correctly
- [ ] Query latency <50ms

**Duration:** 5 minutes  
**Responsible:** Support Operator  

---

### Step 7: Dry-Run Kill Switch & Circuit Breaker (T+40min, 09:40)

**Actions:**
```python
# Test kill switch activation
from core.execution_controller import get_execution_controller

controller = get_execution_controller()

# Verify initial state
print(f"Kill switch active: {controller.kill_switch_active}")
# Should be: True

# Test deactivation (for testing only)
controller.deactivate_kill_switch("Launch test - operator approval")
print(f"Kill switch active: {controller.kill_switch_active}")
# Should be: False

# Re-activate for simulation
controller.activate_kill_switch("Launch test - returning to safe state")
print(f"Kill switch active: {controller.kill_switch_active}")
# Should be: True
```

**Verification:**
- [ ] Kill switch toggles correctly
- [ ] Dashboard reflects state changes
- [ ] Logs record all state transitions
- [ ] Audit trail captures events
- [ ] Kill switch returned to ACTIVE

**Duration:** 10 minutes  
**Responsible:** Lead Operator  

---

### Step 8: Monitor Stage 0 Operations (T+50min, 09:50)

**Actions:**
- Monitor system for 3-5 days in simulation mode
- Review metrics daily
- Collect baseline data

**Daily Checklist (Stage 0):**
- [ ] Run `python run_tests.py` (should pass 7/7)
- [ ] Review dashboard metrics
- [ ] Check for any incidents
- [ ] Verify Neo4j health
- [ ] Review logs for errors
- [ ] Document any anomalies

**Success Criteria (Stage 0):**
- [ ] 3-5 days of stable operation
- [ ] Zero critical incidents
- [ ] All daily tests passing
- [ ] No unexpected errors
- [ ] Operators comfortable with system

**Duration:** 3-5 days  
**Responsible:** All Operators (rotating)  

---

## Launch Sequence: Stage 1 (Micro Capital)

**Duration:** 7 days  
**Capital:** $100  
**Objective:** First real capital deployment with minimal risk  

### Step 9: Stage 0 → Stage 1 Transition (Day 4, 09:00)

**Pre-Transition Checklist:**
- [ ] Stage 0 success criteria met (3-5 days stable)
- [ ] All operators trained and certified
- [ ] Operations Lead approval obtained
- [ ] Technical Lead approval obtained
- [ ] Compliance Officer notified
- [ ] Emergency procedures reviewed

**Actions:**
```bash
# Update configuration
DEPLOYMENT_STAGE=STAGE_1_MICRO
MAX_CAPITAL=100
KILL_SWITCH_ACTIVE=true  # Keep active initially

# Update risk limits for Stage 1
MAX_POSITION_SIZE=10  # $10 per position
MAX_DAILY_TRADES=20
MAX_LEVERAGE=1  # No leverage in Stage 1
```

**Verification:**
- [ ] `DEPLOYMENT_STAGE=STAGE_1_MICRO`
- [ ] `MAX_CAPITAL=100`
- [ ] Risk limits appropriate for Stage 1
- [ ] Kill switch still ACTIVE
- [ ] Configuration reviewed by 2 operators

**Duration:** 15 minutes  
**Responsible:** Lead Operator  
**Reviewer:** Support Operator  

---

### Step 10: Restart Services with Stage 1 Config (Day 4, 09:15)

**Actions:**
```bash
# Graceful shutdown
pkill -TERM -f merid

# Wait for clean shutdown (check logs)
tail -f logs/merid.log
# Wait for: "GraphService connection closed"

# Restart with new config
python startup.py 2>&1 | tee logs/stage1_startup_$(date +%Y%m%d_%H%M%S).log
```

**Verification:**
- [ ] All 8 components initialized
- [ ] All 4 health checks passed
- [ ] Configuration reflects Stage 1 limits
- [ ] Kill switch: ACTIVE
- [ ] Dashboard shows "STAGE 1 - MICRO"

**Duration:** 10 minutes  
**Responsible:** Lead Operator  

---

### Step 11: Confirm Risk Envelopes & Hard Limits (Day 4, 09:25)

**Actions:**
```python
# Verify risk configuration
from core.risk_envelope import get_risk_envelope_manager

risk_mgr = get_risk_envelope_manager()
envelope = risk_mgr.envelope

print(f"Max position size: ${envelope.max_position_size_usd}")
print(f"Max leverage: {envelope.max_leverage}x")
print(f"Max drawdown: {envelope.max_drawdown_pct*100}%")
print(f"Max daily trades: {envelope.max_trades_per_day}")

# Should match Stage 1 limits:
# Max position: $10
# Max leverage: 1x
# Max drawdown: 5%
# Max daily trades: 20
```

**Verification:**
- [ ] Max position size: $10
- [ ] Max leverage: 1x (no leverage)
- [ ] Max drawdown: 5%
- [ ] Max daily trades: 20
- [ ] Limits displayed in dashboard
- [ ] Limits match deployment checklist

**Duration:** 5 minutes  
**Responsible:** Support Operator  

---

### Step 12: Enable Live Connectivity (Day 4, 09:30)

**Actions:**
```bash
# Update .env with REAL credentials (from secure vault)
# IMPORTANT: Use minimal permissions accounts

# For DeFi:
ETHEREUM_RPC_URL=[production RPC]
WALLET_ADDRESS=[hot wallet address]
WALLET_PRIVATE_KEY=[from secure vault - hot wallet only]

# For CEX (if applicable):
EXCHANGE_API_KEY=[read-only or minimal permissions]
EXCHANGE_API_SECRET=[from secure vault]

# Restart to apply
pkill -TERM -f merid
python startup.py
```

**Verification:**
- [ ] Market data streaming (check dashboard)
- [ ] Price feeds updating
- [ ] No orders placed yet (kill switch active)
- [ ] Wallet balance correct
- [ ] Exchange connectivity confirmed

**Duration:** 15 minutes  
**Responsible:** Lead Operator  
**Reviewer:** Support Operator  

**⚠️ CRITICAL:** Verify kill switch remains ACTIVE before proceeding

---

### Step 13: Allow First Live Micro Trades (Day 4, 09:45)

**Actions:**
```python
# Deactivate kill switch to enable trading
from core.execution_controller import get_execution_controller

controller = get_execution_controller()
controller.deactivate_kill_switch("Stage 1 launch - Operations Lead approval [name]")

print(f"Kill switch active: {controller.kill_switch_active}")
# Should be: False

print("🚀 LIVE TRADING ENABLED - STAGE 1 MICRO")
```

**Immediate Monitoring (First 30 Minutes):**
- [ ] Both operators watching dashboards continuously
- [ ] Logs streaming: `tail -f logs/merid.log`
- [ ] First trade executed successfully
- [ ] Lineage query works for first trade
- [ ] Risk limits enforced
- [ ] No unexpected errors

**First Trade Verification:**
```python
# After first trade
from core.graph_integration import create_operator_adapter

adapter = create_operator_adapter()

# Get recent executions
dashboard = adapter.get_system_dashboard()
print(f"Total executions: {dashboard['health']['total_executions']}")

# Explain first trade
# lineage = adapter.explain_trade("[execution_id]")
# Review complete lineage
```

**Verification:**
- [ ] First trade executed within limits
- [ ] PnL tracked correctly
- [ ] Position recorded in Neo4j
- [ ] Audit trail complete
- [ ] No incidents triggered

**Duration:** 30 minutes (intensive monitoring)  
**Responsible:** Both Operators  

---

### Step 14: Review Initial Live Session (Day 4, 10:15)

**After 1-2 Hours or 5-10 Trades:**

**Metrics Review:**
```python
# Get system summary
from core.graph_service import get_graph_service

graph = get_graph_service()
health = graph.get_system_health_summary()

print(f"Total proposals: {health['total_proposals']}")
print(f"Total orders: {health['total_orders']}")
print(f"Total executions: {health['total_executions']}")
print(f"Open incidents: {health['open_incidents']}")
print(f"Circuit breakers (24h): {health['circuit_breakers_24h']}")
```

**Checklist:**
- [ ] No critical incidents
- [ ] All risk limits respected
- [ ] Fill rate >80%
- [ ] Error rate <5%
- [ ] Slippage <1.5x expected
- [ ] PnL reasonable (within expectations)
- [ ] No compliance violations
- [ ] Neo4j queries performing well (<50ms)

**Duration:** 30 minutes  
**Responsible:** Lead Operator  

---

### Step 15: Document Launch Outcome (Day 4, 11:00)

**Create Launch Report:**

```markdown
# MERID Stage 1 Launch Report

**Date:** [Date]
**Time:** [Time]
**Environment:** Production
**Stage:** Stage 1 - Micro Capital

## Deployment Details
- Git Commit: [hash]
- Configuration: STAGE_1_MICRO
- Capital: $100
- Operators: [names]

## Execution Summary
- Trades Executed: [count]
- Success Rate: [%]
- Total Volume: $[amount]
- PnL: $[amount]
- Duration: [hours]

## Incidents
- Critical: [count]
- High: [count]
- Medium: [count]
- Low: [count]

## Performance
- Fill Rate: [%]
- Error Rate: [%]
- Avg Latency: [ms]
- Slippage Ratio: [x]

## Issues Encountered
[List any issues and resolutions]

## Recommendations
[Next steps, improvements, concerns]

## Sign-Off
- Lead Operator: [name] [signature]
- Support Operator: [name] [signature]
- Technical Lead: [name] [signature]
```

**Store Report:**
- Save to: `docs/launch_reports/stage1_YYYYMMDD.md`
- Attach logs: startup, tests, trading
- Share with team

**Duration:** 30 minutes  
**Responsible:** Lead Operator  

---

### Step 16: Decide Next Action (Day 4, 11:30)

**Decision Matrix:**

**If Everything Clean (No Issues):**
- ✅ Continue Stage 1 for full 7-day period
- ✅ Monitor daily with standard procedures
- ✅ Collect metrics for Stage 2 readiness

**If Minor Issues (Non-Critical):**
- ⚠️ Document issues
- ⚠️ Continue with enhanced monitoring
- ⚠️ Fix issues during Stage 1 period
- ⚠️ Re-assess before Stage 2

**If Major Issues (Critical):**
- 🛑 **ACTIVATE KILL SWITCH IMMEDIATELY**
- 🛑 Roll back to Stage 0 (Simulation)
- 🛑 Investigate root cause
- 🛑 Fix issues completely
- 🛑 Re-run Stage 0 for 3-5 days
- 🛑 Attempt Stage 1 again when ready

**Decision Recorded:**
- [ ] Decision: ________________
- [ ] Reason: ________________
- [ ] Approved by: ________________
- [ ] Next review: ________________

**Duration:** 15 minutes  
**Responsible:** Lead Operator + Technical Lead  

---

## Stage 1 Ongoing Operations (Days 4-11)

### Daily Checklist
- [ ] Run `python run_tests.py` (7/7 pass)
- [ ] Review overnight activity
- [ ] Check dashboard metrics
- [ ] Verify no incidents
- [ ] Review agent performance
- [ ] Check Neo4j health
- [ ] Backup verification

### Success Criteria (End of Stage 1)
- [ ] 7 days of stable operation
- [ ] 20+ trades executed
- [ ] 80%+ success rate
- [ ] <5% error rate
- [ ] 99%+ uptime
- [ ] No critical incidents
- [ ] All limits respected
- [ ] Operators confident

### Stage 1 → Stage 2 Transition
- If all success criteria met:
  - Prepare Stage 2 configuration ($1,000 cap)
  - Obtain Operations Lead approval
  - Schedule Stage 2 launch
- If criteria not met:
  - Extend Stage 1 duration
  - Address issues
  - Re-assess readiness

---

## Emergency Procedures

### Emergency Stop (Any Time)

**Trigger Conditions:**
- Unexpected losses >$50
- Error rate >20%
- Compliance violation
- Security incident
- System instability
- Operator judgment

**Actions:**
```python
# IMMEDIATE
from core.execution_controller import get_execution_controller
controller = get_execution_controller()
controller.activate_kill_switch("EMERGENCY STOP - [reason]")

# Verify
print(f"Kill switch: {controller.kill_switch_active}")
# Must be: True
```

**Follow-Up:**
1. Verify all trading stopped
2. Document incident
3. Notify Technical Lead
4. Investigate root cause
5. Do not resume without approval

---

## Rollback Procedure

**If Launch Must Be Aborted:**

1. **Activate Kill Switch**
2. **Stop Services:** `pkill -TERM -f merid`
3. **Revert Configuration:**
   ```bash
   DEPLOYMENT_STAGE=STAGE_0_SIMULATION
   MAX_CAPITAL=0
   KILL_SWITCH_ACTIVE=true
   ```
4. **Restart in Stage 0:** `python startup.py`
5. **Document Rollback:**
   - Reason
   - Issues encountered
   - Lessons learned
   - Next attempt timeline

---

## Communication Plan

### Status Updates

**Every 2 Hours (Day 1):**
- Slack: #merid-launch
- Email: ops@merid.trading
- Status: [Green/Yellow/Red]

**Daily (Days 2-7):**
- Morning standup (09:00)
- End-of-day summary (17:00)

### Escalation

**Level 1:** Operators handle (normal operations)  
**Level 2:** Technical Lead (issues, anomalies)  
**Level 3:** Executive + Compliance (critical incidents)  

---

## Post-Launch Review (Day 11)

**Review Meeting:**
- Date: [Schedule]
- Attendees: All operators, Technical Lead, Compliance
- Agenda:
  - Launch execution review
  - Metrics analysis
  - Issues and resolutions
  - Lessons learned
  - Stage 2 readiness assessment

**Deliverables:**
- Stage 1 final report
- Metrics dashboard
- Incident log
- Recommendations for Stage 2

---

## Appendix: Quick Reference

### Critical Commands
```bash
# Start system
python startup.py

# Run tests
python run_tests.py

# Emergency stop
python -c "from core.execution_controller import get_execution_controller; get_execution_controller().activate_kill_switch('Emergency')"

# Check status
curl http://localhost:8000/operator/dashboard

# View logs
tail -f logs/merid.log
```

### Critical Contacts
- **Lead Operator:** [Phone]
- **Technical Lead:** [Phone]
- **On-Call:** [Phone]
- **Emergency:** [Phone]

### Critical URLs
- Dashboard: http://localhost:8000/dashboard
- Operator Console: http://localhost:8000/operator
- Neo4j: http://localhost:7474

---

**Remember:** When in doubt, activate the kill switch. Better safe than sorry.

**Launch Status:** ☐ NOT STARTED | ☐ IN PROGRESS | ☐ COMPLETE | ☐ ABORTED

**Final Sign-Off:**
- Lead Operator: _________________ Date: _______
- Technical Lead: _________________ Date: _______

---

END OF LAUNCH DAY RUNBOOK
