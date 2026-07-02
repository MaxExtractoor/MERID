# 15m Live Telemetry Probe

**Purpose:** Monitor the 15m stack in real-time, validate each layer's metrics against codified expectations, and log anomalies if anything deviates from the tested behavior.

**Runtime Mode:** Runs under `MERID_RUNTIME_MODE=15m_live`.

---

## Overview

The live telemetry probe (`merid/monitoring/live_15m_end_to_end_probe.py`) is a lightweight Python script that runs alongside the 15m stack, periodically fetching health snapshots from the API and validating them against expectations defined in the scenario tests and health snapshot documentation.

**Key Features:**
- Periodic health snapshot polling (default: 5 seconds)
- Validation of WS, spot, orderbook, risk, and gate metrics
- Cross-layer consistency checks
- Anomaly logging with explicit tags for filtering and alerting
- JSON snapshot export for offline analysis
- Scenario mapping to correlate live state with tested scenarios

---

## What the Probe Checks

### 1. WebSocket Health

**Metrics:**
- `connection_state` - Expected: CONNECTED
- `is_connected` - Expected: True
- `latency_ms` - Threshold: < 5000ms (5 seconds)
- `heartbeat_age_s` - Threshold: < 10s

**Anomalies:**
- `ws_state` - Connection state not CONNECTED
- `ws_connected` - Not connected
- `ws_latency` - Latency exceeds threshold
- `ws_heartbeat_age` - Heartbeat age exceeds threshold

---

### 2. Spot Service Health

**Metrics:**
- `service_running` - Expected: True
- `is_stale` - Expected: False
- `last_update_age_s` - Warning threshold: < 30s, Critical threshold: < 60s

**Anomalies:**
- `spot_running` - Service not running
- `spot_stale` - Spot is stale
- `spot_age` - Age exceeds warning threshold
- `spot_age_critical` - Age exceeds critical threshold

---

### 3. Orderbook Health

**Metrics:**
- `book_consistency` - Expected: GOOD
- `is_stale` - Expected: False
- `last_update_age_s` - Threshold: < 10s
- `is_dual_sided` - Expected: True
- `spread_pct` - Warning threshold: < 10%

**Anomalies:**
- `book_consistency` - Consistency not GOOD (e.g., SUSPECT)
- `book_stale` - Book is stale
- `book_age` - Age exceeds threshold
- `book_dual_sided` - Not dual-sided
- `book_spread` - Spread exceeds threshold

---

### 4. Risk Environment Health

**Metrics:**
- `has_capacity` - Expected: True
- `is_exhausted` - Expected: False
- `utilization_pct` - Threshold: < 95%

**Anomalies:**
- `risk_capacity` - No capacity
- `risk_exhausted` - Risk budget exhausted
- `risk_utilization` - Utilization exceeds threshold

---

### 5. Gate Decisions

**Metrics:**
- `overall` - Expected: PASS
- `spot_age` - Expected: PASS
- `book_freshness` - Expected: PASS
- `liquidity` - Expected: PASS
- `data_quality` - Expected: PASS
- `edge` - Expected: PASS
- `risk` - Expected: PASS

**Anomalies:**
- `gate_overall` - Overall gate not PASS
- `gate_spot_age` - Spot age gate not PASS
- `gate_book_freshness` - Book freshness gate not PASS
- `gate_liquidity` - Liquidity gate not PASS
- `gate_data_quality` - Data quality gate not PASS
- `gate_edge` - Edge gate not PASS
- `gate_risk` - Risk gate not PASS

---

### 6. Cross-Layer Consistency

**Checks:**
- If WS is disconnected, spot and book should be stale
- If book is SUSPECT, data quality gate should fail

**Anomalies:**
- `consistency_ws_spot` - WS disconnected but spot not stale
- `consistency_ws_book` - WS disconnected but book not stale
- `consistency_book_gate` - Book SUSPECT but data quality gate PASS

---

## Installation

The probe is part of the MERID codebase and requires no additional dependencies beyond the standard library and `requests`.

**Dependencies:**
- Python 3.8+
- `requests` (for HTTP requests to health snapshot API)

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MERID_HEALTH_SNAPSHOT_URL` | `http://127.0.0.1:8011/api/v1/health-snapshot/` | Health snapshot API endpoint |
| `MERID_RUNTIME_MODE` | `15m_live` | Runtime mode (auto-set by probe) |
| `MERID_PROBE_OUTPUT_DIR` | `./probe_snapshots` | Directory for JSON snapshot exports |

### Thresholds

Thresholds are defined in the probe script and can be adjusted as needed:

```python
MAX_WS_LATENCY_MS = 5000.0  # 5 seconds
MAX_WS_HEARTBEAT_AGE_S = 10.0  # 10 seconds
MAX_SPOT_AGE_S = 30.0  # 30 seconds
MAX_SPOT_STALE_AGE_S = 60.0  # 60 seconds (hard fail)
MAX_BOOK_AGE_S = 10.0  # 10 seconds
MAX_SPREAD_PCT = 10.0  # 10% spread
MAX_RISK_UTILIZATION_PCT = 0.95  # 95% utilization
```

### Monitor Interval

Default polling interval is 5 seconds. Adjust in the script:

```python
MONITOR_INTERVAL = 5.0  # seconds
```

---

## Usage

### Starting the 15m Stack

First, start the 15m stack with your usual command:

```powershell
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

### Starting the Probe

In a separate shell, start the probe:

```powershell
CD C:\Dev\MERID
python -m merid.monitoring.live_15m_end_to_end_probe
```

### Expected Output

The probe will log periodic health checks:

```
2026-06-05 16:00:00 - merid.monitoring.live_15m_probe - INFO - [15M-PROBE] Starting live end-to-end probe
2026-06-05 16:00:00 - merid.monitoring.live_15m_probe - INFO - [15M-PROBE] Health URL: http://127.0.0.1:8011/api/v1/health-snapshot/
2026-06-05 16:00:00 - merid.monitoring.live_15m_probe - INFO - [15M-PROBE] Monitor interval: 5.0s
2026-06-05 16:00:00 - merid.monitoring.live_15m_probe - INFO - [15M-PROBE] Iteration 1 at 2026-06-05T16:00:00
2026-06-05 16:00:00 - merid.monitoring.live_15m_probe - INFO - [15M-PROBE] Current state maps to scenario: test_dual_sided_book_good_edge_scenario
2026-06-05 16:00:05 - merid.monitoring.live_15m_probe - INFO - [15M-PROBE] Iteration 2 at 2026-06-05T16:00:05
```

### Anomaly Logging

If anomalies are detected, they are logged with explicit tags:

```
2026-06-05 16:01:00 - merid.monitoring.live_15m_probe - ERROR - [15M-PROBE-ANOMALY] type=spot_age actual=35.2s threshold=30.0s
2026-06-05 16:01:00 - merid.monitoring.live_15m_probe - ERROR - [15M-PROBE-ANOMALY] type=book_consistency expected=GOOD actual=SUSPECT reason=queue_overflow
2026-06-05 16:01:00 - merid.monitoring.live_15m_probe - ERROR - [15M-PROBE-ANOMALY] type=gate_overall expected=PASS actual=REJECT reason=book_suspect
```

---

## Soak Testing

Run the probe for 30-60 minutes to validate the 15m stack under live conditions:

1. Start the 15m stack in paper trading mode
2. Start the probe
3. Monitor for anomalies
4. Review JSON snapshots for offline analysis

### Interpreting Anomalies

**Recurring Anomalies:**
- If you see recurring anomalies (e.g., spot age spikes, WS age spikes, books flipping to SUSPECT), these are bugs to investigate.

**Mapping to Scenarios:**
- Cross-reference anomaly types with scenario tests:
  - `spot_age` → `test_spot_stale_scenario`
  - `book_consistency` → `test_suspect_book_queue_overflow_scenario`
  - `ws_latency` → `test_ws_high_latency_scenario`

**Go/No-Go Checklist:**
- Check if anomalies trigger emergency stop criteria in the go/no-go checklist

---

## JSON Snapshots

The probe writes JSON snapshots to disk for offline analysis:

**Location:** `./probe_snapshots/` (configurable via `MERID_PROBE_OUTPUT_DIR`)

**Filename Format:** `probe_snapshot_YYYY-MM-DDTHH-MM-SS.json`

**Example:**
```json
{
  "timestamp": "2026-06-05T16:00:00",
  "ws": {
    "connection_state": "CONNECTED",
    "latency_ms": 150.0,
    "heartbeat_age_s": 0.5,
    "is_connected": true
  },
  "spot": {
    "last_update_age_s": 5.0,
    "service_running": true,
    "is_stale": false
  },
  "book": {
    "book_consistency": "GOOD",
    "last_update_age_s": 1.0,
    "is_dual_sided": true,
    "spread_pct": 2.5
  },
  "risk": {
    "utilization_pct": 0.3,
    "has_capacity": true,
    "is_exhausted": false
  },
  "gates": {
    "overall": "PASS",
    "spot_age": "PASS",
    "book_freshness": "PASS",
    "liquidity": "PASS",
    "data_quality": "PASS",
    "edge": "PASS",
    "risk": "PASS"
  }
}
```

---

## Integration with Control System

The live telemetry probe completes the control system:

- **Spec** - 15m stack definition, scenario design, trade path definitions, go/no-go checklist
- **Tests** - Scenario + trade path suites under `MERID_RUNTIME_MODE=15m_live`
- **Observability** - Health snapshot and API
- **Guardrails** - Runtime + CI
- **Live Probe** - Real-time validation of live health snapshots

---

## Alerting

### Log Filtering

Filter logs for anomalies:

```bash
# Filter for anomalies
python -m merid.monitoring.live_15m_end_to_end_probe 2>&1 | grep "15M-PROBE-ANOMALY"

# Filter for specific anomaly type
python -m merid.monitoring.live_15m_end_to_end_probe 2>&1 | grep "type=spot_age"
```

### External Alerting

Integrate with external alerting systems (e.g., PagerDuty, Slack, email) by:

1. Parsing anomaly logs
2. Triggering alerts based on anomaly type and severity
3. Including context (timestamp, metric values, thresholds)

---

## Troubleshooting

### Probe Cannot Connect to Health API

**Issue:** Probe fails to fetch health snapshot.

**Solution:**
- Verify 15m stack is running
- Check health API endpoint URL (`MERID_HEALTH_SNAPSHOT_URL`)
- Verify port is correct (default: 8011)

### False Positive Anomalies

**Issue:** Probe logs anomalies that are expected or benign.

**Solution:**
- Adjust thresholds in the probe script
- Add exception logic for known benign conditions
- Document the exception in this documentation

### High CPU Usage

**Issue:** Probe consumes too much CPU.

**Solution:**
- Increase monitor interval (`MONITOR_INTERVAL`)
- Disable JSON snapshot exports (comment out `write_snapshot_json`)

---

## Future Enhancements

- Add per-asset monitoring (BTC, ETH, SOL, XRP, DOGE)
- Add historical trend analysis
- Add anomaly severity levels (warning, error, critical)
- Add automatic recovery actions for specific anomalies
- Add integration with Prometheus metrics
- Add dashboard visualization

---

## Related Documentation

- `docs/kalshi_15m_stack.md` - Canonical 15m stack definition
- `docs/15m_health_snapshot.md` - Health snapshot documentation
- `docs/15m_go_no_go_checklist.md` - Go/no-go checklist
- `tests/15m_scenario_tests/README.md` - Scenario test documentation
- `tests/15m_trade_path_tests/README.md` - Trade path test documentation
- `merid/monitoring/health_snapshot.py` - Health snapshot implementation
- `web/api/health_snapshot_api.py` - Health snapshot API

---

**End of Live Telemetry Probe Documentation**
