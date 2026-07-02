# 15m Health Snapshot - Observability Layer

**Purpose:** Provides a structured health snapshot that mirrors the scenario categories tested in `tests/15m_scenario_tests/`, allowing production issues to be mapped back to tested scenarios.

**Last Updated:** 2026-06-05

---

## Overview

The 15m health snapshot is an observability layer that collects and exposes structured health metrics for the 15m Kalshi crypto stack. It is designed to:

1. **Mirror Scenario Tests:** The health snapshot structure directly corresponds to the scenario categories in `tests/15m_scenario_tests/` (WS, spot, book, risk, gates).

2. **Enable Production Debugging:** When something misbehaves in production, the health snapshot can be mapped to a specific scenario test, making it easier to understand and fix issues.

3. **Provide Structured Logging:** Health snapshots are logged in both human-readable and JSON formats for different use cases (quick checks vs. automated analysis).

4. **Expose via API:** Health snapshots are available via REST API endpoints for external monitoring systems.

---

## Architecture

### Components

1. **`merid/monitoring/health_snapshot.py`** - Core health snapshot module
   - Data classes for health metrics (WsHealth, SpotHealth, BookHealth, RiskHealth, GateDecision)
   - `HealthSnapshot` data class that aggregates all health metrics
   - `get_health_snapshot()` function to collect health from 15m components
   - `log_health_snapshot()` function for structured logging
   - `map_to_scenario()` method to map current health to scenario tests

2. **`web/api/health_snapshot_api.py`** - REST API endpoints
   - `GET /api/v1/health-snapshot/` - Full health snapshot
   - `GET /api/v1/health-snapshot/summary` - Human-readable summary
   - `GET /api/v1/health-snapshot/scenario` - Scenario mapping

3. **Integration in `main_15m_lean.py`** - Health snapshot router included in FastAPI app

---

## Health Metrics

### WebSocket Health (WsHealth)

| Metric | Type | Description |
|--------|------|-------------|
| `connection_state` | string | Current WS state: CONNECTED, DISCONNECTED, RECONNECTING |
| `latency_ms` | float | Current latency in milliseconds |
| `last_heartbeat_ts` | float | Unix timestamp of last heartbeat |
| `heartbeat_age_s` | float | Age of last heartbeat in seconds |
| `is_connected` | bool | Whether WS is currently connected |

**Scenario Mapping:**
- `connection_state == "DISCONNECTED"` → `test_ws_down_scenario`
- `latency_ms > 5000` → `test_ws_high_latency_scenario`
- `connection_state == "RECONNECTING"` → `test_ws_reconnect_scenario`

### Spot Health (SpotHealth)

| Metric | Type | Description |
|--------|------|-------------|
| `last_update_age_s` | float | Age of last spot update in seconds |
| `service_running` | bool | Whether spot service is running |
| `freshness_threshold_s` | float | Configured freshness threshold |
| `is_stale` | bool | Whether spot is considered stale (age > 60s) |
| `stale_reason` | string | Reason if stale (e.g., "age > 60s") |

**Scenario Mapping:**
- `is_stale == True` and `age > 60` → `test_spot_stale_scenario`
- `age >= 60` → `test_spot_boundary_60s_scenario`
- `age >= 30` → `test_spot_boundary_30s_scenario`
- `service_running == False` → `test_spot_service_restart_scenario`
- `age > 1000` → `test_spot_missing_scenario`

### Orderbook Health (BookHealth)

| Metric | Type | Description |
|--------|------|-------------|
| `book_consistency` | string | Book state: GOOD, SUSPECT |
| `suspect_reason` | string | Reason if SUSPECT (e.g., "queue_overflow") |
| `last_update_age_s` | float | Age of last book update in seconds |
| `has_bids` | bool | Whether book has bids |
| `has_asks` | bool | Whether book has asks |
| `is_dual_sided` | bool | Whether book is dual-sided |
| `best_bid_cents` | int | Best bid price in cents |
| `best_ask_cents` | int | Best ask price in cents |
| `spread_cents` | int | Spread in cents |
| `spread_pct` | float | Spread as percentage of mid |
| `is_stale` | bool | Whether book is considered stale (age > 10s) |

**Scenario Mapping:**
- `book_consistency == "SUSPECT"` and `suspect_reason == "queue_overflow"` → `test_suspect_book_queue_overflow_scenario`
- `book_consistency == "SUSPECT"` → `test_suspect_book_recovery_scenario`
- `is_dual_sided == False` and `has_bids == False` → `test_one_sided_book_no_bids_scenario`
- `is_dual_sided == False` and `has_asks == False` → `test_one_sided_book_no_asks_scenario`
- `is_stale == True` → `test_book_stale_scenario`
- `spread_pct > 10` → `test_wide_spread_scenario`

### Risk Health (RiskHealth)

| Metric | Type | Description |
|--------|------|-------------|
| `utilization_pct` | float | Risk budget utilization (0.0 to 1.0) |
| `has_capacity` | bool | Whether risk budget has capacity |
| `is_exhausted` | bool | Whether risk budget is exhausted |

**Scenario Mapping:**
- `is_exhausted == True` → `test_risk_budget_exhausted_scenario`

### Gate Decision (GateDecision)

| Metric | Type | Description |
|--------|------|-------------|
| `spot_age` | string | Spot age gate: PASS, FAIL |
| `book_freshness` | string | Book freshness gate: PASS, FAIL |
| `liquidity` | string | Liquidity gate: PASS, FAIL |
| `data_quality` | string | Data quality gate: PASS, FAIL |
| `edge` | string | Edge gate: PASS, FAIL |
| `risk` | string | Risk gate: PASS, FAIL |
| `overall` | string | Overall gate: PASS, REJECT |
| `reason` | string | Reason if REJECT |

**Scenario Mapping:**
- `overall == "REJECT"` and `reason == "spot_stale"` → `test_spot_stale_scenario`
- `overall == "REJECT"` and `reason == "book_stale"` → `test_book_stale_scenario`
- `overall == "REJECT"` and `reason == "insufficient_liquidity"` → `test_one_sided_book_no_bids_scenario`
- `overall == "REJECT"` and `reason == "book_suspect"` → `test_suspect_book_queue_overflow_scenario`
- `overall == "REJECT"` and `reason == "edge_insufficient"` → `test_wide_spread_scenario`
- `overall == "REJECT"` and `reason == "risk_budget_exhausted"` → `test_risk_budget_exhausted_scenario`

---

## Usage

### Collecting Health Snapshots

```python
from merid.monitoring.health_snapshot import get_health_snapshot, log_health_snapshot
from utils.logger import get_logger

logger = get_logger("15m_health")

# Collect health snapshot from 15m components
snapshot = get_health_snapshot(
    ws_bridge=ws_bridge,
    spot_service=spot_service,
    market_state_store=market_state_store,
    risk_env=risk_env,
    gate_decision=gate_decision,
)

# Log health snapshot
log_health_snapshot(snapshot, logger)
```

### Mapping to Scenario Tests

```python
# Map current health to a scenario test
scenario = snapshot.map_to_scenario()
if scenario:
    logger.info(f"[HEALTH-SCENARIO] Current state maps to: {scenario}")
else:
    logger.info("[HEALTH-SCENARIO] Current state does not map to a specific scenario")
```

### Accessing via API

```bash
# Get full health snapshot
curl http://localhost:8011/api/v1/health-snapshot/

# Get human-readable summary
curl http://localhost:8011/api/v1/health-snapshot/summary

# Get scenario mapping
curl http://localhost:8011/api/v1/health-snapshot/scenario
```

---

## Example Output

### Human-Readable Summary

```
[HEALTH-SNAPSHOT] 2026-06-05T20:30:00.123456Z
  WS: state=CONNECTED, latency=150ms, age=2s
  Spot: age=5s, stale=False
  Book: consistency=GOOD, dual_sided=True, age=1s
  Risk: utilization=30.0%, exhausted=False
  Gates: overall=PASS, reason=none
```

### JSON Snapshot

```json
{
  "timestamp": "2026-06-05T20:30:00.123456Z",
  "ws": {
    "connection_state": "CONNECTED",
    "latency_ms": 150.0,
    "heartbeat_age_s": 2.0,
    "is_connected": true
  },
  "spot": {
    "last_update_age_s": 5.0,
    "service_running": true,
    "is_stale": false,
    "stale_reason": null
  },
  "book": {
    "book_consistency": "GOOD",
    "suspect_reason": null,
    "last_update_age_s": 1.0,
    "is_dual_sided": true,
    "best_bid_cents": 99,
    "best_ask_cents": 101,
    "spread_cents": 2,
    "spread_pct": 2.0,
    "is_stale": false
  },
  "risk": {
    "utilization_pct": 0.3,
    "has_capacity": true,
    "is_exhausted": false
  },
  "gates": {
    "spot_age": "PASS",
    "book_freshness": "PASS",
    "liquidity": "PASS",
    "data_quality": "PASS",
    "edge": "PASS",
    "risk": "PASS",
    "overall": "PASS",
    "reason": null
  }
}
```

### Scenario Mapping

```
[HEALTH-SCENARIO-MAP] Current state maps to scenario: test_dual_sided_book_good_edge_scenario
```

---

## Integration with 15m Loop

To integrate health snapshot collection into the 15m loop:

```python
# In merid/loop_15m.py Kalshi15mLoop.run_cycle()

async def run_cycle(self):
    # ... existing cycle logic ...
    
    # Collect and log health snapshot
    snapshot = get_health_snapshot(
        ws_bridge=self.ws_bridge,
        spot_service=self.spot_service,
        market_state_store=self.market_state_store,
        risk_env=self.risk_env,
        gate_decision=self.gate_decision,
    )
    log_health_snapshot(snapshot, self.logger)
    
    # ... continue with cycle logic ...
```

---

## Monitoring and Alerting

### Prometheus Metrics (Future Enhancement)

The health snapshot can be extended to export Prometheus metrics:

```python
from prometheus_client import Gauge

# Define metrics
ws_latency = Gauge('merid_15m_ws_latency_ms', 'WebSocket latency in milliseconds')
spot_age = Gauge('merid_15m_spot_age_s', 'Spot age in seconds')
book_consistency = Gauge('merid_15m_book_consistency', 'Book consistency (0=SUSPECT, 1=GOOD)')
risk_utilization = Gauge('merid_15m_risk_utilization', 'Risk budget utilization')

# Update metrics from health snapshot
ws_latency.set(snapshot.ws.latency_ms)
spot_age.set(snapshot.spot.last_update_age_s)
book_consistency.set(1 if snapshot.book.book_consistency == "GOOD" else 0)
risk_utilization.set(snapshot.risk.utilization_pct)
```

### Alerting Rules (Future Enhancement)

Example Prometheus alerting rules:

```yaml
groups:
  - name: merid_15m_alerts
    rules:
      - alert: Merid15mWsDown
        expr: merid_15m_ws_latency_ms == 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "15m WebSocket is down"
          scenario: "test_ws_down_scenario"
      
      - alert: Merid15mSpotStale
        expr: merid_15m_spot_age_s > 60
        for: 10s
        labels:
          severity: warning
        annotations:
          summary: "15m spot data is stale"
          scenario: "test_spot_stale_scenario"
      
      - alert: Merid15mBookSuspect
        expr: merid_15m_book_consistency == 0
        for: 5s
        labels:
          severity: warning
        annotations:
          summary: "15m orderbook is SUSPECT"
          scenario: "test_suspect_book_queue_overflow_scenario"
```

---

## Troubleshooting

### Health Snapshot Returns Unknown Values

**Issue:** Health snapshot shows "UNKNOWN" for some metrics.

**Solution:** Ensure the 15m components (ws_bridge, spot_service, market_state_store, risk_env) are properly initialized and attached to app.state before collecting health snapshots.

### Scenario Mapping Returns None

**Issue:** `map_to_scenario()` returns None even when health is degraded.

**Solution:** The mapping logic is conservative and only maps to scenarios when conditions closely match the test setup. Review the `map_to_scenario()` method in `health_snapshot.py` to adjust mapping thresholds if needed.

### API Endpoint Returns 503

**Issue:** `/api/v1/health-snapshot/` returns 503 Service Unavailable.

**Solution:** The health snapshot API is not yet fully integrated with app.state. The endpoint is a placeholder that needs to be completed by collecting components from app.state and calling `get_health_snapshot()`.

---

## Future Enhancements

1. **Full API Integration:** Complete the health snapshot API endpoints to collect health from app.state components.

2. **Prometheus Metrics:** Export health snapshot metrics to Prometheus for monitoring dashboards.

3. **Alerting Integration:** Create alerting rules based on health snapshot metrics and scenario mappings.

4. **Historical Tracking:** Store health snapshots in a time-series database for trend analysis.

5. **Automated Scenario Testing:** Use health snapshot data to automatically trigger scenario tests when conditions match.

6. **Health Dashboard:** Create a web dashboard that visualizes health snapshot data over time.

---

## Related Documentation

- `docs/kalshi_15m_stack.md` - Canonical 15m stack definition
- `tests/15m_scenario_tests.md` - Scenario test design document
- `tests/15m_scenario_tests/README.md` - Scenario test suite documentation
- `scripts/validate_15m_stack.py` - CI validation script for 15m stack

---

**End of 15m Health Snapshot Documentation**
