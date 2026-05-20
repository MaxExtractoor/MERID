# Unified Logging Schema

**Date:** 2026-05-13
**Purpose:** Define unified logging schema for MERID system

## Current Logging Infrastructure

The codebase already has a sophisticated logging infrastructure in `utils/logger.py`:

### Existing Components

1. **JsonFormatter** - Structured JSON log format
   - Timestamps in UTC ISO format
   - Level, logger name, message
   - Correlation ID from contextvars
   - Exception information
   - Task context (venue, agent_id, mode, env, tick)
   - Extra fields (component, endpoint, duration_ms, status_code, market_id, strategy)

2. **Context Variables** - Structured context propagation
   - `correlation_id_var` - HTTP request correlation ID
   - `_task_venue_var` - Trading venue (kalshi, alpaca, etc.)
   - `_task_agent_id_var` - Agent identifier
   - `_task_mode_var` - Trading mode (paper, live)
   - `_task_env_var` - Environment (demo, production)
   - `_task_tick_var` - Loop tick number

3. **SafeRotatingFileHandler** - Windows-compatible log rotation
   - 5MB max file size
   - 5 backup files
   - UTF-8 encoding
   - Graceful handling of Windows file locking

4. **Dual Format Support**
   - JSON format for file logs (structured, parseable)
   - Text format for console (human-readable)
   - Controlled by `MERID_JSON_LOGS` environment variable

## Unified Logging Schema

### Standard Log Fields

All log entries should include these base fields:

```json
{
  "ts": "2026-05-13T10:30:45.123456Z",
  "level": "INFO",
  "logger": "merid.prediction.agent_grid_config",
  "message": "Configuration loaded successfully"
}
```

### Context Fields (Optional)

When available, logs should include context from contextvars:

```json
{
  "correlation_id": "abc123-def456-ghi789",
  "venue": "kalshi",
  "agent_id": "btc_15m_regime",
  "mode": "paper",
  "env": "demo",
  "tick": 12345
}
```

### Domain-Specific Fields

#### Trading Domain
```json
{
  "market_id": "KXBTUPDOWN-15M",
  "strategy": "mean_reversion",
  "side": "YES",
  "contracts": 10,
  "price_cents": 50,
  "notional_usd": 500.00
}
```

#### Risk Domain
```json
{
  "risk_check": "position_limit",
  "current_exposure_usd": 2000.00,
  "max_exposure_usd": 3000.00,
  "action": "allow"
}
```

#### Execution Domain
```json
{
  "order_id": "ord_abc123",
  "status": "filled",
  "fill_price_cents": 52,
  "fill_quantity": 10,
  "latency_ms": 234
}
```

#### API Domain
```json
{
  "endpoint": "/api/v1/kalshi/orders",
  "method": "POST",
  "status_code": 200,
  "duration_ms": 145,
  "client_ip": "192.168.1.100"
}
```

### Log Levels

- **DEBUG** - Detailed diagnostic information (development only)
- **INFO** - Normal operational events
- **WARNING** - Unexpected but recoverable situations
- **ERROR** - Error conditions that don't prevent operation
- **CRITICAL** - Critical conditions requiring immediate attention

## Usage Guidelines

### Setting Task Context

For background tasks (loop ticks, agent cycles), set context at the start:

```python
from utils.logger import set_task_context

# At the start of a loop tick or agent cycle
set_task_context(
    venue="kalshi",
    agent_id="btc_15m_regime",
    mode="paper",
    env="demo",
    tick=12345
)
```

### Adding Extra Fields

Use the `extra` parameter to add domain-specific fields:

```python
logger.info(
    "Order submitted",
    extra={
        "market_id": "KXBTUPDOWN-15M",
        "side": "YES",
        "contracts": 10,
        "price_cents": 50
    }
)
```

### Structured Logging for Errors

```python
try:
    # risky operation
    pass
except Exception as e:
    logger.error(
        "Failed to submit order",
        extra={
            "market_id": market_id,
            "error_type": type(e).__name__,
            "error_message": str(e)
        },
        exc_info=True  # includes stack trace
    )
```

## Log Routing Configuration

### Current Configuration

- **File Handler**: `logs/full.log`
  - JSON format (controlled by `MERID_JSON_LOGS`)
  - 5MB max size
  - 5 backup files
  - UTF-8 encoding

- **Console Handler**: stdout
  - Text format (human-readable)
  - For development ergonomics

### Recommended Enhancements

1. **Domain-Specific Log Files**
   - `logs/trading.log` - Trading operations
   - `logs/risk.log` - Risk checks and limits
   - `logs/api.log` - API requests/responses
   - `logs/errors.log` - ERROR and CRITICAL only

2. **Log Level Filtering**
   - DEBUG logs only in development
   - INFO+ in production
   - ERROR+ to separate error log

3. **Structured Log Aggregation**
   - Centralized log collection (ELK, Loki, etc.)
   - Indexing on correlation_id for request tracing
   - Alerting on ERROR/CRITICAL patterns

## Critical Logging Points

### Trading Operations
- Order submission (with market_id, side, contracts, price)
- Order fills (with fill_price, fill_quantity, latency)
- Order rejections (with rejection reason)
- Position updates (with market_id, position, pnl)

### Risk Checks
- Pre-trade risk validation (with risk type, current vs max, action)
- Position limit checks (with current exposure, limit, action)
- Drawdown warnings (with current drawdown, limit, action)
- Daily loss cap breaches (with daily loss, limit, action)

### Execution Guards
- Guardrail checks (with guardrail type, value, threshold, action)
- Slippage checks (with expected vs actual slippage)
- Spread checks (with current spread, max spread, action)
- Depth checks (with current depth, min depth, action)

### API Operations
- Request receipt (with endpoint, method, client_ip)
- Response completion (with status_code, duration_ms)
- Error responses (with error_type, error_message, status_code)
- Rate limit hits (with client, limit, window)

## Implementation Priority

### High Priority (Immediate)
1. Document current logging schema (this document)
2. Identify gaps in logging coverage
3. Add structured logging to critical paths

### Medium Priority (Short-term)
1. Implement domain-specific log files
2. Add log level filtering by environment
3. Create logging utilities/helpers for common patterns

### Low Priority (Long-term)
1. Centralized log aggregation
2. Log-based alerting
3. Log analysis dashboards

## Migration Path

1. **Phase 1: Documentation** - Define schema and guidelines
2. **Phase 2: Critical Path Logging** - Add structured logging to trading/risk/execution
3. **Phase 3: Log Routing** - Implement domain-specific log files
4. **Phase 4: Aggregation** - Centralized log collection and analysis

## Examples

### Trading Operation
```json
{
  "ts": "2026-05-13T10:30:45.123456Z",
  "level": "INFO",
  "logger": "merid.trading.execution",
  "message": "Order submitted",
  "correlation_id": "abc123",
  "venue": "kalshi",
  "agent_id": "btc_15m_regime",
  "mode": "paper",
  "env": "demo",
  "tick": 12345,
  "market_id": "KXBTUPDOWN-15M",
  "side": "YES",
  "contracts": 10,
  "price_cents": 50,
  "notional_usd": 500.00
}
```

### Risk Check
```json
{
  "ts": "2026-05-13T10:30:46.123456Z",
  "level": "INFO",
  "logger": "merid.risk.portfolio_risk",
  "message": "Position limit check passed",
  "correlation_id": "abc123",
  "venue": "kalshi",
  "risk_check": "position_limit",
  "current_exposure_usd": 2000.00,
  "max_exposure_usd": 3000.00,
  "action": "allow"
}
```

### API Request
```json
{
  "ts": "2026-05-13T10:30:47.123456Z",
  "level": "INFO",
  "logger": "web.api.kalshi_api",
  "message": "Order submission request",
  "correlation_id": "def456",
  "endpoint": "/api/v1/kalshi/orders",
  "method": "POST",
  "client_ip": "192.168.1.100"
}
```
