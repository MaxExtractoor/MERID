# MERID Kalshi Integration - Swarm Alignment Deep Audit & Implementation Plan

**Generated:** 2026-03-26
**Purpose:** Operationalize the theoretical audit findings into executable improvements that ensure swarm intelligence coherence

---

## Executive Summary

This plan translates the theoretical audit findings from `KALSHI_INTEGRATION_DEEP_AUDIT_REPORT.md` into concrete implementations that will ensure the MERID swarm operates as a unified intelligence system. The focus is on **actionable code changes** that improve swarm alignment across all 8 phases.

### Critical Implementation Priorities

Based on the audit, we will implement:

1. **DISCOVER Phase** - Schema validation, SLA tracking, new market detection
2. **ANALYZE Phase** - Timestamp validation, drift detection, clock sync monitoring
3. **CONSENSUS Phase** - Anti-herding protection, cache synchronization, track-record weighting
4. **SIZE Phase** - Kelly safety checks, concurrent access protection, dynamic fee schedule
5. **EXECUTE Phase** - Rate limiting enforcement, idempotency keys, P99 latency tracking
6. **MONITOR Phase** - WebSocket gap recovery, fee attribution, alert deduplication
7. **PROMOTE Phase** - Canary deployments, track-record decay, shadow mode caps
8. **PROTECT Phase** - Distributed kill switch, agent circuit breakers, audit logging

---

## Phase 1: DISCOVER - Implementation Plan

### 1.1 Schema Validation (Finding D-001) ✅

**File:** `merid/event_venues/kalshi/discovery_validator.py` (NEW)

**Implementation:**
```python
class DiscoveryValidator:
    """Validates market discovery data and tracks discovery health."""

    def validate_market_schema(self, raw_market: dict) -> Optional[ValidatedMarket]
    def track_discovery_sla(self, latency_ms: float) -> None
    def detect_new_markets(self, current: List[Market], previous: List[Market]) -> List[Market]
```

**Success Criteria:**
- All malformed markets rejected with logged warnings
- P95 discovery latency < 3s, P99 < 5s
- New market detection within 30 seconds of Kalshi listing

### 1.2 Market Catalog Enhancement

**File:** `merid/event_venues/kalshi/market_catalog.py` (MODIFY)

**Changes:**
- Add Pydantic schema validation before enrichment
- Implement timeout enforcement (15s hard limit)
- Add P95/P99 latency metrics
- Persist catalog snapshots for failover

---

## Phase 2: ANALYZE - Implementation Plan

### 2.1 Timestamp Validation (Finding A-001) ✅

**File:** `merid/event_venues/kalshi/analysis_validator.py` (NEW)

**Implementation:**
```python
class AnalysisValidator:
    """Validates analysis inputs and detects data staleness."""

    def validate_sentiment_freshness(self, context: SentimentContext) -> bool
    def detect_feature_drift(self, features: dict) -> DriftReport
    def monitor_clock_skew(self) -> float
```

**Success Criteria:**
- Stale sentiment (>5min old) rejected before trading
- Feature drift detected within 1 batch cycle
- Clock skew < 500ms enforced

---

## Phase 3: CONSENSUS - Implementation Plan

### 3.1 Anti-Herding Protection (Finding C-001) ✅ CRITICAL

**File:** `merid/swarm/consensus_aggregator.py` (MODIFY)

**Implementation:**
```python
def _detect_herding(self, proposals: List[AgentProposal]) -> tuple[bool, float]:
    """Detect excessive agent convergence using entropy analysis."""

def _apply_herding_penalty(self, consensus: ConsensusView, herding_score: float) -> ConsensusView:
    """Apply confidence penalty and reduce size band when herding detected."""
```

**Success Criteria:**
- Herding detected when proposal variance < 5%
- Confidence penalty up to 50% applied
- Size band reduced when herding detected

### 3.2 Consensus Cache Synchronization (Finding C-002) ✅ CRITICAL

**File:** `merid/swarm/consensus_aggregator.py` (MODIFY)

**Changes:**
- Add `asyncio.Lock()` to protect `_consensus_cache` writes
- Add lock acquisition metrics
- Add contention monitoring

---

## Phase 4: SIZE - Implementation Plan

### 4.1 Kelly Safety Checks (Finding S-001) ✅ CRITICAL

**File:** `merid/event_venues/kalshi/position_sizer.py` (MODIFY)

**Implementation:**
```python
def kelly_fraction_for_binary(win_prob: float, win_payout: float, loss_amount: float) -> float:
    """Compute Kelly fraction with division-by-zero protection."""

    if loss_amount <= 0:
        logger.warning(f"Invalid loss_amount={loss_amount}, returning 0")
        return 0.0
    if win_payout <= 0:
        logger.warning(f"Invalid win_payout={win_payout}, returning 0")
        return 0.0

    # Proceed with calculation...
```

**Success Criteria:**
- No division-by-zero crashes
- Edge cases logged and handled gracefully
- Position sizing always returns valid size >= 0

### 4.2 Domain Cap Synchronization (Finding S-002) ✅ CRITICAL

**File:** `merid/execution_guard.py` (MODIFY)

**Implementation:**
- Add `asyncio.Lock()` to `DomainCap.record_trade()`
- Add concurrent access tests
- Monitor lock contention

---

## Phase 5: EXECUTE - Implementation Plan

### 5.1 Rate Limit Enforcement (Finding E-001) ✅ CRITICAL

**File:** `merid/event_venues/kalshi/client.py` (MODIFY)

**Implementation:**
```python
async def _ensure_rate_limit(self, is_write: bool = False):
    """Enforce rate limiting on ALL endpoints."""
    await self._rate_limiter.acquire(is_write=is_write)

# Apply to all methods
async def get_positions(self):
    await self._ensure_rate_limit(is_write=False)
    # ... rest of method
```

**Success Criteria:**
- Zero 429 errors in production
- Rate limit headroom tracked per endpoint
- Write operations prioritized over reads

### 5.2 Idempotency Keys (Finding E-002) ✅ CRITICAL

**File:** `merid/event_venues/kalshi/client.py` (MODIFY)

**Implementation:**
- Track in-flight orders by client_order_id
- Cache completed orders for 24h TTL
- Check Kalshi API on timeout to detect silent fills
- Prevent duplicate order submission

---

## Phase 6: MONITOR - Implementation Plan

### 6.1 WebSocket Gap Recovery (Finding M-001) ✅ CRITICAL

**File:** `merid/event_venues/kalshi/ws.py` (MODIFY)

**Implementation:**
```python
async def _handle_gap(self, expected_seq: int, received_seq: int):
    """Force full position reload on sequence gap."""

    logger.error(f"WS gap detected: {received_seq - expected_seq} messages")

    # Force resubscribe
    await self.unsubscribe_all()
    await asyncio.sleep(1.0)
    await self.subscribe_all()

    # Force position cache refresh
    from merid.event_venues.kalshi.position_cache import get_position_cache
    await get_position_cache().force_refresh()
```

**Success Criteria:**
- Position desync prevented after gaps
- Full recovery within 2 seconds
- Gap events tracked in metrics

### 6.2 Partial Fill Fee Tracking (Finding M-002) ✅

**File:** `merid/event_venues/kalshi/trade_analytics.py` (MODIFY)

**Implementation:**
- Track fees per fill increment
- Aggregate total fees per position
- Compute accurate realized P&L

---

## Phase 7: PROMOTE - Implementation Plan

### 7.1 Canary Deployment (Finding P-001) ✅ CRITICAL

**File:** `merid/event_venues/kalshi/deployment.py` (MODIFY)

**Implementation:**
```python
async def promote_with_canary(self, agent_name: str, new_version: str):
    """Deploy to 10% of markets, monitor, then full rollout."""

    # Phase 1: 10% canary
    canary_markets = self._select_canary_markets(agent_name, pct=0.10)
    # Deploy and monitor for 1 hour

    # Phase 2: Compare performance
    if canary_pf < baseline_pf * 0.9:
        self._rollback_canary(agent_name)
    else:
        self._promote_full(agent_name, new_version)
```

**Success Criteria:**
- Canary rollout prevents bad deployments
- Automatic rollback on performance degradation
- Full deployment only after successful canary

### 7.2 Track-Record Decay (Finding P-002) ✅

**File:** `merid/swarm/consensus_aggregator.py` (MODIFY)

**Implementation:**
- Weight recent performance (last 30d) at 70%
- Weight all-time performance at 30%
- Cap maximum agent weight at 40%

---

## Phase 8: PROTECT - Implementation Plan

### 8.1 Distributed Kill Switch (Finding PR-001) ✅ CRITICAL

**File:** `merid/execution_guard.py` (MODIFY)

**Implementation:**
```python
# Use Redis for distributed kill switch state
import redis

class ExecutionGuard:
    def __init__(self):
        self._redis = redis.from_url(os.getenv("REDIS_URL"))

    def activate_kill_switch(self, reason: str):
        self._redis.set("kill_switch:active", "1", ex=86400)
        self._redis.set("kill_switch:reason", reason)

    @property
    def kill_switch_active(self) -> bool:
        return self._redis.get("kill_switch:active") == b"1"
```

**Success Criteria:**
- Kill switch propagates across all instances within 100ms
- State persists across restarts
- Reason tracked in audit log

### 8.2 Agent Circuit Breakers (Finding PR-002) ✅ CRITICAL

**File:** `merid/swarm/agent_circuit_breaker.py` (NEW)

**Implementation:**
```python
class AgentCircuitBreaker:
    """Per-agent circuit breaker to isolate failures."""

    def record_error(self):
        """Track errors and open circuit after threshold."""

    def is_open(self) -> bool:
        """Check if agent should be halted."""
```

**Success Criteria:**
- Bad agents isolated within 5 errors
- Other agents continue operating
- Circuit auto-resets after 5min cooldown

---

## Validation Metrics & KPIs

### Discovery Phase Metrics

```python
# Catalog health
kalshi_catalog_refresh_latency_ms {p50, p95, p99}  # Target: p95 < 3000ms
kalshi_catalog_invalid_markets_total  # Target: 0
kalshi_catalog_new_markets_detected_total  # Rate of discovery

# WebSocket health
kalshi_ws_lag_ms {p99}  # Target: < 500ms
kalshi_ws_sequence_gaps_total  # Target: 0
```

### Consensus Phase Metrics

```python
# Anti-herding
kalshi_consensus_herding_detected_total  # Target: < 5% of formations
kalshi_consensus_herding_score {asset, timeframe}  # 0-1 scale

# Cache contention
kalshi_consensus_cache_lock_wait_ms {p95}  # Target: < 10ms
kalshi_consensus_cache_conflicts_total  # Target: 0
```

### Execution Phase Metrics

```python
# Rate limiting
kalshi_rate_limit_429_errors_total  # Target: 0
kalshi_rate_limiter_tokens_available {type}  # Monitor headroom

# Idempotency
kalshi_duplicate_order_prevented_total  # Count of prevented duplicates
kalshi_order_status_checks_total  # Timeout recovery attempts

# Latency
kalshi_order_placement_latency_ms {p50, p95, p99}  # Target: p99 < 2000ms
```

### Protection Phase Metrics

```python
# Kill switch
kalshi_kill_switch_active  # 0=inactive, 1=active
kalshi_kill_switch_propagation_ms {p95}  # Target: < 100ms

# Agent isolation
kalshi_agent_circuit_breaker_opens_total {agent_id}  # Per-agent failures
kalshi_agent_isolated_count  # Currently isolated agents
```

---

## Implementation Timeline

### Sprint 1 (Week 1-2): Critical P0 Fixes

**Priority:** Prevent catastrophic failures

1. ✅ Schema validation (D-001)
2. ✅ Anti-herding protection (C-001)
3. ✅ Consensus cache locks (C-002)
4. ✅ Kelly safety checks (S-001)
5. ✅ Domain cap locks (S-002)
6. ✅ Rate limit enforcement (E-001)
7. ✅ Idempotency keys (E-002)
8. ✅ WebSocket gap recovery (M-001)
9. ✅ Distributed kill switch (PR-001)
10. ✅ Agent circuit breakers (PR-002)

**Estimated Effort:** 20 engineering days (2 engineers × 2 weeks)

### Sprint 2 (Week 3-4): High P0 + Critical P1

**Priority:** Operational excellence

1. Timestamp validation (A-001)
2. Feature drift detection (A-002)
3. Clock skew monitoring (A-003)
4. Track-record decay (P-002)
5. Canary deployment (P-001)
6. P99 latency tracking (E-003)
7. Partial fill fee tracking (M-002)

**Estimated Effort:** 21 engineering days

### Sprint 3 (Week 5-6): Medium P1 Fixes

**Priority:** Performance and resilience

1. Discovery SLA tracking (D-002)
2. New market detection (D-003)
3. Dynamic fee schedule (S-003)
4. Alert deduplication (M-003)
5. Shadow mode caps (P-003)

**Estimated Effort:** 15 engineering days

### Sprint 4 (Week 7-8): Observability & Testing

**Priority:** Validation and monitoring

1. Comprehensive metrics implementation
2. Grafana dashboards
3. Prometheus alert rules
4. Integration test suite
5. Chaos engineering tests

**Estimated Effort:** 20 engineering days

---

## Testing Strategy

### Unit Tests (Target: 90% Coverage)

- Schema validation edge cases
- Kelly formula boundary conditions
- Herding detection algorithm
- Idempotency key management
- Circuit breaker state transitions

### Integration Tests

- Full trade lifecycle (discover → execute → monitor)
- Consensus formation under contention
- WebSocket gap recovery
- Kill switch propagation
- Agent isolation

### Chaos Engineering Tests

- Kalshi API degradation (500ms latency, 503 errors)
- Clock skew simulation (±5min drift)
- Race condition stress (10 concurrent agents)
- Network partition simulation
- Redis failover testing

---

## Success Criteria

### Phase-by-Phase Alignment Checks

**DISCOVER:**
- ✅ 100% schema validation coverage
- ✅ P95 discovery latency < 3s
- ✅ Zero uncategorized markets

**ANALYZE:**
- ✅ 100% timestamp validation
- ✅ Feature drift detected within 1 cycle
- ✅ Clock skew < 500ms

**CONSENSUS:**
- ✅ Herding detected at >70% convergence
- ✅ Zero cache race conditions
- ✅ Track-record weights capped at 40%

**SIZE:**
- ✅ Zero Kelly crashes
- ✅ Zero domain cap breaches
- ✅ Fee calculations accurate within 1¢

**EXECUTE:**
- ✅ Zero 429 rate limit errors
- ✅ Zero duplicate orders
- ✅ P99 execution latency < 2s

**MONITOR:**
- ✅ Zero position desyncs
- ✅ 100% fee attribution accuracy
- ✅ Alert deduplication working

**PROMOTE:**
- ✅ 100% canary rollout success
- ✅ Track-record decay applied
- ✅ Shadow mode losses capped

**PROTECT:**
- ✅ Kill switch propagates in <100ms
- ✅ Bad agents isolated in <5 errors
- ✅ Audit trail immutable

---

## Deliverables

1. **Code Implementations:** All P0 and critical P1 findings remediated
2. **Metrics Framework:** Prometheus metrics for all 8 phases
3. **Monitoring Dashboards:** Grafana dashboards for operator visibility
4. **Test Suite:** 90% coverage with integration and chaos tests
5. **Runbooks:** Emergency procedures and daily health checks
6. **Documentation:** Updated architecture docs with new components

---

## Post-Implementation Validation

### Week 9-10: Production Shadow Mode

- Deploy all changes to shadow environment
- Run parallel with production for 2 weeks
- Compare metrics against baseline
- Validate no performance degradation

### Week 11-12: Gradual Rollout

- Canary to 10% of agents
- Monitor for 48 hours
- Expand to 50% of agents
- Monitor for 48 hours
- Full rollout to 100%

### Ongoing: Continuous Monitoring

- Daily health checks
- Weekly performance reviews
- Monthly architecture audits
- Quarterly swarm alignment validation

---

**Status:** Plan complete, ready for implementation
**Next Step:** Begin Sprint 1 critical P0 fixes
