# MERID Operations Guide: Log Noise Controls

## Overview

MERID implements rate-limited logging and configurable severity controls to reduce log noise while maintaining full observability when needed.

## Prediction Market Connector Logging

### Environment Variable
```bash
PREDICTION_CONNECTOR_STRICT_ERRORS=false  # Default: warnings, rate-limited
PREDICTION_CONNECTOR_STRICT_ERRORS=true   # Debug: errors, no rate limiting
```

### Behavior

#### Default Mode (`false`)
- **Log Level**: Warnings for expected failures
- **Rate Limiting**: One message per connector per 60 seconds
- **Connectors**: Polymarket, Augur, Manifold
- **Use Case**: Production, reduced log noise

#### Strict Mode (`true`)
- **Log Level**: Errors for all failures
- **No Rate Limiting**: Every failure logged
- **Use Case**: Debugging connector issues

### Implementation
- File: `monitoring/real_prediction_markets.py`
- Method: `_log_connector_issue()` with rate limiting
- Config: `STRICT_CONNECTOR_ERRORS` environment variable

## Health Monitor Rate Limiting

### Configuration
- **Interval**: Every 5 minutes maximum
- **Override**: No environment variable (hard-coded for production)
- **Purpose**: Reduce noise from recurring system health issues

### Behavior
- System health status logged at most once every 5 minutes
- Individual check failures still logged immediately
- Critical health changes bypass rate limiting

### Implementation
- File: `core/health_monitor.py`
- Method: `_monitor_loop()` with time-based gating
- Config: `_health_log_interval = 300.0` seconds

## Log Scenarios

### Normal Operation (Recommended)
```bash
export PREDICTION_CONNECTOR_STRICT_ERRORS=false
```

Expected logs:
```
WARNING | monitoring.real_prediction_markets | Polymarket connector not available, skipping fetch
WARNING | monitoring.real_prediction_markets | No markets fetched from augur (connector may be unavailable)
WARNING | monitoring.real_prediction_markets | Manifold API error: 404
ERROR   | core.health_monitor | System health: UNHEALTHY - 2 errors  # Every 5 minutes max
```

### Debug Mode (Troubleshooting)
```bash
export PREDICTION_CONNECTOR_STRICT_ERRORS=true
```

Expected logs:
```
ERROR   | monitoring.real_prediction_markets | Polymarket fetch error: Connection timeout
ERROR   | monitoring.real_prediction_markets | Augur fetch error: DNS resolution failed
ERROR   | monitoring.real_prediction_markets | Manifold API error: 404
ERROR   | core.health_monitor | System health: UNHEALTHY - 2 errors  # Every 30 seconds
```

## Monitoring and Alerting

### Health Endpoints
- `/api/v1/system/health` - Current system health
- `/readyz` - Readiness check with synthetic mode flag
- `/api/v1/paper/session/state` - Paper session lifecycle

### Log Patterns to Watch
- **Connector spam**: Check `PREDICTION_CONNECTOR_STRICT_ERRORS` setting
- **Health noise**: Verify 5-minute rate limiting is working
- **Critical errors**: Always bypass rate limiting for immediate attention

## Production Deployment

### Recommended Settings
```bash
# .env configuration
PREDICTION_CONNECTOR_STRICT_ERRORS=false
```

### Log Management
- Prediction market warnings: 1 per minute per connector max
- Health monitor status: 1 per 5 minutes max
- Critical errors: Immediate, no rate limiting
- Individual check failures: Immediate, no rate limiting

### Alert Configuration
- Alert on ERROR level logs (bypass rate limiting)
- Monitor health endpoint for status changes
- Track prediction market availability separately

## Troubleshooting

### Too Much Log Noise
1. Verify `PREDICTION_CONNECTOR_STRICT_ERRORS=false`
2. Check for multiple MERID instances running
3. Validate health monitor rate limiting (5-minute intervals)

### Missing Error Information
1. Set `PREDICTION_CONNECTOR_STRICT_ERRORS=true` temporarily
2. Check individual health check endpoints
3. Review system metrics for underlying issues

### Connector Debugging
1. Enable strict mode for detailed error logs
2. Monitor specific connector endpoints
3. Check external API availability independently

## Implementation Details

### Rate Limiting Logic
```python
def _log_connector_issue(self, message: str) -> None:
    now = time.time()
    if now - self._last_issue_log < self._issue_log_interval:
        return
    
    if STRICT_CONNECTOR_ERRORS:
        logger.error(message)
    else:
        logger.warning(message)
    
    self._last_issue_log = now
```

### Health Monitor Logic
```python
if now - self._last_health_log >= self._health_log_interval:
    # Log health status
    self._last_health_log = now
```

## Best Practices

1. **Production**: Always use `PREDICTION_CONNECTOR_STRICT_ERRORS=false`
2. **Debugging**: Temporarily enable strict mode for connector issues
3. **Monitoring**: Set up alerts for ERROR level logs only
4. **Log Retention**: Keep warnings for 24-48 hours, errors for 7+ days
5. **Performance**: Rate limiting reduces I/O overhead in production
