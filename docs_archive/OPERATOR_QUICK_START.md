# MERID OPERATOR QUICK START GUIDE
## Essential Commands and Procedures for Production Operations

**Version:** 1.0  
**Last Updated:** January 11, 2026  
**Target Audience:** Certified MERID Operators  

---

## Quick Reference

### Emergency Contacts
- **Technical Lead:** [Contact Info]
- **Operations Lead:** [Contact Info]
- **On-Call Engineer:** [Contact Info]
- **Compliance Officer:** [Contact Info]

### Critical URLs
- **Operator Console:** http://localhost:8000/operator
- **Dashboard:** http://localhost:8000/dashboard
- **Neo4j Browser:** http://localhost:7474
- **Documentation:** http://localhost:8000/docs

---

## Daily Operations

### 1. System Startup

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Start MERID
python startup.py

# Expected output:
# ✓ Components Initialized (8)
# ✓ Health Checks Passed (4)
# 🚀 MERID IS READY FOR OPERATION
```

**Verify:**
- All 8 components initialized
- All 4 health checks passed
- No critical errors in output

### 2. Daily Health Check

```bash
# Run comprehensive tests
python run_tests.py

# Expected output:
# ✓ PASS | T001 | Neo4j Integration
# ✓ PASS | T002 | Reality Registry
# ... (7 tests total)
# 🎉 ALL TESTS PASSED - SYSTEM READY
```

**Action if tests fail:**
1. Review failure details in output
2. Check logs: `tail -f logs/merid.log`
3. Escalate if critical component failed

### 3. Monitor System Health

**Access Dashboard:**
```
http://localhost:8000/dashboard
```

**Key Metrics to Monitor:**
- **Fill Rate:** Should be >90%
- **Error Rate:** Should be <5%
- **Slippage Ratio:** Should be <1.5x
- **Service Uptime:** Should be >99%
- **Open Incidents:** Should be 0

**Alert Thresholds:**
- Fill rate <90% → Investigate venue connectivity
- Error rate >5% → Check logs, may need kill switch
- Slippage >2x → MEV attack suspected, review MEV defense
- Uptime <99% → Service degradation, check infrastructure

---

## Common Operations

### Kill Switch Management

**Activate Kill Switch (Emergency Stop):**
```python
from core.execution_controller import get_execution_controller

controller = get_execution_controller()
controller.activate_kill_switch("Operator emergency stop - [reason]")
```

**Verify Kill Switch Active:**
```python
controller = get_execution_controller()
print(f"Kill switch active: {controller.kill_switch_active}")
# Should print: Kill switch active: True
```

**Deactivate Kill Switch (Resume Trading):**
```python
controller = get_execution_controller()
controller.deactivate_kill_switch("Operator approval - [reason]")
```

**⚠️ CRITICAL:** Only deactivate kill switch after:
1. Root cause identified and resolved
2. System health verified
3. Approval from Operations Lead obtained

### Query Trade Lineage

**Explain a Trade:**
```python
from core.graph_integration import create_operator_adapter

adapter = create_operator_adapter()

# By execution ID
lineage = adapter.explain_trade("exec_12345")
print(lineage)

# By proposal ID
lineage = adapter.explain_proposal("prop_67890")
print(lineage)
```

**Via API:**
```bash
curl http://localhost:8000/operator/explain/execution/exec_12345
curl http://localhost:8000/operator/explain/proposal/prop_67890
```

### Check Wallet Exposure

**Get Current Exposure:**
```python
from core.graph_service import get_graph_service

graph = get_graph_service()
exposure = graph.get_wallet_exposure("trading_eth_1")

for exp in exposure:
    print(f"{exp['asset']} on {exp['venue']}: ${exp['exposure_usd']:,.2f}")
```

**Via API:**
```bash
curl http://localhost:8000/operator/wallet/trading_eth_1/summary
```

### Review Active Incidents

**Check Incidents:**
```python
from core.graph_service import get_graph_service

graph = get_graph_service()

# For wallet
incidents = graph.get_active_incidents_for_wallet("trading_eth_1")
print(f"Active incidents: {len(incidents)}")

# For venue
incidents = graph.get_active_incidents_for_venue("uniswap-v3")
print(f"Active incidents: {len(incidents)}")
```

**Via API:**
```bash
curl http://localhost:8000/operator/dashboard
```

### Agent Performance Review

**Get Agent Report:**
```python
from core.graph_integration import create_operator_adapter

adapter = create_operator_adapter()
report = adapter.get_agent_report("analyst_agent", days=30)

print(f"Proposals created: {report['proposals_created']}")
print(f"Orders executed: {report['orders_executed']}")
print(f"Proposals blocked: {report['proposals_blocked']}")
print(f"Average confidence: {report['avg_confidence']:.2f}")
```

**Via API:**
```bash
curl http://localhost:8000/operator/agent/analyst_agent/report?days=30
```

---

## Emergency Procedures

### Procedure 1: System Unresponsive

**Symptoms:**
- Dashboard not loading
- API requests timing out
- No new trades executing

**Actions:**
1. Check if process is running: `ps aux | grep python`
2. Check logs: `tail -100 logs/merid.log`
3. Check system resources: `top` or `htop`
4. If hung, restart: `pkill -f merid && python startup.py`
5. Verify health: `python run_tests.py`
6. Document incident in log

### Procedure 2: Abnormal Trading Activity

**Symptoms:**
- Unusual trade volume
- Repeated rejections
- High slippage
- Unexpected losses

**Actions:**
1. **ACTIVATE KILL SWITCH IMMEDIATELY**
2. Review recent trades in dashboard
3. Check for active incidents
4. Review agent reasoning logs
5. Check MEV defense alerts
6. Investigate root cause
7. Document findings
8. Get approval before resuming

### Procedure 3: Data Feed Outage

**Symptoms:**
- "Blindness mode" activated
- No new price data
- Stale assertions in Reality Registry

**Actions:**
1. System should auto-enter blindness mode (verify)
2. Check data feed connectivity
3. Review backup feed status
4. If prolonged (>30min), activate kill switch
5. Contact data provider
6. Monitor for recovery
7. Verify data quality before resuming
8. Document outage duration and impact

### Procedure 4: Neo4j Connection Lost

**Symptoms:**
- Graph query errors in logs
- "GraphService unavailable" warnings
- Lineage queries failing

**Actions:**
1. Check Neo4j status: `systemctl status neo4j` (Linux)
2. Check connection: `python -c "from core.graph_service import get_graph_service; get_graph_service()"`
3. If down, restart Neo4j
4. Verify connection restored
5. Run `graph.run_init()` to ensure consistency
6. **Note:** Trading can continue (graph is observability, not critical path)
7. Document outage and recovery

### Procedure 5: Compliance Violation Detected

**Symptoms:**
- "Sanctions hit detected" alert
- "High-risk wallet" warning
- Transaction blocked by compliance engine

**Actions:**
1. **DO NOT OVERRIDE COMPLIANCE BLOCK**
2. Review blocked transaction details
3. Verify sanctions/risk scoring accuracy
4. Document incident with full details
5. Notify Compliance Officer immediately
6. File SAR if required (within regulatory timeframe)
7. Update screening rules if false positive
8. Never resume trading with flagged address

### Procedure 6: Circuit Breaker Triggered

**Symptoms:**
- "Circuit breaker activated" alert
- Trading halted automatically
- Specific breaker type identified

**Actions:**
1. Identify breaker type (drawdown, error rate, slippage, etc.)
2. Review metrics that triggered breaker
3. Investigate root cause
4. Check for related incidents
5. Resolve underlying issue
6. Verify metrics return to normal
7. Reset circuit breaker (if authorized)
8. Monitor closely for 1 hour after reset

---

## Monitoring Checklist

### Hourly (Automated Alerts)
- [ ] Fill rate >90%
- [ ] Error rate <5%
- [ ] No critical incidents
- [ ] All services healthy

### Every 4 Hours
- [ ] Review dashboard metrics
- [ ] Check for circuit breaker triggers
- [ ] Review agent performance
- [ ] Verify data feed quality

### Daily
- [ ] Run `python run_tests.py`
- [ ] Review overnight activity
- [ ] Check for compliance alerts
- [ ] Verify backup completion
- [ ] Review incident log

### Weekly
- [ ] Generate agent performance reports
- [ ] Review risk metrics trends
- [ ] Check Neo4j database size
- [ ] Verify all operators certified
- [ ] Update documentation if needed

---

## Useful Commands

### System Status
```bash
# Check all services
python -c "from core.graph_service import get_graph_service; print(get_graph_service().get_system_health_summary())"

# Check kill switch status
python -c "from core.execution_controller import get_execution_controller; print(f'Kill switch: {get_execution_controller().kill_switch_active}')"

# Check active incidents
python -c "from core.graph_service import get_graph_service; print(f'Open incidents: {get_graph_service().get_system_health_summary()[\"open_incidents\"]}')"
```

### Logs
```bash
# Tail main log
tail -f logs/merid.log

# Search for errors
grep ERROR logs/merid.log | tail -50

# Search for specific proposal
grep "prop_12345" logs/merid.log

# View audit log
tail -f logs/audit.log
```

### Database
```bash
# Neo4j status
systemctl status neo4j  # Linux
# OR check http://localhost:7474

# Run Neo4j initialization
python -c "from core.graph_service import get_graph_service; get_graph_service().run_init()"

# Query proposal count
python -c "from core.graph_service import get_graph_service; print(get_graph_service().get_system_health_summary())"
```

---

## Escalation Matrix

### Level 1: Operator Response
- Normal operations
- Minor alerts
- Routine maintenance
- **Response Time:** Immediate

### Level 2: Operations Lead
- Multiple failed health checks
- Circuit breaker triggered
- Abnormal trading patterns
- **Response Time:** 15 minutes

### Level 3: Technical Lead
- System unresponsive
- Data corruption suspected
- Critical component failure
- **Response Time:** 30 minutes

### Level 4: Executive/Compliance
- Major financial loss (>$10k)
- Compliance violation
- Security breach suspected
- Regulatory inquiry
- **Response Time:** 1 hour

---

## Best Practices

### DO
✅ Monitor dashboard regularly  
✅ Activate kill switch when in doubt  
✅ Document all incidents thoroughly  
✅ Follow runbooks for known issues  
✅ Escalate early if uncertain  
✅ Verify system health after changes  
✅ Keep credentials secure  
✅ Review logs daily  

### DON'T
❌ Override compliance blocks  
❌ Deactivate kill switch without approval  
❌ Ignore circuit breaker triggers  
❌ Skip health checks  
❌ Make changes without documentation  
❌ Share credentials  
❌ Bypass security controls  
❌ Trade during blindness mode  

---

## Training Resources

- **Full Operator Manual:** `/docs/OPERATOR_MANUAL.md`
- **System Architecture:** `/docs/INSTITUTIONAL_MASTER_SPECIFICATION.md`
- **Threat Runbooks:** `/docs/LAST_MILE_INSTITUTIONAL_HARDENING.md`
- **Neo4j Integration:** `/docs/NEO4J_INTEGRATION_GUIDE.md`
- **API Documentation:** `http://localhost:8000/docs`

---

## Certification

**Operator Name:** _______________________

**Certification Date:** _______________________

**Certified By:** _______________________

**Renewal Date:** _______________________

---

## Quick Command Reference Card

```bash
# Start system
python startup.py

# Run tests
python run_tests.py

# Activate kill switch
python -c "from core.execution_controller import get_execution_controller; get_execution_controller().activate_kill_switch('Emergency stop')"

# Check status
curl http://localhost:8000/operator/dashboard

# View logs
tail -f logs/merid.log

# Emergency stop
pkill -f merid
```

---

**Remember:** When in doubt, activate the kill switch and escalate. Better safe than sorry.

**Emergency Hotline:** [Phone Number]  
**Slack Channel:** #merid-ops  
**Email:** ops@merid.trading  

---

END OF OPERATOR QUICK START GUIDE
