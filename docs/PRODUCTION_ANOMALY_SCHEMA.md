# Production-Wide Anomaly Schema

**Purpose**: Defines the JSON/CSV schema for production anomaly data collected by the anomaly monitor (`scripts/scan_bias_and_exit_health.py`). This schema enables structured anomaly detection, alerting, and historical analysis.

**Last Updated**: 2026-07-24

---

## Overview

The production anomaly schema captures anomalies across the MERID stack in a structured format. This enables:
- Real-time anomaly detection and alerting
- Historical trend analysis
- Root cause investigation
- SSOT drift monitoring
- Performance regression detection

---

## JSON Schema

### Root Object

```json
{
  "scan_timestamp": "2026-07-24T12:00:00Z",
  "log_file": "path/to/log.txt",
  "scan_duration_seconds": 1.5,
  "summary": { ... },
  "assets": { ... },
  "issues": [ ... ],
  "warnings": [ ... ],
  "metadata": { ... }
}
```

### Summary

```json
{
  "summary": {
    "total_issues": 0,
    "total_warnings": 0,
    "exit_invariant_violations": 0,
    "exit_post_size_issues": 0,
    "bias_issues": 0,
    "price_side_mismatches": 0,
    "signal_intent_sync_issues": 0,
    "ssot_invariant_fires": 0,
    "data_staleness_issues": 0,
    "cheap_wrong_side_candidates": 0
  }
}
```

**Fields**:
- `total_issues`: Count of critical issues (zero tolerance)
- `total_warnings`: Count of warnings (investigate if frequent)
- `exit_invariant_violations`: Exit logic violations
- `exit_post_size_issues`: Exit order size issues (post_size >= pre_size)
- `bias_issues`: Signal=NO but no NO orders sent
- `price_side_mismatches`: Price-side alignment violations
- `signal_intent_sync_issues`: Signal→thesis→candidate→order side mismatches
- `ssot_invariant_fires`: Runtime SSOT enforcement warnings
- `data_staleness_issues`: Stale data (orderbook, catalog)
- `cheap_wrong_side_candidates`: Correctly rejected cheap wrong side (info only)

### Assets

```json
{
  "assets": {
    "BTC": {
      "no_signals_seen": 10,
      "no_orders_sent": 10,
      "yes_signals_seen": 5,
      "yes_orders_sent": 5,
      "exit_invariant_violations": 0,
      "exit_post_size_issues": 0,
      "bias_issues": 0,
      "price_side_mismatches": 0,
      "signal_intent_sync_issues": 0,
      "ssot_invariant_fires": 0,
      "data_staleness_issues": 0,
      "cheap_wrong_side_candidates": 0
    },
    "ETH": { ... },
    "SOL": { ... },
    "XRP": { ... },
    "DOGE": { ... }
  }
}
```

**Fields**: Per-asset counts for each anomaly type.

### Issues (Critical)

```json
{
  "issues": [
    {
      "type": "EXIT-INVARIANT-VIOLATION",
      "category": "point",
      "severity": "critical",
      "timestamp": "2026-07-24T12:00:00Z",
      "line_num": 1234,
      "market_id": "KXBTC15M-26JUL211745-45",
      "asset": "BTC",
      "position_id": "abc123",
      "details": "Exit order did not reduce position size",
      "line": "Full log line..."
    }
  ]
}
```

**Issue Types**:
- `EXIT-INVARIANT-VIOLATION`: Exit logic violation
- `EXIT-POST-SIZE-ISSUE`: Exit size >= pre-size
- `BISSUE`: Signal=NO but no NO orders
- `PRICE-SIDE-CHECK-VIOLATION`: Price-side mismatch
- `SIGNAL-INTENT-SYNC-ISSUE`: Signal→thesis→candidate→order side mismatch

**Categories**:
- `point`: Individual event anomaly
- `contextual`: Window-based anomaly (e.g., NO signals but YES orders)
- `pattern`: Sequence anomaly (e.g., clusters of mismatches)

**Severity**:
- `critical`: Zero tolerance, must investigate immediately
- `high`: Investigate within 1 hour
- `medium`: Investigate within 4 hours
- `low`: Monitor for trends

### Warnings (Non-Critical)

```json
{
  "warnings": [
    {
      "type": "SSOT-INVARIANT",
      "category": "point",
      "severity": "medium",
      "timestamp": "2026-07-24T12:00:00Z",
      "line_num": 5678,
      "market_id": "KXBTC15M-26JUL211745-45",
      "asset": "BTC",
      "details": "Runtime SSOT guard forced panic_fade_enabled=False",
      "line": "Full log line..."
    },
    {
      "type": "DATA-STALENESS-ISSUE",
      "category": "point",
      "severity": "medium",
      "timestamp": "2026-07-24T12:00:00Z",
      "line_num": 9012,
      "market_id": "KXETH15M-26JUL211730-30",
      "asset": "ETH",
      "staleness_seconds": 65,
      "details": "Catalog data stale for 65 seconds",
      "line": "Full log line..."
    }
  ]
}
```

**Warning Types**:
- `SSOT-INVARIANT`: Runtime SSOT enforcement (investigate if frequent)
- `DATA-STALENESS-ISSUE`: Stale data (investigate if > 60s)

### Metadata

```json
{
  "metadata": {
    "scan_version": "1.0",
    "scanner_name": "ProductionAnomalyMonitor",
    "profile_version": "2.4.0",
    "profile_name": "kalshi_crypto_15m_v2",
    "environment": "production",
    "host": "server-01"
  }
}
```

---

## CSV Schema

### Header Row

```
timestamp,asset,no_signals_seen,no_orders_sent,yes_signals_seen,yes_orders_sent,exit_invariant_violations,exit_post_size_issues,bias_issues,price_side_mismatches,signal_intent_sync_issues,ssot_invariant_fires,data_staleness_issues,cheap_wrong_side_candidates
```

### Data Rows

```
2026-07-24T12:00:00Z,BTC,10,10,5,5,0,0,0,0,0,0,0,0
2026-07-24T12:00:00Z,ETH,8,8,6,6,0,0,0,0,0,0,0,0
2026-07-24T12:00:00Z,SOL,12,12,4,4,0,0,0,0,0,0,0,0
2026-07-24T12:00:00Z,XRP,9,9,7,7,0,0,0,0,0,0,0,0
2026-07-24T12:00:00Z,DOGE,11,11,3,3,0,0,0,0,0,0,0,0
```

---

## Alert Thresholds

### Critical Issues (Zero Tolerance)

- `exit_invariant_violations > 0` → Alert immediately
- `exit_post_size_issues > 0` → Alert immediately
- `bias_issues > 0` → Alert immediately
- `price_side_mismatches > 0` → Alert immediately
- `signal_intent_sync_issues > 0` → Alert immediately

### Warnings (Investigate if Frequent)

- `ssot_invariant_fires > 10` in 1 hour → Investigate (possible config drift)
- `data_staleness_issues > 5` in 1 hour → Investigate (data pipeline issue)
- `data_staleness_seconds > 60` → Warning (catalog staleness)
- `data_staleness_seconds > 120` → Alert (critical staleness)

### Pattern Anomalies

- Clusters of 3+ price_side_mismatches on same asset in 10 minutes → Alert
- No signals for 30 minutes but orders continue → Alert (contextual anomaly)
- Exit reconciliation failures on same market 3+ times → Alert (pattern anomaly)

---

## Anomaly Categories

### Point Anomalies
Individual events where side/price mismatch occurs. Example:
- Single PRICE-SIDE-CHECK-VIOLATION on KXBTC15M
- Single EXIT-INVARIANT-VIOLATION on KXETH15M

### Contextual Anomalies
Windows where NO signals appear but YES orders dominate. Example:
- 30-minute window with 0 NO signals but 15 YES orders on BTC
- 15-minute window with stale catalog data but orders continue

### Pattern Anomalies
Sequences where exits fail to reconcile ledger state, or price-side mismatches cluster. Example:
- 5 price_side_mismatches on SOL in 10 minutes
- 3 exit reconciliation failures on same market in 1 hour
- SSOT invariant fires on all 5 assets in 5 minutes (config drift)

---

## Usage Examples

### Running the Anomaly Monitor

```bash
# Text output (default)
python scripts/scan_bias_and_exit_health.py logs/merid_2026-07-24.log

# JSON output
python scripts/scan_bias_and_exit_health.py logs/merid_2026-07-24.log --output json

# CSV output
python scripts/scan_bias_and_exit_health.py logs/merid_2026-07-24.log --output csv

# Write to file
python scripts/scan_bias_and_exit_health.py logs/merid_2026-07-24.log --output json --output-file anomaly_report.json
```

### Integrating with Alerting

```python
import json

# Load anomaly report
with open('anomaly_report.json', 'r') as f:
    report = json.load(f)

# Check for critical issues
if report['summary']['total_issues'] > 0:
    # Send alert
    send_alert(f"CRITICAL: {report['summary']['total_issues']} production anomalies detected")

# Check for SSOT drift
if report['summary']['ssot_invariant_fires'] > 10:
    # Send warning
    send_alert(f"WARNING: {report['summary']['ssot_invariant_fires']} SSOT invariant fires - possible config drift")
```

### Historical Trend Analysis

```python
import pandas as pd

# Load CSV reports
df = pd.read_csv('anomaly_report.csv')

# Plot trends over time
df.plot(x='timestamp', y=['price_side_mismatches', 'signal_intent_sync_issues'])

# Identify assets with most issues
issues_by_asset = df.groupby('asset')[['price_side_mismatches', 'signal_intent_sync_issues']].sum()
```

---

## Integration with CI/CD

### Pre-Deployment Check

```yaml
# .github/workflows/ci.yml
- name: Run Anomaly Monitor
  run: |
    python scripts/scan_bias_and_exit_health.py logs/latest_test_run.log --output json --output-file anomaly_report.json
    
- name: Check for Critical Issues
  run: |
    python -c "
    import json
    with open('anomaly_report.json') as f:
        report = json.load(f)
    if report['summary']['total_issues'] > 0:
        exit(1)
    "
```

### Scheduled Health Checks

```yaml
# .github/workflows/health_check.yml
on:
  schedule:
    - cron: '0 * * * *'  # Every hour
jobs:
  health_check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Anomaly Monitor
        run: |
          python scripts/scan_bias_and_exit_health.py logs/production.log --output json --output-file health_report.json
      - name: Upload Report
        uses: actions/upload-artifact@v2
        with:
          name: health-report
          path: health_report.json
```

---

## Future Enhancements

- **Real-time streaming**: Integrate with log aggregation (ELK, Splunk) for real-time anomaly detection
- **Machine learning**: Train anomaly detection models on historical data
- **Root cause analysis**: Auto-correlate anomalies with config changes, deployments, or market events
- **Dashboard integration**: Feed anomaly data into Grafana for visualization
- **Automated remediation**: Auto-rollback config changes when SSOT drift detected
