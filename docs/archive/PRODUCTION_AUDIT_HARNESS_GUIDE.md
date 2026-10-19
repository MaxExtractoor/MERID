# Production Audit Harness Guide

## Overview

The Production Audit Harness provides continuous monitoring of the 15m Kalshi crypto trading system, running automated audits every 15-minute cycle to compare intended behavior (from profile/config) vs actual behavior (runtime state). It fails loud on any mismatch in data, sizing, routing, fills, exits, or state reconciliation.

## Architecture

### Audit Layers

The harness audits 7 layers of the trading stack:

1. **Data Layer** - Price feeds, market catalog, WebSocket subscriptions
2. **Sizing Layer** - Risk limits, position sizes, window-based tracking
3. **Routing Layer** - Order gate, order router, execution pipeline
4. **Fills Layer** - Execution results, position cache, reconciliation
5. **Exits Layer** - Trailing stops, ratchets, 99c exits
6. **State Layer** - Window tracking, exposure, position state
7. **Reconciliation Layer** - Cross-layer consistency checks

### Critical Invariants Audited

- All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) must be present and active
- 3% per agent / 5% total per 15m window risk limits must be respected
- Profile YAML is single source of truth for all risk parameters
- Window tracking state must be consistent across all envelope instances
- Position cache must match actual positions from Kalshi API
- Order routing must respect guardrails (75c spread, 10c min price, etc.)
- Exit policies (trailing stop, ratchet, 99c) must execute when triggered

## Integration

### Basic Usage

```python
from merid.audit import start_production_audit_harness, stop_production_audit_harness

# Start the audit harness (runs in background thread)
harness = start_production_audit_harness()

# ... trading system runs ...

# Stop the audit harness when shutting down
stop_production_audit_harness()
```

### With Custom Failure Callbacks

```python
from merid.audit import get_production_audit_harness

def critical_failure_handler(report, critical_findings):
    """Handle critical failures (e.g., halt trading)."""
    logger.error(f"CRITICAL AUDIT FAILURE: {len(critical_findings)} critical findings")
    # Implement halt trading logic here
    # e.g., set global halt flag, send alert, etc.

def high_failure_handler(report, high_findings):
    """Handle high severity failures (e.g., send alert)."""
    logger.warning(f"HIGH AUDIT FAILURE: {len(high_findings)} high findings")
    # Implement alert logic here
    # e.g., send Telegram notification, PagerDuty alert, etc.

# Get harness instance and set callbacks
harness = get_production_audit_harness()
harness.set_critical_failure_callback(critical_failure_handler)
harness.set_high_failure_callback(high_failure_handler)

# Start the harness
harness.start()
```

### Integration with main_15m_lean.py

Add to the FastAPI lifespan events in `web/main_15m_lean.py`:

```python
from merid.audit import start_production_audit_harness, stop_production_audit_harness

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting production audit harness")
    audit_harness = start_production_audit_harness()
    
    yield
    
    # Shutdown
    logger.info("Stopping production audit harness")
    stop_production_audit_harness()
```

## Audit Checks

### Data Layer Checks

1. **Required Assets in Catalog** - Ensures all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are present in the market catalog
2. **Price Feed Freshness** - Ensures price feeds are not stale (max 60s staleness)
3. **WebSocket Subscriptions** - Ensures WebSocket subscriptions are active (placeholder, to be implemented)

### Sizing Layer Checks

1. **Profile/Risk Envelope Consistency** - Ensures profile YAML values match risk envelope defaults
2. **Window Risk Limits** - Ensures 3% per agent / 5% total per 15m window limits are enforced
3. **Per-Asset Caps** - Ensures all 5 assets have caps defined in profile

### Routing Layer Checks

1. **Order Gate Guardrails** - Ensures order gate enforces guardrails (placeholder)
2. **Order Router Venue** - Ensures order router routes to correct venue (placeholder)
3. **Execution Pipeline Error Handling** - Ensures execution pipeline handles errors gracefully (placeholder)

### Fills Layer Checks

1. **Position Cache Consistency** - Ensures position cache matches actual positions (placeholder)
2. **Fills Recording** - Ensures fills are recorded correctly (placeholder)
3. **Reconciliation Detection** - Ensures reconciliation detects mismatches (placeholder)

### Exits Layer Checks

1. **Trailing Stop Activation** - Ensures trailing stop activates when price crosses threshold (placeholder)
2. **Ratchet Activation** - Ensures ratchet sets profit floor when price hits threshold (placeholder)
3. **99c Exit Execution** - Ensures 99c exit executes when price reaches 99c (placeholder)

### State Layer Checks

1. **Window Tracking Consistency** - Ensures window tracking state is consistent across envelope instances
2. **Exposure Tracking** - Ensures exposure tracking is accurate (placeholder)
3. **Position State** - Ensures position state is up-to-date (placeholder)

### Reconciliation Layer Checks

1. **Risk Envelope/Position Cache Consistency** - Ensures risk envelope exposure matches position cache (placeholder)
2. **Order Router/Fills Consistency** - Ensures order router execution count matches fills (placeholder)
3. **Window Exposure/Position Sum Consistency** - Ensures window exposure matches sum of position notional (placeholder)

## Severity Levels

- **CRITICAL** - System-breaking issue, halt trading immediately
- **HIGH** - Significant deviation, requires immediate attention
- **MEDIUM** - Minor deviation, monitor closely
- **LOW** - Informational, no action required

## Audit Reports

### Structure

Each audit report contains:
- `cycle_id` - 15-minute window identifier (e.g., "20260707_1000")
- `cycle_start_ts` - Window start timestamp
- `cycle_end_ts` - Window end timestamp
- `passed` - Whether the audit passed (no critical/high findings)
- `findings` - List of audit findings
- `total_findings` - Total number of findings
- `critical_findings` - Number of critical findings
- `high_findings` - Number of high findings

### Accessing Reports

```python
from merid.audit import get_production_audit_harness

harness = get_production_audit_harness()

# Get most recent report
current_report = harness.get_current_report()

# Get historical reports (last 10 by default)
historical_reports = harness.get_historical_reports(limit=10)

# Export report to JSON
harness.export_report_to_json(current_report, "/path/to/report.json")
```

## Loud Failure Mechanisms

The harness provides two callback mechanisms for loud failures:

1. **Critical Failure Callback** - Triggered when critical findings are detected
   - Use to halt trading immediately
   - Send emergency alerts
   - Trigger circuit breakers

2. **High Failure Callback** - Triggered when high severity findings are detected
   - Use to send alerts
   - Log warnings
   - Escalate to on-call

## Implementation Status

### Fully Implemented

- Data layer: Required assets in catalog, price feed freshness
- Sizing layer: Profile/risk envelope consistency, window risk limits, per-asset caps
- State layer: Window tracking consistency
- Loud failure mechanisms with callbacks
- Continuous 15-minute cycle monitoring
- Audit report generation and export

### Placeholder (To Be Implemented)

- Data layer: WebSocket subscriptions
- Routing layer: All checks
- Fills layer: All checks
- Exits layer: All checks
- State layer: Exposure tracking, position state
- Reconciliation layer: All checks

## Testing

### Unit Tests

Create unit tests for individual audit checks:

```python
# tests/audit/test_production_audit_harness.py
from merid.audit import ProductionAuditHarness, AuditSeverity, AuditLayer

def test_required_assets_in_catalog():
    harness = ProductionAuditHarness()
    report = harness._run_audit_cycle("test_cycle", 0, 900)
    
    # Assert no critical findings for required assets
    critical_findings = [f for f in report.findings if f.severity == AuditSeverity.CRITICAL]
    assert len(critical_findings) == 0
```

### Integration Tests

Test the harness with a running trading system:

```python
# tests/audit/test_audit_harness_integration.py
def test_audit_harness_with_live_system():
    from merid.audit import start_production_audit_harness, stop_production_audit_harness
    
    harness = start_production_audit_harness()
    
    # Wait for one audit cycle
    time.sleep(910)  # 15 minutes + buffer
    
    report = harness.get_current_report()
    assert report is not None
    assert report.passed  # Or handle failures appropriately
    
    stop_production_audit_harness()
```

## Troubleshooting

### Audit Harness Not Starting

- Check that required modules are importable
- Verify threading is not blocked
- Check logs for initialization errors

### Critical Findings on Startup

- Review the specific finding details
- Check if profile YAML is correctly configured
- Verify risk envelope is properly initialized
- Check if all 5 assets are in the market catalog

### False Positives

- Adjust tolerance thresholds in audit checks
- Review intended vs actual behavior descriptions
- Check if placeholder checks are triggering

## Future Enhancements

1. Implement all placeholder checks
2. Add real-time alerting (Telegram, PagerDuty)
3. Add Grafana dashboard integration
4. Add automated remediation for common issues
5. Add historical trend analysis
6. Add performance metrics for audit checks
7. Add configurable audit schedules (not just 15m cycles)
8. Add per-asset detailed audit reports
