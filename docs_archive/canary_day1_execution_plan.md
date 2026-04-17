# 🚀 MERID Canary Day 1 Execution Plan

**Purpose:** Execute first live canary trading day with comprehensive monitoring  
**Date:** 2026-01-26  
**Trading Window:** 9:30 AM - 3:30 PM ET (6 hours)  
**Risk Level:** LOW - Ultra-conservative parameters  

---

## 📊 **CANARY CONFIGURATION**

### **Strategy Parameters:**
- **Strategy ID:** `canary_mm_v1`
- **Strategy Name:** Conservative Market Making
- **Deployment Mode:** CANARY (1% traffic)
- **Venue:** Coinbase Pro
- **Symbols:** BTC/USD, ETH/USD
- **Max Daily Notional:** $1,000 USD
- **Max Per-Trade Size:** $100 USD
- **Max Daily Trade Count:** 20 trades
- **Daily Loss Limit:** $50 USD

### **Risk Controls:**
- **Order Types:** Limit orders only
- **Spread Requirements:** Minimum 0.1% spread
- **Holding Period:** Max 30 minutes per position
- **Inventory Limits:** Max 2 positions per symbol
- **Leverage:** 1x (no leverage)

---

## 🕐 **EXECUTION SCHEDULE**

### **Pre-Launch (8:30 AM - 9:30 AM):**
- [ ] **System Preparation (8:30-9:00)**
  - Verify all systems green on dashboard
  - Confirm risk limits configured correctly
  - Test all kill switches
  - Validate venue connectivity
  - Check market data quality

- [ ] **Final Checks (9:00-9:15)**
  - Run pre-launch health checks
  - Verify monitoring and alerting active
  - Confirm team communication established
  - Review emergency procedures

- [ ] **Launch Preparation (9:15-9:30)**
  - Set strategy to CANARY mode
  - Configure 1% traffic routing
  - Verify first order execution capability
  - Final dashboard verification

### **Trading Window (9:30 AM - 3:30 PM):**
- [ ] **Launch (9:30 AM)**
  - Enable live trading
  - Monitor first order execution
  - Verify reconciliation working
  - Confirm all systems operational

- [ ] **Continuous Monitoring (9:30 AM - 3:30 PM)**
  - Real-time dashboard monitoring
  - SLO compliance tracking
  - Risk limit monitoring
  - Reconciliation verification
  - Alert response readiness

- [ ] **Hourly Reviews (10:30 AM, 11:30 AM, 12:30 PM, 1:30 PM, 2:30 PM)**
  - Performance assessment
  - Risk limit check
  - Reconciliation status
  - Alert history review
  - Decision point: continue/adjust/stop

### **Post-Launch (3:30 PM - 4:30 PM):**
- [ ] **Shutdown (3:30 PM)**
  - Disable new trading
  - Cancel all open orders
  - Close all positions
  - Final reconciliation

- [ ] **Data Collection (3:45 PM - 4:15 PM)**
  - Export all trading data
  - Generate performance reports
  - Compile alert history
  - Collect reconciliation results

- [ ] **Initial Review (4:15 PM - 4:30 PM)**
  - Preliminary performance assessment
  - Issue identification
  - Success/failure determination
  - Next steps planning

---

## 📊 **MONITORING DASHBOARD**

### **Primary Metrics (Real-time):**
- **P&L:** Current, daily, cumulative
- **Position Exposure:** Current positions, total exposure
- **Order Flow:** Orders placed, filled, cancelled
- **Latency:** Order submission, venue response, total
- **Error Rate:** By type, by venue, by operation
- **Reconciliation:** Position balance, cash balance

### **SLO Monitoring:**
- **Order Latency p95:** < 250ms (Target), < 500ms (Alert), < 1000ms (Kill)
- **Error Rate:** < 0.1% (Target), < 1% (Alert), < 5% (Kill)
- **Reconciliation:** 0 mismatches (Target), < $0.01 (Alert), > $0.01 (Kill)
- **Drawdown:** < 1% (Target), < 2% (Alert), > 2% (Kill)

### **Alert Configuration:**
- **WARNING:** 70% of threshold breached
- **CRITICAL:** 90% of threshold breached
- **EMERGENCY:** 100% threshold breached (auto-kill)

---

## 🚨 **KILL SWITCH PROCEDURES**

### **Manual Kill Triggers:**
- Any unusual market behavior
- Unexpected system behavior
- Intuition that something is wrong
- Pre-defined threshold breaches
- Team consensus to stop

### **Kill Switch Priority:**
1. **Global Kill Switch:** `global_canary_mm_v1` (stops everything)
2. **Venue Kill Switch:** `venue_coinbase_canary_mm_v1` (stops Coinbase)
3. **Strategy Kill Switch:** `strategy_canary_mm_v1` (stops strategy)
4. **Symbol Kill Switches:** `symbol_btc_canary_mm_v1`, `symbol_eth_canary_mm_v1`

### **Kill Commands:**
```bash
# Global kill (fastest)
curl -X POST "https://api.merid.com/v1/kill-switch/trigger" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"switch_id": "global_canary_mm_v1", "reason": "Manual emergency stop"}'

# Venue kill
curl -X POST "https://api.merid.com/v1/kill-switch/trigger" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"switch_id": "venue_coinbase_canary_mm_v1", "reason": "Venue issues"}'
```

---

## 📋 **BABYSITTING MODE CHECKLIST**

### **Pre-Launch Verification:**
- [ ] Dashboard accessible and updating
- [ ] All systems showing green status
- [ ] Kill switches tested and functional
- [ ] Alert channels active (Slack, email, SMS)
- [ ] Team communication established
- [ ] Emergency contacts available
- [ ] Market conditions normal
- [ ] Venue API status healthy

### **During Trading - Continuous Monitoring:**
- [ ] P&L trending within expected range
- [ ] Order execution latency < 500ms
- [ ] Error rate < 1%
- [ ] Reconciliation showing 0 mismatches
- [ ] Risk limits not breached
- [ ] No unexpected alerts
- [ ] Market data quality good
- [ ] Team communication active

### **Hourly Review Points:**
- [ ] Performance metrics within targets
- [ ] Risk limits respected
- [ ] Reconciliation perfect
- [ ] No critical alerts
- [ ] Market conditions appropriate
- [ ] Team comfortable with status
- [ ] Decision: continue/adjust/stop

### **Emergency Response:**
- [ ] Kill switch triggered (if needed)
- [ ] Team notified immediately
- [ ] All positions closed
- [ ] Reconciliation completed
- [ ] Incident documented
- [ ] Root cause analysis started

---

## 📊 **DATA COLLECTION PLAN**

### **Trading Data:**
- **Order Log:** All orders placed, filled, cancelled
- **Trade Log:** All executed trades with timestamps
- **Position Log:** Position changes over time
- **P&L Log:** Realized and unrealized P&L
- **Market Data:** Prices, spreads, volumes

### **System Data:**
- **Latency Metrics:** Order submission, venue response, total
- **Error Logs:** All errors with timestamps and context
- **System Metrics:** CPU, memory, network usage
- **Reconciliation Results:** Position and balance reconciliation
- **Alert History:** All alerts triggered and resolved

### **Performance Data:**
- **SLO Time Series:** All SLOs over time
- **Business KPIs:** Win rate, Sharpe ratio, slippage
- **Risk Metrics:** Drawdown, position exposure
- **Trading Metrics:** Trade frequency, average size
- **Operational Metrics:** Uptime, availability

---

## 📝 **POST-SESSION REPORT TEMPLATE**

### **Canary Session Report v1 - Day 1**

**Execution Summary:**
- Date: [Date]
- Trading Window: [Start] - [End]
- Strategy: [Strategy ID]
- Venue: [Venue]
- Symbols: [Symbols]

**Performance Metrics:**
- Total P&L: $[Amount]
- Win Rate: [Percentage]%
- Total Trades: [Number]
- Average Trade Size: $[Amount]
- Max Drawdown: [Percentage]%
- Sharpe Ratio: [Ratio]

**Technical Metrics:**
- Order Latency p95: [ms]
- Error Rate: [Percentage]%
- System Uptime: [Percentage]%
- Reconciliation Mismatches: [Number]

**Risk Management:**
- Max Position Exposure: $[Amount]
- Daily Loss Limit Used: [Percentage]%
- Risk Limit Breaches: [Number]
- Kill Switch Triggers: [Number]

**Issues and Incidents:**
- [List all issues encountered]
- [List all alerts triggered]
- [List any manual interventions]
- [List any unexpected behaviors]

**Success/Failure Determination:**
- Keep as is: [Yes/No]
- Scale slightly: [Yes/No]
- Tighten controls: [Yes/No]
- Stop trading: [Yes/No]

**Lessons Learned:**
- [What worked well]
- [What didn't work]
- [What needs improvement]
- [What was surprising]

**Next Steps:**
- [Adjustments for Day 2]
- [Threshold changes]
- [Process improvements]
- [Team feedback]

---

## 🎯 **SUCCESS/FAILURE CRITERIA**

### **KEEP AS IS (All conditions met):**
- P&L > -$25 USD (within 50% of loss limit)
- Win rate ≥ 40%
- No critical alerts
- Perfect reconciliation (0 mismatches)
- All SLOs green
- No manual interventions required

### **SCALE SLIGHTLY (Keep criteria + any of these):**
- P&L > $10 USD (profitable)
- Win rate ≥ 60%
- Zero errors for 2+ hours
- Perfect reconciliation for 2+ hours
- All SLOs comfortably green

### **TIGHTEN CONTROLS (Any condition met):**
- P&L between -$25 and -$50 USD
- Win rate between 30% and 40%
- Minor SLO breaches (warning level)
- Small reconciliation mismatches (< $0.01)
- Some manual alerts triggered

### **STOP TRADING (Any condition met):**
- P&L < -$50 USD (loss limit exceeded)
- Win rate < 30%
- Critical SLO breaches
- Reconciliation failures
- Multiple manual interventions required

---

## 📞 **CONTACT INFORMATION**

### **Primary Team:**
- **Engineering Lead:** [Name] - [Phone] - [Email]
- **Operations Lead:** [Name] - [Phone] - [Email]
- **Risk Lead:** [Name] - [Phone] - [Email]

### **Emergency Contacts:**
- **24/7 On-Call:** [Phone]
- **Emergency Hotline:** [Phone]
- **Venue Support:** [Phone]

### **Communication Channels:**
- **Slack:** #merid-canary
- **Email:** canary@merid.com
- **SMS:** [Phone numbers]

---

## ✅ **EXECUTION CHECKLIST**

### **Pre-Launch (8:30 AM):**
- [ ] All systems green on dashboard
- [ ] Risk limits configured correctly
- [ ] Kill switches tested and functional
- [ ] Venue connectivity verified
- [ ] Market data quality confirmed
- [ ] Team communication established
- [ ] Emergency procedures reviewed
- [ ] Monitoring stations ready

### **Launch (9:30 AM):**
- [ ] Strategy enabled in CANARY mode
- [ ] 1% traffic routing confirmed
- [ ] First order execution verified
- [ ] Reconciliation working
- [ ] All systems operational
- [ ] Team ready for monitoring

### **During Trading (9:30 AM - 3:30 PM):**
- [ ] Continuous monitoring active
- [ ] Hourly reviews completed
- [ ] All alerts responded to
- [ ] Risk limits respected
- [ ] Reconciliation perfect
- [ ] Team communication maintained

### **Post-Launch (3:30 PM):**
- [ ] Trading disabled gracefully
- [ ] All orders cancelled
- [ ] All positions closed
- [ ] Final reconciliation completed
- [ ] Data exported successfully
- [ ] Initial review completed
- [ ] Next steps planned

---

**Status:** READY FOR EXECUTION  
**Risk Level:** LOW - Ultra-conservative parameters  
**Team Preparedness:** HIGH - All procedures documented and reviewed
