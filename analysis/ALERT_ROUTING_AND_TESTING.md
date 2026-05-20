# Alert Routing and Testing Configuration

**Date:** 2026-05-13
**Purpose:** Configure alert routing and define testing strategy

## Alert Routing Configuration

### Environment Variables
```bash
# Slack Webhooks
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/...
SLACK_WEBHOOK_WARNINGS=https://hooks.slack.com/services/...
SLACK_WEBHOOK_INFO=https://hooks.slack.com/services/...

# PagerDuty
PAGERDUTY_API_KEY=...

# Twilio SMS
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+15551234567
ALERT_SMS_RECIPIENTS=+15551234568,+15551234569
```

### Channel Mapping
- **CRITICAL:** PagerDuty → Slack Critical → SMS
- **WARNING:** Slack Warnings → Email
- **INFO:** Slack Info → Log Aggregation

## Testing Strategy

### Unit Tests
- AlertRateLimiter: Test rate limiting logic
- AlertContext: Test serialization
- Payload builders: Test Slack/PagerDuty formats
- send_alert: Test channel routing

### Integration Tests
- Slack webhook delivery (with test webhook)
- PagerDuty event creation (with test API key)
- SMS delivery (with test numbers)
- End-to-end alert flow

### Manual Tests
1. Configure test webhooks/API keys
2. Simulate CRITICAL alert, verify all channels
3. Simulate WARNING alert, verify correct channels
4. Simulate INFO alert, verify log aggregation
5. Test rate limiting prevents spam

## Success Criteria
- Environment variables documented
- Channel mapping defined
- Unit tests pass
- Integration tests pass (when configured)
- Manual testing procedure documented
