# Audit Dashboard Schema

## Overview

This schema defines the data structure for the MERID contract-limit audit dashboard. The dashboard exposes audit data in a single table format that makes drift obvious at a glance, allowing operators to quickly identify whether a failure was caused by policy, routing, or liveness issues.

## Schema Definition

### Core Fields

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `timestamp` | string (ISO 8601) | Event timestamp in UTC | All event sources |
| `asset` | string | Asset symbol (BTC, ETH, SOL, XRP, DOGE) | All event sources |
| `account_tier` | string | Account tier (e.g., "prod", "test") | Profile config |
| `environment` | string | Environment (e.g., "production", "simulation") | Runtime config |
| `signal_mode_profile` | string | Signal mode from profile YAML | Profile YAML |
| `signal_mode_runtime` | string | Signal mode actually used at runtime | Agent grid runtime |
| `entry_limit_contracts` | integer | Max contracts per entry order | Profile YAML |
| `exit_limit_contracts` | integer | Max contracts per exit order | Profile YAML |
| `exposure_cap` | float | Fixed exposure cap in USD | Profile YAML / env var |
| `thesis_side` | string | Thesis side from intent ("yes" or "no") | Intent metadata |
| `candidate_side` | string | Candidate side from signal generation | Signal layer |
| `order_side` | string | Order side that was routed or blocked | Order intent |
| `selected_price_cents` | integer | Selected price in cents | Candidate selection |
| `limit_violation` | boolean | Whether a limit was violated | Risk check |
| `routing_block_reason` | string | Reason for routing block (if blocked) | Router validation |
| `circuit_breaker_state` | string | Circuit breaker state at event time | Circuit breaker |
| `md_staleness_seconds` | float | Market data staleness in seconds | MD health check |
| `exit_liveness_state` | string | Exit liveness state (e.g., "filled", "failed", "blocked") | Exit tracking |
| `event_type` | string | Event type ("blocked_order", "exit_intent", "expected_route_failure") | Event source |

### Event-Specific Fields

#### Blocked Order Events
- `order_type`: "entry" or "exit"
- `market_id`: Kalshi market ID
- `limit_violation`: Boolean indicating if this was a limit violation
- `circuit_breaker_state`: Circuit breaker state at time of block
- `md_staleness_seconds`: Market data staleness in seconds
- `exit_liveness_state`: Exit liveness state (for exit blocks)

#### Exit Intent Events
- `market_id`: Kalshi market ID
- `position_size`: Current position size before exit
- `exit_count`: Number of contracts to exit
- `latency_seconds`: Time from intent to outcome in seconds
- `outcome`: Exit outcome ("filled", "failed", "blocked", "timeout")

#### Expected Route Failure Events
- `market_id`: Kalshi market ID
- `expected_action`: What was expected to happen
- `actual_outcome`: What actually happened
- `blocker`: What blocked the expected action

## Routing Block Reasons

The `routing_block_reason` field uses standardized values from the audit anomaly monitor:

| Reason | Description | Severity |
|--------|-------------|----------|
| `contract_limit_violation` | Order exceeds max contracts per order | Critical |
| `stale_market_data` | Market data is too stale for safe execution | High |
| `venue_unavailable` | Trading venue is unavailable | Critical |
| `circuit_breaker_cooldown` | Circuit breaker is in cooldown period | High |
| `side_thesis_mismatch` | Order side does not match thesis_side | Critical |
| `price_range_violation` | Order price outside 10-75c canonical range | High |
| `duplicate_order` | Duplicate order detected | Medium |
| `open_order_exists` | Open resting order already exists | Medium |
| `strip_cooldown` | Asset strip is in cooldown | Medium |
| `other` | Other reason not categorized | Low |

## Exit Liveness States

The `exit_liveness_state` field tracks exit lifecycle:

| State | Description | Action Required |
|-------|-------------|-----------------|
| `filled` | Exit order filled successfully | None |
| `failed` | Exit order failed (venue error) | Retry investigation |
| `blocked` | Exit order blocked by router | Blocker investigation |
| `timeout` | Exit order timed out | Timeout investigation |
| `pending` | Exit intent created, awaiting outcome | Monitor |
| `VENUE_UNAVAILABLE` | Venue unavailable at exit time | Wait and retry |
| `CIRCUIT_BREAKER_COOLDOWN` | Circuit breaker blocked exit | Wait for cooldown |
| `stale_data` | Market data too stale for exit | Wait for fresh data |

## Dashboard Queries

### Example: Blocked Orders by Asset and Reason

```sql
SELECT 
    asset,
    routing_block_reason,
    COUNT(*) as blocked_count,
    AVG(md_staleness_seconds) as avg_staleness,
    COUNT(CASE WHEN limit_violation = true THEN 1 END) as limit_violations
FROM audit_events
WHERE event_type = 'blocked_order'
GROUP BY asset, routing_block_reason
ORDER BY blocked_count DESC;
```

### Example: Exit Latency by Asset

```sql
SELECT 
    asset,
    AVG(latency_seconds) as avg_latency,
    MIN(latency_seconds) as min_latency,
    MAX(latency_seconds) as max_latency,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_seconds) as p95_latency,
    COUNT(*) as exit_count
FROM audit_events
WHERE event_type = 'exit_intent' AND latency_seconds IS NOT NULL
GROUP BY asset;
```

### Example: Signal Mode Drift Detection

```sql
SELECT 
    signal_mode_profile,
    signal_mode_runtime,
    COUNT(*) as event_count,
    COUNT(CASE WHEN signal_mode_profile != signal_mode_runtime THEN 1 END) as drift_count
FROM audit_events
GROUP BY signal_mode_profile, signal_mode_runtime;
```

### Example: Contract Limit Violations

```sql
SELECT 
    asset,
    entry_limit_contracts,
    exit_limit_contracts,
    exposure_cap,
    COUNT(CASE WHEN limit_violation = true THEN 1 END) as limit_violations,
    COUNT(*) as total_orders
FROM audit_events
WHERE event_type = 'blocked_order'
GROUP BY asset, entry_limit_contracts, exit_limit_contracts, exposure_cap;
```

## Alert Thresholds

Recommended alert thresholds for dashboard monitoring:

| Metric | Threshold | Severity | Action |
|--------|-----------|----------|--------|
| Blocked orders per asset (1h) | > 10 | Warning | Investigate routing issues |
| Blocked orders per asset (1h) | > 20 | Critical | Immediate investigation |
| Exit failures per asset (1h) | > 5 | Warning | Investigate exit liveness |
| Exit failures per asset (1h) | > 10 | Critical | Immediate investigation |
| Expected route failures (1h) | > 3 | Critical | Immediate investigation |
| Signal mode drift events | > 0 | Critical | Immediate investigation |
| Contract limit violations | > 0 | Critical | Immediate investigation |
| Exit latency p95 > 30s | Warning | Investigate exit delays |
| Exit latency p95 > 60s | Critical | Investigate exit delays |

## Data Retention

- **In-memory buffer**: 10,000 events (circular buffer)
- **File storage**: Daily rotation, 30-day retention
- **Long-term storage**: Archive to cold storage after 30 days

## Integration Points

### Data Sources

1. **Order Router** (`merid/event_venues/kalshi/order_router.py`)
   - Blocked order events
   - Routing block reasons
   - Circuit breaker state
   - MD staleness

2. **Loop 15m** (`merid/loop_15m.py`)
   - Exit intent events
   - Exit outcomes
   - Exit latency tracking
   - Exit liveness state

3. **Agent Grid** (`merid/prediction/agent_grid_15m.py`)
   - Signal mode runtime
   - Candidate side
   - Selected price
   - Expected route events

4. **Profile Adapter** (`merid/risk/profiles/crypto_15m_profile.py`)
   - Signal mode profile
   - Entry/exit limits
   - Exposure cap
   - Account tier

### Consumer Interfaces

1. **Grafana Dashboard**
   - Real-time visualization
   - Alert integration
   - Historical trends

2. **API Endpoint** (`/api/audit/metrics`)
   - JSON metrics export
   - Dashboard data export
   - Alert status

3. **Log Aggregation**
   - Structured logging
   - ELK/Splunk integration
   - Alert routing

## Implementation Notes

### Performance Considerations

- In-memory counters for real-time metrics (no disk I/O)
- Async file logging for event persistence
- Sampling support for high-frequency systems
- Circular buffer to prevent memory growth

### Thread Safety

- Thread-safe counter updates using locks
- Queue-based async logging
- Singleton pattern for global access

### Extensibility

- Easy to add new event types
- Configurable thresholds
- Pluggable alert backends
- Custom field support via additional_context

## Future Enhancements

1. **Tier-Specific Tracking**
   - Add per-tier limit tracking
   - Tier-specific alert thresholds
   - Tier comparison views

2. **Simulation vs Production Comparison**
   - Side-by-side limit comparison
   - Drift detection between environments
   - Simulation validation before production deployment

3. **Machine Learning Anomaly Detection**
   - Pattern recognition for unusual blocking patterns
   - Predictive alerting
   - Root cause analysis

4. **Cross-Asset Correlation**
   - Correlated blocking across assets
   - Market-wide issue detection
   - System health scoring
