# Risk Module API Documentation

**Module**: `merid.risk`  
**Version**: 1.0  
**Last Updated**: 2026-02-04

---

## Overview

The risk module provides kill switches and safety controls for trading operations. It prevents runaway losses and provides emergency halt capabilities.

## Quick Start

```python
from merid.risk import risk_controller, can_trade, emergency_stop, get_risk_status

# Check if trading is allowed
if can_trade():
    # Place order...
    pass

# Record P&L after trade
risk_controller.record_pnl(-25.50)

# Emergency stop
emergency_stop("Manual halt - investigating anomaly")

# Get current status
status = get_risk_status()
print(status)
```

---

## Classes

### `RiskController`

Main risk management class. Singleton instance available as `risk_controller`.

#### Constructor

```python
RiskController(
    daily_loss_limit: float = 500.0,
    max_position_value: float = 10000.0,
    error_threshold: int = 10
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `daily_loss_limit` | `float` | `500.0` | Max daily loss before kill switch triggers |
| `max_position_value` | `float` | `10000.0` | Max total position value |
| `error_threshold` | `int` | `10` | Error count before kill switch |

#### Methods

##### `can_trade() -> bool`

Check if trading is currently allowed.

```python
if risk_controller.can_trade():
    execute_order(order)
else:
    logger.warning("Trading blocked by kill switch")
```

**Returns**: `True` if trading is allowed, `False` if kill switch is active.

##### `record_pnl(pnl: float) -> bool`

Record realized P&L. May trigger daily loss kill switch.

```python
# After closing a position
realized_pnl = -50.25
can_continue = risk_controller.record_pnl(realized_pnl)
if not can_continue:
    logger.error("Daily loss limit exceeded")
```

**Parameters**:
- `pnl`: Realized profit/loss amount (negative for losses)

**Returns**: `True` if trading can continue, `False` if kill switch triggered.

##### `update_position_value(total_value: float) -> bool`

Update current total position value. May trigger position limit kill.

```python
total_positions = sum(p.value for p in positions)
risk_controller.update_position_value(total_positions)
```

**Parameters**:
- `total_value`: Current total position value in USD

**Returns**: `True` if within limits, `False` if kill switch triggered.

##### `record_error() -> bool`

Record an error occurrence. May trigger error threshold kill.

```python
try:
    response = await venue_client.place_order(order)
except Exception as e:
    risk_controller.record_error()
    raise
```

**Returns**: `True` if within threshold, `False` if kill switch triggered.

##### `emergency_stop(reason: str) -> None`

Immediately halt all trading.

```python
risk_controller.emergency_stop("Detected price anomaly")
```

**Parameters**:
- `reason`: Human-readable reason for the stop

##### `reset(operator: str) -> None`

Reset kill switch after investigation. **Use with caution.**

```python
# Only after confirming issue is resolved
risk_controller.reset("operator_name")
```

**Parameters**:
- `operator`: Name/ID of operator performing reset (for audit)

##### `get_state() -> KillSwitchState`

Get current kill switch state.

```python
from merid.risk import KillSwitchState

state = risk_controller.get_state()
if state == KillSwitchState.TRIGGERED:
    notify_ops_team()
```

**Returns**: `KillSwitchState.ACTIVE` or `KillSwitchState.TRIGGERED`

##### `get_status() -> dict`

Get comprehensive status dictionary.

```python
status = risk_controller.get_status()
# {
#     "state": "active",
#     "can_trade": True,
#     "daily_pnl": -125.50,
#     "daily_loss_limit": 500.0,
#     "daily_loss_pct": 25.1,
#     "position_value": 2500.0,
#     "max_position_value": 10000.0,
#     "error_count": 2,
#     "error_threshold": 10,
#     "kill_reason": None,
#     "kill_details": None,
#     "events": [...]
# }
```

##### `on_kill(callback: Callable[[KillSwitchEvent], None]) -> None`

Register callback for kill switch events.

```python
def alert_ops(event):
    send_slack_alert(f"Kill switch triggered: {event.reason}")

risk_controller.on_kill(alert_ops)
```

**Parameters**:
- `callback`: Function called when kill switch triggers

---

## Enums

### `KillSwitchState`

```python
from merid.risk import KillSwitchState

KillSwitchState.ACTIVE     # Trading allowed
KillSwitchState.TRIGGERED  # Trading blocked
```

### `KillSwitchReason`

```python
from merid.risk import KillSwitchReason

KillSwitchReason.MANUAL          # emergency_stop() called
KillSwitchReason.DAILY_LOSS      # Daily loss limit exceeded
KillSwitchReason.POSITION_LIMIT  # Position value too high
KillSwitchReason.ERROR_THRESHOLD # Too many errors
```

---

## Data Classes

### `KillSwitchEvent`

Event recorded when kill switch state changes.

```python
@dataclass
class KillSwitchEvent:
    timestamp: float      # Unix timestamp
    reason: KillSwitchReason
    details: str          # Human-readable details
    daily_pnl: float      # P&L at time of event
    position_value: float # Position value at time of event
```

---

## Convenience Functions

### `can_trade() -> bool`

Module-level function using singleton controller.

```python
from merid.risk import can_trade

if can_trade():
    place_order(order)
```

### `emergency_stop(reason: str) -> None`

Module-level emergency stop.

```python
from merid.risk import emergency_stop

emergency_stop("Market data anomaly detected")
```

### `get_risk_status() -> dict`

Module-level status getter.

```python
from merid.risk import get_risk_status

status = get_risk_status()
```

---

## Configuration

Risk limits can be configured via environment variables:

```bash
# Maximum daily loss before kill switch (USD)
export MERID_MAX_DAILY_LOSS_USD=500

# Maximum position size per market (USD)  
export MERID_MAX_POSITION_SIZE_USD=1000

# Maximum single order size (USD)
export MERID_MAX_ORDER_SIZE_USD=100
```

Or programmatically:

```python
from merid.risk import RiskController

# Create custom controller (not recommended for production)
custom_controller = RiskController(
    daily_loss_limit=1000.0,
    max_position_value=50000.0,
    error_threshold=5
)
```

---

## Integration Examples

### With Paper Trading

```python
from merid.risk import risk_controller

class PaperTradingEngine:
    def place_order(self, order):
        # Check risk before placing
        if not risk_controller.can_trade():
            return OrderResult(status="rejected", reason="kill_switch")
        
        # Execute order...
        result = self._execute(order)
        return result
    
    def close_position(self, position):
        pnl = self._calculate_pnl(position)
        
        # Record P&L (may trigger kill switch)
        risk_controller.record_pnl(pnl)
        
        return pnl
```

### With Circuit Breakers

```python
from merid.risk import risk_controller
from merid.resilience import CircuitOpenError

async def fetch_with_risk_tracking(client, market_id):
    try:
        return await client.get_market(market_id)
    except CircuitOpenError:
        risk_controller.record_error()
        raise
    except Exception as e:
        risk_controller.record_error()
        raise
```

### Alert Integration

```python
from merid.risk import risk_controller, KillSwitchEvent

def setup_alerts():
    def on_kill(event: KillSwitchEvent):
        # Send Slack alert
        slack_webhook.post({
            "text": f"🚨 KILL SWITCH: {event.reason.value}",
            "attachments": [{
                "color": "danger",
                "fields": [
                    {"title": "Reason", "value": event.details},
                    {"title": "Daily P&L", "value": f"${event.daily_pnl:.2f}"},
                    {"title": "Time", "value": datetime.fromtimestamp(event.timestamp).isoformat()}
                ]
            }]
        })
    
    risk_controller.on_kill(on_kill)
```

---

## Error Handling

The risk module is designed to fail safely:

```python
# All methods handle internal errors gracefully
try:
    risk_controller.record_pnl(pnl)
except Exception:
    # Should never happen, but if it does, halt trading
    risk_controller.emergency_stop("Risk module error")
```

Callback exceptions are caught and logged:

```python
def bad_callback(event):
    raise RuntimeError("Callback failed")

# This won't prevent kill switch from triggering
risk_controller.on_kill(bad_callback)
risk_controller.emergency_stop("Test")  # Still works
```

---

## See Also

- `docs/OPERATOR_RUNBOOK.md` — Operational procedures
- `docs/GO_LIVE_CHECKLIST.md` — Pre-launch checklist
- `merid/resilience/` — Circuit breaker documentation
