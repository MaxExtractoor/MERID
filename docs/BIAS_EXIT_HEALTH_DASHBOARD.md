# Bias and Exit Health Dashboard Integration

This document describes how to integrate the bias and exit health log scanner output with Grafana or Metabase for live monitoring of YES/NO balance and exit health.

## Output Formats

### JSON Format

The log scanner can output structured JSON with the following schema:

```json
{
  "scan_timestamp": "2026-07-24T12:00:00Z",
  "log_file": "path/to/log.txt",
  "summary": {
    "total_issues": 0,
    "exit_invariant_violations": 0,
    "exit_post_size_issues": 0,
    "bias_issues": 0,
    "price_side_mismatches": 0,
    "cheap_wrong_side_candidates": 0
  },
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
      "cheap_wrong_side_candidates": 0
    },
    "ETH": { ... },
    "SOL": { ... },
    "XRP": { ... },
    "DOGE": { ... }
  },
  "issues": [
    {
      "type": "EXIT-INVARIANT-VIOLATION",
      "timestamp": "2026-07-24T12:00:00Z",
      "line_num": 1234,
      "market_id": "KXBTC15M-26JUL211745-45",
      "asset": "BTC",
      "position_id": "abc123",
      "details": "..."
    },
    {
      "type": "PRICE-SIDE-CHECK-VIOLATION",
      "timestamp": "2026-07-24T12:00:00Z",
      "line_num": 5678,
      "market_id": "KXBTC15M-26JUL211745-45",
      "asset": "BTC",
      "thesis_side": "no",
      "order_side": "BUY_YES",
      "details": "Order side does not match thesis_side from intent"
    }
  ]
}
```

### CSV Format

The log scanner can output CSV with the following schema:

```csv
timestamp,asset,no_signals_seen,no_orders_sent,yes_signals_seen,yes_orders_sent,exit_invariant_violations,exit_post_size_issues,bias_issues,price_side_mismatches,cheap_wrong_side_candidates
2026-07-24T12:00:00Z,BTC,10,10,5,5,0,0,0,0,0
2026-07-24T12:00:00Z,ETH,8,8,6,6,0,0,0,0,0
2026-07-24T12:00:00Z,SOL,12,12,4,4,0,0,0,0,0
2026-07-24T12:00:00Z,XRP,6,6,7,7,0,0,0,0,0
2026-07-24T12:00:00Z,DOGE,9,9,5,5,0,0,0,0,0
```

## Usage

### Generate JSON Output

```bash
python scripts/scan_bias_and_exit_health.py path/to/log.txt --output json --output-file bias_health_report.json
```

### Generate CSV Output

```bash
python scripts/scan_bias_and_exit_health.py path/to/log.txt --output csv --output-file bias_health_report.csv
```

### Generate Text Output (Default)

```bash
python scripts/scan_bias_and_exit_health.py path/to/log.txt
```

## Grafana Integration

### Data Source Setup

1. **JSON Data Source**: Use the JSON API plugin or upload JSON files to a time-series database
2. **CSV Data Source**: Import CSV files into InfluxDB, Prometheus, or use the CSV plugin

### Dashboard Panel Mappings

#### Panel 1: NO vs YES Signal Distribution

- **Panel Type**: Pie Chart or Bar Chart
- **Query**: Group by `asset`, sum `no_signals_seen` and `yes_signals_seen`
- **Field Mappings**:
  - `asset`: Label
  - `no_signals_seen`: Value (NO signals)
  - `yes_signals_seen`: Value (YES signals)
- **Alert**: If `no_signals_seen` = 0 for any asset in bearish regime

#### Panel 2: NO vs YES Order Distribution

- **Panel Type**: Pie Chart or Bar Chart
- **Query**: Group by `asset`, sum `no_orders_sent` and `yes_orders_sent`
- **Field Mappings**:
  - `asset`: Label
  - `no_orders_sent`: Value (NO orders)
  - `yes_orders_sent`: Value (YES orders)
- **Alert**: If `no_orders_sent` = 0 when `no_signals_seen` > 0

#### Panel 3: Exit Invariant Violations

- **Panel Type**: Stat Panel or Table
- **Query**: Sum `exit_invariant_violations` by `asset`
- **Field Mappings**:
  - `asset`: Label
  - `exit_invariant_violations`: Value
- **Alert**: If `exit_invariant_violations` > 0 for any asset

#### Panel 4: Exit Post-Size Issues

- **Panel Type**: Stat Panel or Table
- **Query**: Sum `exit_post_size_issues` by `asset`
- **Field Mappings**:
  - `asset`: Label
  - `exit_post_size_issues`: Value
- **Alert**: If `exit_post_size_issues` > 0 for any asset

#### Panel 5: Bias Issues Summary

- **Panel Type**: Stat Panel
- **Query**: Sum `bias_issues` across all assets
- **Field Mappings**:
  - `bias_issues`: Value
- **Alert**: If `bias_issues` > 0

#### Panel 6: Total Issues Trend

- **Panel Type**: Time Series Graph
- **Query**: Time series of `summary.total_issues`
- **Field Mappings**:
  - `scan_timestamp`: Time
  - `total_issues`: Value
- **Alert**: If `total_issues` > 0

#### Panel 7: Price-Side Discipline (Cheap Wrong Side Rejections)

- **Panel Type**: Stat Panel or Table
- **Query**: Sum `cheap_wrong_side_candidates` by `asset`
- **Field Mappings**:
  - `asset`: Label
  - `cheap_wrong_side_candidates`: Value
- **Interpretation**: Higher values indicate the invariant is working (cheapness on wrong side is correctly ignored). This is a positive metric showing the system is protecting against "cheap but wrong" trades.

#### Panel 8: Price-Side Mismatches (Critical)

- **Panel Type**: Stat Panel or Table
- **Query**: Sum `price_side_mismatches` by `asset`
- **Field Mappings**:
  - `asset`: Label
  - `price_side_mismatches`: Value
- **Alert**: If `price_side_mismatches` > 0 for any asset (CRITICAL - indicates invariant violation)

### Grafana Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| `exit_invariant_violations` | > 0 | > 0 |
| `exit_post_size_issues` | > 0 | > 0 |
| `bias_issues` | > 0 | > 0 |
| `no_orders_sent` / `no_signals_seen` | < 0.8 | < 0.5 |
| `price_side_mismatches` | > 0 | > 0 |
| `cheap_wrong_side_candidates` | N/A | N/A (positive metric - higher is better) |

### Example Panel: NO-Order Share vs Expected NO-Signal Share (BTC 15m)

This panel provides a direct visual for residual bias by comparing the actual NO-order execution rate against the expected NO-signal share.

**Panel Configuration:**

```json
{
  "title": "NO-Order Share vs Expected NO-Signal Share (BTC 15m)",
  "type": "timeseries",
  "gridPos": {
    "h": 8,
    "w": 12,
    "x": 0,
    "y": 0
  },
  "targets": [
    {
      "expr": "bias_health_no_orders_sent{asset=\"BTC\"} / (bias_health_no_orders_sent{asset=\"BTC\"} + bias_health_yes_orders_sent{asset=\"BTC\"})",
      "legendFormat": "NO-Order Share (Actual)",
      "refId": "A"
    },
    {
      "expr": "bias_health_no_signals_seen{asset=\"BTC\"} / (bias_health_no_signals_seen{asset=\"BTC\"} + bias_health_yes_signals_seen{asset=\"BTC\"})",
      "legendFormat": "NO-Signal Share (Expected)",
      "refId": "B"
    }
  ],
  "fieldConfig": {
    "defaults": {
      "color": {
        "mode": "palette-classic"
      },
      "custom": {
        "lineWidth": 2,
        "fillOpacity": 10
      },
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {
            "color": "green",
            "value": null
          },
          {
            "color": "yellow",
            "value": 0.8
          },
          {
            "color": "red",
            "value": 0.5
          }
        ]
      }
    }
  },
  "alert": {
    "conditions": [
      {
        "evaluator": {
          "params": [
            0.8
          ],
          "type": "lt"
        },
        "operator": {
          "type": "and"
        },
        "query": {
          "params": [
            "A",
            "5m",
            "now"
          ]
        },
        "reducer": {
          "params": [],
          "type": "avg"
        },
        "type": "query"
      }
    ],
    "executionErrorState": "alerting",
    "frequency": "1m",
    "handler": 1,
    "name": "BTC NO-Order Share Below Expected",
    "noDataState": "no_data",
    "notifications": []
  }
}
```

**Interpretation:**

- **Green zone (≥0.8)**: NO orders are being executed at ≥80% of the expected NO-signal rate - healthy bias-free behavior
- **Yellow zone (0.5-0.8)**: NO orders are being executed at 50-80% of expected - potential bias developing
- **Red zone (<0.5)**: NO orders are being executed at <50% of expected - critical bias, immediate investigation required

**What this panel reveals:**

- **Residual bias**: If the NO-Order Share line consistently runs below the NO-Signal Share line, there's structural bias preventing NO orders from executing
- **Execution gaps**: Spikes where NO-Signal Share rises but NO-Order Share doesn't follow indicate execution pipeline issues
- **Regime shifts**: When NO-Signal Share drops (bullish regime), NO-Order Share should drop proportionally - if it doesn't, there's lag or stuck orders

**Prometheus Query Alternative (if using Prometheus):**

```promql
# NO-Order Share (Actual)
(
  sum(bias_health_no_orders_sent{asset="BTC"}) 
  / 
  (sum(bias_health_no_orders_sent{asset="BTC"}) + sum(bias_health_yes_orders_sent{asset="BTC"}))
)

# NO-Signal Share (Expected)
(
  sum(bias_health_no_signals_seen{asset="BTC"}) 
  / 
  (sum(bias_health_no_signals_seen{asset="BTC"}) + sum(bias_health_yes_signals_seen{asset="BTC"}))
)

# Bias Gap (Expected - Actual)
(
  (sum(bias_health_no_signals_seen{asset="BTC"}) / (sum(bias_health_no_signals_seen{asset="BTC"}) + sum(bias_health_yes_signals_seen{asset="BTC"})))
  -
  (sum(bias_health_no_orders_sent{asset="BTC"}) / (sum(bias_health_no_orders_sent{asset="BTC"}) + sum(bias_health_yes_orders_sent{asset="BTC"})))
)
```

**InfluxDB Query Alternative (if using InfluxDB):**

```flux
from(bucket: "merid_bias_health")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "bias_health_report")
  |> filter(fn: (r) => r["asset"] == "BTC")
  |> pivot(columnKey: ["_field"], valueColumn: "_value")
  |> map(fn: (r) => ({
    r with 
    no_order_share: r.no_orders_sent / (r.no_orders_sent + r.yes_orders_sent),
    no_signal_share: r.no_signals_seen / (r.no_signals_seen + r.yes_signals_seen),
    bias_gap: (r.no_signals_seen / (r.no_signals_seen + r.yes_signals_seen)) - (r.no_orders_sent / (r.no_orders_sent + r.yes_orders_sent))
  }))
```

## Metabase Integration

### Data Source Setup

1. **JSON Import**: Upload JSON files to Metabase as a CSV/JSON data source
2. **CSV Import**: Import CSV files directly into Metabase

### Dashboard Question Mappings

#### Question 1: NO Signal Coverage by Asset

- **Query**: 
  ```sql
  SELECT 
    asset,
    no_signals_seen,
    yes_signals_seen,
    no_signals_seen / (no_signals_seen + yes_signals_seen) as no_signal_ratio
  FROM bias_health_report
  ```
- **Visualization**: Bar Chart
- **Field Mappings**:
  - `asset`: X-axis
  - `no_signal_ratio`: Y-axis

#### Question 2: NO Order Execution Rate

- **Query**:
  ```sql
  SELECT 
    asset,
    no_signals_seen,
    no_orders_sent,
    CASE 
      WHEN no_signals_seen > 0 THEN no_orders_sent / no_signals_seen
      ELSE 0
    END as no_order_execution_rate
  FROM bias_health_report
  ```
- **Visualization**: Bar Chart
- **Field Mappings**:
  - `asset`: X-axis
  - `no_order_execution_rate`: Y-axis

#### Question 3: Exit Health Summary

- **Query**:
  ```sql
  SELECT 
    asset,
    exit_invariant_violations,
    exit_post_size_issues,
    bias_issues
  FROM bias_health_report
  WHERE 
    exit_invariant_violations > 0 
    OR exit_post_size_issues > 0 
    OR bias_issues > 0
  ```
- **Visualization**: Table
- **Field Mappings**:
  - `asset`: Column
  - `exit_invariant_violations`: Column
  - `exit_post_size_issues`: Column
  - `bias_issues`: Column

## Automation

### CI/CD Integration

Add to your CI pipeline:

```yaml
# Example GitHub Actions
- name: Scan logs for bias and exit health
  run: |
    python scripts/scan_bias_and_exit_health.py logs/merid.log --output json --output-file bias_health_report.json
    
- name: Upload to dashboard
  run: |
    # Upload bias_health_report.json to your time-series database
    # or trigger dashboard refresh
```

### Scheduled Scans

Run the scanner after each live session (12-15 hours):

```bash
# Cron job example
0 */12 * * * cd /path/to/MERID && python scripts/scan_bias_and_exit_health.py logs/merid.log --output json --output-file /var/www/dashboards/bias_health.json
```

## Alert Configuration

### Email Alerts

Configure alerts to trigger when:
- Any `exit_invariant_violations` > 0
- Any `exit_post_size_issues` > 0
- Any `bias_issues` > 0
- NO order execution rate < 80%

### Slack/Webhook Alerts

Send alerts to Slack when critical issues are detected:

```json
{
  "text": "MERID Bias/Exit Health Alert",
  "attachments": [
    {
      "color": "danger",
      "title": "Exit Invariant Violation Detected",
      "fields": [
        {
          "title": "Asset",
          "value": "BTC"
        },
        {
          "title": "Market ID",
          "value": "KXBTC15M-26JUL211745-45"
        }
      ]
    }
  ]
}
```

## Performance Considerations

- **Log Size**: For large log files (>1GB), consider splitting by time windows
- **Scan Frequency**: Run scans after each session, not in real-time
- **Data Retention**: Keep historical data for trend analysis (30-90 days)
- **Dashboard Refresh**: Update dashboards every 5-15 minutes

## Troubleshooting

### No Data in Dashboard

- Verify log file path is correct
- Check that log file contains SIDE-PRESERVATION-CHECK logs
- Ensure JSON/CSV output is being generated correctly

### False Positives

- Review log entries manually to confirm violations
- Adjust alert thresholds based on your risk tolerance
- Filter out known benign patterns

### Performance Issues

- Reduce log scan frequency
- Use incremental scanning (only new log entries)
- Consider pre-processing logs to extract relevant fields
