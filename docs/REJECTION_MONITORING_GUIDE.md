# Rejection Monitoring System - Integration Guide

## Overview

The Rejection Monitoring System provides comprehensive tracking and analysis of signal rejections across the 15M Kalshi crypto trading pipeline. This system captures every rejection event with detailed context, enabling data-driven threshold optimization and bug detection.

Based on 2026 industry best practices for algorithmic trading rejection monitoring, the system implements:

- **Structured JSON logging** for all rejection events
- **Zero-overhead async logging** to avoid trading latency
- **Real-time metrics** for per-asset and per-category rejection tracking
- **Post-hoc analysis** for threshold optimization recommendations
- **Counterfactual analysis support** (Post-Rejection Follow-up Sampling methodology)

## Architecture

### Components

1. **RejectionMonitor** (`merid/monitoring/rejection_monitor.py`)
   - Production-grade rejection capture with async file logging
   - In-memory circular buffer for real-time metrics
   - Configurable sampling rates for high-frequency systems
   - Thread-safe counters for per-asset/category tracking

2. **RejectionAnalyzer** (`scripts/rejection_analyzer.py`)
   - Post-hoc analysis of rejection logs
   - Category-based rejection classification
   - Threshold gap analysis (near-miss detection)
   - Optimization recommendations

3. **Integration Points**
   - `merid/prediction/agent_grid_15m.py` - Signal generation rejections
   - `merid/prediction/unified_edge.py` - Edge check rejections

## Installation & Setup

### 1. Verify Integration

The rejection monitor is already integrated into the production codebase:

```python
# In agent_grid_15m.py
from merid.monitoring.rejection_monitor import (
    get_rejection_monitor,
    log_time_window_rejection,
    log_price_range_rejection,
    log_trend_alignment_rejection,
    log_edge_check_rejection,
)
```

### 2. Configure Output Directory

Rejection logs are written to `data/rejections/` by default. The directory is created automatically.

### 3. Enable/Disable Monitoring

The monitor is enabled by default but can be disabled if needed:

```python
# In production code, the monitor auto-starts on first use
monitor = get_rejection_monitor()

# To disable (e.g., for testing), set environment variable or modify code
# REJECTION_MONITOR_ENABLED = False
```

## Usage

### Production Usage (Automatic)

The rejection monitor automatically captures rejections from:

1. **Time Window Filters**
   - Too early (> max_entry_mins)
   - Too late (< min_entry_mins)
   - Terminal phase (< cutoff_mins)

2. **Price Range Filters**
   - Both YES and NO outside 10c-50c sweet spot

3. **Trend Alignment Filters**
   - 5m and 1h trends not aligned

4. **Session Filters**
   - Trading session not active

5. **Edge Check Filters** (via unified_edge.py)
   - Spread too wide
   - Spread percentage too high
   - Price too low (longshot trap)
   - Price too high (low-profit trap)
   - Insufficient depth
   - Edge insufficient
   - OTM distance too large
   - Time trap (too early/late)
   - Edge/lag ratio insufficient

### Manual Rejection Logging

For custom rejection scenarios, use the monitor directly:

```python
from merid.monitoring.rejection_monitor import get_rejection_monitor

monitor = get_rejection_monitor()
monitor.log_rejection(
    asset="BTC",
    category="custom_filter",
    reason="Custom rejection reason",
    spot_price=65000.0,
    yes_price_cents=45,
    no_price_cents=55,
    minutes_to_expiry=8.5,
    threshold_value=50.0,
    actual_value=45.0,
    additional_context={"filter_name": "my_custom_filter"},
)
```

### Convenience Functions

Use pre-configured functions for common rejection types:

```python
from merid.monitoring.rejection_monitor import (
    log_time_window_rejection,
    log_price_range_rejection,
    log_trend_alignment_rejection,
    log_edge_check_rejection,
)

# Time window rejection
log_time_window_rejection(
    asset="BTC",
    minutes_to_expiry=16.5,
    reason="too early: >15.0min",
    market_id="KXBTC15M-...",
)

# Price range rejection
log_price_range_rejection(
    asset="ETH",
    yes_price_cents=5,
    no_price_cents=95,
    reason="both sides outside side-aware ranges (regime=NORMAL)",
)

# Trend alignment rejection
log_trend_alignment_rejection(
    asset="SOL",
    reason="5m and 1h trends not aligned",
)

# Edge check rejection
log_edge_check_rejection(
    asset="XRP",
    reason="spread_too_wide: spread=25c > 20c threshold",
    spread_cents=25,
    threshold_value=20,
    actual_value=25,
)
```

## Analysis & Reporting

### Analyze Existing Logs

```bash
# Analyze recent log file
python scripts/rejection_analyzer.py --mode analyze --log_file logs/merid.log --lines 1000 --output data/rejections/captured.jsonl

# This will:
# 1. Parse log file for rejection events
# 2. Save to JSONL format
# 3. Generate immediate analysis report
```

### Generate Comprehensive Report

```bash
# Generate detailed report from captured rejections
python scripts/rejection_analyzer.py --mode report --input_jsonl data/rejections/captured.jsonl --output reports/rejection_analysis_20260710.json
```

### Report Contents

The analysis report includes:

1. **Category Analysis**
   - Total rejections by category
   - Percentage breakdown
   - Top rejection categories

2. **Asset Analysis**
   - Rejections per asset (BTC, ETH, SOL, XRP, DOGE)
   - Per-asset category breakdown
   - Asset-specific issues

3. **Time Analysis**
   - Rejections over time (per-minute buckets)
   - Average rejection rate
   - Peak rejection periods

4. **Threshold Gap Analysis**
   - Near-miss detection (within 10% of threshold)
   - Average/median gap from threshold
   - Optimization opportunities

5. **Recommendations**
   - Threshold adjustment suggestions
   - High-rejection category alerts
   - Asset-specific recommendations

### Example Report Output

```json
{
  "report_metadata": {
    "generated_at": "2026-07-10T05:30:00Z",
    "total_rejections_analyzed": 1234
  },
  "category_analysis": {
    "total_rejections": 1234,
    "by_category": {
      "time_window": 456,
      "price_range": 312,
      "spread_quality": 234,
      "edge_insufficient": 156,
      "trend_alignment": 76
    },
    "category_percentages": {
      "time_window": 37.0,
      "price_range": 25.3,
      "spread_quality": 19.0,
      "edge_insufficient": 12.6,
      "trend_alignment": 6.2
    }
  },
  "asset_analysis": {
    "by_asset": {
      "BTC": 312,
      "ETH": 287,
      "SOL": 234,
      "XRP": 198,
      "DOGE": 203
    }
  },
  "threshold_analysis": {
    "near_misses": [
      {
        "asset": "BTC",
        "category": "spread_quality",
        "threshold": 20,
        "actual": 21,
        "gap": 1,
        "gap_percentage": 5.0
      }
    ],
    "average_gap_percentage": 15.3
  },
  "recommendations": [
    "CRITICAL: time_window accounts for 37.0% of all rejections. Review if threshold is too strict.",
    "OPTIMIZATION: 23 rejections were within 10% of threshold. Consider small threshold adjustments.",
    "WARNING: BTC has 312 rejections (25.3%). Check if asset-specific thresholds need adjustment."
  ]
}
```

## Real-Time Monitoring

### Access Real-Time Metrics

```python
from merid.monitoring.rejection_monitor import get_rejection_monitor

monitor = get_rejection_monitor()
metrics = monitor.get_metrics()

print(f"Total rejections: {metrics['total_rejections']}")
print(f"By asset: {metrics['by_asset']}")
print(f"By category: {metrics['by_category']}")
print(f"Buffer utilization: {metrics['buffer_utilization']:.1%}")
```

### Get Recent Events

```python
# Get last 100 rejection events
recent_events = monitor.get_recent_events(limit=100)

for event in recent_events:
    print(f"{event['timestamp']} - {event['asset']} - {event['rejection_category']}: {event['rejection_reason']}")
```

## Threshold Optimization

### Using Near-Miss Analysis

The threshold gap analysis identifies rejections that were close to passing:

1. **Near-misses** (within 10% of threshold): Consider small threshold adjustments
2. **Large gaps** (> 50% of threshold): Threshold is appropriate, rejection is correct
3. **Systematic patterns**: If an asset consistently has near-misses, adjust asset-specific thresholds

### Example Threshold Adjustment Process

1. **Generate analysis report**
   ```bash
   python scripts/rejection_analyzer.py --mode report --input_jsonl data/rejections/rejections_20260710.jsonl
   ```

2. **Review near-misses**
   - Look for patterns in specific categories
   - Check if certain assets are consistently near thresholds

3. **Adjust profile configuration**
   - Edit `config/profiles/kalshi_crypto_15m_v2.yaml`
   - Adjust relevant thresholds (e.g., `guardrails_max_spread_cents`)

4. **Test in shadow mode**
   - Run with new thresholds but without live trading
   - Compare rejection rates before/after

5. **Deploy incrementally**
   - Monitor rejection rates after deployment
   - Roll back if rejection rate spikes unexpectedly

## Performance Considerations

### Overhead

The rejection monitor is designed for minimal overhead:

- **Sampling check**: O(1) operation
- **In-memory counter update**: Thread-safe, ~1μs
- **Queue put**: Non-blocking, ~10μs
- **File I/O**: Background thread, no impact on trading

### Sampling Rate

For high-frequency systems (>1000 rejections/minute), use sampling:

```python
monitor = get_rejection_monitor(sampling_rate=0.1)  # Log 10% of rejections
```

### Memory Usage

Default configuration: 10,000 events in memory (~2MB RAM)

Adjust based on requirements:
```python
monitor = get_rejection_monitor(max_memory_events=5000)  # ~1MB RAM
```

## Troubleshooting

### No Rejections Captured

1. Check if monitor is enabled:
   ```python
   from merid.monitoring.rejection_monitor import get_rejection_monitor
   monitor = get_rejection_monitor()
   print(monitor.get_metrics())
   ```

2. Verify integration points are calling rejection functions
3. Check log files for import errors

### High Memory Usage

Reduce buffer size:
```python
monitor = get_rejection_monitor(max_memory_events=1000)
```

### File I/O Errors

Check disk space and permissions:
```bash
# Verify directory exists and is writable
ls -la data/rejections/
```

## Integration with Existing Monitoring

### Grafana Dashboard

Create a dashboard showing:

- Rejection rate per minute
- Rejection breakdown by category
- Per-asset rejection rates
- Near-miss rate over time

### Alerts

Set up alerts for:

- Rejection rate > 50/minute (possible system issue)
- Single category > 80% of rejections (threshold too strict)
- Asset-specific rejection rate spike

## Best Practices

1. **Review rejection reports daily** during initial deployment
2. **Adjust thresholds incrementally** based on data, not intuition
3. **Use near-miss analysis** to find optimization opportunities
4. **Monitor rejection rates** after any threshold changes
5. **Keep historical data** for trend analysis
6. **Document threshold changes** with rationale

## References

Based on 2026 industry research:

- **Post-Rejection Follow-up Sampling (PRFS)**: Counterfactual methodology for filter quality evaluation
- **Decision Logging in Algorithmic Trading**: Foundational practice for professional trading systems
- **Monitoring & Incident Response for Trading Bots**: Real-time metrics and alerting best practices

## Support

For issues or questions:

1. Check this guide for common scenarios
2. Review generated analysis reports for insights
3. Examine raw rejection logs in `data/rejections/`
4. Consult threshold optimization recommendations

## File Locations

- **Monitor**: `merid/monitoring/rejection_monitor.py`
- **Analyzer**: `scripts/rejection_analyzer.py`
- **Integration**: `merid/prediction/agent_grid_15m.py`, `merid/prediction/unified_edge.py`
- **Logs**: `data/rejections/rejections_YYYY-MM-DD.jsonl`
- **Reports**: `reports/rejection_analysis_YYYYMMDD.json`
