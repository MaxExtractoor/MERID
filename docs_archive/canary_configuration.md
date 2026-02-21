# 🚀 MERID Real-Money Canary Configuration

**Purpose:** First real-money canary deployment configuration with conservative parameters  
**Status:** Ready for implementation  
**Date:** 2026-01-25  
**Risk Level:** LOW - Ultra-conservative parameters

---

## 📊 **CANARY OVERVIEW**

### **Canary Strategy:**
- **Strategy Name:** Conservative Market Making
- **Strategy ID:** `canary_mm_v1`
- **Version:** `1.0.0`
- **Risk Level:** LOW
- **Deployment Mode:** CANARY (1% traffic)

### **Trading Parameters:**
- **Venue:** Coinbase Pro (Primary)
- **Symbols:** BTC/USD, ETH/USD (Low volatility pairs)
- **Max Daily Notional:** $1,000 USD
- **Max Per-Trade Size:** $100 USD
- **Max Daily Trade Count:** 20 trades
- **Time Window:** 6 hours (9:30 AM - 3:30 PM ET)

---

## 🎯 **CONSERVATIVE CAPS & LIMITS**

### **Risk Management Limits:**
- **Daily Loss Limit:** $50 USD (5% of max notional)
- **Per-Trade Loss Limit:** $5 USD (5% of per-trade size)
- **Maximum Drawdown:** 2% daily
- **Position Exposure:** Max $500 USD at any time
- **Leverage:** 1x (no leverage)

### **Trading Controls:**
- **Order Types:** Limit orders only (no market orders)
- **Spread Requirements:** Minimum 0.1% spread
- **Holding Period:** Max 30 minutes per position
- **Inventory Limits:** Max 2 positions per symbol
- **Quote Size:** $10-$50 USD per quote

### **Technical Limits:**
- **Latency Threshold:** 500ms (kill if exceeded)
- **Error Rate Threshold:** 1% (kill if exceeded)
- **Reconciliation Tolerance:** $0.01 USD
- **API Rate Limits:** 10 requests/second

---

## 📈 **SUCCESS/FAILURE CRITERIA**

### **✅ KEEP CANARY RUNNING (All conditions must be met):**
- **Performance Metrics:**
  - P&L > -$25 USD (within 50% of loss limit)
  - Win rate ≥ 40%
  - Sharpe ratio ≥ 0.5
  - Max drawdown ≤ 1.5%

- **Technical Metrics:**
  - p95 latency < 400ms
  - Error rate < 0.5%
  - Reconciliation mismatches = 0
  - No kill switch triggers

- **Operational Metrics:**
  - All orders executed successfully
  - No venue connectivity issues
  - No data quality problems
  - All monitoring systems healthy

### **📈 SCALE UP (Meet KEEP criteria + any of these):**
- **Performance Excellence:**
  - P&L > $10 USD (profitable)
  - Win rate ≥ 60%
  - Sharpe ratio ≥ 1.0
  - Slippage < 0.05%

- **Operational Excellence:**
  - Zero errors for 2+ hours
  - Perfect reconciliation for 2+ hours
  - All SLOs green for 2+ hours
  - No manual interventions needed

### **🚨 KILL CANARY (Any condition met):**
- **Critical Failures:**
  - Daily loss > $50 USD
  - Per-trade loss > $5 USD
  - Max drawdown > 2%
  - Any kill switch triggered

- **Technical Failures:**
  - p95 latency > 500ms for 5 minutes
  - Error rate > 1% for 5 minutes
  - Reconciliation mismatch > $0.01 USD
  - Venue connectivity loss > 1 minute

- **Operational Failures:**
  - Order failure rate > 5%
  - Data quality issues detected
  - Manual intervention required
  - Any SLO breach for 10+ minutes

---

## 🔍 **MONITORING & ALERTING**

### **Critical Metrics (Real-time):**
- **P&L:** Current, daily, cumulative
- **Position Exposure:** Current positions, total exposure
- **Latency:** Order submission, venue response, total
- **Error Rate:** By type, by venue, by operation
- **Reconciliation:** Position balance, cash balance

### **SLO Monitoring:**
- **Order Latency p95:** Target < 250ms, Alert > 400ms, Kill > 500ms
- **Error Rate:** Target < 0.1%, Alert > 0.5%, Kill > 1%
- **Reconciliation:** Target 0 mismatches, Alert > 0, Kill > $0.01
- **Drawdown:** Target < 1%, Alert > 1.5%, Kill > 2%

### **Alert Configuration:**
- **WARNING:** 70% of threshold breached
- **CRITICAL:** 90% of threshold breached
- **EMERGENCY:** 100% threshold breached (auto-kill)

---

## 🛡️ **SAFETY MECHANISMS**

### **Kill Switches:**
- **Global Kill Switch:** `global_canary_mm_v1`
- **Venue Kill Switch:** `venue_coinbase_canary_mm_v1`
- **Symbol Kill Switches:** `symbol_btc_canary_mm_v1`, `symbol_eth_canary_mm_v1`
- **Strategy Kill Switch:** `strategy_canary_mm_v1`

### **Auto-Kill Triggers:**
- Daily loss limit exceeded
- Per-trade loss limit exceeded
- Technical SLO breaches
- Reconciliation failures
- Manual emergency stop

### **Manual Override:**
- Emergency stop button in dashboard
- CLI commands for immediate shutdown
- Phone escalation procedure
- Backup communication channels

---

## 📊 **BUSINESS KPI TRACKING**

### **Primary KPIs:**
- **Realized P&L:** $10 target, -$25 minimum
- **Win Rate:** 60% target, 40% minimum
- **Sharpe Ratio:** 1.0 target, 0.5 minimum
- **Slippage:** < 0.05% target, < 0.1% maximum

### **Secondary KPIs:**
- **Trade Frequency:** 2-4 trades/hour
- **Average Trade Size:** $25-$50 USD
- **Holding Period:** 5-15 minutes
- **Spread Capture:** 0.05%-0.15%

### **Risk KPIs:**
- **Maximum Drawdown:** < 1% target, < 2% maximum
- **Value at Risk (VaR):** < $20 USD daily
- **Position Concentration:** < 50% in one symbol
- **Leverage Ratio:** 1.0 (no leverage)

---

## 🕐 **TIME WINDOW & SCHEDULE**

### **Trading Window:**
- **Start Time:** 9:30 AM ET
- **End Time:** 3:30 PM ET
- **Duration:** 6 hours
- **Days:** Monday-Friday (no weekends)

### **Monitoring Schedule:**
- **Pre-Launch:** 8:30 AM - 9:30 AM (system checks)
- **Trading:** 9:30 AM - 3:30 PM (continuous monitoring)
- **Post-Launch:** 3:30 PM - 4:30 PM (reconciliation, review)

### **Review Points:**
- **Hourly:** Performance and risk review
- **Mid-day:** Strategy adjustment consideration
- **End-of-day:** Full reconciliation and assessment

---

## 📋 **LAUNCH CHECKLIST**

### **Pre-Launch (T-1 hour):**
- [ ] All systems green on dashboard
- [ ] Risk limits configured and tested
- [ ] Kill switches tested and functional
- [ ] Monitoring and alerting active
- [ ] Reconciliation scripts tested
- [ ] Venue connectivity verified
- [ ] Market data quality confirmed
- [ ] Team communication established

### **Launch (T=0):**
- [ ] Enable strategy in CANARY mode
- [ ] Confirm 1% traffic routing
- [ ] Verify first order execution
- [ ] Monitor initial metrics
- [ ] Confirm reconciliation working

### **During Trading:**
- [ ] Continuous monitoring of all metrics
- [ ] Hourly performance reviews
- [ ] Immediate response to any alerts
- [ ] Documentation of all events
- [ ] Team communication maintained

### **Post-Launch:**
- [ ] Final reconciliation completed
- [ ] Performance metrics calculated
- [ ] Success/failure determination
- [ ] Lessons learned documented
- [ ] Next steps decided

---

## 🚨 **EMERGENCY PROCEDURES**

### **Immediate Kill (Critical Issues):**
1. Trigger global kill switch
2. Cancel all open orders
3. Close all positions
4. Notify team immediately
5. Document all actions

### **Escalation Contacts:**
- **Engineering Lead:** [Contact Information]
- **Operations Lead:** [Contact Information]
- **Trading Desk:** [Contact Information]
- **Emergency Contact:** [Contact Information]

### **Communication Plan:**
- **Internal:** Immediate team notification
- **Management:** Within 15 minutes of critical event
- **External:** Only if customer impact

---

## ✅ **CANARY APPROVAL**

**Engineering Lead:** _________________________ Date: _________

**Operations Lead:** ___________________________ Date: _________

**Risk Lead:** _________________________________ Date: _________

**Final Decision:**
- [ ] **APPROVED** - Proceed with canary launch
- [ ] **APPROVED WITH CONDITIONS** - Address specific items first
- [ ] **REJECTED** - Critical issues must be resolved

**Notes:**
