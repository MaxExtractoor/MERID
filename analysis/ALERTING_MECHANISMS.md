# Alerting Mechanisms Selection

**Date:** 2026-05-13
**Purpose:** Choose and document alerting mechanisms for MERID system

## Alerting Mechanism Options

### Option 1: PagerDuty
**Description:** Incident response platform with on-call scheduling

**Pros:**
- Industry standard for critical alerts
- Built-in on-call scheduling and escalation
- Integration with Slack, SMS, phone calls
- Rich alert context and notes
- Mobile app for quick response
- Analytics and reporting

**Cons:**
- Cost (starting at ~$21/user/month)
- Additional cost for SMS/phone calls
- Learning curve for configuration
- May be overkill for smaller teams

**Cost:** $21-50/month per user
**Complexity:** Medium
**Suitability:** Excellent for CRITICAL alerts

### Option 2: Slack Webhooks
**Description:** Direct integration with Slack channels

**Pros:**
- Free (within Slack limits)
- Familiar interface for most teams
- Easy to set up with webhooks
- Rich formatting with blocks
- Threaded conversations for context
- Integration with other Slack apps

**Cons:**
- No built-in on-call scheduling
- No automatic escalation
- Relies on team monitoring Slack
- No phone/SMS fallback
- May be missed if Slack not monitored

**Cost:** Free (with existing Slack workspace)
**Complexity:** Low
**Suitability:** Good for WARNING/INFO alerts

### Option 3: Email Alerts
**Description:** Traditional email notifications

**Pros:**
- Universal (everyone has email)
- Free (with existing email infrastructure)
- Easy to set up
- Good for non-urgent alerts
- Searchable and archivable

**Cons:**
- Slow delivery (minutes to hours)
- Easy to miss in inbox
- No on-call scheduling
- No automatic escalation
- Spam filtering issues

**Cost:** Free (with existing email infrastructure)
**Complexity:** Low
**Suitability:** Good for INFO alerts, supplemental for others

### Option 4: SMS/Phone via Twilio
**Description:** Direct SMS and phone call alerts

**Pros:**
- Immediate delivery
- Hard to miss
- Works without internet
- Reliable for critical alerts
- Can be combined with other mechanisms

**Cons:**
- Cost (SMS ~$0.0075/message, calls ~$0.013/minute)
- Limited character count for SMS
- Phone calls can be disruptive
- No built-in scheduling
- Requires phone number management

**Cost:** Variable based on usage
**Complexity:** Medium
**Suitability:** Excellent for CRITICAL alerts as backup

### Option 5: Custom Alerting Service
**Description:** Build custom alerting infrastructure

**Pros:**
- Full control over features
- Can integrate with existing systems
- No external dependencies
- Customizable to exact needs
- No ongoing subscription costs

**Cons:**
- High development effort
- Maintenance burden
- Need to build reliability features
- Need to build on-call scheduling
- Need to build escalation logic

**Cost:** Development time only
**Complexity:** High
**Suitability:** Only if team has capacity and specific needs

## Recommended Alerting Strategy

### Multi-Layer Approach

#### Layer 1: CRITICAL Alerts (Immediate Action Required)
**Primary:** PagerDuty
- On-call scheduling
- Escalation policies
- SMS and phone call notifications
- Mobile app for quick acknowledgment

**Backup:** Slack + SMS (Twilio)
- Slack webhook for team visibility
- SMS backup if PagerDuty fails
- Phone call backup for most critical

**Rationale:** PagerDuty provides industry-standard incident response with built-in scheduling and escalation. Slack provides team visibility. SMS/phone provides backup.

#### Layer 2: WARNING Alerts (Attention Required)
**Primary:** Slack Webhooks
- Dedicated #ops-warnings channel
- Rich formatting with context
- Threaded discussions
- @mentions for relevant teams

**Secondary:** Email
- Email backup for team members not on Slack
- Searchable archive
- Can be filtered/routed

**Rationale:** Slack provides immediate visibility with rich context. Email provides backup and archive.

#### Layer 3: INFO Alerts (Informational)
**Primary:** Log Aggregation (ELK/Loki)
- Indexed logs for search
- Dashboards for visualization
- No direct notifications
- Queries for investigation

**Secondary:** Optional Slack #ops-info channel
- Low-volume informational alerts
- Status updates
- Scheduled maintenance notifications

**Rationale:** Log aggregation provides search and analysis. Optional Slack channel for important informational updates.

## Implementation Plan

### Phase 1: Slack Webhooks (Immediate)
**Timeline:** 1-2 days
**Tasks:**
1. Create Slack webhooks for #ops-critical, #ops-warnings, #ops-info
2. Implement webhook sender utility
3. Integrate with structured logging helpers
4. Test alert delivery
5. Document webhook URLs in secure config

**Cost:** Free
**Value:** Immediate team visibility for all alerts

### Phase 2: PagerDuty Integration (Short-term)
**Timeline:** 1-2 weeks
**Tasks:**
1. Set up PagerDuty account and service
2. Configure on-call schedules
3. Configure escalation policies
4. Implement PagerDuty integration API
5. Integrate with CRITICAL alert conditions
6. Test on-call escalation
7. Train team on PagerDuty usage

**Cost:** $21-50/month
**Value:** Professional incident response for critical alerts

### Phase 3: SMS Backup (Medium-term)
**Timeline:** 2-4 weeks
**Tasks:**
1. Set up Twilio account
2. Configure phone numbers
3. Implement SMS sender utility
4. Configure SMS backup for critical alerts
5. Test SMS delivery
6. Manage phone number opt-in/opt-out

**Cost:** Variable based on usage
**Value:** Reliable backup for critical alerts

### Phase 4: Log Aggregation (Long-term)
**Timeline:** 1-2 months
**Tasks:**
1. Choose log aggregation platform (ELK/Loki)
2. Set up log shipping infrastructure
3. Configure log parsing and indexing
4. Build alert queries
5. Create dashboards
6. Train team on log investigation

**Cost:** Infrastructure costs (cloud or self-hosted)
**Value:** Powerful log search and analysis

## Configuration Requirements

### Environment Variables
```bash
# Slack Webhooks
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/...
SLACK_WEBHOOK_WARNINGS=https://hooks.slack.com/services/...
SLACK_WEBHOOK_INFO=https://hooks.slack.com/services/...

# PagerDuty
PAGERDUTY_API_KEY=...
PAGERDUTY_SERVICE_ID=...
PAGERDUTY_ESCALATION_POLICY_ID=...

# Twilio (optional)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
ALERT_SMS_RECIPIENTS=+15551234567,+15551234568
```

### Alert Configuration File
```yaml
# config/alerting.yaml
critical:
  channels:
    - pagerduty
    - slack_critical
    - sms
  rate_limit: 1 per 5 minutes
  escalation:
    - level: on_call
      timeout: 5 minutes
    - level: ops_lead
      timeout: 15 minutes
    - level: engineering_lead
      timeout: 30 minutes

warning:
  channels:
    - slack_warnings
    - email
  rate_limit: 5 per minute
  escalation:
    - level: ops_team
      timeout: 30 minutes

info:
  channels:
    - log_aggregation
    - slack_info
  rate_limit: 10 per minute
  escalation: none
```

## Alert Content Format

### Slack Message Format
```json
{
  "text": "CRITICAL: Global Risk Cap Exceeded",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🚨 CRITICAL: Global Risk Cap Exceeded"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Severity:* CRITICAL"
        },
        {
          "type": "mrkdwn",
          "text": "*Condition:* total_risk_cap"
        },
        {
          "type": "mrkdwn",
          "text": "*Current:* $8,500"
        },
        {
          "type": "mrkdwn",
          "text": "*Limit:* $8,000"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Action:* Halt all trading, investigate exposure\n*Correlation ID:* abc-123-xyz"
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "View Logs"
          },
          "url": "https://logs.example.com/?correlation_id=abc-123-xyz"
        }
      ]
    }
  ]
}
```

### PagerDuty Event Format
```json
{
  "routing_key": "pagerduty_integration_key",
  "event_action": "trigger",
  "payload": {
    "summary": "Global Risk Cap Exceeded",
    "severity": "critical",
    "source": "merid.guards.global_risk_guard",
    "timestamp": "2026-05-13T15:00:00Z",
    "custom_details": {
      "condition": "total_risk_cap",
      "current_value": 8500,
      "threshold_value": 8000,
      "correlation_id": "abc-123-xyz",
      "agent_id": "kalshi-btc_15m"
    }
  }
}
```

### SMS Message Format
```
CRITICAL: Global Risk Cap Exceeded
Current: $8,500, Limit: $8,000
Action: Halt trading, investigate
Correlation: abc-123-xyz
```

## Testing Strategy

### Unit Tests
- Test webhook sender with mock endpoints
- Test PagerDuty API integration with mock service
- Test SMS sender with mock Twilio
- Test alert formatting for each channel
- Test rate limiting logic

### Integration Tests
- Test actual Slack webhook delivery
- Test actual PagerDuty event creation
- Test actual SMS delivery (to test numbers)
- Test alert routing to correct channels
- Test escalation policies

### Manual Tests
- Simulate critical alert, verify all channels receive it
- Simulate warning alert, verify correct channels
- Simulate info alert, verify log aggregation
- Test escalation timing
- Test rate limiting prevents spam

## Success Criteria

1. Alerting mechanism selected with clear rationale
2. Multi-layer strategy documented
3. Implementation plan with timeline
4. Configuration requirements specified
5. Alert content formats defined
6. Testing strategy defined
7. Cost analysis completed

## Decision

**Selected Approach:** Multi-layer alerting with Slack webhooks (immediate), PagerDuty (short-term), SMS backup (medium-term), log aggregation (long-term)

**Rationale:**
- Slack provides immediate team visibility at no cost
- PagerDuty provides professional incident response for critical alerts
- SMS provides reliable backup for critical alerts
- Log aggregation provides powerful search and analysis
- Phased implementation allows incremental value delivery

**Next Steps:**
1. Implement Slack webhooks (Phase 1)
2. Set up PagerDuty account (Phase 2)
3. Implement PagerDuty integration (Phase 2)
4. Set up Twilio for SMS backup (Phase 3)
5. Implement log aggregation (Phase 4)
