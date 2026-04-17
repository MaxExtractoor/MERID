# MERID Bot Integration

> **Primary Module**: `bots/bot_integration.py`  
> **Test File**: `tests/test_sections_8_14.py`

---

## Overview

MERID bots (Telegram, Twitter/X) are **thin frontends on the event bus**—not separate systems. They:

1. Read from Kafka topics and post human-readable summaries
2. Accept commands that become events on `{platform}.commands.*` topics
3. Enforce RBAC: only privileged users can execute sensitive commands
4. Rate limit all interactions to prevent abuse

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Telegram   │────▶│ BotManager  │────▶│   Kafka     │
│  Twitter/X  │     │             │◀────│   Topics    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │
       │    Commands       │    Alerts from
       │    (/status)      │    risk.*, alerts.*
       ▼                   ▼
  telegram.commands.*   Bot broadcasts
```

---

## Supported Commands

| Command | Permission | Description | Cooldown |
|---------|------------|-------------|----------|
| `/help` | PUBLIC | Show available commands | 5s |
| `/status` | PUBLIC | Get system status | 10s |
| `/risk` | AUTHENTICATED | Get risk metrics | 30s |
| `/portfolio` | AUTHENTICATED | Get portfolio summary | 30s |
| `/mute [mins]` | AUTHENTICATED | Mute alerts temporarily | 60s |
| `/unmute` | AUTHENTICATED | Unmute alerts | 10s |
| `/pause [reason]` | OPERATOR | Pause trading | 60s |
| `/resume` | OPERATOR | Resume trading | 60s |
| `/kill [reason]` | ADMIN | Trigger kill switch | 0s |

---

## Permission Tiers

| Level | Who | Capabilities |
|-------|-----|--------------|
| `PUBLIC` | Anyone | `/help`, `/status` |
| `AUTHENTICATED` | Registered users | + `/risk`, `/portfolio`, `/mute` |
| `OPERATOR` | Trading operators | + `/pause`, `/resume` |
| `ADMIN` | System admins | + `/kill` (emergency only) |

### Registering Privileged Users

```python
from bots.bot_integration import TelegramBot

bot = TelegramBot(token="your-bot-token")

# Register users by platform user ID
bot.register_admin("123456789")      # Telegram user ID
bot.register_operator("987654321")

# Check permission level
level = bot.get_user_permission("123456789")
# Returns: PermissionLevel.ADMIN
```

---

## Telegram Bot

### Setup

```python
from bots.bot_integration import TelegramBot, get_bot_manager

# Create bot
telegram = TelegramBot(token="your-telegram-bot-token")

# Add alert channels
telegram.add_alert_channel("-1001234567890")  # Group/channel ID

# Register with manager
manager = get_bot_manager()
manager.register_bot(telegram)

# Start
await manager.start_all()
```

### Command Handling

```python
from bots.bot_integration import BotCommand, CommandType

command = BotCommand(
    user_id="123456789",
    username="trader_alice",
    chat_id="-1001234567890",
    command_type=CommandType.STATUS,
    raw_text="/status",
)

response = await telegram.handle_command(command)
# Returns formatted status message
```

### Response Formats

**Status Response**:
```
📊 **MERID Status**
├ Mode: paper
├ Agents: 5/5 healthy
├ Daily PnL: $1,234.56
└ Last Update: 14:30:00
```

**Risk Response**:
```
⚠️ **Risk Metrics**
├ Exposure: $50,000.00
├ Leverage: 1.50x
├ Drawdown: 2.3%
├ Daily Loss: $500.00
└ Kill Switch: 🟢 Ready
```

---

## Twitter/X Bot

### Setup

```python
from bots.bot_integration import TwitterBot

twitter = TwitterBot(
    api_key="your-api-key",
    api_secret="your-api-secret",
)

manager.register_bot(twitter)
```

### Posting Tweets

```python
# Post market summary
content = twitter.format_market_summary({
    "btc_price": 50000,
    "btc_change": 2.5,
    "eth_price": 3000,
    "eth_change": 1.2,
    "sentiment": "Bullish",
})

await twitter.post_tweet(content)
# Output:
# 📊 MERID Market Update
# BTC: $50,000 (+2.5%)
# ETH: $3,000 (+1.2%)
# Sentiment: Bullish
#
# #MERID #CryptoTrading #AI
```

### Rate Limits

Twitter bot has built-in rate limiting:

```python
# Default: 10 tweets per hour
twitter._tweets_per_hour = 10

# Automatically tracked
if len(twitter._tweet_history) >= twitter._tweets_per_hour:
    # Will not post, returns False
    pass
```

---

## Alert Broadcasting

### Subscribing to Topics

```python
from bots.bot_integration import BotType, get_bot_manager

manager = get_bot_manager()

# Subscribe Telegram to risk alerts
manager.subscribe_to_topic("alerts.*", BotType.TELEGRAM)
manager.subscribe_to_topic("risk.alerts.*", BotType.TELEGRAM)

# Subscribe both to kill switch events
manager.subscribe_to_topic("governance.kill_switch", BotType.TELEGRAM)
manager.subscribe_to_topic("governance.kill_switch", BotType.TWITTER)
```

### Handling Kafka Events

```python
# Called by Kafka consumer
await manager.handle_kafka_event("risk.alerts.critical", {
    "event_id": "evt_abc123",
    "title": "Position Limit Breach",
    "message": "BTC position exceeds 25% of portfolio",
    "severity": "critical",
})

# Automatically routes to subscribed bots
```

### Alert Formatting

```python
from bots.bot_integration import BotAlert

alert = BotAlert(
    title="Daily Loss Limit Warning",
    message="Daily loss at 80% of limit ($4,000/$5,000)",
    severity="warning",
    target_platforms=[BotType.TELEGRAM],
)

# Formatted output:
# ⚠️ **Daily Loss Limit Warning**
# Daily loss at 80% of limit ($4,000/$5,000)
```

### Severity Icons

| Severity | Icon |
|----------|------|
| `info` | ℹ️ |
| `warning` | ⚠️ |
| `critical` | 🚨 |

---

## Rate Limiting

### User-Level Limits

```python
# Default: 10 commands per minute per user
bot._user_rate_limit = 10

# Check before executing
if not bot.check_rate_limit(user_id):
    return "Rate limit exceeded. Please wait."
```

### Command Cooldowns

Each command has a cooldown defined in `COMMAND_DEFINITIONS`:

```python
COMMAND_DEFINITIONS = {
    CommandType.STATUS: {
        "cooldown_seconds": 10,  # 10 second cooldown
    },
    CommandType.KILL: {
        "cooldown_seconds": 0,   # No cooldown for emergencies
    },
}
```

---

## Muting

Users can mute alerts temporarily:

```python
# Mute for 60 minutes
command = BotCommand(
    command_type=CommandType.MUTE,
    arguments=["60"],
    chat_id="-1001234567890",
)

await bot.handle_command(command)
# "🔇 Alerts muted for 60 minutes"

# Unmute
await bot.handle_command(BotCommand(command_type=CommandType.UNMUTE))
# "🔊 Alerts unmuted"
```

Muted channels won't receive broadcasts:

```python
async def send_message(self, chat_id: str, message: str) -> bool:
    if chat_id in self._muted_channels:
        return False  # Silently skip
    # ... send message
```

---

## Activity Logging

All bot interactions are logged:

```python
# Get recent activity
activity = manager.get_activity_log(limit=100)

# Each entry:
# {
#   "timestamp": 1738750800.0,
#   "topic": "risk.alerts.critical",
#   "event_id": "evt_abc123",
#   "bots_notified": ["telegram", "twitter"],
# }
```

---

## Command Events

Commands become Kafka events for auditing:

```python
# When user sends /pause "Market volatile"
event = command.to_event()

# Output:
# {
#   "event_type": "telegram.command",
#   "event_id": "cmd_abc123",
#   "timestamp": 1738750800.0,
#   "user_id": "123456789",
#   "username": "trader_alice",
#   "command": "pause",
#   "arguments": ["Market volatile"],
#   "raw_text": "/pause Market volatile",
# }

# Published to telegram.commands.* topic
```

---

## Default Setup

Quick setup with default configuration:

```python
from bots.bot_integration import setup_default_bots

manager = setup_default_bots()

# Creates Telegram + Twitter bots
# Subscribes to alerts.*, risk.alerts.*, governance.kill_switch
# Ready to start

await manager.start_all()
```

---

## Status & Monitoring

```python
status = manager.get_status()

# Output:
# {
#   "bots": {
#     "telegram": {"running": True, "muted_channels": 0},
#     "twitter": {"running": True, "muted_channels": 0},
#   },
#   "subscriptions": {
#     "alerts.*": ["telegram"],
#     "governance.kill_switch": ["telegram", "twitter"],
#   },
#   "activity_count": 1542,
# }
```

---

## Security Notes

1. **Never expose bot tokens in logs** – Use `SecretsManager`
2. **Validate user IDs** – Platform user IDs can be spoofed in some contexts
3. **Rate limit aggressively** – Bots are public-facing
4. **Audit all commands** – Especially `/pause` and `/kill`
5. **Restrict admin access** – Only trusted operators should have `/kill`

---

*See also*: `docs/PROGRESS_CHECKPOINT_2026-02-05.md` for full module context.
