# 🚀 MERID Pre-Launch Checklist

**Purpose:** End-to-end production readiness verification before live canary execution  
**Version:** 1.0  
**Date:** 2026-01-26  
**Environment:** prod_canary  
**Status:** READY FOR EXECUTION  

---

## 📋 **A. ENVIRONMENT & DEPLOYMENT**

### **Configuration & Deployment**
- [ ] Correct environment selected: `prod_canary` (Coinbase Pro, BTC/USD & ETH/USD)
- [ ] Deployed commit hash recorded and tagged: `[COMMIT_HASH]`
- [ ] Config files for `prod_canary` checked in and match live settings
- [ ] All services up: streams, oracles, agents, trading engine, API, DB, Neo4j, monitoring
- [ ] System resources healthy (CPU, RAM, disk, network)
- [ ] Time sync verified (NTP) across all hosts

### **Security & Access**
- [ ] All secrets in env or secret store; none in repo or logs
- [ ] API keys for venues are least-privilege (trade only, no withdrawal)
- [ ] Admin access to MERID dashboards requires auth; logins audited
- [ ] Firewalls and security groups allow only expected traffic
- [ ] OS and runtime patched to baseline; vulnerability scans passed

---

## 📋 **B. EXTERNAL CONNECTIVITY**

### **Venue Connectivity**
- [ ] Coinbase Pro REST + WebSocket reachable; auth test succeeds
- [ ] Coinbase Pro sandbox vs production endpoints correctly configured
- [ ] Venue API rate limits understood and configured
- [ ] Order types supported by venue match MERID expectations

### **Data Providers**
- [ ] Oracle provider reachable and returns valid prices for BTC/USD, ETH/USD
- [ ] Price sanity checks enabled (within 5% of reference)
- [ ] Outlier price handling tested and alerts configured
- [ ] Backup data source configured and tested

### **Database & Storage**
- [ ] DB connections healthy with correct users/roles
- [ ] Neo4j connections healthy with correct permissions
- [ ] Backup procedures tested and verified
- [ ] Data retention policies configured

### **Monitoring & Observability**
- [ ] Monitoring/alerting backend reachable
- [ ] Dashboards accessible and loading correctly
- [ ] Alert routing configured (email, Slack, PagerDuty)
- [ ] Log aggregation working and searchable

---

## 📋 **C. RISK & LIMITS CONFIGURATION**

### **Global Limits**
- [ ] Global daily notional limit set to **$1,000**
- [ ] Per-trade max size set to **$100**
- [ ] Daily P&L loss limit set to **$50** with kill-switch wiring
- [ ] Max daily trade count set to **20 trades**

### **Symbol & Market Controls**
- [ ] Symbol whitelist: **BTC/USD, ETH/USD only**
- [ ] Per-symbol exposure limits configured
- [ ] Market status checks enabled (halted, suspended, maintenance)
- [ ] Venue status monitoring enabled

### **Strategy-Level Controls**
- [ ] Per-strategy exposure limits configured for `canary_mm_v1`
- [ ] Strategy versioning and rollback capability tested
- [ ] Strategy kill switch tested and verified
- [ ] Model version tracking enabled

---

## 📋 **D. SAFETY CONTROLS & KILL SWITCHES**

### **Kill Switch Hierarchy**
- [ ] Global kill switch tested in staging and logs correctly
- [ ] Venue-level kill switch for Coinbase Pro tested
- [ ] Strategy-level kill switch for `canary_mm_v1` tested
- [ ] Symbol-level kill switches tested
- [ ] Manual kill switch procedures documented and tested

### **Risk Controls**
- [ ] Reconciliation auto-kill threshold set (position or balance mismatch > $0.01)
- [ ] Order rate limiting enabled and verified
- [ ] Circuit-breaker behavior confirmed for repeated venue errors
- [ ] Pre-trade risk checks enabled and tested

### **Failure Handling**
- [ ] Graceful degradation on venue connectivity loss
- [ ] Queue behavior on temporary failures tested
- [ ] Timeout and retry logic verified
- [ ] Error escalation paths tested

---

## 📋 **E. OBSERVABILITY & ALERTS**

### **Dashboard Verification**
- [ ] Dashboards show:
  - Order latency (p50/p95/p99)
  - Error rate (by endpoint)
  - Orders, fills, cancels
  - P&L, positions, balances
  - Reconciliation status
  - System health metrics

### **Alert Configuration**
- [ ] Alerts configured for:
  - Latency SLO breaches (p95 > 250ms, p99 > 500ms)
  - Error rate spikes (> 0.1% warning, > 1% critical)
  - Reconciliation mismatches (> $0.01)
  - P&L and drawdown limits (loss > $25 warning, > $50 critical)
  - Daily notional limits (> 80% warning, > 95% critical)

### **Synthetic Testing**
- [ ] Synthetic test order path run end-to-end and visible in logs/metrics
- [ ] Alert firing tested with intentional SLO breach
- [ ] Kill switch activation tested and verified
- [ ] Recovery procedures tested after kill switch

---

## 📋 **F. DATA INTEGRITY & RECONCILIATION**

### **Initial Synchronization**
- [ ] Initial positions and balances fetched from Coinbase Pro and stored
- [ ] MERID internal positions/balances match venue to within $0.01
- [ ] OMS and PMS positions/holdings match MERID and venue
- [ ] Reconciliation job runs and reports "clean" before launch

### **Real-Time Reconciliation**
- [ ] Position reconciliation enabled and tested
- [ ] Balance reconciliation enabled and tested
- [ ] Trade reconciliation enabled and tested
- [ ] Mismatch detection thresholds configured
- [ ] Auto-kill on reconciliation failures enabled

### **Audit Trail**
- [ ] All order modifications logged with timestamps
- [ ] All configuration changes logged and auditable
- [ ] All kill switch activations logged with reasons
- [ ] All manual interventions logged and auditable

---

## 📋 **G. GOVERNANCE, COMPLIANCE & AUDIT**

### **Pre-Trade Compliance**
- [ ] Pre-trade compliance rules enabled (notional, symbol, margin checks)
- [ ] Strategy & model versions logged with every order and decision
- [ ] Account/portfolio mapping verified
- [ ] Leverage/margin checks enabled and tested

### **Regulatory Alignment**
- [ ] Audit logging enabled for:
  - Deployments and config changes
  - Kill switch activations
  - Manual overrides
  - Order decisions and executions
- [ ] Data retention policies compliant with requirements
- [ ] Ability to reconstruct "why a trade happened" from logs

### **Documentation & Procedures**
- [ ] Launch runbook accessible and updated with today's parameters
- [ ] Incident response procedures documented and tested
- [ ] Escalation procedures documented and tested
- [ ] Contact information current and verified

---

## 📋 **H. PERFORMANCE & SCALABILITY**

### **System Performance**
- [ ] Order latency within acceptable ranges (< 250ms p95, < 500ms p99)
- [ ] System throughput tested under expected load
- [ ] Memory and CPU usage within acceptable limits
- [ ] Database performance within acceptable ranges

### **Load Testing**
- [ ] Burst order handling tested (50-100 orders in quick succession)
- [ ] Data burst handling tested (increased tick frequency)
- [ ] Graceful degradation confirmed under load
- [ ] Resource exhaustion scenarios tested

### **Recovery Testing**
- [ ] Service restart procedures tested
- [ ] Database recovery procedures tested
- [ ] Full system recovery from backup tested
- [ ] Disaster recovery procedures documented

---

## 📋 **I. SECURITY TESTING**

### **Authentication & Authorization**
- [ ] API authentication tested and verified
- [ ] Role-based access control tested
- [ ] Session management tested
- [ ] Multi-factor authentication enabled for admin access

### **Data Protection**
- [ ] Data encryption at rest verified
- [ ] Data encryption in transit verified
- [ ] Sensitive data masking verified
- [ ] Data access logging enabled

### **Vulnerability Assessment**
- [ ] Dependency vulnerability scans passed
- [ ] Network vulnerability scans passed
- [ ] Application security tests passed
- [ ] Penetration testing completed (if applicable)

---

## 📋 **J. FINAL VERIFICATION**

### **End-to-End Testing**
- [ ] Complete trading workflow tested in sandbox
- [ ] Order lifecycle tested (submit, modify, cancel, fill)
- [ ] Error scenarios tested and verified
- [ ] Recovery scenarios tested and verified

### **Documentation Review**
- [ ] All documentation up to date
- [ ] Runbooks reviewed and approved
- [ ] Contact information verified
- [ ] Emergency procedures reviewed

### **Go/No-Go Decision**
- [ ] Engineering lead sign-off: _________________________ Date: _________
- [ ] Operations lead sign-off: ___________________________ Date: _________
- [ ] Risk lead sign-off: _________________________________ Date: _________
- [ ] Final decision: _____________________________________ Date: _________

---

## 🚨 **CRITICAL STOP CONDITIONS**

**DO NOT PROCEED IF ANY OF THESE FAIL:**

- [ ] Any reconciliation mismatch > $0.01
- [ ] Any security vulnerability unaddressed
- [ ] Any critical system component unhealthy
- [ ] Any kill switch not functioning
- [ ] Any pre-trade compliance check failing
- [ ] Any monitoring/alerting not working
- [ ] Any documentation incomplete

---

## 📊 **EXECUTION SUMMARY**

**Total Checklist Items:** [ ] / [ ]  
**Critical Items Passed:** [ ] / [ ]  
**Warning Items:** [ ]  
**Blockers:** [ ]  

**Overall Status:** 
- [ ] **READY FOR LAUNCH** - All critical items passed
- [ ] **CONDITIONAL** - Minor issues, proceed with caution
- [ ] **NOT READY** - Critical issues must be resolved

**Notes:** _____________________________________________________________
_______________________________________________________________________
_______________________________________________________________________

---

**Last Updated:** 2026-01-26  
**Next Review:** Before each canary execution  
**Owner:** MERID Engineering Team
