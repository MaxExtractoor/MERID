# Phase 4: Execution Layer and Kalshi Integration

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate API correctness, profile latency and slippage, and implement venue health dashboard

---

## Executive Summary

This document defines validation checks for the execution layer and Kalshi integration. All API interactions must be validated for correctness, latency must be profiled and monitored, slippage must be measured and bounded, and venue health must be continuously monitored via a dashboard.

---

## API Validation

### Requirement 1: API Version Tracking

**Statement:** Kalshi API version must be tracked and validated on startup.

**Current Implementation:**
- `KALSHI_API_VERSION` environment variable
- Base URL: `https://api.elections.kalshi.com/trade-api/v2`
- Version hardcoded in client URLs

**Validation:**
- API version must be set in environment variable
- Base URL must match expected version
- Log API version on startup
- Alert on version mismatch between runs

**Enforcement Point:** Startup validation, client initialization

**Violation Action:** Log warning, alert operator, prevent startup if critical mismatch

---

### Requirement 2: API Authentication Validation

**Statement:** API authentication must be validated before any trade execution.

**Current Implementation:**
- RSA private key signing in `client_v2.py`
- `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE` headers
- 5000ms timestamp buffer to prevent "header timestamp expired" errors

**Validation:**
- Private key must be loadable (file or PEM string)
- API key ID must be set
- Signature generation must succeed
- Authentication must succeed on `/portfolio/balance` call

**Thresholds:**
- Key file exists or PEM string provided
- Key is valid RSA private key
- Signature generation completes without error
- Balance call returns 200 OK

**Enforcement Point:** Client initialization, pre-trade check

**Violation Action:** Log error, alert operator, prevent trading if auth fails

---

### Requirement 3: API Endpoint Validation

**Statement:** All API endpoints must be validated for correct usage.

**Current Implementation:**
- `KalshiClientV2` implements: `get_balance`, `get_market`, `place_order`
- `KalshiExecutor` wraps order_router for API use
- Endpoints defined in client methods

**Validation:**
- All endpoints use correct HTTP method (GET/POST)
- All endpoints use correct path (including `/trade-api/v2` prefix)
- Request bodies match API schema
- Response parsing handles all expected fields

**Enforcement Point:** Unit tests, integration tests

**Violation Action:** Log error, alert operator, fix endpoint usage

---

### Requirement 4: API Response Validation

**Statement:** All API responses must be validated for correctness and completeness.

**Current Implementation:**
- `KalshiClientV2` returns explicit result types (Success/TemporaryError/PermanentError)
- No assertions on external data
- Graceful handling of missing fields

**Validation:**
- HTTP status code is 2xx for success
- Response body is valid JSON
- Required fields are present (no assertions, but logging)
- Values are within expected ranges
- Error responses are properly categorized

**Thresholds:**
- Status code 200-299 for success
- 4xx = client error (permanent)
- 5xx = server error (temporary)
- JSON parseable
- Required fields present

**Enforcement Point:** Client response handling, error categorization

**Violation Action:** Log error, categorize as temporary/permanent, alert if permanent

---

### Requirement 5: Rate Limit Compliance

**Statement:** API rate limits must be respected and self-monitored.

**Current Implementation:**
- `KalshiTokenBucket` implements token-bucket rate limiting
- Tier-based limits: Basic (20r/10w), Advanced (30/30), Premier (100/100), Prime (400/400)
- Self-limiting before hitting 429s

**Validation:**
- Token bucket refills at correct rate
- Tokens are consumed on each request
- Requests are blocked if tokens exhausted
- 429 responses are handled gracefully

**Thresholds:**
- Token bucket configured for correct tier
- Request rate < tier limit
- 429 responses < 1% of requests
- Backoff on 429 (exponential)

**Enforcement Point:** Token bucket, client retry logic

**Violation Action:** Log warning, backoff exponentially, alert if persistent

---

## Latency Profiling

### Requirement 1: End-to-End Latency Measurement

**Statement:** End-to-end latency from signal to fill must be measured and monitored.

**Current Implementation:**
- Latency tracking in `kalshi_robustness.py` (latency_ms_avg)
- Execution health tracking in `execution_diagnostics.py`
- Timestamps in fills_ledger (created_time, ingested_at)

**Validation:**
- Measure latency at each stage:
  - Signal generation → Order intent
  - Order intent → Order submission
  - Order submission → Order ack
  - Order ack → Fill
- Calculate p50, p95, p99 latencies
- Alert if latency exceeds threshold

**Thresholds:**
- Signal → Intent: < 100ms
- Intent → Submission: < 50ms
- Submission → Ack: < 500ms (network)
- Ack → Fill: < 2000ms (market)
- Total E2E: < 3000ms

**Enforcement Point:** Latency tracking at each stage, Prometheus metrics

**Violation Action:** Log warning, alert operator, investigate latency spike

---

### Requirement 2: API Call Latency Profiling

**Statement:** Individual API call latencies must be profiled and monitored.

**Current Implementation:**
- Latency tracking in `client_v2.py` (latency_ms in BalanceSuccess)
- `kalshi_robustness.py` tracks latency_ms_avg with EMA

**Validation:**
- Measure latency for each API endpoint:
  - `/portfolio/balance`
  - `/portfolio/positions`
  - `/portfolio/fills`
  - `/exchange/order`
  - `/exchange/order_cancel`
- Calculate p50, p95, p99 per endpoint
- Alert if latency exceeds threshold

**Thresholds:**
- Balance: < 500ms
- Positions: < 500ms
- Fills: < 1000ms
- Order: < 500ms
- Cancel: < 500ms

**Enforcement Point:** Client latency tracking, Prometheus metrics

**Violation Action:** Log warning, alert operator, investigate endpoint latency

---

### Requirement 3: WebSocket Latency Profiling

**Statement:** WebSocket message latency must be profiled and monitored.

**Current Implementation:**
- WebSocket implementation in `ws.py`, `ws_bridge.py`
- Event bus channels for price updates, fills, order updates

**Validation:**
- Measure latency from server event to client receipt
- Measure latency from client receipt to processing
- Calculate p50, p95, p99 latencies
- Alert if latency exceeds threshold

**Thresholds:**
- Server → Client: < 100ms
- Client → Processing: < 50ms
- Total WS latency: < 200ms

**Enforcement Point:** WebSocket latency tracking, Prometheus metrics

**Violation Action:** Log warning, alert operator, investigate WS connection

---

### Requirement 4: Event Loop Latency Profiling

**Statement:** Event loop latency must be monitored to detect blocking operations.

**Current Implementation:**
- Event loop monitoring in `loop_robustness.py`
- Loop lag kill switch in `risk/kill_switches.py`

**Validation:**
- Measure event loop lag (time between scheduled and actual execution)
- Alert if lag exceeds threshold
- Kill switch if lag exceeds critical threshold

**Thresholds:**
- Normal lag: < 10ms
- Warning: 10-50ms
- Critical: > 50ms (kill switch if enabled)

**Enforcement Point:** Event loop monitoring, kill switch

**Violation Action:** Log warning, alert operator, kill switch if critical

---

## Slippage Profiling

### Requirement 1: Entry Slippage Measurement

**Statement:** Entry slippage from intended price to fill price must be measured.

**Current Implementation:**
- Paper slippage config: `MERID_KALSHI_PAPER_SLIPPAGE_BPS` (default 8.0 bps)
- Slippage not explicitly tracked for live trades

**Validation:**
- Measure slippage for each fill:
  - `slippage_bps = (fill_price - intended_price) / intended_price * 10000`
- Calculate average slippage per asset
- Calculate p50, p95, p99 slippage
- Alert if slippage exceeds threshold

**Thresholds:**
- Average slippage: < 10 bps
- p95 slippage: < 20 bps
- p99 slippage: < 50 bps
- Alert threshold: 20 bps

**Enforcement Point:** Slippage tracking in fills_ledger, Prometheus metrics

**Violation Action:** Log warning, alert operator, investigate slippage spike

---

### Requirement 2: Exit Slippage Measurement

**Statement:** Exit slippage from intended exit price to fill price must be measured.

**Current Implementation:**
- Dynamic take profit engine computes exit targets
- Slippage not explicitly tracked for exits

**Validation:**
- Measure slippage for each exit fill:
  - `slippage_bps = (fill_price - intended_exit_price) / intended_exit_price * 10000`
- Calculate average slippage per asset
- Calculate p50, p95, p99 slippage
- Alert if slippage exceeds threshold

**Thresholds:**
- Average slippage: < 15 bps
- p95 slippage: < 30 bps
- p99 slippage: < 75 bps
- Alert threshold: 30 bps

**Enforcement Point:** Slippage tracking in fills_ledger, Prometheus metrics

**Violation Action:** Log warning, alert operator, investigate slippage spike

---

### Requirement 3: Paper vs Live Slippage Comparison

**Statement:** Paper slippage configuration must be validated against live slippage.

**Current Implementation:**
- Paper slippage: `MERID_KALSHI_PAPER_SLIPPAGE_BPS` (default 8.0 bps)
- Paper partial fill prob: `MERID_KALSHI_PAPER_PARTIAL_FILL_PROB` (default 0.35)

**Validation:**
- Compare live slippage with paper slippage config
- Adjust paper slippage if live slippage differs significantly
- Log comparison metrics

**Thresholds:**
- Live vs paper diff: < 5 bps
- Alert if diff > 10 bps
- Auto-adjust if diff > 20 bps

**Enforcement Point:** Weekly comparison job, config update

**Violation Action:** Log warning, alert operator, auto-adjust config

---

### Requirement 4: Partial Fill Profiling

**Statement:** Partial fill frequency and impact must be measured.

**Current Implementation:**
- Paper partial fill prob: `MERID_KALSHI_PAPER_PARTIAL_FILL_PROB` (default 0.35)
- Paper min fill ratio: `MERID_KALSHI_PAPER_MIN_FILL_RATIO` (default 0.4)

**Validation:**
- Measure partial fill frequency in live trades
- Measure fill ratio (filled / requested)
- Compare with paper config
- Alert if partial fill rate exceeds threshold

**Thresholds:**
- Partial fill rate: < 40%
- Average fill ratio: > 0.6
- Alert threshold: 50% partial fill rate

**Enforcement Point:** Fill tracking in fills_ledger, Prometheus metrics

**Violation Action:** Log warning, alert operator, adjust sizing logic

---

## Venue Health Dashboard

### Requirement 1: Health Status Aggregation

**Statement:** Venue health status must be aggregated from multiple sources.

**Current Implementation:**
- `KalshiHealthStatus` in `kalshi_robustness.py`
- `get_execution_health()` in `execution_diagnostics.py`
- Health checks: client, ws, order_manager, position_cache

**Validation:**
- Aggregate health from:
  - Client health (API connectivity)
  - WebSocket health (connection status)
  - Order manager health (order processing)
  - Position cache health (position sync)
  - Error budget status (P0/P1 error counts)
  - Latency metrics (p50, p95, p99)
  - Circuit breaker status

**Enforcement Point:** Health aggregation service, periodic health checks

**Violation Action:** Log degraded health, alert operator

---

### Requirement 2: Health Metrics Visualization

**Statement:** Health metrics must be visualized in a dashboard.

**Current Implementation:**
- Grafana dashboards in `monitoring/grafana-dashboards/`
- Prometheus metrics for various components

**Validation:**
- Dashboard must show:
  - Overall health status (green/yellow/red)
  - API latency (p50, p95, p99)
  - WebSocket latency (p50, p95, p99)
  - Error rates (P0, P1, P2, P3 per 100 fills)
  - Circuit breaker status
  - Rate limit utilization
  - Order success rate
  - Fill latency distribution

**Enforcement Point:** Grafana dashboard configuration

**Violation Action:** Log dashboard errors, alert if dashboard unavailable

---

### Requirement 3: Health Alerting

**Statement:** Health alerts must be triggered on degraded health.

**Current Implementation:**
- Alertmanager configuration in `alertmanager/alertmanager.yml`
- Telegram alerts for critical events

**Validation:**
- Alert on:
  - Health status degraded (yellow → red)
  - API latency > threshold
  - WebSocket disconnected
  - Circuit breaker open
  - Error rate > threshold
  - Order success rate < threshold
  - Fill latency > threshold

**Thresholds:**
- Health degraded: yellow status
- Health critical: red status
- API latency > 1s: alert
- WS disconnected: alert
- Circuit breaker open: alert
- Error rate > 5%: alert
- Order success rate < 95%: alert

**Enforcement Point:** Alertmanager rules, Prometheus alerting

**Violation Action:** Send alert (Telegram, email), log incident

---

### Requirement 4: Health Recovery Monitoring

**Statement:** Health recovery must be monitored and verified.

**Current Implementation:**
- Auto-reconnection in `kalshi_robustness.py`
- Circuit breaker recovery
- Health monitoring loop

**Validation:**
- Monitor health recovery:
  - Client reconnection success
  - WebSocket reconnection success
  - Circuit breaker reset
  - Error rate return to normal
  - Latency return to normal
- Verify recovery is stable (no flapping)

**Thresholds:**
- Recovery time: < 5 minutes
- Stable for: > 10 minutes after recovery
- Flap threshold: < 2 recoveries per hour

**Enforcement Point:** Health monitoring loop, recovery tracking

**Violation Action:** Log recovery, alert if recovery fails or flapping

---

## Automated Test Plan

### Test Suite: `tests/execution/test_execution_layer_and_kalshi_integration.py`

**Test Classes:**

1. `TestAPIValidation`
   - Test: API version tracking
   - Test: API authentication validation
   - Test: API endpoint validation
   - Test: API response validation
   - Test: Rate limit compliance

2. `TestLatencyProfiling`
   - Test: end-to-end latency measurement
   - Test: API call latency profiling
   - Test: WebSocket latency profiling
   - Test: event loop latency profiling
   - Test: latency threshold alerts

3. `TestSlippageProfiling`
   - Test: entry slippage measurement
   - Test: exit slippage measurement
   - Test: paper vs live slippage comparison
   - Test: partial fill profiling
   - Test: slippage threshold alerts

4. `TestVenueHealthDashboard`
   - Test: health status aggregation
   - Test: health metrics visualization
   - Test: health alerting
   - Test: health recovery monitoring
   - Test: dashboard availability

5. `TestKalshiClientV2`
   - Test: balance fetch success
   - Test: balance fetch temporary error
   - Test: balance fetch permanent error
   - Test: request signing
   - Test: timeout handling

6. `TestOrderRouter`
   - Test: order routing in mock mode
   - Test: order routing in paper mode
   - Test: order routing in live mode
   - Test: caller authorization
   - Test: block reason mapping

7. `TestExecutionQueue`
   - Test: queue submission
   - Test: queue rejection (risk)
   - Test: queue rejection (recon)
   - Test: queue rejection (state)
   - Test: queue processing

8. `TestFillsLedger`
   - Test: fill ingestion from HTTP
   - Test: fill ingestion from WS
   - Test: fill deduplication
   - Test: fill reconciliation
   - Test: fee validation

9. `TestKalshiRobustness`
   - Test: auto-reconnection
   - Test: circuit breaker integration
   - Test: health monitoring loop
   - Test: request deduplication
   - Test: graceful degradation

**Total Target:** 80+ execution layer tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify Kalshi client (client.py, client_v2.py)
- ✅ Identify execution queue (execution_queue.py)
- ✅ Identify executor (executors/kalshi.py)
- ✅ Identify robustness layer (kalshi_robustness.py)
- ✅ Identify fills ledger (fills_ledger.py)
- ✅ Document current implementation

### Step 2: Define Validation Checks (DONE)
- ✅ Define API validation requirements
- ✅ Define latency profiling requirements
- ✅ Define slippage profiling requirements
- ✅ Define venue health dashboard requirements

### Step 3: Implement API Validation Enhancements (NEXT)
- [ ] Add API version tracking to client
- [ ] Add authentication validation on startup
- [ ] Add endpoint validation tests
- [ ] Add response validation logging
- [ ] Add rate limit monitoring

### Step 4: Implement Latency Profiling
- [ ] Add E2E latency tracking
- [ ] Add API call latency profiling
- [ ] Add WebSocket latency profiling
- [ ] Add event loop latency profiling
- [ ] Add latency threshold alerts

### Step 5: Implement Slippage Profiling
- [ ] Add entry slippage measurement
- [ ] Add exit slippage measurement
- [ ] Add paper vs live comparison
- [ ] Add partial fill profiling
- [ ] Add slippage threshold alerts

### Step 6: Implement Venue Health Dashboard
- [ ] Create health aggregation service
- [ ] Configure Grafana dashboard
- [ ] Configure Alertmanager rules
- [ ] Add health recovery monitoring
- [ ] Add dashboard availability monitoring

### Step 7: Implement Test Suite
- [ ] Create `tests/execution/test_execution_layer_and_kalshi_integration.py`
- [ ] Implement all 9 test classes
- [ ] Target: 80+ tests passing
- [ ] Wire into CI pipeline

### Step 8: Add Monitoring and Alerting
- [ ] Add Prometheus metrics for execution
- [ ] Add alerting for latency spikes
- [ ] Add alerting for slippage spikes
- [ ] Add alerting for health degradation
- [ ] Add dashboard for venue health

---

## Success Criteria

Phase 4 is complete when:

1. ✅ This design document is approved
2. [ ] API validation is implemented and tested
3. [ ] Latency profiling is implemented and monitored
4. [ ] Slippage profiling is implemented and monitored
5. [ ] Venue health dashboard is deployed
6. [ ] All 80+ execution layer tests are implemented and passing
7. [ ] Monitoring and alerting are wired
8. [ ] CI pipeline includes execution layer test suite
9. [ ] No API errors detected in production
10. [ ] Latency and slippage within thresholds in production

---

## References

- `merid/event_venues/kalshi/client.py` - Kalshi REST client
- `merid/event_venues/kalshi/client_v2.py` - Kalshi client v2 with explicit result types
- `merid/execution/execution_queue.py` - Top-edge execution queue
- `merid/execution/executors/kalshi.py` - Kalshi executor
- `merid/event_venues/kalshi/kalshi_robustness.py` - Robustness layer
- `merid/event_venues/kalshi/execution_diagnostics.py` - Execution health diagnostics
- `merid/event_venues/kalshi/order_router.py` - Order router
- `merid/event_venues/kalshi/fills_ledger.py` - Canonical fills ledger
- `merid/event_venues/kalshi/ws.py` - WebSocket implementation
- `merid/event_venues/kalshi/ws_bridge.py` - WebSocket bridge
- Kalshi API Documentation (v2)
- Grafana Documentation
- Prometheus Documentation

---

**Next Phase:** Phase 5 - PnL, attribution, and performance truth (canonical PnL engine, reconciliation, strategy attribution)
