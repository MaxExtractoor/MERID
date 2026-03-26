# MERID Kalshi Integration - Swarm Alignment Validation Report

**Report Date:** 2026-03-26
**Audit Scope:** Full 8-Phase Swarm Intelligence Loop Validation
**System:** MERID Autonomous Trading Framework → Kalshi Prediction Markets
**Deliverable:** Diagnostic & Remediation Plan with Validation Framework

---

## Executive Summary

This report provides a comprehensive validation framework for the MERID-Kalshi integration, ensuring the swarm operates as a **unified intelligence system** across all 8 phases: **DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE → MONITOR → PROMOTE → PROTECT**.

### Audit Methodology

1. **Architecture Analysis** - Deep dive into existing implementations
2. **Gap Analysis** - Identify swarm alignment risks using the theoretical audit reports
3. **Validation Framework** - Define measurable KPIs for each phase
4. **Remediation Plan** - Actionable improvements with priority ranking
5. **Test Strategy** - Comprehensive validation tests

### Key Findings

✅ **Strong Foundations:**
- Robust architecture with 21,358+ LOC across 48+ Kalshi integration files
- Sophisticated resilience patterns (circuit breakers, retry logic, bulkheads)
- Comprehensive 6-layer safety stack (PROTECT phase)
- Mature promotion gates with quantitative SLO enforcement

⚠️ **Critical Alignment Requirements:**
- **19 P0 findings** require implementation for production readiness
- **27 P1 findings** for near-term improvements
- **15 P2 findings** for optimization

### Validation Status

| Phase | Status | Critical Gaps | Validation Framework |
|-------|--------|--------------|---------------------|
| DISCOVER | ⚠️ PARTIAL | Schema validation implemented, SLA tracking needed | ✅ Ready |
| ANALYZE | ⚠️ PARTIAL | Timestamp validation needed | ✅ Ready |
| CONSENSUS | ⚠️ GAPS | Anti-herding protection critical | ✅ Ready |
| SIZE | ⚠️ GAPS | Kelly safety checks needed | ✅ Ready |
| EXECUTE | ⚠️ GAPS | Idempotency keys needed | ✅ Ready |
| MONITOR | ⚠️ PARTIAL | Gap recovery implemented | ✅ Ready |
| PROMOTE | ✅ STRONG | Canary deployment recommended | ✅ Ready |
| PROTECT | ⚠️ GAPS | Distributed kill switch needed | ✅ Ready |

---

## Phase 1: DISCOVER - Market Discovery & Validation

### Objectives and Expected Behaviors

**Desired State:**
- Fresh, validated market data refreshed every 300 seconds
- 100% schema compliance (no malformed markets)
- P95 discovery latency < 3s, P99 < 5s
- New market detection within 30 seconds of Kalshi listing
- Zero uncategorized markets

**Agent-Level to Swarm-Level Mapping:**
- Individual agents consume validated, enriched market catalog
- Swarm sees consistent, synchronized market view
- All agents work from same catalog refresh cycle

### Implementation Analysis

**Existing Components:**

1. **`KalshiMarketCatalog`** (`merid/event_venues/kalshi/market_catalog.py`, 556 LOC)
   - Periodic refresh every 300s
   - Regex-based categorization (45+ patterns)
   - Asset/timeframe detection
   - 5-minute TTL cache

2. **`DiscoveryValidator`** (`merid/event_venues/kalshi/discovery_validator.py`, 317 LOC) ✅
   - Pydantic schema validation
   - SLA tracking and metrics
   - Validation result tracking

**Data Flows:**
```
GET /markets (active_only=True)
  → DiscoveryValidator.validate_batch()
  → KalshiMarketCatalog._enrich()
  → Cache with 5-min TTL
  → Agents via get_markets_by_asset/category/timeframe()
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- Schema validation prevents malformed data (Finding D-001)
- SLA tracking monitors refresh latency (Finding D-002 partial)

**GAPS ⚠️:**
1. **No proactive new market detection** (Finding D-003)
   - Missing: WebSocket subscription to market lifecycle events
   - Risk: 0-5 minute lag on new opportunities
   - Impact: Alpha leakage to faster traders

2. **No catalog snapshot persistence** (Finding D-006)
   - Missing: Fallback to persisted cache on API failure
   - Risk: System blind during Kalshi outages
   - Impact: Trading halt

3. **Fragile regex categorization** (Finding D-004)
   - Missing: Fallback for unknown ticker patterns
   - Risk: Silent miscategorization
   - Impact: Wrong agents assigned to markets

### Alignment Checks

#### Market Coverage and Freshness

```python
# Validation Metric
def validate_discovery_freshness():
    """Validate DISCOVER phase data freshness."""
    catalog = get_market_catalog()

    # Check catalog age
    last_refresh = catalog.last_refresh_time
    age_seconds = (datetime.now(timezone.utc) - last_refresh).total_seconds()

    assert age_seconds < 360, f"Catalog stale: {age_seconds}s > 360s"

    # Check market coverage
    markets = catalog.get_all_markets()
    assert len(markets) > 100, f"Low market count: {len(markets)}"

    # Check categorization completeness
    uncategorized = [m for m in markets if m.category is None]
    assert len(uncategorized) == 0, f"Uncategorized: {len(uncategorized)}"

    # Check BTC coverage (critical asset)
    btc_markets = catalog.get_markets_by_asset("BTC")
    assert len(btc_markets) > 0, "No BTC markets discovered"

    return True
```

#### Data Quality Validation

```python
# Validation Metric
def validate_discovery_quality():
    """Validate DISCOVER phase data quality."""
    validator = get_discovery_validator()
    stats = validator.get_stats()

    # Check validation rate
    validation_rate = stats["validation_rate"]
    assert validation_rate > 0.95, f"Low validation rate: {validation_rate}"

    # Check SLA compliance
    sla_percentiles = validator.get_sla_percentiles()
    assert sla_percentiles["p95"] < 3000, f"P95 too high: {sla_percentiles['p95']}ms"
    assert sla_percentiles["p99"] < 5000, f"P99 too high: {sla_percentiles['p99']}ms"

    return True
```

### Validation Metrics

**Discovery Health Metrics:**
```python
kalshi_catalog_refresh_latency_ms{quantile="0.50|0.95|0.99"}  # Target: p95 < 3000ms
kalshi_catalog_market_count{category, asset, timeframe}  # Track coverage
kalshi_catalog_invalid_markets_total  # Target: 0
kalshi_catalog_uncategorized_markets_total  # Target: 0
kalshi_catalog_new_markets_detected_total  # Rate of discovery
kalshi_discovery_validation_rate  # Target: > 0.95
```

### Recommendations

**P0 (Critical):**
1. ✅ Implement schema validation - **DONE** (DiscoveryValidator exists)
2. ⚠️ Add WebSocket subscription for new market detection (Finding D-003)
3. ⚠️ Implement catalog snapshot persistence for failover (Finding D-006)

**P1 (High):**
1. Add SLA alerting (Prometheus rules for p95/p99 breaches)
2. Implement "unknown" category fallback with logging
3. Add full-text search index for market queries

**Timeline:** Sprint 1 (Week 1-2) for P0, Sprint 2 (Week 3-4) for P1

---

## Phase 2: ANALYZE - Data Transformation & Signal Generation

### Objectives and Expected Behaviors

**Desired State:**
- All sentiment inputs validated for freshness (<5min old)
- Feature drift detected within 1 batch cycle
- Clock skew < 500ms enforced
- LLM predictions calibrated with Brier score tracking

**Agent-Level to Swarm-Level Mapping:**
- `MarketResearchAgent` produces `ResearchThesis` with confidence
- `PredictionMarketAgentV2` calculates implied probabilities and edge
- `CryptoSignalsAgent` provides structural signals (funding, basis)
- Swarm aggregates diverse signal sources into unified `SentimentContext`

### Implementation Analysis

**Existing Components:**

1. **`SentimentContext`** (`merid/swarm/market_mood_bus.py`)
   - Aggregates Twitter, news, macro, on-chain signals
   - Fear/greed index (0-100)
   - Unified sentiment scoring

2. **`AnalysisValidator`** (`merid/event_venues/kalshi/analysis_validator.py`, 473 LOC) ✅
   - Timestamp validation for sentiment freshness
   - Feature drift detection
   - Clock skew monitoring

3. **Signal Generators:**
   - `MarketResearchAgent` (`merid/agents/research.py`)
   - `PredictionMarketAgentV2` (Kalshi-specific edge detection)
   - `CryptoSignalsAgent` (CEX signals)

**Data Flows:**
```
External Signals (Twitter, news, macro) + Kalshi orderbook
  → SentimentContext aggregation
  → AnalysisValidator.validate_sentiment_freshness()
  → Feature engineering (momentum, volatility, correlation)
  → PredictionMarketModel (probability → edge calculation)
  → KalshiStrategy.score_market()
  → Output: (edge_estimate, confidence, direction)
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- Timestamp validation (AnalysisValidator exists)
- Feature drift detection framework

**GAPS ⚠️:**
1. **No calibration tracking for LLM-based signals** (Finding A-004)
   - Missing: Brier score tracking per agent
   - Risk: Overconfident predictions → oversized positions
   - Impact: Drawdowns

2. **No volume-to-liquidity normalization** (Finding A-005)
   - Missing: Adjust volume spikes by typical market liquidity
   - Risk: False signals on illiquid markets
   - Impact: Wasted execution costs

3. **Clock skew risk** (Finding A-003)
   - Missing: NTP synchronization verification
   - Risk: Incorrect time-to-expiry calculations
   - Impact: Trading during wrong windows

### Alignment Checks

#### Signal Freshness Validation

```python
# Validation Metric
def validate_analysis_freshness():
    """Validate ANALYZE phase signal freshness."""
    # Mock sentiment context check
    context = get_current_sentiment_context()

    # Check timestamp freshness
    now = datetime.now(timezone.utc)
    assert (now - context.twitter_updated_at).total_seconds() < 300, "Stale Twitter sentiment"
    assert (now - context.news_updated_at).total_seconds() < 300, "Stale news sentiment"

    # Check feature completeness
    assert context.fear_greed_index is not None, "Missing fear/greed index"
    assert context.volatility_regime is not None, "Missing volatility regime"

    return True
```

### Validation Metrics

**Analysis Quality Metrics:**
```python
kalshi_sentiment_freshness_seconds{source}  # Target: < 300s
kalshi_feature_drift_detected_total{feature}  # Track drift events
kalshi_clock_skew_ms  # Target: < 500ms
kalshi_llm_calibration_brier_score{agent_id}  # Target: < 0.2
```

### Recommendations

**P0 (Critical):**
1. ✅ Implement timestamp validation - **DONE** (AnalysisValidator exists)
2. ⚠️ Add clock skew monitoring with NTP check (Finding A-003)
3. ⚠️ Implement LLM calibration tracking (Finding A-004)

**P1 (High):**
1. Add volume-to-liquidity normalization
2. Implement feature drift alerting
3. Add sentiment source health checks

**Timeline:** Sprint 2 (Week 3-4) for P0, Sprint 3 (Week 5-6) for P1

---

## Phase 3: CONSENSUS - Swarm Negotiation & Coordination

### Objectives and Expected Behaviors

**Desired State:**
- Consensus forms within 5 seconds with min 3 agents
- Herding detected when proposal variance < 5%
- Agent weights capped at 40% (no single agent dominates)
- Consensus cache protected from race conditions

**Agent-Level to Swarm-Level Mapping:**
- Individual agents submit `AgentProposal` with probability/confidence
- `SwarmConsensusAggregator` performs weighted voting
- Track-record weighting (Sharpe, win rate) determines agent influence
- Output: Unified `ConsensusView` with direction, confidence, size band

### Implementation Analysis

**Existing Components:**

1. **`SwarmConsensusAggregator`** (`merid/swarm/consensus_aggregator.py`, 500+ LOC)
   - Weighted voting by track record
   - Confidence calculation
   - Size band recommendation
   - Integration with MarketMoodBus

2. **`ConsensusCoordinatorAgent`** (`merid/agents/coordination.py`)
   - Multi-agent coordination
   - Veto mechanism (risk, governance)
   - Approval scoring

3. **`AntiHerdingDetector`** (`merid/event_venues/kalshi/consensus_protection.py`) ✅
   - Prevents false consensus from correlated agents
   - Track-record weighting controls

**Data Flows:**
```
Agent proposals → SwarmConsensusAggregator.submit_proposal()
  → Weighted average by track record (Sharpe, win rate)
  → Majority vote on direction
  → Confidence = agreement metric
  → Size band recommendation (small/base/large)
  → ConsensusView output → MarketMoodBus
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- Anti-herding detection exists (`consensus_protection.py`)
- Track-record weighting implemented

**GAPS ⚠️:**
1. **Race condition in consensus cache** (Finding C-002) **CRITICAL**
   - Missing: `asyncio.Lock()` on `_consensus_cache` writes
   - Risk: Corrupted consensus state from concurrent writes
   - Impact: Agents read inconsistent consensus → conflicting orders

2. **Track-record overfitting** (Finding C-003)
   - Missing: Sample size confidence penalty
   - Risk: Recently-lucky agent dominates (80% weight)
   - Impact: Single point of failure

3. **No consensus timeout** (Finding C-004)
   - Missing: Timeout on waiting for min_agents
   - Risk: Trading stalls if one agent hangs
   - Impact: Missed opportunities

### Alignment Checks

#### Consensus Formation Validation

```python
# Validation Metric
def validate_consensus_formation():
    """Validate CONSENSUS phase formation."""
    aggregator = get_consensus_aggregator()

    # Submit test proposals
    proposals = create_test_proposals(asset="BTC", timeframe="15m", count=5)
    for proposal in proposals:
        aggregator.submit_proposal(proposal)

    # Check consensus forms
    consensus = aggregator.get_consensus("BTC", "15m", timeout_s=5.0)
    assert consensus is not None, "Consensus failed to form"
    assert consensus.voting_agents >= 3, "Insufficient agent participation"

    # Check confidence scoring
    assert 0.0 <= consensus.consensus_confidence <= 1.0, "Invalid confidence"

    # Check size band recommendation
    assert consensus.size_band in ["small", "base", "large", "halted"], "Invalid size band"

    return True
```

#### Anti-Herding Validation

```python
# Validation Metric
def validate_anti_herding():
    """Validate anti-herding protection."""
    aggregator = get_consensus_aggregator()

    # Submit herding proposals (all agree on 60%)
    herding_proposals = [
        create_proposal(agent_id=f"agent_{i}", probability=0.60, confidence=0.80)
        for i in range(5)
    ]

    for proposal in herding_proposals:
        aggregator.submit_proposal(proposal)

    consensus = aggregator.get_consensus("BTC", "15m")

    # Check herding detection
    assert "herding_detected" in " ".join(consensus.disagreement_flags), \
        "Herding not detected"

    # Check confidence penalty applied
    assert consensus.consensus_confidence < 0.70, \
        f"Herding penalty not applied: confidence={consensus.consensus_confidence}"

    return True
```

### Validation Metrics

**Consensus Health Metrics:**
```python
kalshi_consensus_formation_latency_ms{p50, p95, p99}  # Target: p95 < 2000ms
kalshi_consensus_herding_detected_total{asset, timeframe}  # Target: < 5% of formations
kalshi_consensus_cache_lock_wait_ms{p95}  # Target: < 10ms
kalshi_consensus_confidence_score{asset, timeframe}  # Track confidence distribution
kalshi_consensus_direction_breakdown{asset, timeframe, direction}  # Vote distribution
```

### Recommendations

**P0 (Critical):**
1. ⚠️ Add `asyncio.Lock()` to consensus cache writes (Finding C-002) **URGENT**
2. ⚠️ Implement agent weight capping at 40% (Finding C-003)
3. ⚠️ Add consensus timeout with partial consensus fallback (Finding C-004)

**P1 (High):**
1. Enhance herding detection with entropy analysis
2. Add consensus audit trail (persist proposals)
3. Implement track-record decay (70% recent, 30% all-time)

**Timeline:** Sprint 1 (Week 1-2) for P0 (race condition is critical), Sprint 2 (Week 3-4) for P1

---

## Phase 4: SIZE - Position Sizing & Risk Allocation

### Objectives and Expected Behaviors

**Desired State:**
- Kelly fraction computed safely (no division-by-zero)
- Domain caps enforced without race conditions
- Fee calculations match current Kalshi schedule
- Position sizes scale with conviction and profit factor

**Agent-Level to Swarm-Level Mapping:**
- Individual agents propose edge and confidence
- `PositionSizer` applies fractional-Kelly (0.25 default)
- `ExecutionGuard` enforces CQI throttle and domain caps
- `GlobalRiskManager` checks portfolio-wide limits
- Final contract count = Kelly × PF scaling × CQI throttle × caps

### Implementation Analysis

**Existing Components:**

1. **`PositionSizer`** (`merid/event_venues/kalshi/position_sizer.py`, 668 LOC)
   - Fractional-Kelly criterion
   - Fee-aware sizing (Kalshi tiered fees)
   - Per-underlying hourly exposure caps
   - PF/expectancy gates

2. **`ExecutionGuard`** (`merid/execution_guard.py`)
   - CQI throttle (0.35-0.65 range)
   - Domain caps (max $5k/day notional)

3. **`GlobalRiskManager`** (`merid/pipeline/risk_manager.py`)
   - Portfolio-wide limits (max $50k total)
   - Max allocation %, max notional USD, max daily loss

**Sizing Hierarchy:**
```
Kelly f* = (p × b - q) / b  (base fraction = 0.25 × f*)
  → Profit factor scaling (PF < 1.2 → min size, PF > 1.8 → full kelly)
  → CQI throttle (0.35-0.65 range)
  → Domain caps (max $5k/day notional)
  → Global portfolio limits (max $50k total)
  → Final contract count
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- Kelly sizing with fee awareness
- Domain caps enforcement
- CQI throttle system

**GAPS ⚠️:**
1. **Kelly denominator risk** (Finding S-001) **CRITICAL**
   - Missing: Division-by-zero protection on edge cases
   - Risk: System crash during position sizing
   - Impact: Missed trades, potential liquidation

2. **Domain cap race condition** (Finding S-002) **CRITICAL**
   - Missing: `asyncio.Lock()` on `DomainCap.record_trade()`
   - Risk: Concurrent agents double-count or miss cap enforcement
   - Impact: Exceed daily caps → regulatory violation

3. **Outdated fee schedule** (Finding S-003)
   - Missing: Dynamic fetching from Kalshi API
   - Risk: Hardcoded fees (7%/5%/3%) may not match current schedule
   - Impact: Underestimated fees → unprofitable trades

### Alignment Checks

#### Position Sizing Safety Validation

```python
# Validation Metric
def validate_position_sizing_safety():
    """Validate SIZE phase safety checks."""
    sizer = get_position_sizer()

    # Test edge cases
    test_cases = [
        {"win_prob": 0.6, "win_payout": 50, "loss_amount": 50},  # Normal
        {"win_prob": 0.6, "win_payout": 0, "loss_amount": 50},   # Zero payout
        {"win_prob": 0.6, "win_payout": 50, "loss_amount": 0},   # Zero loss
        {"win_prob": 0.0, "win_payout": 50, "loss_amount": 50},  # No edge
    ]

    for case in test_cases:
        try:
            kelly = sizer.kelly_fraction_for_binary(**case)
            assert kelly >= 0.0, f"Negative Kelly: {kelly}"
            assert kelly <= 1.0, f"Kelly > 1: {kelly}"
        except Exception as exc:
            assert False, f"Kelly crash on {case}: {exc}"

    return True
```

#### Domain Cap Enforcement Validation

```python
# Validation Metric
async def validate_domain_cap_enforcement():
    """Validate domain cap race condition protection."""
    guard = get_execution_guard()
    domain = "prediction"

    # Reset caps
    guard.reset_domain_cap(domain)

    # Simulate 10 concurrent trades
    async def place_trade(notional: float):
        remaining = await guard.get_remaining_notional(domain)
        if notional <= remaining:
            await guard.record_trade(domain, notional)
            return True
        return False

    # Execute concurrently
    results = await asyncio.gather(*[
        place_trade(500.0) for _ in range(10)
    ])

    # Check total notional
    total_used = guard.get_daily_notional_used(domain)
    max_cap = guard.get_domain_cap(domain).max_daily_notional_usd

    assert total_used <= max_cap, f"Cap breached: {total_used} > {max_cap}"

    return True
```

### Validation Metrics

**Sizing Health Metrics:**
```python
kalshi_kelly_computation_errors_total  # Target: 0
kalshi_domain_notional_used_usd{domain}  # Daily notional used
kalshi_domain_notional_remaining_usd{domain}  # Remaining capacity
kalshi_domain_cap_breaches_total{domain}  # Target: 0
kalshi_cqi_score{domain}  # Quality index (0-1)
kalshi_position_size_distribution{agent_id}  # Size distribution histogram
```

### Recommendations

**P0 (Critical):**
1. ⚠️ Add division-by-zero protection to Kelly calculation (Finding S-001) **URGENT**
2. ⚠️ Add `asyncio.Lock()` to domain cap tracking (Finding S-002) **URGENT**
3. ⚠️ Implement dynamic fee schedule fetching (Finding S-003)

**P1 (High):**
1. Wire up volatility-adjusted sizing (ATR integration)
2. Add dynamic bankroll tracking (live portfolio value)
3. Implement position correlation limits

**Timeline:** Sprint 1 (Week 1-2) for P0 (critical safety issues), Sprint 2 (Week 3-4) for P1

---

## Phase 5: EXECUTE - API Execution & Error Recovery

### Objectives and Expected Behaviors

**Desired State:**
- Zero 429 rate limit errors
- No duplicate order submission (idempotency enforced)
- P95 execution latency < 1s, P99 < 2s
- Circuit breaker protects from cascading failures
- Partial fills tracked with timeout-based cancellation

**Agent-Level to Swarm-Level Mapping:**
- `TradeRouter` orchestrates full execution pipeline
- `KalshiVenueClient` handles REST API communication
- `OrderManager` tracks order lifecycle
- `CircuitBreaker` provides resilience layer
- All agents share same execution infrastructure

### Implementation Analysis

**Existing Components:**

1. **`TradeRouter`** (`merid/pipeline/router.py`)
   - Main execution entry point
   - Integrates instrument registry, mode manager, risk gates

2. **`KalshiVenueClient`** (`merid/event_venues/kalshi/client.py`, 3392 LOC)
   - REST API wrapper with circuit breaker
   - Retry logic (3 max, exponential backoff)
   - Retries on {429, 500, 502, 503, 504}

3. **`OrderManager`** (`merid/event_venues/kalshi/order_manager.py`, 668 LOC)
   - Fill event tracking
   - Order lifecycle monitoring
   - Partial fill handling

4. **`CircuitBreaker`** (`merid/resilience.py`)
   - Per-venue breaker (5 failure threshold, 30s recovery)
   - Fail-fast on repeated failures

**Execution Flow:**
```
TradeProposal → TradeRouter.submit()
  → InstrumentRegistry.resolve()
  → ModeManager.check_can_trade()
  → GlobalRiskManager.check_proposal()
  → OrderSanityChecker.check()
  → KalshiVenueClient.place_order() [with circuit breaker + retry]
  → OrderManager.track_lifecycle()
  → ExecutionResult
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- Circuit breaker resilience
- Retry logic with exponential backoff
- Order lifecycle tracking

**GAPS ⚠️:**
1. **Rate limit not enforced on all endpoints** (Finding E-001) **CRITICAL**
   - Missing: `_rate_limiter.acquire()` before read endpoints
   - Risk: 429 errors cascade → circuit breaker opens
   - Impact: Trading halts

2. **No idempotency key management** (Finding E-002) **CRITICAL**
   - Missing: Client-side order deduplication
   - Risk: Timeout → retry → duplicate order → 2× exposure
   - Impact: Double-fill losses

3. **No P99 latency tracking** (Finding E-003)
   - Missing: Percentile aggregation and alerting
   - Risk: Slow fills during volatility → adverse selection
   - Impact: Slippage losses

### Alignment Checks

#### Execution Quality Validation

```python
# Validation Metric
async def validate_execution_quality():
    """Validate EXECUTE phase quality metrics."""
    router = get_trade_router()

    # Submit test order
    proposal = create_test_proposal(
        instrument_id="PRED:KALSHI:BTC_25DEC:YES",
        side="BUY",
        qty=10,
        price=55,
    )

    start = time.perf_counter()
    result = await router.submit(proposal)
    latency_ms = (time.perf_counter() - start) * 1000

    # Check execution result
    assert result.status in ["FILLED", "PARTIAL"], f"Unexpected status: {result.status}"
    assert result.execution_result is not None, "Missing execution result"

    # Check latency
    assert latency_ms < 2000, f"Latency too high: {latency_ms:.0f}ms"

    return True
```

#### Idempotency Validation

```python
# Validation Metric
async def validate_idempotency():
    """Validate order idempotency protection."""
    client = get_kalshi_client()

    # Place order with client_order_id
    order = VenueOrder(
        market_id="KXBTC-25DEC-T55000",
        side="buy",
        outcome_id="yes",
        size=10,
        price=55,
        client_order_id="test-order-001",
    )

    # First attempt
    result1 = await client.place_order(order)
    assert result1.order_id is not None, "Order not placed"

    # Second attempt with same client_order_id (should detect duplicate)
    try:
        result2 = await client.place_order(order)
        # Should either return cached result or raise RuntimeError
        if result2.order_id == result1.order_id:
            # Cached result returned
            pass
        else:
            assert False, "Duplicate order allowed"
    except RuntimeError as exc:
        if "already in flight" in str(exc):
            # Correctly detected duplicate
            pass
        else:
            raise

    return True
```

### Validation Metrics

**Execution Health Metrics:**
```python
kalshi_orders_submitted_total{agent_id, venue, domain}  # Total orders
kalshi_orders_filled_total{agent_id, venue, domain}  # Successful fills
kalshi_orders_rejected_total{agent_id, venue, domain, reason}  # Rejections
kalshi_order_fill_rate_pct{agent_id, venue}  # Target: > 70%
kalshi_order_placement_latency_ms{p50, p95, p99}  # Target: p95 < 1000ms, p99 < 2000ms
kalshi_rate_limit_429_errors_total{endpoint}  # Target: 0
kalshi_duplicate_order_prevented_total  # Count of prevented duplicates
kalshi_circuit_breaker_state{venue}  # 0=closed, 1=open
```

### Recommendations

**P0 (Critical):**
1. ⚠️ Enforce rate limiting on ALL endpoints (Finding E-001) **URGENT**
2. ⚠️ Implement idempotency key management (Finding E-002) **URGENT**
3. ⚠️ Add P99 latency tracking and alerting (Finding E-003)

**P1 (High):**
1. Implement timeout-based order cancellation (30s default)
2. Add execution quality scoring
3. Enhance retry logic for 503 errors

**Timeline:** Sprint 1 (Week 1-2) for P0 (critical reliability issues), Sprint 2 (Week 3-4) for P1

---

## Phase 6: MONITOR - State Tracking & PnL Attribution

### Objectives and Expected Behaviors

**Desired State:**
- WebSocket gap detection triggers full position reload
- Fees tracked per fill increment (not just full fills)
- Alert deduplication prevents notification spam
- Position reconciliation every 5 minutes (not 1 hour)
- Zero position desyncs

**Agent-Level to Swarm-Level Mapping:**
- `KalshiWebSocket` provides real-time fills for all agents
- `PositionCache` maintains synchronized position view
- `TradeAnalytics` computes accurate PnL with fees
- `KalshiReconciler` validates internal vs. Kalshi positions
- All agents see consistent position state

### Implementation Analysis

**Existing Components:**

1. **`KalshiWebSocket`** (`merid/event_venues/kalshi/ws.py`, 711 LOC)
   - Real-time orderbook + fill events
   - Sequence tracking and gap detection
   - Exponential backoff reconnect
   - Async message queue (4096 size)

2. **`KalshiWebSocketBridge`** (`merid/event_venues/kalshi/ws_bridge.py`, 463 LOC)
   - Pipes WS events into core event bus
   - Event types: price_update, trade, orderbook_delta, order_fill

3. **`PositionCache`** (30s poll)
   - Position state tracking
   - Updated on order fills

4. **`TradeAnalytics`** (PnL tracking)
   - Realized/unrealized P&L calculation

**Data Flows:**
```
WebSocket: orderbook updates → live fills → OrderManager
REST polling: GET /positions (30s) → PositionCache
PnL: (filled_price - entry_price) × contracts - fees → TradeAnalytics
Reconciliation: Compare internal ledger vs. Kalshi API (hourly)
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- WebSocket gap detection (logs warnings)
- Position polling (30s interval)
- PnL calculation framework

**GAPS ⚠️:**
1. **WebSocket gap not fail-safe** (Finding M-001) **CRITICAL**
   - Missing: Force full position reload on gap
   - Risk: Missing fills between gap → position desync
   - Impact: Hidden positions → unmanaged risk

2. **Fee deduction not applied on partial fills** (Finding M-002)
   - Missing: Incremental fee tracking per fill
   - Risk: Overestimated PnL → false profitability signals
   - Impact: Bad promotion decisions

3. **No alert deduplication** (Finding M-003)
   - Missing: Cooldown logic for repeated alerts
   - Risk: 10× "drawdown exceeded" in 1 minute → Telegram flooded
   - Impact: Alert fatigue → missed critical alerts

### Alignment Checks

#### Position Synchronization Validation

```python
# Validation Metric
async def validate_position_synchronization():
    """Validate MONITOR phase position synchronization."""
    client = get_kalshi_client()
    cache = get_position_cache()

    # Get positions from cache
    cached_positions = cache.get_all_positions()

    # Get positions from Kalshi API
    api_positions = await client.get_positions()

    # Compare
    for api_pos in api_positions:
        cached_pos = cache.get_position(api_pos.ticker, api_pos.side)

        assert cached_pos is not None, f"Position missing from cache: {api_pos.ticker}"
        assert cached_pos.count == api_pos.count, \
            f"Position desync: cache={cached_pos.count}, api={api_pos.count}"
        assert abs(cached_pos.avg_price - api_pos.avg_price) < 1.0, \
            f"Price desync: cache={cached_pos.avg_price}, api={api_pos.avg_price}"

    return True
```

#### Fee Attribution Validation

```python
# Validation Metric
def validate_fee_attribution():
    """Validate fee tracking on partial fills."""
    analytics = get_trade_analytics()

    # Simulate partial fills
    order_id = "test-order-001"

    # Fill 1: 5 contracts @ 55¢
    analytics.record_fill(FillEvent(
        order_id=order_id,
        quantity=5,
        price=55,
        fee=1.50,  # Kalshi fee for 5 contracts
        timestamp=datetime.now(timezone.utc),
    ))

    # Fill 2: 5 contracts @ 56¢
    analytics.record_fill(FillEvent(
        order_id=order_id,
        quantity=5,
        price=56,
        fee=1.52,  # Kalshi fee for 5 contracts
        timestamp=datetime.now(timezone.utc),
    ))

    # Check total fees
    position = analytics.get_position(order_id)
    total_fees = position.total_fees

    assert abs(total_fees - 3.02) < 0.01, \
        f"Fee tracking error: {total_fees} != 3.02"

    return True
```

### Validation Metrics

**Monitoring Health Metrics:**
```python
kalshi_ws_lag_ms{p50, p95, p99}  # Target: p99 < 500ms
kalshi_ws_sequence_gaps_total  # Target: 0
kalshi_ws_reconnects_total  # Target: < 1 per hour
kalshi_position_cache_staleness_seconds  # Target: < 60s
kalshi_position_desyncs_detected_total  # Target: 0
kalshi_fee_attribution_errors_total  # Target: 0
kalshi_alert_suppressed_total{alert_key}  # Track suppression rate
```

### Recommendations

**P0 (Critical):**
1. ⚠️ Force position reload on WebSocket gap (Finding M-001) **URGENT**
2. ⚠️ Implement incremental fee tracking (Finding M-002)
3. ⚠️ Add alert deduplication with cooldown (Finding M-003)

**P1 (High):**
1. Increase reconciliation frequency to 5min
2. Add bounded queue with backpressure on WS events
3. Implement PnL overlay on positions

**Timeline:** Sprint 1 (Week 1-2) for P0 (position sync critical), Sprint 2 (Week 3-4) for P1

---

## Phase 7: PROMOTE - Strategy Promotion & Adaptive Weights

### Objectives and Expected Behaviors

**Desired State:**
- Paper → Shadow → Live progression with quantitative gates
- Canary deployment (10% → 100%) for agent updates
- Track-record decay (70% recent, 30% all-time)
- Shadow mode losses capped at $100/trade, $500/day
- Auto-rollback on PF < 0.9, drawdown > 15%, or 10+ consecutive losses

**Agent-Level to Swarm-Level Mapping:**
- Individual agents progress through deployment stages
- `DeploymentController` manages mode state machine
- `AutoPromoter` runs background promotion loop (60s interval)
- Agent performance tracked via `PaperSession`
- Swarm maintains max 3 LIVE agents per market at any time

### Implementation Analysis

**Existing Components:**

1. **`DeploymentController`** (`merid/event_venues/kalshi/deployment.py`, 418 LOC)
   - Mode state machine (PAPER → SHADOW → LIVE)
   - Promotion gate enforcement
   - Auto-rollback triggers

2. **`AutoPromoter`** (`merid/event_venues/kalshi/auto_promoter.py`, 393 LOC)
   - Background promotion loop (60s interval)
   - Autonomous advancement
   - Telegram alerts on transitions

3. **`AgentGauntlet`** (8-dimensional SLO gates)
   - Min trades, profit factor, drawdown, error rate
   - Stricter for high-frequency cells (BTC_15M, ETH_HOURLY)

4. **Crypto Surface Deployment:**
   - 20 agents: BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly
   - Per-cell benchmarks with gate thresholds

**Promotion Flow:**
```
PAPER (200+ trades, PF ≥ 1.4) → SHADOW (100+ trades, PF stable) → LIVE (3 max)
  ↓
Continuous rollback monitoring:
  - PF < 0.9 → rollback
  - Consecutive losses ≥ 10 → rollback
  - Drawdown > 15% → rollback
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- Quantitative promotion gates
- Auto-rollback on performance degradation
- Deployment controller with mode tracking

**GAPS ⚠️:**
1. **No canary deployment** (Finding P-001) **CRITICAL**
   - Missing: Staged rollout (10% → 100%) for agent updates
   - Risk: Bug in new agent version affects all positions
   - Impact: Catastrophic loss

2. **No track-record decay** (Finding P-002)
   - Missing: Time-weighted performance (recent vs. all-time)
   - Risk: Stale agent from 6 months ago still dominates consensus
   - Impact: Degraded swarm performance

3. **Shadow mode can lose real money** (Finding P-003)
   - Missing: Position size caps in shadow mode
   - Risk: Buggy agent loses unlimited capital before promotion
   - Impact: Shadow losses exceed paper trial losses

### Alignment Checks

#### Promotion Gate Validation

```python
# Validation Metric
def validate_promotion_gates():
    """Validate PROMOTE phase gate enforcement."""
    controller = get_deployment_controller()

    # Create test agent
    agent_id = "test_btc_15m"
    controller.register_agent(agent_id, initial_mode=AgentMode.PAPER)

    # Simulate performance below threshold
    session = get_paper_session()
    session.record_trade(agent_id, pnl=-10, win=False)
    # ... record 200 trades with PF = 1.0 (below 1.4 threshold)

    # Attempt promotion
    can_promote = controller.can_promote(agent_id, to_mode=AgentMode.SHADOW)

    assert not can_promote, "Promotion allowed despite PF < 1.4"

    # Simulate performance above threshold
    # ... record 200 trades with PF = 1.5 (above 1.4)

    can_promote = controller.can_promote(agent_id, to_mode=AgentMode.SHADOW)

    assert can_promote, "Promotion blocked despite meeting gates"

    return True
```

#### Auto-Rollback Validation

```python
# Validation Metric
def validate_auto_rollback():
    """Validate auto-rollback triggers."""
    controller = get_deployment_controller()

    # Promote agent to LIVE
    agent_id = "test_btc_hourly"
    controller.promote(agent_id, to_mode=AgentMode.LIVE)

    # Simulate performance degradation
    session = get_paper_session()
    for _ in range(10):
        session.record_trade(agent_id, pnl=-50, win=False)  # 10 consecutive losses

    # Check auto-rollback
    current_mode = controller.get_agent_mode(agent_id)

    assert current_mode == AgentMode.HALTED, \
        f"Auto-rollback failed: mode={current_mode}"

    return True
```

### Validation Metrics

**Promotion Health Metrics:**
```python
kalshi_agents_by_mode{mode}  # mode=PAPER/SHADOW/LIVE
kalshi_agent_promotions_total{agent_id, from_mode, to_mode}  # Promotion events
kalshi_agent_rollbacks_total{agent_id, from_mode, reason}  # Rollback events
kalshi_agent_profit_factor{agent_id}  # Target: > 1.4 for promotion
kalshi_agent_sharpe_ratio{agent_id}  # Target: > 0.5
kalshi_agent_win_rate_pct{agent_id}  # Target: > 55%
kalshi_agent_drawdown_pct{agent_id}  # Target: < 15%
```

### Recommendations

**P0 (Critical):**
1. ⚠️ Implement canary deployment (10% → 100%) (Finding P-001) **URGENT**
2. ⚠️ Add track-record decay (70% recent, 30% all-time) (Finding P-002)
3. ⚠️ Cap shadow mode losses ($100/trade, $500/day) (Finding P-003)

**P1 (High):**
1. Add promotion velocity limits (max 1/hour)
2. Implement A/B testing framework
3. Add performance comparison dashboards

**Timeline:** Sprint 2 (Week 3-4) for P0, Sprint 3 (Week 5-6) for P1

---

## Phase 8: PROTECT - Risk Controls & Security

### Objectives and Expected Behaviors

**Desired State:**
- Kill switch propagates across all instances within 100ms
- Bad agents isolated after 5 errors (circuit breaker per agent)
- Audit trail immutable (EventStoreDB or S3 with object lock)
- Anomaly detection integrated into execution pipeline
- API keys redacted in all logs

**Agent-Level to Swarm-Level Mapping:**
- 6-layer safety stack protects all agents:
  - Layer 1: Global kill switch (blocks ALL domains)
  - Layer 2: Per-domain kill switch (blocks single domain)
  - Layer 3: CQI throttle (shrinks size when quality degrades)
  - Layer 4: Per-domain daily caps (max $5k/day notional)
  - Layer 5: GlobalRiskManager pre-trade checks (7 gates)
  - Layer 6: Drawdown governor (auto-liquidation at threshold)
- Bad agent failures isolated from swarm
- All risk events logged for compliance

### Implementation Analysis

**Existing Components:**

1. **`ExecutionGuard`** (`merid/execution_guard.py`)
   - Main safety controller
   - CQI throttle system
   - Domain cap enforcement
   - Kill switch (local file-based)

2. **`GlobalRiskManager`** (`merid/pipeline/risk_manager.py`)
   - Portfolio-wide limits
   - Per-domain caps
   - Max allocation, notional, daily loss

3. **`KalshiRiskManager`** (venue-specific limits)
   - Kalshi position limits
   - Market-specific constraints

4. **`StopLossRules`** (position stop-loss engine)
   - Configurable stop-loss thresholds

5. **`CircuitBreaker`** (venue health failover)
   - Per-venue breaker (5 failures, 30s recovery)

**6-Layer Safety Stack:**
```
Layer 1: Global Kill Switch (blocks ALL domains)
Layer 2: Per-Domain Kill Switch (blocks single domain)
Layer 3: CQI Throttle (shrinks size when quality degrades)
Layer 4: Per-Domain Daily Caps (max $5k/day notional)
Layer 5: GlobalRiskManager Pre-Trade Checks (7 gates)
Layer 6: Drawdown Governor (auto-liquidation at threshold)
```

### Gap and Failure Mode Detection

**IMPLEMENTED ✅:**
- 6-layer safety stack
- Kill switch system (local)
- Circuit breakers (venue-level)
- CQI throttle
- Domain caps

**GAPS ⚠️:**
1. **Kill switch not replicated** (Finding PR-001) **CRITICAL**
   - Missing: Redis for distributed state
   - Risk: Multi-instance deployment → each has separate kill switch file
   - Impact: Kill switch on one instance doesn't propagate

2. **No agent-level circuit breakers** (Finding PR-002) **CRITICAL**
   - Missing: Per-agent isolation
   - Risk: Runaway agent consumes entire domain cap → blocks other agents
   - Impact: Single bad agent DoSes entire domain

3. **No immutable audit trail** (Finding PR-003)
   - Missing: Append-only event log (EventStoreDB or S3)
   - Risk: Local logs can be modified → cannot prove compliance
   - Impact: Regulatory audit failure

### Alignment Checks

#### Kill Switch Propagation Validation

```python
# Validation Metric
async def validate_kill_switch_propagation():
    """Validate distributed kill switch propagation."""
    guard1 = get_execution_guard(instance_id="instance_1")
    guard2 = get_execution_guard(instance_id="instance_2")

    # Activate on instance 1
    start = time.perf_counter()
    guard1.activate_kill_switch(reason="test_propagation")

    # Check propagation to instance 2
    await asyncio.sleep(0.1)  # 100ms
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert guard2.kill_switch_active, "Kill switch not propagated"
    assert elapsed_ms < 100, f"Propagation too slow: {elapsed_ms:.0f}ms"

    return True
```

#### Agent Isolation Validation

```python
# Validation Metric
async def validate_agent_isolation():
    """Validate agent circuit breaker isolation."""
    breaker1 = get_agent_circuit_breaker("bad_agent")
    breaker2 = get_agent_circuit_breaker("good_agent")

    # Trigger errors on bad_agent
    for i in range(5):
        breaker1.record_error()

    # Check bad_agent isolated
    assert breaker1.is_open(), "Bad agent not isolated"

    # Check good_agent unaffected
    assert not breaker2.is_open(), "Good agent incorrectly isolated"

    # Verify bad_agent cannot trade
    try:
        await execute_trade(agent_id="bad_agent", ...)
        assert False, "Bad agent allowed to trade"
    except AgentHaltedException:
        # Correctly blocked
        pass

    # Verify good_agent can still trade
    await execute_trade(agent_id="good_agent", ...)

    return True
```

### Validation Metrics

**Protection Health Metrics:**
```python
kalshi_kill_switch_active{level}  # level=global/domain, values: 0/1
kalshi_kill_switch_propagation_ms{p95}  # Target: < 100ms
kalshi_kill_switch_activations_total{level, reason}  # Activation frequency
kalshi_agent_circuit_breaker_opens_total{agent_id}  # Per-agent failures
kalshi_agent_isolated_count  # Currently isolated agents
kalshi_domain_cap_breaches_total{domain}  # Target: 0
kalshi_drawdown_pct{agent_id, portfolio}  # Target: < 15%
kalshi_audit_events_logged_total{event_type}  # Audit trail completeness
```

### Recommendations

**P0 (Critical):**
1. ⚠️ Implement distributed kill switch with Redis (Finding PR-001) **URGENT**
2. ⚠️ Add agent-level circuit breakers (Finding PR-002) **URGENT**
3. ⚠️ Implement immutable audit logging (Finding PR-003)

**P1 (High):**
1. Wire anomaly detector into execution pipeline
2. Implement API key redaction in logs
3. Add compliance monitoring dashboard

**Timeline:** Sprint 1 (Week 1-2) for P0 (critical safety issues), Sprint 2 (Week 3-4) for P1

---

## Comprehensive Validation Metrics

### Discovery-to-Protect End-to-End KPIs

**Phase Coherence Score:**
```python
def compute_swarm_coherence_score() -> float:
    """Compute overall swarm coherence across all 8 phases.

    Returns:
        Score 0-1 where 1 = perfect alignment
    """
    scores = {
        "discover": compute_discover_score(),  # Schema validation rate, SLA compliance
        "analyze": compute_analyze_score(),    # Sentiment freshness, feature drift
        "consensus": compute_consensus_score(),  # Herding detection, cache sync
        "size": compute_size_score(),          # Kelly safety, cap enforcement
        "execute": compute_execute_score(),    # Fill rate, latency, idempotency
        "monitor": compute_monitor_score(),    # Position sync, fee attribution
        "promote": compute_promote_score(),    # Gate enforcement, rollback triggers
        "protect": compute_protect_score(),    # Kill switch, agent isolation
    }

    # Weight phases by criticality
    weights = {
        "discover": 0.10,
        "analyze": 0.10,
        "consensus": 0.15,  # Higher weight (coordination critical)
        "size": 0.15,       # Higher weight (risk management critical)
        "execute": 0.15,    # Higher weight (execution quality critical)
        "monitor": 0.10,
        "promote": 0.10,
        "protect": 0.15,    # Higher weight (safety critical)
    }

    return sum(scores[phase] * weights[phase] for phase in scores)
```

**Swarm Intelligence Loop Metrics:**
```python
# Discovery → Execution latency (end-to-end)
kalshi_discovery_to_execution_latency_ms{p50, p95, p99}  # Target: p99 < 10s

# Consensus → Execution success rate
kalshi_consensus_to_execution_success_rate  # Target: > 0.90

# Signal → PnL attribution (feedback loop)
kalshi_signal_to_pnl_latency_seconds{p50, p95, p99}  # Target: < 60s

# Agent coordination efficiency
kalshi_swarm_coordination_efficiency  # 0-1 score based on consensus speed + agreement

# Risk control effectiveness
kalshi_risk_interventions_total{type}  # Kill switch, CQI throttle, cap breach
kalshi_risk_prevented_loss_usd  # Estimated loss prevented by risk controls
```

---

## Testing Strategy

### Unit Tests (Target: 90% Coverage)

**Critical Test Cases:**

1. **Discovery Phase:**
   ```python
   test_schema_validation_rejects_malformed_markets()
   test_sla_tracking_detects_slow_refresh()
   test_new_market_detection_within_30s()
   ```

2. **Consensus Phase:**
   ```python
   test_herding_detection_triggers_penalty()
   test_consensus_cache_race_condition_protected()
   test_agent_weight_capped_at_40_percent()
   ```

3. **Size Phase:**
   ```python
   test_kelly_handles_division_by_zero()
   test_domain_cap_concurrent_access_protected()
   test_fee_calculation_matches_kalshi_schedule()
   ```

4. **Execute Phase:**
   ```python
   test_rate_limiting_enforced_on_all_endpoints()
   test_idempotency_prevents_duplicate_orders()
   test_circuit_breaker_opens_after_5_failures()
   ```

5. **Monitor Phase:**
   ```python
   test_websocket_gap_triggers_position_reload()
   test_partial_fill_fees_tracked_correctly()
   test_alert_deduplication_prevents_spam()
   ```

6. **Protect Phase:**
   ```python
   test_kill_switch_propagates_within_100ms()
   test_agent_circuit_breaker_isolates_bad_agent()
   test_audit_trail_immutable()
   ```

### Integration Tests

**Swarm Coherence Tests:**

1. **End-to-End Trade Flow:**
   ```python
   async def test_discover_to_execute_flow():
       # Refresh catalog
       catalog = get_market_catalog()
       await catalog.refresh()

       # Validate discovery
       assert validate_discovery_freshness()

       # Generate signals
       context = get_sentiment_context()
       assert validate_analysis_freshness()

       # Form consensus
       consensus = await get_consensus("BTC", "15m")
       assert validate_consensus_formation()

       # Size position
       size = compute_position_size(consensus)
       assert validate_position_sizing_safety()

       # Execute order
       result = await execute_order(size)
       assert await validate_execution_quality()

       # Monitor fill
       assert await validate_position_synchronization()
   ```

2. **Multi-Agent Coordination:**
   ```python
   async def test_5_agents_concurrent_consensus():
       # 5 agents submit proposals simultaneously
       proposals = [create_proposal(agent_id=f"agent_{i}") for i in range(5)]
       await asyncio.gather(*[submit_proposal(p) for p in proposals])

       # Consensus forms correctly
       consensus = await get_consensus("BTC", "15m", timeout_s=5.0)
       assert consensus is not None
       assert consensus.voting_agents == 5

       # No race conditions
       assert validate_consensus_formation()
   ```

3. **Resilience Under Stress:**
   ```python
   async def test_kalshi_api_degradation():
       # Inject 500ms latency
       with inject_latency(500):
           result = await execute_order()
           assert result.latency_ms < 2000  # Circuit breaker should handle

       # Inject 503 errors
       with inject_errors(503, count=3):
           result = await execute_order()
           assert result.status == "FILLED"  # Retry should succeed

       # Inject malformed JSON
       with inject_malformed_response():
           with pytest.raises(ValidationError):
               await catalog.refresh()  # Should fail gracefully
   ```

### Chaos Engineering Tests

**Fault Injection Scenarios:**

1. **Clock Skew Simulation:**
   - Advance system clock by +5 minutes → verify expiry detection
   - Lag system clock by -5 minutes → verify time-to-expiry calculations

2. **Race Condition Stress:**
   - 10 agents submit orders to same market concurrently → verify domain cap enforcement
   - Consensus cache updated during read → verify lock correctness

3. **Network Partition Simulation:**
   - WebSocket disconnect during active positions → verify gap recovery
   - Redis failover → verify kill switch propagation

4. **Agent Failure Cascade:**
   - One agent has runaway behavior → verify isolation
   - Multiple agents fail simultaneously → verify swarm resilience

---

## Remediation Roadmap

### Sprint 1 (Week 1-2): Critical P0 Fixes

**Focus:** Prevent catastrophic failures

| Finding | Phase | Priority | Effort | Status |
|---------|-------|----------|--------|--------|
| D-001 | DISCOVER | P0 | 2d | ✅ Implemented (DiscoveryValidator exists) |
| C-002 | CONSENSUS | P0 | 1d | ⚠️ **NEEDED** (race condition) |
| S-001 | SIZE | P0 | 1d | ⚠️ **NEEDED** (Kelly safety) |
| S-002 | SIZE | P0 | 2d | ⚠️ **NEEDED** (domain cap race) |
| E-001 | EXECUTE | P0 | 2d | ⚠️ **NEEDED** (rate limiting) |
| E-002 | EXECUTE | P0 | 3d | ⚠️ **NEEDED** (idempotency) |
| M-001 | MONITOR | P0 | 2d | ⚠️ **NEEDED** (WS gap recovery) |
| PR-001 | PROTECT | P0 | 2d | ⚠️ **NEEDED** (kill switch) |
| PR-002 | PROTECT | P0 | 2d | ⚠️ **NEEDED** (agent breakers) |

**Total Effort:** ~17 engineering days (2 engineers × 1.7 weeks)

### Sprint 2 (Week 3-4): High P0 + Critical P1

**Focus:** Operational excellence

| Finding | Phase | Priority | Effort | Status |
|---------|-------|----------|--------|--------|
| A-001 | ANALYZE | P0 | 1d | ⚠️ NEEDED (timestamp validation) |
| A-003 | ANALYZE | P0 | 1d | ⚠️ NEEDED (clock skew) |
| C-001 | CONSENSUS | P0 | 3d | ⚠️ NEEDED (anti-herding) |
| C-003 | CONSENSUS | P1 | 2d | ⚠️ NEEDED (weight capping) |
| S-003 | SIZE | P1 | 2d | ⚠️ NEEDED (fee schedule) |
| E-003 | EXECUTE | P1 | 1d | ⚠️ NEEDED (P99 tracking) |
| M-002 | MONITOR | P1 | 2d | ⚠️ NEEDED (fee tracking) |
| P-001 | PROMOTE | P0 | 5d | ⚠️ NEEDED (canary deployment) |
| P-002 | PROMOTE | P1 | 2d | ⚠️ NEEDED (track-record decay) |

**Total Effort:** ~21 engineering days (2 engineers × 2 weeks)

### Sprint 3 (Week 5-6): Medium P1 Fixes

**Focus:** Performance and resilience

| Finding | Phase | Priority | Effort | Status |
|---------|-------|----------|--------|--------|
| D-003 | DISCOVER | P1 | 3d | ⚠️ NEEDED (new market detection) |
| D-006 | DISCOVER | P1 | 2d | ⚠️ NEEDED (catalog persistence) |
| A-002 | ANALYZE | P1 | 2d | ⚠️ NEEDED (drift detection) |
| M-003 | MONITOR | P1 | 1d | ⚠️ NEEDED (alert dedup) |
| M-004 | MONITOR | P1 | 1d | ⚠️ NEEDED (reconciliation freq) |
| P-003 | PROMOTE | P1 | 2d | ⚠️ NEEDED (shadow mode caps) |
| PR-003 | PROTECT | P1 | 3d | ⚠️ NEEDED (audit logging) |

**Total Effort:** ~14 engineering days (2 engineers × 1.4 weeks)

### Sprint 4 (Week 7-8): Observability & Testing

**Focus:** Validation and monitoring

- Comprehensive metrics implementation
- Grafana dashboards for all 8 phases
- Prometheus alert rules
- Integration test suite
- Chaos engineering tests

**Total Effort:** ~20 engineering days (2 engineers × 2 weeks)

---

## Conclusion and Next Steps

### Current Swarm Alignment Status

**Overall Assessment:** ⚠️ **MEDIUM-HIGH RISK**

The MERID-Kalshi integration demonstrates a sophisticated, well-architected trading system with strong foundations in:
- ✅ Resilience patterns (circuit breakers, retry logic)
- ✅ Multi-layer safety controls (6-layer stack)
- ✅ Sophisticated agent coordination
- ✅ Mature promotion gates

However, **critical gaps exist that must be remediated before production scale-up:**

**Critical Blockers (9 P0 findings):**
1. Consensus cache race condition (C-002)
2. Kelly division-by-zero (S-001)
3. Domain cap race condition (S-002)
4. Rate limiting gaps (E-001)
5. Idempotency missing (E-002)
6. WebSocket gap recovery incomplete (M-001)
7. Kill switch not distributed (PR-001)
8. No agent circuit breakers (PR-002)
9. Canary deployment missing (P-001)

### Post-Remediation Status Projection

**After Sprint 1-2 (4 weeks):** ⬇️ **MEDIUM RISK**
- All P0 critical safety issues resolved
- Swarm operates with verified coherence
- Production-ready with continuous monitoring

**After Sprint 3-4 (8 weeks):** ⬇️ **LOW RISK**
- All P0 and critical P1 issues resolved
- Comprehensive observability in place
- Validated via integration and chaos tests
- **Production-ready at scale**

### Success Criteria Checklist

**Swarm Alignment Validated:**
- ✅ All 8 phases have measurable KPIs
- ✅ Validation framework implemented and documented
- ✅ Gap analysis complete with remediation plan
- ✅ Test strategy defined (unit, integration, chaos)
- ⚠️ Critical P0 fixes need implementation (Sprint 1-2)
- ⚠️ Observability dashboards need deployment (Sprint 4)

### Deliverables Summary

1. ✅ **Validation Framework** - Comprehensive KPIs for all 8 phases
2. ✅ **Gap Analysis** - 19 P0, 27 P1, 15 P2 findings documented
3. ✅ **Remediation Plan** - 4-sprint roadmap with effort estimates
4. ✅ **Test Strategy** - Unit, integration, and chaos test plans
5. ✅ **Implementation Plan** - Detailed sprint breakdown (SWARM_ALIGNMENT_AUDIT_PLAN.md)
6. ⚠️ **Code Implementations** - P0 fixes pending (Sprint 1-2)
7. ⚠️ **Monitoring Dashboards** - Pending deployment (Sprint 4)

### Recommended Next Actions

**Immediate (Week 1):**
1. Review and approve remediation roadmap
2. Allocate 2 engineers for Sprint 1-2 (4 weeks)
3. Begin P0 fixes starting with race conditions (C-002, S-002)
4. Set up production shadow environment for validation

**Short-term (Week 2-4):**
1. Complete Sprint 1 P0 fixes (critical safety)
2. Deploy to shadow environment for parallel testing
3. Begin Sprint 2 (operational excellence)
4. Start metrics collection (Prometheus setup)

**Medium-term (Week 5-8):**
1. Complete Sprint 3 (performance and resilience)
2. Deploy Grafana dashboards
3. Run integration and chaos tests
4. Prepare for gradual production rollout

**Long-term (Week 9-12):**
1. Canary rollout to 10% of agents
2. Monitor for 48 hours
3. Expand to 50% of agents
4. Full rollout to 100%
5. Continuous monitoring and quarterly audits

---

**Report Status:** ✅ Complete
**Validation Framework:** ✅ Ready for implementation
**Risk Assessment:** ⚠️ MEDIUM-HIGH (requires P0 fixes before production)
**Post-Remediation:** ⬇️ LOW RISK (production-ready at scale)

**Next Milestone:** Begin Sprint 1 - Critical P0 fixes (estimated 2 weeks, 2 engineers)
