# Phase 3: High-Load Stress & End-to-End Validation

**Priority:** Medium (Gates Live Deployment)  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** Full system integration (WS bridge, trading agents, explainability, risk, observability)

## Summary

Validate MERID's Kalshi integration under production-like load with concurrent agents, high-frequency decisions, and end-to-end latency requirements. This phase gates live deployment.

## Acceptance Criteria

### 1. High-Load Explainability Stress Test

- [ ] Spawn 10 concurrent `KalshiTradingAgent` instances
- [ ] Each agent emits 100 decisions/sec for 60 seconds (60K total decisions)
- [ ] Verify `ExplainabilityTracker` handles concurrent writes without data corruption
- [ ] Assert no race conditions or lost decision records
- [ ] Measure P99 latency for `_record_explainability_decision` (target: <10ms)
- [ ] Verify memory usage stays bounded (no leaks)

### 2. End-to-End Latency Validation

- [ ] Inject orderbook update via Kalshi WS mock
- [ ] Measure time from WS message receipt → agent decision → explainability record → API query result
- [ ] Target end-to-end latency: <100ms at P95
- [ ] Break down latency by component:
  - WS bridge event publishing: <5ms
  - Agent decision logic: <30ms
  - Explainability recording: <10ms
  - API query retrieval: <20ms
- [ ] Test under various load conditions (1x, 5x, 10x normal throughput)

### 3. Full Kalshi Integration Suite

- [ ] Run comprehensive test suite across all three modes:
  - Mock mode: All Kalshi API calls mocked
  - Paper mode: Simulated fills using real orderbook data
  - Live mode: Actual API integration (staging/testnet if available)
- [ ] Validate orderbook correctness: `yes_bid + no_bid <= 100 + ε`
- [ ] Test order routing with risk checks enabled
- [ ] Verify reconciliation between internal ledger and Kalshi portfolio API
- [ ] Confirm rate-limit self-throttling works under sustained load

**Commands:**
```bash
pytest tests/test_kalshi_deep_integration.py -v
pytest tests/event_venues/kalshi/ -v
pytest tests/prediction/ -k "kalshi" -v
```

### 4. Observability Validation

- [ ] Verify structured logs emitted for:
  - WS connection/reconnection events
  - Orderbook updates and sequence gaps
  - Trading decisions (allowed and blocked)
  - Risk rejections with specific rules
  - Explainability record creation
- [ ] Export metrics for:
  - WS latency (message receipt to event bus publish)
  - Orderbook freshness (time since last update)
  - Decision recording rate and latency
  - Risk rejection rate by rule type
  - API query latency (P50, P95, P99)
- [ ] Test alert triggers for:
  - WS disconnect/reconnect
  - Sequence gap detected
  - Risk kill switch activated
  - Swarm health degraded

### 5. Data Authenticity & Swarm Health

- [ ] Test `/api/v1/explainability/decisions` with empty `ExplainabilityTracker`
- [ ] Verify response returns empty list, never fabricated placeholder data
- [ ] Mock unavailable Kalshi portfolio API
- [ ] Assert no synthetic balances generated, clear error message returned
- [ ] Test trading agent with swarm health <100%
- [ ] Confirm orders blocked and explainability records capture health state

## Test File Location

`tests/integration/test_kalshi_e2e_stress.py`

## Performance Targets

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Decision recording latency (P99) | <10ms | <20ms |
| End-to-end latency (P95) | <100ms | <200ms |
| Concurrent agents | 10 | 5 minimum |
| Throughput | 1000 decisions/sec | 500 decisions/sec |
| Memory usage | <500MB delta | <1GB delta |
| WS reconnect time | <5s | <10s |

## Implementation Notes

- Use `pytest-benchmark` for performance measurements
- Use `asyncio.gather()` for concurrent agent spawning
- Mock Kalshi WS with realistic message timing (1-10ms intervals)
- Monitor system resources (CPU, memory) during stress tests
- Use profiling tools (cProfile, py-spy) to identify bottlenecks

## Definition of Done

- [ ] All stress test scenarios pass
- [ ] Performance targets met at P95/P99
- [ ] No memory leaks or resource exhaustion under load
- [ ] Full Kalshi integration suite passes in mock/paper modes
- [ ] Observability validated (logs, metrics, alerts)
- [ ] Data authenticity and swarm health gates verified
- [ ] CI green
- [ ] **Sign-off required before live deployment**
