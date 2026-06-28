# Phase 3: High-Load Stress & End-to-End Validation

**Priority:** Medium (Gates Live Deployment)  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** Full system integration (WS bridge, trading agents, explainability, risk, observability)

## Summary

Validate MERID's Kalshi integration under production-like load with concurrent agents, high-frequency decisions, and end-to-end latency requirements. This phase gates live deployment.

## Acceptance Criteria

### 1. High-Load Explainability Stress Test

- [x] Spawn 10 concurrent agents (200 decisions each = 2K total)
- [x] Verify `ExplainabilityTracker` handles concurrent writes without data corruption
- [x] Assert no race conditions or lost decision records
- [x] Measure P99 latency for `record_decision` (target: <10ms) — verified
- [x] Verify memory usage stays bounded (history trim at max_history)

### 2. End-to-End Latency Validation

- [x] WS `_parse_message` latency validated: <5ms at P95
- [x] Explainability query latency: <20ms at P95
- [x] Decision stats latency: <50ms at P95 with 10k records
- [x] Sequence check throughput: >10k messages/sec
- [x] Full pipeline (WS parse → record → query) validated end-to-end

### 3. Full Kalshi Integration Suite

- [x] Mock mode integration validated (WS parse + tracker pipeline)
- [x] Concurrent pipeline: 5 agents, no cross-contamination
- [x] WS bridge handles all known message types (ticker, trade, orderbook)
- [x] Orderbook delta requires snapshot (validated)
- [x] Rate-limit self-throttling validated (Phase 2 tests)

**Commands:**
```bash
pytest tests/test_kalshi_deep_integration.py -v
pytest tests/event_venues/kalshi/ -v
pytest tests/prediction/ -k "kalshi" -v
```

### 4. Observability Validation

- [x] WS counters validated: messages_received, errors_received, reconnect_count
- [x] Sequence gap tracking: cumulative _seq_gaps counter
- [x] Decision stats surface per-type breakdown
- [x] Processing time recorded on every decision
- [x] Human-readable output format validated
- [x] Test alert triggers for:
  - WS disconnect/reconnect (reconnect counter verified)
  - Sequence gap detected (gap counter + cache invalidation)
  - Risk kill switch activated (blocks can_trade, reason captured, daily-loss auto-trigger, reset)
  - Swarm health degraded (IntegrityReport captured for alert routing)

### 5. Data Authenticity & Swarm Health

- [x] Empty ExplainabilityTracker returns [], never fabricated data
- [x] Empty tracker stats show 0 totals, not mocked numbers
- [x] Unknown agent query returns [], not fabricated decisions
- [x] Unknown decision_id returns None, not fabricated record
- [x] DecisionReasoning.to_dict() round-trips via JSON
- [x] IntegrityReport serialization: healthy + degraded states

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

- [x] All stress test scenarios pass (28/28 passed)
- [x] Performance targets met at P95/P99
- [x] No memory leaks or resource exhaustion under load
- [x] Full Kalshi integration suite passes in mock mode
- [x] Observability validated (counters, metrics, human-readable output)
- [x] Data authenticity and swarm health gates verified
- [x] CI green — added to `hardening-tests` job
- [ ] **Sign-off required before live deployment**
