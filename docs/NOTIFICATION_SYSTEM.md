# Debate Alert Notification System

This document describes the notification system that routes debate alerts to Telegram and X/Twitter channels.

## Overview

The notification system treats Telegram and X as downstream notification channels driven by the `/debates/alerts` endpoint. It provides:

- **Real-time alert routing** based on severity and rules
- **Message formatting** for each platform
- **Rate limiting** to respect API constraints
- **Daily summaries** of debate activity
- **Configuration management** for routing preferences

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  /debates/alerts │───▶│ NotificationRouter │───▶│ Telegram Client │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   X/Twitter     │
                       │    Client       │
                       └─────────────────┘
```

### Components

1. **Notification Formatters** (`notification_formatters.py`)
   - Convert `AlertItem` objects to platform-specific messages
   - Handle aggregation of similar alerts
   - Format daily summaries

2. **Channel Clients** (`telegram_client.py`, `x_client.py`)
   - HTTP clients for Telegram Bot API and X API v2
   - Handle authentication and rate limiting
   - Provide simple send methods

3. **Notification Router** (`notification_router.py`)
   - Apply routing rules based on severity and filters
   - Manage deduplication and rate limiting
   - Coordinate with channel clients

4. **Configuration Manager** (`notification_config.py`)
   - Load/save configuration from YAML and environment
   - Provide runtime configuration updates
   - Manage channel enable/disable states

5. **Worker Process** (`notification_worker.py`)
   - Periodically poll `/debates/alerts` endpoint
   - Process alerts through the router
   - Send daily summaries at scheduled times

6. **REST API** (`notification_api.py`)
   - Control worker start/stop
   - Update configuration
   - Send test notifications
   - Monitor system status

## Setup

### 1. Environment Variables

```bash
# Telegram Bot (required for Telegram notifications)
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
export TELEGRAM_CHAT_ID="-1001234567890"

# X/Twitter API (required for X notifications)
export X_BEARER_TOKEN="your_bearer_token_here"
# OR use OAuth 1.0a credentials
export X_API_KEY="your_api_key"
export X_API_SECRET="your_api_secret"
export X_ACCESS_TOKEN="your_access_token"
export X_ACCESS_TOKEN_SECRET="your_access_token_secret"

# Optional configuration overrides
export TELEGRAM_ENABLED="true"
export X_ENABLED="false"
export CRITICAL_TO_TELEGRAM="true"
export CRITICAL_TO_X="false"
export WARNINGS_TO_TELEGRAM="true"
export WARNINGS_TO_X="false"
export NOTIFICATION_POLL_MINUTES="5"
export DAILY_SUMMARY_TIME_UTC="9"
```

### 2. Configuration File

Create `notification_config.yaml` (optional - defaults will be created):

```yaml
channels:
  telegram:
    enabled: true
    critical_alerts: true
    warning_alerts: true
    daily_summary: true
  x_twitter:
    enabled: false
    critical_alerts: false
    warning_alerts: false
    daily_summary: false

routing:
  critical_to_telegram: true
  critical_to_x: false
  warnings_to_telegram: true
  warnings_to_x: false
  high_utilization_only: false
  aggregate_similar: true

poll_interval_minutes: 5
daily_summary_time_utc: 9
```

### 3. Telegram Bot Setup

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Get the bot token and add to `TELEGRAM_BOT_TOKEN`
3. Add the bot to your target chat/group
4. Get the chat ID (use [@userinfobot](https://t.me/userinfobot) or inspect bot updates)
5. Add chat ID to `TELEGRAM_CHAT_ID`

### 4. X/Twitter Setup

1. Create a X app at [developer.twitter.com](https://developer.twitter.com/)
2. Get API keys and access tokens
3. Add credentials to environment variables
4. Ensure the app has write permissions for posting tweets

## Usage

### Starting the Notification Worker

```bash
# Run continuously (recommended for production)
python -m web.api.notification_worker

# Run a single cycle (for testing)
python -m web.api.notification_worker --once
```

### Using the REST API

```bash
# Start the worker
curl -X POST "http://localhost:8000/api/v1/notifications/worker/start"

# Stop the worker
curl -X POST "http://localhost:8000/api/v1/notifications/worker/stop"

# Run a single cycle
curl -X POST "http://localhost:8000/api/v1/notifications/worker/run-once"

# Send test notification
curl -X POST "http://localhost:8000/api/v1/notifications/test" \
  -H "Content-Type: application/json" \
  -d '{"channel": "telegram", "message": "Test notification"}'

# Get system status
curl "http://localhost:8000/api/v1/notifications/status"

# Get configuration
curl "http://localhost:8000/api/v1/notifications/config"

# Update channel configuration
curl -X PUT "http://localhost:8000/api/v1/notifications/config/channels/telegram" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "critical_alerts": true}'
```

## Message Formats

### Telegram Messages

Telegram messages use Markdown formatting with emojis and structured information:

```
🔴 **Debate Alert** 14:30 UTC

🥇 **Agent:** `debate-agent-001`
📊 **Tier:** GOLD
📈 **Utilization:** 95.0%

🔍 **Issue:** Agent quota utilization is 95.0%
📈 **Metric:** Quota utilization above 90%

#debate #alert #critical
```

### X/Twitter Messages

X messages are concise (≤280 characters) with hashtags:

```
🚨 CRITICAL: debate-agent-001 - Agent quota utilization is 95.0% #debate #trading
```

### Daily Summaries

**Telegram**: Detailed summary with top performers and metrics
**X**: High-level summary with key statistics

## Routing Rules

The system applies routing rules based on alert properties:

1. **Critical alerts**: Sent to all enabled channels by default
2. **Warning alerts**: Sent to Telegram only by default
3. **High utilization filter**: Optional filter for >90% utilization only
4. **Aggregation**: Similar alerts are grouped to reduce spam

### Default Routing

| Severity | Telegram | X/Twitter |
|----------|----------|-----------|
| Critical | ✅ | ❌ |
| Warning  | ✅ | ❌ |
| Daily Summary | ✅ | ❌ |

## Rate Limiting

Built-in rate limiting prevents API abuse:

- **Telegram**: 50 messages per hour
- **X/Twitter**: 20 tweets per day
- **Deduplication**: Same alert not sent more than once per hour

## Testing

Run the test suite to verify functionality:

```bash
python test_notifications.py
```

This tests:
- Message formatting for both platforms
- Alert aggregation logic
- Daily summary generation
- Basic worker functionality

## Monitoring

### API Endpoints

- `GET /api/v1/notifications/status` - System status and rate limits
- `GET /api/v1/notifications/recent-alerts` - Recent alerts for debugging
- `POST /api/v1/notifications/test` - Send test notifications

### Logging

The system logs at INFO level for normal operations and ERROR level for issues:

```bash
# View logs in real-time
tail -f /var/log/merid/notifications.log
```

## Troubleshooting

### Common Issues

1. **"Telegram not configured"**
   - Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` environment variables
   - Verify bot is added to the target chat

2. **"X not configured"**
   - Check X API credentials in environment variables
   - Verify app has write permissions

3. **"Rate limit exceeded"**
   - Wait for rate limit reset (hourly for Telegram, daily for X)
   - Consider adjusting aggregation settings

4. **"No alerts found"**
   - Check if there are active alerts in `/debates/alerts?problems_only=true`
   - Verify worker is running and polling correctly

### Debug Mode

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
python -m web.api.notification_worker
```

## Security Considerations

- Store API tokens securely (environment variables, not in code)
- Use dedicated bot accounts with minimal permissions
- Monitor for unauthorized API usage
- Consider IP whitelisting for production deployments

## Integration with Existing Systems

The notification system integrates seamlessly with:

- **Debate Data APIs**: Uses `/debates/alerts` as the source of truth
- **FastAPI Application**: Runs as part of the main web application
- **Configuration System**: Uses existing environment variable patterns
- **Logging Framework**: Uses the existing logging infrastructure

## Future Enhancements

Potential improvements:

1. **Slack Integration**: Add Slack client for enterprise teams
2. **Email Notifications**: Add email client for critical alerts
3. **Custom Webhooks**: Support for custom webhook endpoints
4. **Alert Templates**: Configurable message templates
5. **Multi-language Support**: Internationalization for messages
6. **Dashboard Integration**: Real-time status in the web UI
