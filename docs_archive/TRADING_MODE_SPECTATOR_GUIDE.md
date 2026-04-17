# MERID Trading Mode & Spectator Feature Guide

## Overview

The MERID Trading Mode Controller provides a comprehensive system for managing trading execution modes across the entire platform. It includes a powerful **Spectator Feature** that allows you to watch agents perform paper trades in real-time, logging all activity for future strategy development.

## Trading Modes

### 1. Paper Mode (Default)
- **All trades are simulated**
- No real capital at risk
- Perfect for testing strategies
- Uses live market data for realistic simulation

```bash
# Set paper mode
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "paper", "reason": "Testing new strategy"}'
```

### 2. Hybrid Mode
- **Paper trades with live data**
- Manual approval required for live execution
- Best for transitioning from paper to live
- Allows careful oversight of each trade

```bash
# Set hybrid mode
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "hybrid", "reason": "Transitioning to live"}'
```

### 3. Live Mode
- **Real execution on exchanges**
- All trades execute immediately
- Requires exchange API keys
- Use with extreme caution

```bash
# Set live mode
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "live", "reason": "Going live"}'
```

### 4. Autonomous Mode
- **Full autonomous live trading**
- Subject to safety limits
- Automatic execution within bounds
- Ideal for proven strategies

```bash
# Set autonomous mode
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "autonomous", "reason": "Deploying proven strategy"}'
```

## Autonomous Mode Limits

Autonomous mode includes built-in safety limits to prevent runaway trading:

### Default Limits
- **Max Position Size**: $1,000 USD
- **Max Daily Trades**: 50
- **Max Daily Volume**: $10,000 USD
- **Allowed Symbols**: BTC/USDT, ETH/USDT, SOL/USDT

### Updating Limits

```bash
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/limits \
  -H "Content-Type: application/json" \
  -d '{
    "max_position_usd": 2000.0,
    "max_daily_trades": 100,
    "max_daily_volume_usd": 25000.0,
    "allowed_symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"]
  }'
```

### Checking Execution Permission

```bash
# Check if a trade can execute
curl "http://127.0.0.1:8000/api/v1/trading-mode/can-execute?symbol=BTC/USDT&amount_usd=500"

# Response
{
  "can_execute": true,
  "reason": "Execution allowed",
  "mode": "autonomous"
}
```

## Spectator Feature

The Spectator Feature allows you to watch agents perform trades in real-time, providing invaluable insights for strategy development.

### Key Features
- **Real-time trade feed** - Watch trades as they happen
- **Agent tracking** - See which agents are most active
- **Strategy analysis** - Compare performance by strategy
- **P&L tracking** - Monitor profitability
- **Trade history** - Full audit trail for analysis

### Accessing Spectator Mode

#### Via UI
1. Navigate to **Spectator** in the sidebar
2. Click **Start Watching**
3. Trades will appear in real-time

#### Via API

```bash
# Get live spectator feed
curl "http://127.0.0.1:8000/api/v1/trading-mode/spectator/live?limit=50"

# Response includes:
# - trades: Array of recent trades
# - summary: Total trades, open/closed, P&L
# - agents: Per-agent statistics
```

### Recording Trades

Trades are automatically recorded when executed through the ExecutionAgent. You can also manually record trades:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/spectator/record \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "analyst-gemma-01",
    "symbol": "BTC/USDT",
    "action": "buy",
    "quantity": 0.05,
    "price": 42500.00,
    "strategy": "momentum_breakout",
    "confidence": 0.85,
    "reasoning": "Strong bullish momentum detected with volume confirmation",
    "metadata": {
      "signal_type": "technical",
      "timeframe": "15m"
    }
  }'
```

### Closing Trades

```bash
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/spectator/close \
  -H "Content-Type: application/json" \
  -d '{
    "trade_id": "640c6a93-d835-453a-8f7f-d016100fac99",
    "exit_price": 43200.00,
    "pnl": 35.00
  }'
```

### Trading Statistics

```bash
# Get comprehensive statistics
curl "http://127.0.0.1:8000/api/v1/trading-mode/spectator/stats"

# Response includes:
# - total_trades, open_trades, closed_trades
# - winning_trades, losing_trades, win_rate
# - total_pnl, avg_pnl
# - by_symbol: Performance breakdown by symbol
# - by_strategy: Performance breakdown by strategy
```

## Integration with Execution Agent

The Trading Mode Controller is fully integrated with the ExecutionAgent:

```python
from trading.mode_controller import get_trading_mode_controller

# Get controller
controller = get_trading_mode_controller()

# Check if live execution allowed
can_execute, reason = controller.can_execute_live("BTC/USDT", 500.0)

if can_execute:
    # Execute trade
    pass
else:
    # Log reason and continue in paper mode
    print(f"Live execution blocked: {reason}")

# Record trade for spectator
controller.record_trade(
    agent_id="my-agent",
    symbol="BTC/USDT",
    action="buy",
    quantity=0.1,
    price=42000.0,
    strategy="trend_following",
    confidence=0.78,
    reasoning="Uptrend continuation",
    metadata={"timeframe": "1h"}
)
```

## Mode Change History

Track all mode changes for audit purposes:

```bash
curl "http://127.0.0.1:8000/api/v1/trading-mode/history?limit=20"

# Response
{
  "history": [
    {
      "event_id": "122f04b2-d671-4263-ac65-af3079806745",
      "old_mode": "paper",
      "new_mode": "autonomous",
      "changed_by": "api",
      "timestamp": 1768164103.8617327,
      "reason": "Testing autonomous mode"
    }
  ],
  "count": 1
}
```

## Best Practices

### 1. Start with Paper Mode
Always test new strategies in paper mode first. Use the spectator feature to analyze performance before going live.

### 2. Use Hybrid for Transition
When moving from paper to live, use hybrid mode to manually approve each trade until you're confident.

### 3. Set Conservative Autonomous Limits
Start with low limits in autonomous mode and gradually increase as you gain confidence.

### 4. Monitor Spectator Feed
Regularly check the spectator feed to identify:
- Which agents are most profitable
- Which strategies work best
- Which symbols have best performance
- Patterns in winning vs losing trades

### 5. Log Everything
The spectator feature logs all trades with reasoning and metadata. Use this for:
- Strategy backtesting
- Performance analysis
- Agent behavior analysis
- Future strategy development

## API Endpoints Reference

### Trading Mode
- `GET /api/v1/trading-mode/status` - Get current status
- `GET /api/v1/trading-mode/mode` - Get current mode
- `POST /api/v1/trading-mode/mode` - Change mode
- `GET /api/v1/trading-mode/history` - Mode change history
- `GET /api/v1/trading-mode/limits` - Get autonomous limits
- `POST /api/v1/trading-mode/limits` - Update autonomous limits
- `GET /api/v1/trading-mode/can-execute` - Check execution permission

### Spectator
- `GET /api/v1/trading-mode/spectator/trades` - Get trades (with filters)
- `GET /api/v1/trading-mode/spectator/live` - Live feed with summary
- `POST /api/v1/trading-mode/spectator/record` - Record a trade
- `POST /api/v1/trading-mode/spectator/close` - Close a trade
- `GET /api/v1/trading-mode/spectator/stats` - Trading statistics

## UI Components

### Trading Mode Panel
Located in the Spectator section:
- 4 mode buttons (Paper, Hybrid, Live, Autonomous)
- Current mode indicator badge
- Daily statistics display
- Warning for live modes

### Spectator Panel
- Live trade feed with real-time updates
- Summary statistics (total trades, open/closed, P&L)
- Agent list with per-agent stats
- Trade details including reasoning and metadata

### Statistics Panel
- Win rate and average P&L
- Performance by symbol
- Performance by strategy
- Detailed breakdowns

## Example Workflow

### Testing a New Strategy

1. **Set Paper Mode**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "paper", "reason": "Testing new momentum strategy"}'
```

2. **Run Strategy and Watch Spectator**
- Navigate to Spectator section in UI
- Click "Start Watching"
- Let strategy run for several hours/days

3. **Analyze Results**
```bash
curl "http://127.0.0.1:8000/api/v1/trading-mode/spectator/stats"
```

4. **If Profitable, Move to Hybrid**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "hybrid", "reason": "Strategy proven in paper mode"}'
```

5. **Manually Approve Trades**
- Review each trade in hybrid mode
- Approve only high-confidence trades

6. **If Consistent, Move to Autonomous**
```bash
# Set conservative limits first
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/limits \
  -H "Content-Type: application/json" \
  -d '{"max_position_usd": 500.0, "max_daily_trades": 10}'

# Then enable autonomous
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "autonomous", "reason": "Deploying proven strategy with limits"}'
```

## Safety Features

### Built-in Protections
1. **Mode-based gating** - Trades blocked based on current mode
2. **Autonomous limits** - Position size, daily trade, and volume limits
3. **Symbol allowlist** - Only approved symbols in autonomous mode
4. **Daily reset** - Limits reset every 24 hours
5. **Audit trail** - All mode changes and trades logged

### Emergency Procedures
If something goes wrong:

1. **Immediately switch to Paper Mode**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/trading-mode/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "paper", "reason": "EMERGENCY STOP"}'
```

2. **Review spectator logs** to identify the issue
3. **Adjust strategy or limits** before resuming

## Troubleshooting

### Trades Not Appearing in Spectator
- Ensure ExecutionAgent is properly integrated
- Check that trades are being recorded via API
- Verify spectator polling is active in UI

### Autonomous Mode Rejecting Trades
- Check limits: `GET /api/v1/trading-mode/limits`
- Verify symbol is in allowlist
- Check daily stats haven't exceeded limits
- Use `can-execute` endpoint to diagnose

### Mode Changes Not Taking Effect
- Verify API response shows success
- Check mode history to confirm change
- Restart any cached components if needed

## Future Enhancements

Planned features for future releases:
- WebSocket streaming for real-time spectator updates
- Advanced filtering in spectator view
- Trade replay functionality
- Strategy comparison tools
- Automated strategy optimization
- Risk-adjusted performance metrics
- Integration with backtesting engine

## Support

For issues or questions:
- Check server logs: `tail -f logs/merid.log`
- Review API responses for error details
- Consult MERID documentation
- Check GitHub issues

---

**Remember**: Always start with paper mode, use spectator to analyze performance, and only move to live trading when you have proven, consistent results.
