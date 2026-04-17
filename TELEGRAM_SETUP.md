# Telegram Bot Setup for MERID

## Quick Setup

1. **Bot Token**: Already configured in `.env` 
2. **Get Chat ID**: Run the helper script
3. **Test Connection**: Verify bot works

## Step 1: Get Your Telegram Chat ID

```bash
py get_telegram_chat_id.py
```

Follow the instructions:
1. Find your bot in Telegram (search for the bot name)
2. Send any message to the bot (like "hello")
3. The script will show your chat ID
4. Update `.env` with: `TELEGRAM_CHAT_ID=YOUR_CHAT_ID`

## Step 2: Test the Bot

```bash
py test_telegram_bot.py
```

## Step 3: Enable in MERID

The bot is automatically available in the system:
- `core/telegram_bot.py` - Bot implementation
- `telegram_notifier` - Global singleton instance
- `swarm_telegram_bridge` - Bridge for swarm alerts

## Usage Examples

```python
# Send trading signal
await telegram_notifier.send_signal(
    ticker="BTC",
    signal="BUY", 
    price=Decimal("43250.00"),
    confidence=0.85
)

# Send risk alert
await telegram_notifier.send_risk_alert(
    ticker="ETH",
    risk_type="EXPOSURE_LIMIT",
    current=Decimal("15000"),
    threshold=Decimal("10000")
)

# Send custom alert
from core.telegram_bot import TelegramAlert
alert = TelegramAlert(
    alert_type="info",
    ticker=None,
    message="System started successfully",
    severity="low",
    timestamp=datetime.now(),
    data={"Component": "MERID Core"}
)
await telegram_notifier.send_alert(alert)
```

## Integration Points

- **Swarm Agents**: Use `swarm_telegram_bridge` for agent notifications
- **Risk System**: Automatic risk breach alerts
- **Trading**: Signal notifications on trades
- **System**: Error reporting and status updates

## Troubleshooting

- **Chat not found**: Ensure you've messaged the bot first
- **Token invalid**: Check bot token with BotFather
- **No messages**: Verify bot has permission to send messages
