# Live Run Escalation Protocol

**Version**: 1.0
**Last Updated**: 2026-05-23
**Profile**: kalshi_crypto_15m_v2

---

## Overview

This protocol defines automated and manual escalation triggers for live trading sessions. It ensures that anomalous behavior is detected early and responded to with appropriate urgency.

---

## Automated Escalation Triggers

### P0 - Immediate Stop (Critical)

| Trigger | Threshold | Action | Recovery |
|---------|-----------|--------|----------|
| **Kill Switch Activated** | Any kill switch fires | Stop all trading, close positions, alert operators | Manual investigation before restart |
| **Bankroll Drawdown** | > 10% from session start | Stop trading, preserve capital, alert operators | Manual review of strategy parameters |
| **Risk Envelope Violation** | 3 consecutive violations | Stop trading, alert operators | Review risk envelope configuration |
| **API Rate Limiting** | > 50% of rate limit hit | Throttle orders, log warning | Wait for rate limit reset |
| **Authentication Failure** | Any auth failure | Stop trading, alert operators | Check credentials and permissions |

### P1 - Pause and Review (High)

| Trigger | Threshold | Action | Recovery |
|---------|-----------|--------|----------|
| **Consecutive No-Fill Cycles** | 3 consecutive 15m cycles with 0 fills | Pause trading, log summary, alert operators | Review edge thresholds, market conditions |
| **Fill Rate Drop** | Fill rate < 20% over 10 cycles | Pause trading, investigate execution quality | Check order pricing, market liquidity |
| **Market Data Stale** | Market state age > 30s for > 1 min | Pause trading, alert operators | Check WebSocket bridge, API connectivity |
| **Reconciliation Delta** | Bankroll delta > $1.00 | Pause trading, investigate discrepancy | Review fill ledger, API balance |
| **Order Rejection Rate** | > 50% rejection rate over 5 cycles | Pause trading, review rejection reasons | Check risk gates, market conditions |

### P2 - Warning and Monitor (Medium)

| Trigger | Threshold | Action | Recovery |
|---------|-----------|--------|----------|
| **Edge Gap Increase** | Average edge gap increases by 50% | Log warning, monitor | Consider edge threshold adjustment |
| **Exposure Cap Breach** | Exposure > 90% of cap | Log warning, reduce new orders | Wait for exposure to normalize |
| **Latency Spike** | Order latency > 2000ms for 5 orders | Log warning, monitor infrastructure | Check network, API performance |
| **Position Concentration** | > 50% of exposure in single asset | Log warning, diversify | Review asset allocation strategy |
| **Deep-OTM/ITM Filter Rate** | > 80% of contracts filtered | Log warning, review market conditions | Check if market regime has changed |

---

## Manual Escalation Criteria

### Operator-Initiated Pause

Operators may manually pause trading if:

- Dashboard shows anomalous metrics not covered by automated triggers
- External market events (news, volatility spikes) warrant caution
- Infrastructure issues (database, network, third-party services) are suspected
- Strategy parameters need adjustment during session

### Manual Stop Conditions

Operators must manually stop trading if:

- Any P0 trigger occurs and automated stop fails
- Legal/compliance issues arise
- Financial institution limits are approached
- Operator confidence in system integrity is compromised

---

## Escalation Response Procedure

### Step 1: Detection (Automated or Manual)

- **Automated**: System logs trigger, sends alert via configured channels (Telegram, email, dashboard)
- **Manual**: Operator identifies issue, initiates escalation

### Step 2: Immediate Action

- **P0**: Immediate stop, position closure if safe
- **P1**: Pause new orders, allow existing orders to fill or expire
- **P2**: Log warning, continue monitoring with increased scrutiny

### Step 3: Investigation

- Review logs for trigger context
- Check dashboard metrics for patterns
- Verify external factors (market conditions, infrastructure)
- Document findings in incident log

### Step 4: Decision

- **Resume**: If issue is transient and resolved
- **Adjust**: If parameters need tuning (edge thresholds, exposure caps)
- **Stop**: If issue is systemic or requires deeper investigation

### Step 5: Post-Incident Review

- Document root cause
- Update protocol if new trigger needed
- Adjust monitoring thresholds if appropriate
- Share learnings with team

---

## Escalation Channels

### Alert Routing

| Severity | Channels | Response Time |
|----------|----------|---------------|
| P0 | Telegram (urgent), Email (urgent), Dashboard banner | < 5 min |
| P1 | Telegram (warning), Email (warning), Dashboard alert | < 15 min |
| P2 | Dashboard warning, Log entry | < 30 min |

### Contact Information

- **Primary Operator**: [TBD]
- **Secondary Operator**: [TBD]
- **On-Call Engineer**: [TBD]
- **Emergency Contact**: [TBD]

---

## Session State Management

### Pause State

- New orders: Blocked
- Existing orders: Allowed to fill or expire naturally
- Position management: Continue (stop-loss, take-profit)
- Monitoring: Increased frequency

### Stop State

- New orders: Blocked
- Existing orders: Cancel if safe and prudent
- Position management: Manual review
- Monitoring: Full investigation mode

### Resume State

- Pre-resume checklist:
  - [ ] Root cause identified and resolved
  - [ ] Dashboard metrics normalized
  - [ ] External factors stable
  - [ ] Operator approval obtained
- Gradual ramp-up: Start with reduced size, monitor closely

---

## Configuration

### Threshold Customization

These thresholds can be adjusted via environment variables or profile configuration:

```yaml
escalation:
  p0:
    max_drawdown_pct: 10
    risk_envelope_violations: 3
    api_rate_limit_pct: 50
  p1:
    consecutive_no_fill_cycles: 3
    min_fill_rate_pct: 20
    market_state_stale_seconds: 30
    reconciliation_delta_usd: 1.00
    max_rejection_rate_pct: 50
  p2:
    edge_gap_increase_pct: 50
    exposure_cap_breach_pct: 90
    max_latency_ms: 2000
    max_position_concentration_pct: 50
    max_filter_rate_pct: 80
```

### Alert Configuration

```yaml
alerts:
  telegram:
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
  email:
    enabled: true
    smtp_server: ${SMTP_SERVER}
    recipients:
      - operator@example.com
  dashboard:
    enabled: true
    refresh_interval_ms: 5000
```

---

## Testing and Validation

### Escalation Testing

Before each live session:

- [ ] Verify alert channels are operational
- [ ] Test P0 trigger (simulate kill switch)
- [ ] Test P1 trigger (simulate consecutive no-fills)
- [ ] Verify dashboard alerts display correctly
- [ ] Confirm contact information is current

### Protocol Review

Review and update this protocol:

- **Monthly**: Threshold tuning based on session data
- **Quarterly**: Full protocol review and update
- **After Incident**: Update if new patterns discovered

---

## Appendix: Incident Log Template

```markdown
## Incident Log

**Incident ID**: [UUID]
**Timestamp**: [ISO 8601]
**Severity**: P0 / P1 / P2
**Trigger**: [Trigger name]
**Threshold**: [Value that triggered]
**Actual Value**: [Value at trigger time]

### Context
- Session ID: [Run ID]
- Cycle Number: [N]
- Market Conditions: [Description]
- System State: [Description]

### Actions Taken
1. [Action 1]
2. [Action 2]
3. [Action 3]

### Investigation Findings
- Root Cause: [Description]
- Contributing Factors: [List]
- External Factors: [List]

### Resolution
- Resolution Time: [Timestamp]
- Resolution Action: [Description]
- System State After: [Description]

### Follow-Up
- Protocol Changes Needed: [Yes/No, details]
- Monitoring Changes Needed: [Yes/No, details]
- Configuration Changes Needed: [Yes/No, details]
```

---

**Document Owner**: Cascade AI Assistant
**Approval Status**: Pending
**Next Review Date**: 2026-06-23
