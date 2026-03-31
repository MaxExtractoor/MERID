# Crypto Coverage Live Monitoring Guide

## Overview

This guide documents the runtime monitoring infrastructure for the 25-market crypto coverage system (5 assets × 5 timeframes). These tools provide continuous validation that the system remains production-ready as markets evolve.

## Architecture

### Three-Layer Monitoring

1. **Scheduled Readiness Checks** (GitHub Actions)
   - Runs daily at 06:00 UTC
   - Executes comprehensive coverage tests
   - Runs full readiness validation
   - Stores 90 days of historical results
   - Creates GitHub issues on failure

2. **Live Status API** (FastAPI endpoints)
   - Real-time readiness status queries
   - Historical trending and uptime statistics
   - 25-cell matrix health view
   - On-demand check triggers

3. **UI Dashboard Widget** (React component)
   - Visual 25-cell matrix (5×5 grid)
   - Color-coded health indicators
   - Component-level drill-down
   - Auto-refresh every 60 seconds

## Scheduled Readiness Checks

### GitHub Actions Workflow

**File**: `.github/workflows/crypto-readiness-check.yml`

**Schedule**: Daily at 06:00 UTC (before US market open)

**Triggers**:
- Scheduled cron
- Manual workflow dispatch
- Push to main/develop (if crypto files change)

**What It Does**:
1. Runs `test_crypto_coverage_comprehensive.py` (4 tests)
2. Runs `kalshi_crypto_live_readiness.py --json` (5 sections)
3. Generates markdown report
4. Uploads artifacts (90-day retention)
5. Creates GitHub issue on failure

**Artifacts**:
- `coverage_test_results.txt` - Test output
- `readiness_results.json` - JSON status
- `readiness_report.md` - Human-readable summary

### Manual Trigger

```bash
# Via GitHub CLI
gh workflow run crypto-readiness-check.yml

# Via GitHub UI
# Actions → Crypto Readiness Check → Run workflow
```

### Viewing History

```bash
# List recent runs
gh run list --workflow=crypto-readiness-check.yml --limit 10

# Download artifacts from specific run
gh run download <run-id>
```

## Live Status API

### Endpoints

#### 1. Current Readiness Status

```bash
GET /api/v1/crypto/readiness/status
```

Returns current readiness check results:

```json
{
  "timestamp": "2026-03-31T16:00:00Z",
  "live_ready": true,
  "blocking_failures": [],
  "env_vars_valid": 12,
  "env_vars_total": 12,
  "formulas_valid": 8,
  "formulas_total": 8,
  "proposals_valid": 3,
  "proposals_total": 3,
  "markets_covered": 25,
  "markets_total": 25,
  "config_validation": true,
  "data_feeds_healthy": true,
  "cfb_status": "✓ CFB RTI feed healthy: BRTI",
  "duration_ms": 3542
}
```

#### 2. Historical Readiness Data

```bash
GET /api/v1/crypto/readiness/history?limit=100
```

Returns historical results with uptime statistics:

```json
{
  "latest": { ... },
  "history": [ ... ],
  "uptime_pct": 98.5,
  "total_checks": 147
}
```

#### 3. 25-Cell Matrix Status

```bash
GET /api/v1/crypto/readiness/matrix
```

Returns health status for each asset × timeframe:

```json
{
  "cells": [
    {
      "asset": "BTC",
      "timeframe": "15m",
      "catalog_ok": true,
      "strategy_ok": true,
      "sizing_ok": true,
      "execution_ok": true,
      "monitor_ok": true,
      "overall_ok": true,
      "notes": ""
    },
    ...
  ],
  "total_markets": 25,
  "healthy_markets": 24,
  "degraded_markets": 1,
  "failed_markets": 0,
  "last_updated": "2026-03-31T16:05:00Z"
}
```

#### 4. Trigger On-Demand Check

```bash
POST /api/v1/crypto/readiness/check
```

Triggers an immediate readiness check and returns results.

### API Usage Examples

```python
import requests

# Check current status
response = requests.get("http://localhost:8000/api/v1/crypto/readiness/status")
status = response.json()

if status["live_ready"]:
    print("✓ System ready for live trading")
else:
    print(f"✗ Blocking failures: {status['blocking_failures']}")

# Get uptime stats
response = requests.get("http://localhost:8000/api/v1/crypto/readiness/history")
history = response.json()
print(f"Uptime: {history['uptime_pct']}% over {history['total_checks']} checks")

# Check matrix
response = requests.get("http://localhost:8000/api/v1/crypto/readiness/matrix")
matrix = response.json()
print(f"Healthy markets: {matrix['healthy_markets']}/25")
```

## UI Dashboard Widget

### Component

**File**: `web/react/src/components/CryptoReadinessMatrixWidget.tsx`

### Features

- **5×5 Grid Layout**: One row per asset, one column per timeframe
- **Color-Coded Status**:
  - 🟢 Green: All 5 components healthy (catalog, strategy, sizing, execution, monitor)
  - 🟡 Amber: Some components healthy (degraded state)
  - 🔴 Red: All components failed
- **Hover Tooltips**: Show component-level status on mouse hover
- **Auto-Refresh**: Updates every 60 seconds
- **Summary Stats**: Count of healthy/degraded/failed markets

### Integration

Add to any view:

```typescript
import CryptoReadinessMatrixWidget from '../components/CryptoReadinessMatrixWidget';

export default function MyView() {
  return (
    <div>
      {/* Other components */}
      <CryptoReadinessMatrixWidget />
    </div>
  );
}
```

### Cell States

Each cell can be in one of three states:

| State | Color | Criteria |
|-------|-------|----------|
| Healthy | Green | All 5 components OK |
| Degraded | Amber | 1-4 components OK |
| Failed | Red | 0 components OK |

### Tooltip Details

Hovering over a cell shows:
- Asset and timeframe
- Individual component status (✓ or ✗):
  - Catalog: Market discovery working
  - Strategy: Risk profile configured
  - Sizing: Kelly sizing working
  - Execution: Order execution ready
  - Monitor: Risk monitoring active
- Any error notes

## CFB RTI Settlement Logging

### Purpose

Captures actual CF Benchmarks RTI settlement prices and compares them to our internal spot price estimates. This data is used to:

- Validate internal pricing accuracy
- Detect systematic bias
- Fine-tune confidence thresholds
- Ensure feed quality

### Usage

```python
from monitoring.cfb_rti_logger import log_settlement_comparison

# After a trade settles
log_settlement_comparison(
    asset="BTC",
    timeframe="15m",
    settlement_price_cfb=50123.45,  # Official CFB RTI price
    internal_spot=50125.10,          # Our internal estimate
    market_mid=0.52,                 # Kalshi market mid-price
    edge=0.035,                      # Our calculated edge
    market_id="KXBTCUSD-26MAR31-M15",
    notes="First settlement of the day"
)
```

### Log Storage

Logs are stored in `data/cfb_rti_logs/` as daily JSONL files:

```
data/cfb_rti_logs/
  cfb_settlements_2026-03-31.jsonl
  cfb_settlements_2026-04-01.jsonl
  ...
```

### Analysis

```python
from monitoring.cfb_rti_logger import analyze_settlement_drift

# Analyze BTC 15m settlements over last 7 days
analysis = analyze_settlement_drift("BTC", "15m", days=7)
print(analysis)
```

Output:
```
CFB RTI Settlement Analysis (BTC 15m, 7 days):
  Count: 142 settlements
  Mean Divergence: +2.3 bps (overestimating)
  Std Deviation: 4.1 bps
  Range: [-8.5, +12.3] bps

  Assessment: EXCELLENT - internal pricing very accurate
```

### Divergence Thresholds

| Mean Divergence | Assessment | Action |
|-----------------|------------|--------|
| < 5 bps | Excellent | No action needed |
| 5-10 bps | Good | Monitor for trends |
| 10-20 bps | Fair | Consider recalibration |
| > 20 bps | Poor | Investigate feed quality |

### Statistics API

```python
from monitoring.cfb_rti_logger import get_settlement_statistics

stats = get_settlement_statistics(
    asset="BTC",
    timeframe="daily",
    days=30
)

# Returns:
# {
#   "count": 30,
#   "mean_divergence_bps": 1.8,
#   "std_divergence_bps": 3.2,
#   "max_divergence_bps": 9.1,
#   "min_divergence_bps": -5.4,
#   "median_divergence_bps": 1.5
# }
```

## Operational Procedures

### Pre-Flight Checklist

Before enabling live trading:

1. **Check Scheduled Workflow Status**
   ```bash
   gh run list --workflow=crypto-readiness-check.yml --limit 1
   ```
   Ensure latest run passed.

2. **Query Live API Status**
   ```bash
   curl http://localhost:8000/api/v1/crypto/readiness/status | jq
   ```
   Verify `live_ready: true`.

3. **Review Matrix Health**
   ```bash
   curl http://localhost:8000/api/v1/crypto/readiness/matrix | jq
   ```
   Confirm 25/25 markets healthy.

4. **Check Historical Uptime**
   ```bash
   curl http://localhost:8000/api/v1/crypto/readiness/history | jq '.uptime_pct'
   ```
   Verify > 95% uptime over last 100 checks.

### Ongoing Monitoring

**Daily**:
- Review GitHub Actions run results
- Check for new issues created by workflow
- Monitor matrix widget in UI

**Weekly**:
- Analyze CFB RTI settlement drift
- Review divergence statistics per asset/timeframe
- Adjust confidence thresholds if needed

**Monthly**:
- Audit 90-day historical trends
- Update risk profiles based on settlement data
- Review and archive old CFB logs

### Incident Response

If readiness check fails:

1. **Check GitHub Issue**
   - Workflow creates issue with full details
   - Review blocking failures

2. **Query API for Details**
   ```bash
   curl http://localhost:8000/api/v1/crypto/readiness/status | jq '.blocking_failures'
   ```

3. **Review Matrix for Specific Cells**
   - Look for degraded/failed cells
   - Check component-level failures

4. **Do NOT Enable Live Trading**
   - Investigate and fix issues first
   - Re-run readiness check manually
   - Verify LIVE_READY=YES before proceeding

## Integration with Existing Systems

### Production Governance Schedule

The scheduled readiness check complements the existing `ProductionGovernanceScheduler`:

```python
from governance.production_governance_schedule import ProductionGovernanceScheduler

scheduler = ProductionGovernanceScheduler()

# Readiness check runs via GitHub Actions (daily 06:00 UTC)
# Technical gate runs via scheduler (daily 02:00 local)
# Operational gate runs via scheduler (daily 02:30 local)
```

These are separate but complementary checks. Both should pass before live trading.

### Health Probes

The readiness API integrates with the existing health probe framework:

```python
from core.health_probes import register_probe, ProbeType

# Register crypto readiness as a dependency probe
register_probe(
    name="crypto_coverage_readiness",
    probe_type=ProbeType.DEPENDENCY,
    check_fn=lambda: check_crypto_readiness_api(),
    interval_seconds=300  # 5 minutes
)
```

### Monitoring Stack

CFB RTI logs integrate with Prometheus/Grafana via the monitoring API:

```python
from web.api.monitoring import router

# Export CFB divergence metrics
@router.get("/api/v1/monitoring/metrics/cfb_divergence")
async def get_cfb_divergence_metrics():
    # Parse CFB logs and return Prometheus format
    ...
```

## Future Enhancements

### Planned Features

1. **Alerting Integration**
   - Slack/PagerDuty notifications on readiness failures
   - Divergence threshold alerts
   - Cell-specific degradation alerts

2. **Advanced Analytics**
   - Time-series charts of matrix health over time
   - Correlation analysis: settlements vs market performance
   - Predictive alerts for feed degradation

3. **Automated Remediation**
   - Auto-pause agents on cell failures
   - Self-healing for transient catalog issues
   - Circuit breaker integration

4. **Extended Coverage**
   - Quarterly/annual timeframes (when Kalshi adds them)
   - Additional assets (if Kalshi expands crypto offerings)
   - Multi-venue readiness (Polymarket, etc.)

## References

- [CRYPTO_COVERAGE_COMPLETE.md](CRYPTO_COVERAGE_COMPLETE.md) - Initial implementation
- [kalshi_crypto_live_readiness.py](../scripts/kalshi_crypto_live_readiness.py) - Core readiness script
- [test_crypto_coverage_comprehensive.py](../tests/test_crypto_coverage_comprehensive.py) - Test suite
- [CF Benchmarks RTI Docs](https://www.cfbenchmarks.com/data/indices) - Settlement index documentation
