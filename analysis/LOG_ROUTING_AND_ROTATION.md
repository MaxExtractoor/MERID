# Log Routing and Rotation Configuration

**Date:** 2026-05-13
**Purpose:** Document current log routing and rotation configuration

## Current Configuration

### Log File Location
- **Directory:** `logs/` (relative to project root)
- **File:** `full.log`
- **Encoding:** UTF-8

### Rotation Policy
- **Handler:** `SafeRotatingFileHandler` (Windows-compatible)
- **Max file size:** 5,000,000 bytes (5 MB)
- **Backup count:** 5 files
- **Rotation behavior:**
  - When `full.log` reaches 5 MB, it's renamed to `full.log.1`
  - Existing backups shift: `.1` → `.2`, `.2` → `.3`, etc.
  - Oldest backup (`.5`) is deleted when rotation occurs
  - Total disk usage per log stream: ~30 MB (5 MB × 6 files)

### Log Formats

#### JSON Format (File Logs)
- **Enabled by default:** Yes (controlled by `MERID_JSON_LOGS` env var)
- **Formatter:** `JsonFormatter`
- **Fields:**
  - `ts`: ISO 8601 timestamp (UTC)
  - `level`: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - `logger`: Logger name (e.g., "merid.guards.global_risk_guard")
  - `message`: Log message
  - `correlation_id`: Request correlation ID (if available)
  - `venue`: Trading venue (if set in task context)
  - `agent_id`: Agent ID (if set in task context)
  - `mode`: Trading mode (paper/live) (if set in task context)
  - `env`: Environment (demo/production) (if set in task context)
  - `tick`: Loop tick number (if set in task context)
  - `exception`: Exception traceback (if present)
  - Additional fields from structured logging helpers

#### Text Format (Console Logs)
- **Format:** `%(asctime)s | %(levelname)s | %(name)s | %(message)s`
- **Date format:** `%Y-%m-%d %H:%M:%S`
- **Purpose:** Human-readable output for development

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MERID_JSON_LOGS` | `1` | Enable JSON format for file logs (1/true/yes = enabled, 0/false/no = disabled) |

## Log Routing

### File Handler
- **Target:** `logs/full.log`
- **Format:** JSON (or text if `MERID_JSON_LOGS=0`)
- **Level:** INFO and above
- **Rotation:** SafeRotatingFileHandler

### Console Handler
- **Target:** stdout
- **Format:** Text (human-readable)
- **Level:** INFO and above
- **Rotation:** None

## Context Propagation

### HTTP Request Context
- **Correlation ID:** Set by FastAPI middleware in `web/main.py`
- **Propagation:** Automatic via `contextvars.ContextVar`
- **Scope:** Per-request

### Background Task Context
- **Set by:** `set_task_context()` function
- **Fields:**
  - `venue`: Trading venue (kalshi)
  - `agent_id`: Agent identifier
  - `mode`: Trading mode (paper/live)
  - `env`: Environment (demo/production)
  - `tick`: Loop tick number
- **Propagation:** Automatic via `contextvars.ContextVar`
- **Scope:** Per-asyncio-task

## Structured Logging Helpers

The following helpers from `utils/logging_helpers.py` provide domain-specific structured logging:

### Trading Operations
- `log_trading_operation()`: Order submission, fills, rejections, position updates
- **Fields:** market_id, side, contracts, price_cents, notional_usd, etc.

### Risk Checks
- `log_risk_check()`: Position limits, exposure limits, drawdown checks
- **Fields:** risk_check, current_value, limit_value, action, etc.

### Guardrail Checks
- `log_guardrail_check()`: Spread checks, depth checks, slippage checks
- **Fields:** guardrail, value, threshold, passed, market_id, etc.

### API Operations
- `log_api_request()`: Request receipt
- **Fields:** endpoint, method, client_ip, correlation_id, etc.
- `log_api_response()`: Response completion
- **Fields:** endpoint, status_code, duration_ms, correlation_id, etc.

### Error Logging
- `log_error()`: Error events with context
- **Fields:** error_type, error_message, context, etc.

## Log Aggregation Recommendations

### Recommended Tools
1. **ELK Stack** (Elasticsearch, Logstash, Kibana)
   - Full-featured log aggregation and visualization
   - Powerful query capabilities
   - Real-time dashboards

2. **Grafana Loki**
   - Lightweight log aggregation
   - Integrates with Prometheus
   - Lower resource requirements

3. **CloudWatch Logs** (AWS)
   - Managed service
   - Native AWS integration
   - Pay-as-you-go pricing

### Indexing Strategy
- **Primary indices:** correlation_id, timestamp, level, logger
- **Secondary indices:** venue, agent_id, market_id, risk_check, guardrail
- **Retention policy:**
  - Hot storage: 30 days (frequent access)
  - Warm storage: 90 days (occasional access)
  - Cold storage: 1 year (archival)

### Alerting Configuration
- **ERROR level:** Immediate notification
- **CRITICAL level:** Immediate notification with escalation
- **Specific risk_check failures:** Warning threshold
- **Specific guardrail failures:** Warning threshold
- **Rate limit hits:** Warning threshold

## Performance Considerations

### Log Volume Estimation
- **Estimated logs per hour:** 1,000 - 10,000 (depending on activity)
- **Average log size:** 500 bytes (JSON format)
- **Hourly volume:** 0.5 - 5 MB
- **Daily volume:** 12 - 120 MB
- **Rotation frequency:** Every 1-10 days (at 5 MB per file)

### Disk Space Requirements
- **Current configuration:** ~30 MB per log stream
- **Recommended:** 100-500 MB for logs directory
- **With 90-day retention:** ~10-100 GB (depending on activity)

### Performance Impact
- **JSON formatting:** Minimal overhead (< 1ms per log)
- **File rotation:** Occurs infrequently (every 5 MB)
- **Context variable access:** Negligible overhead
- **SafeRotatingFileHandler:** Handles Windows file locking gracefully

## Monitoring and Maintenance

### Log File Monitoring
- **Monitor:** Disk space usage in `logs/` directory
- **Alert:** If disk space > 80% of allocated space
- **Action:** Increase backup count or reduce max file size

### Log Quality Monitoring
- **Monitor:** Missing correlation IDs on request paths
- **Monitor:** Missing task context on background tasks
- **Alert:** If > 5% of logs missing expected context

### Log Rotation Monitoring
- **Monitor:** Rotation frequency
- **Alert:** If rotation occurs more than once per hour (indicates high volume)
- **Action:** Investigate log spam or increase max file size

## Configuration Validation

### Validation Checklist
- [x] Log directory exists and is writable
- [x] SafeRotatingFileHandler works on Windows
- [x] JSON formatter produces valid JSON
- [x] Context variables propagate correctly
- [x] MERID_JSON_LOGS env var works as expected
- [x] Rotation occurs at expected file size
- [x] Backup files are created and cleaned up correctly

## Future Enhancements

### Potential Improvements
1. **Log level filtering by module:** Allow different log levels per module
2. **Multiple log files:** Separate logs by domain (trading, risk, api)
3. **Log compression:** Compress old log files to save disk space
4. **Log shipping:** Ship logs to external aggregation service
5. **Structured error tracking:** Integrate with Sentry or similar service
6. **Log sampling:** Sample debug logs in high-volume scenarios
7. **Log enrichment:** Add additional metadata (host, process ID, etc.)

### Configuration Options to Consider
- `MERID_LOG_DIR`: Custom log directory location
- `MERID_LOG_MAX_BYTES`: Custom max file size
- `MERID_LOG_BACKUP_COUNT`: Custom backup count
- `MERID_LOG_LEVEL`: Global log level override
- `MERID_LOG_MODULE_LEVELS`: Per-module log level configuration

## Summary

The current log routing and rotation configuration is production-ready with:
- Windows-compatible file rotation
- Structured JSON logging for machine readability
- Human-readable console logs for development
- Context propagation for request and task tracing
- Reasonable rotation policy (5 MB files, 5 backups)
- Domain-specific structured logging helpers

The configuration supports the unified logging schema defined in `analysis/UNIFIED_LOGGING_SCHEMA.md` and provides a solid foundation for log aggregation and alerting.
