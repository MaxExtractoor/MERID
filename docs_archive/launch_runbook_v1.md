# 🚀 MERID Launch Runbook v1.0

**Purpose:** Single reference for MERID production launch operations  
**Version:** 1.0  
**Date:** 2026-01-25  
**Status:** Ready for Production Use  

---

## 📋 **SYSTEM OVERVIEW**

### **What's Running:**
- **MERID AI Trading Platform** - Enterprise-grade AI-powered trading system
- **Core Components:** AI models, trading engine, risk management, operations
- **Deployment Mode:** Canary (1% traffic) with conservative parameters
- **Venues:** Coinbase Pro (primary)
- **Symbols:** BTC/USD, ETH/USD (low volatility pairs)

### **Where It's Running:**
- **Production Environment:** AWS us-east-1 (primary)
- **Database:** PostgreSQL RDS with read replicas
- **Cache:** Redis ElastiCache cluster
- **Monitoring:** Prometheus + Grafana + AlertManager
- **Logging:** ELK Stack (Elasticsearch, Logstash, Kibana)

---

## 🎯 **TRADING PARAMETERS**

### **Risk Limits:**
- **Max Daily Notional:** $1,000 USD
- **Max Per-Trade Size:** $100 USD
- **Max Daily Trade Count:** 20 trades
- **Daily Loss Limit:** $50 USD (5% of max notional)
- **Per-Trade Loss Limit:** $5 USD (5% of per-trade size)
- **Maximum Drawdown:** 2% daily

### **Trading Controls:**
- **Order Types:** Limit orders only (no market orders)
- **Spread Requirements:** Minimum 0.1% spread
- **Holding Period:** Max 30 minutes per position
- **Inventory Limits:** Max 2 positions per symbol
- **Quote Size:** $10-$50 USD per quote

---

## 📊 **SLOs AND THRESHOLDS**

### **Performance SLOs:**
- **Order Latency p95:** < 250ms (Target), < 400ms (Alert), < 500ms (Kill)
- **Order Latency p99:** < 500ms (Target), < 800ms (Alert), < 1000ms (Kill)
- **Error Rate:** < 0.1% (Target), < 0.5% (Alert), < 1% (Kill)
- **Throughput:** > 10 trades/hour (Target)

### **Business SLOs:**
- **Realized P&L:** > $10 (Target), > -$25 (Minimum)
- **Win Rate:** > 60% (Target), > 40% (Minimum)
- **Sharpe Ratio:** > 1.0 (Target), > 0.5 (Minimum)
- **Slippage:** < 0.05% (Target), < 0.1% (Maximum)

### **Reconciliation SLOs:**
- **Position Reconciliation:** 0 mismatches (Target), < $0.01 (Alert)
- **Balance Reconciliation:** 0 mismatches (Target), < $0.01 (Alert)
- **Trade Reconciliation:** 0 mismatches (Target), < 0.1% (Alert)

---

## 🚨 **KILL SWITCHES**

### **Global Kill Switches:**
- **ID:** `global_canary_mm_v1`
- **Scope:** All trading activity
- **Trigger:** Manual or automatic (critical failures)
- **Effect:** Immediate stop of all trading, cancel all orders

### **Venue Kill Switches:**
- **ID:** `venue_coinbase_canary_mm_v1`
- **Scope:** Coinbase Pro trading only
- **Trigger:** Venue-specific issues
- **Effect:** Stop trading on Coinbase, keep other venues active

### **Strategy Kill Switches:**
- **ID:** `strategy_canary_mm_v1`
- **Scope:** Conservative Market Making strategy
- **Trigger:** Strategy-specific issues
- **Effect:** Disable strategy, keep system running

### **Symbol Kill Switches:**
- **ID:** `symbol_btc_canary_mm_v1`, `symbol_eth_canary_mm_v1`
- **Scope:** Individual symbol trading
- **Trigger:** Symbol-specific issues
- **Effect:** Stop trading for specific symbol

---

## 📞 **CONTACT AND ESCALATION**

### **Primary Contacts:**
- **Engineering Lead:** [Name] - [Phone] - [Email]
- **Operations Lead:** [Name] - [Phone] - [Email]
- **Risk Lead:** [Name] - [Phone] - [Email]
- **Security Lead:** [Name] - [Phone] - [Email]

### **Escalation Path:**
1. **Level 1:** Operations Lead (immediate response)
2. **Level 2:** Engineering Lead (technical issues)
3. **Level 3:** Risk Lead (risk management)
4. **Level 4:** Security Lead (security issues)
5. **Level 5:** Management (business impact)

### **Emergency Contacts:**
- **24/7 On-Call:** [Phone]
- **Emergency Hotline:** [Phone]
- **IT Support:** [Phone]
- **Venue Support:** [Phone]

---

## 🚀 **LAUNCH PROCEDURES**

### **Pre-Launch (T-1 hour):**
1. **System Checks:**
   - Verify all systems green on dashboard
   - Confirm risk limits configured
   - Test kill switches
   - Validate monitoring and alerting

2. **Market Preparation:**
   - Verify venue connectivity
   - Confirm market data quality
   - Check liquidity conditions
   - Validate trading parameters

3. **Team Preparation:**
   - Confirm team availability
   - Establish communication channels
   - Review runbook procedures
   - Set up monitoring stations

### **Launch (T=0):**
1. **Enable Strategy:**
   - Set deployment mode to CANARY
   - Configure 1% traffic routing
   - Verify first order execution
   - Monitor initial metrics

2. **Initial Validation:**
   - Confirm order flow working
   - Validate reconciliation
   - Check SLO compliance
   - Verify risk limits

### **During Trading:**
1. **Continuous Monitoring:**
   - Watch all SLOs in real-time
   - Monitor risk limits
   - Track P&L and performance
   - Verify reconciliation

2. **Hourly Reviews:**
   - Performance assessment
   - Risk limit check
   - Reconciliation verification
   - Team status check

3. **Alert Response:**
   - Immediate response to alerts
   - Follow escalation procedures
   - Document all actions
   - Update team status

### **Post-Launch:**
1. **Shutdown Procedures:**
   - Graceful strategy shutdown
   - Cancel all open orders
   - Close all positions
   - Final reconciliation

2. **Post-Mortem:**
   - Performance analysis
   - Issues documentation
   - Lessons learned
   - Improvement planning

---

## 🆘 **HOW TO TURN THINGS OFF FAST**

### **Emergency Stop (Critical Issues):**
```bash
# 1. Trigger global kill switch (fastest)
curl -X POST "https://api.merid.com/v1/kill-switch/trigger" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"switch_id": "global_canary_mm_v1", "reason": "Emergency stop"}'

# 2. Alternative: CLI command
merid-cli kill-switch trigger global_canary_mm_v1 --reason "Emergency stop"

# 3. Alternative: Dashboard
# Navigate to: Operations -> Kill Switches -> Trigger Global
```

### **Venue-Specific Stop:**
```bash
# Stop Coinbase Pro trading
curl -X POST "https://api.merid.com/v1/kill-switch/trigger" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"switch_id": "venue_coinbase_canary_mm_v1", "reason": "Venue issues"}'
```

### **Strategy-Specific Stop:**
```bash
# Disable specific strategy
curl -X POST "https://api.merid.com/v1/kill-switch/trigger" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"switch_id": "strategy_canary_mm_v1", "reason": "Strategy issues"}'
```

### **Manual Stop (if automation fails):**
1. **Stop Trading Engine:**
   ```bash
   ssh production-server "sudo systemctl stop merid-trading"
   ```

2. **Cancel Orders:**
   ```bash
   merid-cli orders cancel-all --venue coinbase
   ```

3. **Close Positions:**
   ```bash
   merid-cli positions close-all --venue coinbase
   ```

---

## 📊 **MONITORING DASHBOARD**

### **Primary Dashboard URL:**
- **Main Dashboard:** https://dashboard.merid.com/production
- **Backup Dashboard:** https://dashboard-backup.merid.com/production

### **Key Panels:**
1. **System Health:** Overall system status
2. **Trading Performance:** P&L, win rate, Sharpe ratio
3. **Risk Management:** Position limits, drawdown
4. **Technical Metrics:** Latency, error rates, throughput
5. **Reconciliation:** Position and balance reconciliation
6. **Alerts:** Active alerts and history

### **Alert Channels:**
- **Primary:** Slack #merid-alerts
- **Secondary:** Email alerts@merid.com
- **Emergency:** SMS to on-call team
- **Critical:** Phone call to on-call

---

## 🔧 **TROUBLESHOOTING**

### **Common Issues:**
1. **High Latency:**
   - Check system resources
   - Verify network connectivity
   - Review venue API status
   - Consider kill switch if > 500ms

2. **Order Failures:**
   - Check venue connectivity
   - Verify account balances
   - Review order parameters
   - Check risk limits

3. **Reconciliation Mismatches:**
   - Verify data sources
   - Check timing synchronization
   - Review calculation logic
   - Consider kill switch if critical

4. **P&L Drawdown:**
   - Review market conditions
   - Check strategy performance
   - Verify risk limits
   - Consider scaling down

### **Debug Commands:**
```bash
# Check system status
merid-cli status --verbose

# Check trading status
merid-cli trading status --venue coinbase

# Check reconciliation
merid-cli reconciliation status --venue coinbase --last-hour

# Check kill switches
merid-cli kill-switch status

# Check recent alerts
merid-cli alerts list --last-hour
```

---

## 📋 **CHECKLISTS**

### **Pre-Launch Checklist:**
- [ ] All systems green on dashboard
- [ ] Risk limits configured and tested
- [ ] Kill switches tested and functional
- [ ] Monitoring and alerting active
- [ ] Reconciliation scripts tested
- [ ] Venue connectivity verified
- [ ] Market data quality confirmed
- [ ] Team communication established
- [ ] Emergency procedures reviewed
- [ ] Documentation accessible

### **Post-Launch Checklist:**
- [ ] All positions closed
- [ ] All orders cancelled
- [ ] Final reconciliation completed
- [ ] Performance metrics calculated
- [ ] Issues documented
- [ ] Team debrief conducted
- [ ] Lessons learned captured
- [ ] Improvement actions identified
- [ ] Runbook updated
- [ ] Sign-off obtained

---

## 🚨 **EMERGENCY PROCEDURES**

### **Critical System Failure:**
1. **Immediate Action:** Trigger global kill switch
2. **Assessment:** Evaluate system state and impact
3. **Communication:** Notify all stakeholders immediately
4. **Recovery:** Execute recovery procedures
5. **Documentation:** Document all actions and timeline

### **Market Extreme Volatility:**
1. **Assessment:** Evaluate market conditions
2. **Decision:** Continue or stop trading
3. **Action:** Adjust parameters or stop trading
4. **Monitoring:** Increased monitoring frequency
5. **Communication:** Keep team informed

### **Security Incident:**
1. **Immediate Action:** Stop all trading
2. **Isolation:** Isolate affected systems
3. **Investigation:** Begin security investigation
4. **Communication:** Notify security team
5. **Recovery:** Follow security procedures

---

## 📝 **DOCUMENTATION**

### **Related Documents:**
- **Production Readiness Checklist:** `/docs/production_readiness.md`
- **Canary Configuration:** `/docs/canary_configuration.md`
- **Staging Dress Rehearsal:** `/docs/staging_dress_rehearsal.md`
- **Incident Management:** `/docs/incident_management.md`
- **Security Procedures:** `/docs/security_procedures.md`

### **Quick Links:**
- **Dashboard:** https://dashboard.merid.com
- **API Documentation:** https://api.merid.com/docs
- **Runbook Repository:** https://github.com/merid/runbooks
- **Emergency Contacts:** https://merid.com/contacts

---

## ✅ **RUNBOOK APPROVAL**

**Engineering Lead:** _________________________ Date: _________

**Operations Lead:** ___________________________ Date: _________

**Risk Lead:** _________________________________ Date: _________

**Security Lead:** _____________________________ Date: _________

**Management:** _______________________________ Date: _________

**Version Control:**
- **Created:** 2026-01-25
- **Last Updated:** 2026-01-25
- **Next Review:** 2026-02-25

**Notes:**
