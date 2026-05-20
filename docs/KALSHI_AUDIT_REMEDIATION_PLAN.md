# KALSHI INTEGRATION AUDIT - REMEDIATION PLAN

**Generated**: 2026-03-25
**Based On**: KALSHI_INTEGRATION_AUDIT_REPORT.md
**Status**: DRAFT - Awaiting approval

---

## OVERVIEW

This document provides a structured remediation plan for the 47 issues identified in the Kalshi Integration Deep Audit. Issues are organized by sprint (1-week cycles) with clear acceptance criteria and testing requirements.

---

## SPRINT 1 (Week 1): CRITICAL SAFETY FIXES

**Goal**: Eliminate highest-risk issues that could cause capital loss or system failures

### Story 1.1: Global Rate Limit Coordinator
**Issue**: H1.1 - Rate Limit Coordination Gap Across Clients
**Priority**: P0 - Critical
**Effort**: 5 points

**Implementation**:
```python
# New file: merid/event_venues/kalshi/rate_limit_coordinator.py

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class RateLimitBudget:
    """Global rate limit budget shared across REST/WS/FIX."""
    max_requests_per_second: int = 10
    max_ws_subscriptions_per_second: int = 5
    current_window_start: float = 0.0
    requests_in_window: int = 0
    subscriptions_in_window: int = 0
    lock: asyncio.Lock = None

    def __post_init__(self):
        if self.lock is None:
            self.lock = asyncio.Lock()

    async def acquire_request_permit(self, client_type: str) -> bool:
        """Acquire permit for one request. Returns False if rate limited."""
        async with self.lock:
            now = time.time()
            # Reset window if expired
            if now - self.current_window_start >= 1.0:
                self.current_window_start = now
                self.requests_in_window = 0
                self.subscriptions_in_window = 0

            # Check REST rate limit
            if client_type == "rest":
                if self.requests_in_window >= self.max_requests_per_second:
                    return False
                self.requests_in_window += 1
                return True

            # Check WS subscription rate limit
            elif client_type == "ws":
                if self.subscriptions_in_window >= self.max_ws_subscriptions_per_second:
                    return False
                self.subscriptions_in_window += 1
                return True

            return True

    def get_utilization(self) -> Dict[str, float]:
        """Get current rate limit utilization (0-1)."""
        return {
            "rest_utilization": self.requests_in_window / self.max_requests_per_second,
            "ws_utilization": self.subscriptions_in_window / self.max_ws_subscriptions_per_second,
        }

# Global singleton
_rate_limit_coordinator: Optional[RateLimitBudget] = None

def get_rate_limit_coordinator() -> RateLimitBudget:
    global _rate_limit_coordinator
    if _rate_limit_coordinator is None:
        _rate_limit_coordinator = RateLimitBudget()
    return _rate_limit_coordinator
```

**Integration Points**:
- `client.py`: Call `await coordinator.acquire_request_permit("rest")` before each API call
- `ws.py`: Call `await coordinator.acquire_request_permit("ws")` before subscribing
- `fix_client.py`: Call `await coordinator.acquire_request_permit("rest")` before FIX messages

**Acceptance Criteria**:
- [ ] REST client respects global rate limit
- [ ] WS client respects subscription rate limit
- [ ] Telemetry exposes utilization % (current/max)
- [ ] Alert fires when utilization >80% for >30s
- [ ] Unit test: 100 concurrent requests correctly throttled
- [ ] Integration test: REST + WS combined respect total budget

**Testing**:
```python
# tests/event_venues/kalshi/test_rate_limit_coordinator.py

import asyncio
import pytest
from merid.event_venues.kalshi.rate_limit_coordinator import (
    RateLimitBudget,
    get_rate_limit_coordinator,
)

@pytest.mark.asyncio
async def test_rest_rate_limit():
    """Test REST rate limiting."""
    budget = RateLimitBudget(max_requests_per_second=10)

    # First 10 should succeed
    for _ in range(10):
        assert await budget.acquire_request_permit("rest")

    # 11th should fail
    assert not await budget.acquire_request_permit("rest")

    # After 1s, should reset
    await asyncio.sleep(1.1)
    assert await budget.acquire_request_permit("rest")

@pytest.mark.asyncio
async def test_ws_rate_limit():
    """Test WebSocket subscription rate limiting."""
    budget = RateLimitBudget(max_ws_subscriptions_per_second=5)

    # First 5 should succeed
    for _ in range(5):
        assert await budget.acquire_request_permit("ws")

    # 6th should fail
    assert not await budget.acquire_request_permit("ws")

@pytest.mark.asyncio
async def test_utilization_metrics():
    """Test utilization percentage calculation."""
    budget = RateLimitBudget(max_requests_per_second=10)

    # 5 requests = 50% utilization
    for _ in range(5):
        await budget.acquire_request_permit("rest")

    util = budget.get_utilization()
    assert util["rest_utilization"] == 0.5
```

---

### Story 1.2: Order Idempotency Keys
**Issue**: H5.1 - No Order Deduplication on Retry
**Priority**: P0 - Critical
**Effort**: 3 points

**Implementation**:
```python
# merid/event_venues/kalshi/order_deduplication.py

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

@dataclass
class PendingOrder:
    """Cached order for deduplication."""
    idempotency_key: str
    ticker: str
    side: str
    price_cents: int
    count: int
    submitted_at: datetime
    order_id: Optional[str] = None  # Set when response received

class OrderDeduplicationCache:
    """Cache of recently submitted orders for deduplication."""

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, PendingOrder] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def generate_key(
        self,
        ticker: str,
        side: str,
        price_cents: int,
        count: int,
    ) -> str:
        """Generate unique idempotency key for order."""
        return str(uuid.uuid4())

    def get_or_create(
        self,
        ticker: str,
        side: str,
        price_cents: int,
        count: int,
    ) -> tuple[str, bool]:
        """Get existing idempotency key or create new one.

        Returns:
            (idempotency_key, is_duplicate)
        """
        # Check cache for exact match
        for key, pending in list(self._cache.items()):
            # Prune expired entries
            if datetime.now(timezone.utc) - pending.submitted_at > self._ttl:
                del self._cache[key]
                continue

            # Check for duplicate order
            if (
                pending.ticker == ticker
                and pending.side == side
                and pending.price_cents == price_cents
                and pending.count == count
            ):
                return pending.idempotency_key, True

        # Generate new key
        key = self.generate_key(ticker, side, price_cents, count)
        self._cache[key] = PendingOrder(
            idempotency_key=key,
            ticker=ticker,
            side=side,
            price_cents=price_cents,
            count=count,
            submitted_at=datetime.now(timezone.utc),
        )
        return key, False

    def mark_completed(self, idempotency_key: str, order_id: str) -> None:
        """Mark order as completed (response received)."""
        if idempotency_key in self._cache:
            self._cache[idempotency_key].order_id = order_id

# Global cache
_order_cache: Optional[OrderDeduplicationCache] = None

def get_order_cache() -> OrderDeduplicationCache:
    global _order_cache
    if _order_cache is None:
        _order_cache = OrderDeduplicationCache()
    return _order_cache
```

**Integration**: Modify `client.py` `create_order()`:
```python
async def create_order(self, ticker: str, side: str, price_cents: int, count: int):
    cache = get_order_cache()
    idempotency_key, is_duplicate = cache.get_or_create(ticker, side, price_cents, count)

    if is_duplicate:
        logger.warning(f"Duplicate order detected, using existing key: {idempotency_key}")

    # Add idempotency key to request headers
    headers = {"X-Idempotency-Key": idempotency_key}

    # Submit order...
    result = await self._post("/orders", payload, headers=headers)

    if result.success:
        cache.mark_completed(idempotency_key, result.data["order_id"])
```

**Acceptance Criteria**:
- [ ] Idempotency key generated for every order
- [ ] Duplicate orders detected and skipped
- [ ] Cache expires after 5 minutes
- [ ] Telemetry tracks deduplication rate (% orders deduplicated)
- [ ] Unit test: duplicate order returns same key
- [ ] Integration test: retry after timeout doesn't create duplicate

---

### Story 1.3: Consensus Timeout Enforcement
**Issue**: H3.1 - No Consensus Timeout or Deadlock Detection
**Priority**: P0 - Critical
**Effort**: 3 points

**Implementation**:
```python
# merid/swarm/consensus_aggregator.py (modify)

import asyncio
from datetime import datetime, timezone, timedelta

class ConsensusAggregator:
    def __init__(self, timeout_seconds: float = 10.0):
        self._timeout = timeout_seconds
        self._fallback_decision = "neutral"  # Safe default

    async def aggregate_with_timeout(
        self,
        proposals: List[AgentProposal],
        fallback_probability: float = 0.5,
    ) -> ConsensusView:
        """Aggregate proposals with timeout."""
        try:
            # Run aggregation with timeout
            result = await asyncio.wait_for(
                self._aggregate_internal(proposals),
                timeout=self._timeout,
            )
            return result

        except asyncio.TimeoutError:
            logger.error(
                f"Consensus timeout after {self._timeout}s "
                f"with {len(proposals)} proposals"
            )
            # Return stale consensus with fallback
            return ConsensusView(
                asset=proposals[0].asset if proposals else "unknown",
                timeframe=proposals[0].timeframe if proposals else "unknown",
                timestamp=datetime.now(timezone.utc),
                status=ConsensusStatus.STALE,
                consensus_direction=self._fallback_decision,
                consensus_probability=fallback_probability,
                consensus_confidence=0.0,  # Zero confidence for timeout
                total_agents=len(proposals),
                voting_agents=0,
                direction_breakdown={},
                size_band="halted",  # Don't trade on timeout
                size_rationale="Consensus timeout - halting trading",
                confidence_factors=["timeout"],
                disagreement_flags=["consensus_timeout"],
                raw_proposals=proposals,
            )

    async def _aggregate_internal(
        self,
        proposals: List[AgentProposal],
    ) -> ConsensusView:
        """Internal aggregation logic (existing code)."""
        # ... existing implementation ...
```

**Acceptance Criteria**:
- [ ] Consensus completes within 10s or times out
- [ ] Timeout returns STALE status with halted size_band
- [ ] Telemetry tracks consensus duration P95/P99
- [ ] Alert fires if consensus timeout occurs
- [ ] Unit test: slow agent triggers timeout
- [ ] Integration test: timeout doesn't crash orchestrator

---

### Story 1.4: WebSocket Queue Monitoring
**Issue**: H1.2 - WebSocket Message Queue Unbounded Growth Risk
**Priority**: P0 - Critical
**Effort**: 2 points

**Implementation**: Modify `ws.py`:
```python
# merid/event_venues/kalshi/ws.py

class KalshiWebSocket(EventVenueStream):
    def __init__(self, config: Optional[KalshiConfig] = None):
        # ... existing init ...
        self._msg_queue: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self._queue_full_count: int = 0
        self._queue_drops: int = 0
        self._last_queue_alert: float = 0.0

    async def _enqueue_message(self, msg: Dict[str, Any]) -> None:
        """Enqueue message with backpressure handling."""
        try:
            # Try to enqueue without blocking
            self._msg_queue.put_nowait(msg)
        except asyncio.QueueFull:
            self._queue_full_count += 1

            # Priority: order fills > quotes > trades
            priority = self._get_message_priority(msg)

            if priority == "high":
                # For order fills, wait briefly
                try:
                    await asyncio.wait_for(
                        self._msg_queue.put(msg),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    self._queue_drops += 1
                    logger.error(f"Dropped high-priority message: {msg.get('type')}")
            else:
                # Drop low-priority messages
                self._queue_drops += 1
                logger.warning(f"Dropped low-priority message: {msg.get('type')}")

            # Alert if queue full for extended period
            now = time.time()
            if now - self._last_queue_alert > 60:
                fullness_pct = (self._msg_queue.qsize() / 4096) * 100
                if fullness_pct > 90:
                    logger.error(
                        f"WebSocket queue critical: {fullness_pct:.1f}% full, "
                        f"{self._queue_drops} drops"
                    )
                    self._last_queue_alert = now

    def _get_message_priority(self, msg: Dict[str, Any]) -> str:
        """Determine message priority for backpressure."""
        msg_type = msg.get("type", "")
        if "order" in msg_type or "fill" in msg_type:
            return "high"
        elif "quote" in msg_type or "ticker" in msg_type:
            return "medium"
        else:
            return "low"

    def get_queue_metrics(self) -> Dict[str, Any]:
        """Get queue health metrics."""
        qsize = self._msg_queue.qsize()
        fullness_pct = (qsize / 4096) * 100
        return {
            "queue_size": qsize,
            "queue_capacity": 4096,
            "fullness_pct": fullness_pct,
            "queue_full_count": self._queue_full_count,
            "dropped_messages": self._queue_drops,
        }
```

**Acceptance Criteria**:
- [ ] Queue fullness tracked and exposed in telemetry
- [ ] Messages prioritized: order fills > quotes > trades
- [ ] Alert fires when queue >90% full for >10s
- [ ] Dropped messages logged with type and count
- [ ] Unit test: queue full drops low-priority messages
- [ ] Integration test: burst of 10k messages handled gracefully

---

### Story 1.5: Pre-Trade Daily Loss Cap Enforcement
**Issue**: H8.3 - Daily Loss Cap Not Enforced Pre-Trade
**Priority**: P0 - Critical
**Effort**: 3 points

**Implementation**: Modify `kalshi_risk.py`:
```python
# merid/event_venues/kalshi/kalshi_risk.py

@dataclass
class SessionRiskState:
    """Track session-level risk state."""
    session_start: datetime
    starting_equity_cents: float
    current_equity_cents: float
    session_loss_cap_pct: float = 5.0

    @property
    def session_loss_cents(self) -> float:
        """Current session loss in cents."""
        return self.starting_equity_cents - self.current_equity_cents

    @property
    def session_loss_pct(self) -> float:
        """Current session loss as % of starting equity."""
        if self.starting_equity_cents <= 0:
            return 0.0
        return (self.session_loss_cents / self.starting_equity_cents) * 100

    @property
    def remaining_loss_budget_cents(self) -> float:
        """Remaining loss budget before hitting cap."""
        max_loss = (self.session_loss_cap_pct / 100) * self.starting_equity_cents
        return max_loss - self.session_loss_cents

    def can_risk_amount(self, risk_amount_cents: float) -> tuple[bool, str]:
        """Check if we can risk additional amount without exceeding cap.

        Returns:
            (allowed, reason)
        """
        remaining = self.remaining_loss_budget_cents
        if risk_amount_cents > remaining:
            return False, (
                f"Order risk {risk_amount_cents}¢ exceeds remaining loss budget "
                f"{remaining:.0f}¢ (session loss {self.session_loss_pct:.1f}%, "
                f"cap {self.session_loss_cap_pct}%)"
            )
        return True, ""

class KalshiRiskManager:
    def __init__(self):
        self._session_state: Optional[SessionRiskState] = None

    def init_session(self, starting_equity_cents: float, loss_cap_pct: float = 5.0):
        """Initialize session risk state."""
        self._session_state = SessionRiskState(
            session_start=datetime.now(timezone.utc),
            starting_equity_cents=starting_equity_cents,
            current_equity_cents=starting_equity_cents,
            session_loss_cap_pct=loss_cap_pct,
        )

    def update_equity(self, current_equity_cents: float):
        """Update current equity after trade."""
        if self._session_state:
            self._session_state.current_equity_cents = current_equity_cents

    def check_pre_trade_risk(
        self,
        price_cents: int,
        contracts: int,
    ) -> tuple[bool, str]:
        """Check if order is allowed given current risk state.

        Returns:
            (allowed, reason)
        """
        if not self._session_state:
            return False, "Session risk state not initialized"

        # Worst-case loss: full position value (binary contracts)
        worst_case_loss = price_cents * contracts

        # Check against remaining budget
        return self._session_state.can_risk_amount(worst_case_loss)
```

**Integration**: Modify `order_router.py`:
```python
async def route_order(intent: OrderIntent) -> OrderResult:
    # Pre-trade risk check
    risk_mgr = get_kalshi_risk()
    allowed, reason = risk_mgr.check_pre_trade_risk(
        intent.price_cents,
        intent.count,
    )

    if not allowed:
        logger.warning(f"Order rejected by pre-trade risk check: {reason}")
        return OrderResult(
            status="rejected",
            error=reason,
            timestamp=datetime.now(timezone.utc),
        )

    # Continue with execution...
```

**Acceptance Criteria**:
- [ ] Session risk state initialized at startup
- [ ] Pre-trade check rejects orders exceeding budget
- [ ] Telemetry exposes remaining loss budget %
- [ ] Alert fires when budget <25% remaining
- [ ] Unit test: order rejected when budget insufficient
- [ ] Integration test: multiple orders correctly deplete budget

---

### Story 1.6: Kill Switch CI/CD Testing
**Issue**: H8.1 - Kill Switch Not Tested in CI/CD
**Priority**: P0 - Critical
**Effort**: 2 points

**Implementation**:
```python
# tests/safeguards/test_kill_switch.py

import json
import pytest
from pathlib import Path
from merid.safeguards.swarm_integrity_guard import check_swarm_integrity

@pytest.fixture
def kill_switch_file(tmp_path):
    """Create temporary kill switch file."""
    ks_file = tmp_path / "kill_switch.json"
    yield ks_file
    # Cleanup
    if ks_file.exists():
        ks_file.unlink()

def test_kill_switch_activation(kill_switch_file):
    """Test that kill switch halts trading when activated."""
    # Initially inactive
    kill_switch_file.write_text(json.dumps({"active": False}))

    # Verify trading allowed
    from merid.guardrails import get_kill_switch
    ks = get_kill_switch(str(kill_switch_file))
    assert not ks.is_active()

    # Activate kill switch
    ks.activate("Test emergency stop")

    # Verify file updated
    data = json.loads(kill_switch_file.read_text())
    assert data["active"] is True
    assert "Test emergency stop" in data["reason"]

    # Verify trading blocked
    assert ks.is_active()

    # Deactivate
    ks.deactivate()
    assert not ks.is_active()

def test_kill_switch_blocks_order_router(kill_switch_file):
    """Test that kill switch blocks order routing."""
    from merid.event_venues.kalshi.order_router import route_order, OrderIntent

    ks = get_kill_switch(str(kill_switch_file))
    ks.activate("Test")

    intent = OrderIntent(
        ticker="KXBTC-TEST",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
    )

    result = route_order(intent)
    assert result.status == "rejected"
    assert "kill switch" in result.error.lower()

@pytest.mark.integration
def test_kill_switch_staging_drill():
    """Integration test: activate kill switch in staging and verify all trading halts."""
    # This would run in staging environment weekly
    # 1. Activate kill switch
    # 2. Attempt to place orders
    # 3. Verify all orders rejected
    # 4. Deactivate kill switch
    # 5. Verify trading resumes
    pass
```

**Acceptance Criteria**:
- [ ] Unit test activates and deactivates kill switch
- [ ] Integration test verifies order routing blocked
- [ ] CI/CD runs kill switch test on every commit
- [ ] Staging drill runs weekly (automated)
- [ ] Kill switch status exposed in health endpoint
- [ ] Manual drill scheduled quarterly with runbook

---

## SPRINT 2 (Week 2): TIMEOUT & ATOMIC OPERATIONS

### Story 2.1: Agent Timeout Enforcement
**Issue**: H2.1 - No Timeout Enforcement for Agent Inference
**Priority**: P0 - Critical
**Effort**: 3 points

### Story 2.2: PnL Reconciliation Loop
**Issue**: H6.2 - PnL Attribution Not Validated Against API
**Priority**: P0 - Critical
**Effort**: 5 points

### Story 2.3: Atomic Bankroll Enforcement
**Issue**: H4.2 - Bankroll Fraction Enforcement Not Atomic
**Priority**: P0 - Critical
**Effort**: 3 points

### Story 2.4: Stop Loss Atomic Enforcement
**Issue**: H6.1 - Stop Loss Rules Not Enforced Atomically
**Priority**: P0 - Critical
**Effort**: 3 points

### Story 2.5: Circuit Breaker State Sharing
**Issue**: H8.2 - Circuit Breaker State Not Shared Across Processes
**Priority**: P0 - Critical
**Effort**: 5 points

---

## SPRINT 3 (Week 3): POSITION SIZING & VOLATILITY

### Story 3.1: Volatility Adjustment for Position Sizing
**Issue**: H4.1 - Position Sizing Lacks Volatility Surface Integration
**Priority**: P1 - High
**Effort**: 8 points

### Story 3.2: Sentiment Staleness Tracking
**Issue**: H2.2 - Sentiment Score Staleness Not Tracked
**Priority**: P1 - High
**Effort**: 2 points

### Story 3.3: Agent Weight Update Auditing
**Issue**: H3.2 - Agent Weight Updates Not Audited
**Priority**: P1 - High
**Effort**: 3 points

---

## SPRINT 4 (Week 4): SCHEMA VALIDATION & OBSERVABILITY

### Story 4.1: API Response Schema Validation
**Issue**: M1.1 - No Schema Validation for Kalshi API Responses
**Priority**: P1 - High
**Effort**: 5 points

### Story 4.2: Distributed Tracing
**Issue**: X4 - No Distributed Tracing for Trade Lifecycle
**Priority**: P1 - High
**Effort**: 8 points

### Story 4.3: Unified Observability Dashboard
**Issue**: X3 - No Unified Observability Dashboard
**Priority**: P1 - High
**Effort**: 8 points

---

## SPRINT 5-8: MEDIUM & LOW PRIORITY

_(Additional sprints cover remaining Medium and Low severity issues)_

---

## TESTING STRATEGY

### Unit Tests
- Each story includes unit tests
- Coverage target: >90% for new code
- Run on every commit (CI/CD)

### Integration Tests
- Test cross-component interactions
- Run nightly in staging
- Include failure injection scenarios

### Load Tests
- Simulate 100+ concurrent markets
- Measure latency P95/P99 under load
- Run weekly in staging

### Chaos Tests
- Inject failures: API timeouts, WS disconnects, bad data
- Measure MTTR (mean time to recovery)
- Run monthly in staging

### Production Drills
- Kill switch activation drill (quarterly)
- Circuit breaker coordination test (monthly)
- PnL reconciliation spot check (weekly)

---

## ROLLOUT STRATEGY

### Phase 1: Staging Deployment (Week 1-2)
- Deploy Sprint 1 fixes to staging
- Run 1 week of paper trading
- Monitor telemetry for regressions
- User acceptance testing

### Phase 2: Canary Deployment (Week 3)
- Deploy to 10% of production traffic
- Monitor error rates, latency
- Gradual rollout to 50%, then 100%

### Phase 3: Full Production (Week 4)
- Deploy to all production instances
- Monitor for 48h with oncall
- Publish deployment report

---

## SUCCESS METRICS

### Pre-Deployment
- [ ] All Sprint 1 unit tests passing
- [ ] Integration tests passing in staging
- [ ] Load tests show <5% latency regression
- [ ] Manual testing sign-off from QA

### Post-Deployment
- [ ] Zero critical incidents in first week
- [ ] P95 latency within SLO targets
- [ ] Error rate <1% (down from baseline)
- [ ] No duplicate orders observed
- [ ] No consensus timeouts >10s
- [ ] Kill switch drill successful

---

## APPENDIX: CODE REVIEW CHECKLIST

For each remediation PR:
- [ ] Unit tests added with >90% coverage
- [ ] Integration tests added for cross-component logic
- [ ] Telemetry added (metrics, logs, alerts)
- [ ] Documentation updated (docstrings, README)
- [ ] Performance tested (no significant regression)
- [ ] Security reviewed (no new vulnerabilities)
- [ ] Backward compatibility verified
- [ ] Rollback plan documented

---

**END OF REMEDIATION PLAN**
