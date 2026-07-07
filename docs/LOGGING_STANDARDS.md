# MERID Logging Standards

**Version:** 1.0  
**Last Updated:** 2026-07-07  
**Scope:** Production 15M Kalshi Crypto Trading Stack

---

## Purpose

This document defines the logging standards for the MERID production stack to ensure:
- Consistent logging patterns across all modules
- Effective debugging and operational monitoring
- Clear explainability for risk-critical events
- Proper log level usage
- Structured logging for observability tooling

---

## Logger Initialization

### Standard Pattern

All production modules MUST use `get_logger()` from `utils.logger`:

```python
from utils.logger import get_logger

logger = get_logger("module.path.here")
```

### Forbidden Patterns

- ❌ `logging.getLogger(__name__)` - Inconsistent configuration
- ❌ `print()` statements - Bypass log management
- ❌ Custom logger implementations - Use centralized logger

---

## Log Level Policy

### DEBUG
**Purpose:** Development diagnostics and detailed troubleshooting

**Use Cases:**
- Detailed variable states
- Function entry/exit tracing
- Conditional branch execution
- Development-only diagnostics

**Example:**
```python
logger.debug("[LIFESPAN-DEF] About to define lifespan function")
```

### INFO
**Purpose:** Operational events and normal system operations

**Use Cases:**
- Startup/shutdown milestones
- Component initialization
- Normal state transitions
- Successful operations

**Example:**
```python
logger.info("[SINGLETON-RESET] Resetting singletons for clean startup")
```

### WARNING
**Purpose:** Degraded but functional state requiring attention

**Use Cases:**
- Fallback to default values
- Retry attempts
- Non-critical failures
- Deprecated feature usage

**Example:**
```python
logger.warning("[UNIFIED-SIZING] Profile adapter not available, using hardcoded values")
```

### ERROR
**Purpose:** Failures requiring immediate attention

**Use Cases:**
- API failures
- Validation failures
- Component initialization failures
- Data corruption

**Example:**
```python
logger.error(
    "[PROFILE-VALIDATION-FAILED] Profile validation failed because required field missing",
    extra={"field": missing_field, "profile": profile_name}
)
```

### CRITICAL
**Purpose:** System-impacting failures

**Use Cases:**
- Trading halt events
- Circuit breaker triggers
- Data loss
- Security violations

**Example:**
```python
logger.critical(
    "[RISK-HALT] Trading halted due to drawdown exceeding threshold",
    extra={"drawdown_pct": current_drawdown, "threshold": halt_threshold}
)
```

---

## Required Context

### Trading Logs
All trading-related logs MUST include:
- `asset`: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
- `order_id`: Order identifier (if applicable)
- `notional`: Order notional value in USD
- `timestamp`: Event timestamp

**Example:**
```python
logger.info(
    "[ORDER-EXECUTED] Order filled",
    extra={
        "asset": "BTC",
        "order_id": "ord_123",
        "notional_usd": 0.50,
        "price_cents": 50,
        "contracts": 1
    }
)
```

### Risk Logs
All risk-related logs MUST include:
- `exposure`: Current exposure value
- `limit`: Risk limit value
- `distance_to_limit`: Percentage distance to limit
- `reason`: Why the risk decision was made

**Example:**
```python
logger.warning(
    "[WINDOW-TRACKING] FORCE RESET",
    extra={
        "reason": "stale_exposure",
        "stale_total_exposure": 100.50,
        "stale_agent_count": 3,
        "stale_window_start": 1688745600.0,
        "new_window_start": 1688746500.0
    }
)
```

### Error Logs
All error logs MUST include causal context:
- `because`: Why the error occurred
- `due to`: Root cause
- `caused by`: Causal chain
- `impact`: System impact
- `recovery`: Recovery action taken

**Example:**
```python
logger.error(
    "[WS-AUTO-RECONNECT] Catalog API error during reconnection",
    extra={
        "attempt": 2,
        "max_attempts": 5,
        "error": str(ae),
        "recovery": "Falling back to cached subscriptions",
        "impact": f"{len(saved_subscriptions)} tickers may be stale"
    }
)
```

---

## Structured Logging

### Key-Value Format

Use structured logging with key-value pairs for all contextual data:

```python
logger.info(
    "[WINDOW-TRACKING] Recorded execution",
    extra={
        "agent_id": agent_id,
        "order_notional_usd": order_notional_usd,
        "window_start_ts": window_start_ts,
        "total_exposure_usd": total_exposure_usd
    }
)
```

### Field Naming Conventions

- Use snake_case for field names
- Use descriptive names (e.g., `order_notional_usd` not `notional`)
- Include units in field names (e.g., `usd`, `cents`, `pct`)
- Use consistent names across modules

### Standard Field Names

| Field Name | Type | Description |
|------------|------|-------------|
| `asset` | str | Asset symbol (BTC, ETH, etc.) |
| `order_id` | str | Order identifier |
| `market_id` | str | Market identifier |
| `agent_id` | str | Agent identifier |
| `notional_usd` | float | Notional value in USD |
| `price_cents` | int | Price in cents |
| `contracts` | int | Number of contracts |
| `exposure_usd` | float | Exposure in USD |
| `limit_usd` | float | Risk limit in USD |
| `distance_to_limit_pct` | float | Distance to limit as percentage |
| `reason` | str | Reason for action |
| `error` | str | Error message |
| `impact` | str | System impact |
| `recovery` | str | Recovery action |

---

## Correlation IDs

### Purpose

Correlation IDs enable tracing a single transaction across multiple components and log entries.

### Implementation

Generate a correlation ID at the transaction entry point and propagate through the call stack:

```python
import uuid
from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')

# At entry point
correlation_id = str(uuid.uuid4())
correlation_id_var.set(correlation_id)

# In all related logs
logger.info(
    "[ORDER-SUBMITTED] Order submitted to exchange",
    extra={
        "correlation_id": correlation_id_var.get(''),
        "order_id": order_id,
        "asset": asset
    }
)
```

### Required For

- All order lifecycle events (submit, fill, cancel)
- All risk limit checks
- All position management events
- All error recovery sequences

---

## Diagnostic Noise

### Prohibited Patterns

- ❌ `CRITICAL DIAGNOSTIC` markers in production code
- ❌ Diagnostic file writes (e.g., execution markers)
- ❌ Excessive startup logging (>20 log entries)
- ❌ Debug logs in production code paths

### Allowed Patterns

- ✅ Use `logger.debug()` for development diagnostics
- ✅ Use feature flags to enable diagnostics in dev/test
- ✅ Separate diagnostic log files for development
- ✅ Log aggregation filters for production

---

## Error Explainability

### Causal Context Requirements

All error logs MUST explain:
1. **What** failed
2. **Why** it failed (causal context)
3. **Impact** on system state
4. **Recovery** action taken

### Examples

**Poor (No Causal Context):**
```python
logger.error(f"[WS-AUTO-RECONNECT] Catalog API error: {ae}")
```

**Good (With Causal Context):**
```python
logger.error(
    "[WS-AUTO-RECONNECT] Catalog API error during reconnection attempt 2/5",
    extra={
        "error": str(ae),
        "cause": "Catalog API returned 500 Internal Server Error",
        "impact": f"{len(saved_subscriptions)} tickers may be stale",
        "recovery": "Falling back to cached subscriptions, will retry in 30s"
    }
)
```

---

## Business Context

### Required For Trading Logs

All trading logs SHOULD include business impact information:
- Percentage of bankroll
- Distance to risk limits
- Expected PnL impact
- Market conditions (regime, volatility)

**Example:**
```python
logger.info(
    "[ORDER-EXECUTED] Order filled",
    extra={
        "asset": "BTC",
        "notional_usd": 0.50,
        "bankroll_pct": (0.50 / bankroll_usd) * 100,
        "distance_to_limit_pct": ((limit_usd - current_exposure_usd) / limit_usd) * 100,
        "market_regime": "trending_strong",
        "volatility_percentile": 0.75
    }
)
```

---

## Log Aggregation

### Centralized Collection

All logs MUST be centralized for:
- Search and filtering
- Alerting on critical patterns
- Operational dashboards
- Compliance and auditing

### Recommended Tools

- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **CloudWatch Logs** (AWS)
- **Datadog Logs**
- **Splunk**

### Log Filtering

Implement log filters to:
- Reduce noise in production
- Focus on critical events
- Enable per-component filtering
- Support log level adjustment at runtime

---

## Testing

### Log Standards Tests

All logging changes MUST include tests to verify:
- No print() statements in production code
- No CRITICAL DIAGNOSTIC markers
- Proper logger initialization
- Required context in risk-critical logs
- Causal context in error logs

### Test Location

`tests/test_logging_standards.py`

### Running Tests

```bash
pytest tests/test_logging_standards.py -v
```

---

## Enforcement

### Pre-Commit Hooks

Implement pre-commit hooks to:
- Check for print() statements
- Check for CRITICAL DIAGNOSTIC markers
- Verify logger initialization
- Validate log message format

### CI/CD Pipeline

Add logging standards checks to CI/CD:
- Run logging standards tests on every PR
- Fail builds that violate standards
- Generate compliance reports

---

## Migration Checklist

When updating existing code to meet these standards:

- [ ] Replace `logging.getLogger()` with `get_logger()`
- [ ] Remove all `print()` statements
- [ ] Remove CRITICAL DIAGNOSTIC markers
- [ ] Add context to risk-critical logs
- [ ] Add causal context to error logs
- [ ] Implement correlation IDs for transaction tracing
- [ ] Convert to structured logging format
- [ ] Add/update tests for logging standards
- [ ] Update documentation if behavior changes

---

## References

- Logging Audit Report: `output/logging_audit_report.md`
- Logging Audit Script: `scripts/logging_audit.py`
- Logging Standards Tests: `tests/test_logging_standards.py`
