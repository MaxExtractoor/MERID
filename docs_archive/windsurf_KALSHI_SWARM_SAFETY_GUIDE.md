# Kalshi Swarm Safety Guide
**Critical Failure Modes & Defense Patterns for Multi-Agent Trading**

---

## ⚠️ Core Safety Principle

**NO AGENT TALKS DIRECTLY TO KALSHI OR MUTATES TRUTH STATE**

All venue interaction goes through:
- Single **Venue Controller** (execution pipeline)
- Central **Risk Engine** (deterministic constraints)
- Unified **Event Log** (audit trail & replay)

---

## 🔴 Hidden Failure Modes in High-Frequency Kalshi

### 1. Race Conditions on Shared Venue State

**Problem:**
Multiple agents read stale view of positions/risk and all try to "fill budget," overshooting limits.

**Example:**
```python
# DANGEROUS - Multiple agents doing this simultaneously
current_position = await portfolio.get_position("BTC_15M")
if current_position < MAX_POSITION:
    await kalshi.place_order(qty=100)  # Race! Both agents execute
```

**Defense:**
```python
# SAFE - Single execution pipeline with atomic state updates
class VenueController:
    async def execute_intent(self, intent: OrderIntent):
        async with self._position_lock:
            current = await self._portfolio.get_position(intent.market_ticker)
            allowed = MAX_POSITION - current
            if intent.qty > allowed:
                return RejectedExecution(reason="position_limit")
            # Atomic: check + execute + update
            order_id = await self._client.place_order(intent)
            await self._portfolio.update_position(intent.market_ticker, +intent.qty)
            return order_id
```

**Key Pattern:** Atomic check-execute-update under lock/transaction.

---

### 2. Timeout/Retry Ambiguity → Ghost Orders

**Problem:**
Agent times out on `POST /orders`, retries, and both succeed → double exposure.

**Example:**
```python
# DANGEROUS - No idempotency
async def place_order_with_retry(market, qty):
    for attempt in range(3):
        try:
            return await kalshi.post_order(market, qty)
        except TimeoutError:
            continue  # DANGER: Both requests might succeed!
```

**Defense:**
```python
# SAFE - Idempotent client_order_id
async def place_order_idempotent(market, qty, intent_id):
    # Kalshi deduplicates on client_order_id
    client_order_id = f"{intent_id}_{market}"
    
    for attempt in range(3):
        try:
            return await kalshi.post_order(
                market=market,
                qty=qty,
                client_order_id=client_order_id  # Idempotent key
            )
        except TimeoutError:
            # Safe to retry - Kalshi won't duplicate
            await asyncio.sleep(backoff(attempt))
            continue
```

**Key Pattern:** Use `client_order_id` for idempotency, retry safety.

---

### 3. Implicit State Sharing Without Synchronization

**Problem:**
Agents read/write shared DB rows, Redis keys, or in-memory dicts without concurrency control.

**Example:**
```python
# DANGEROUS - No synchronization
class SharedRiskState:
    exposure = {}  # Multiple agents mutate this
    
async def agent_a():
    current = SharedRiskState.exposure["BTC"]
    # ... decision logic ...
    SharedRiskState.exposure["BTC"] = current + 100  # Race!
    
async def agent_b():
    current = SharedRiskState.exposure["BTC"]  # Reads stale value
    SharedRiskState.exposure["BTC"] = current + 50   # Overwrites agent_a!
```

**Defense:**
```python
# SAFE - Event-sourced state with atomic operations
class RiskStateStore:
    def __init__(self):
        self._events = []
        self._lock = asyncio.Lock()
    
    async def record_exposure_change(self, event: ExposureEvent):
        async with self._lock:
            self._events.append(event)
            return self._compute_current_exposure()
    
    def _compute_current_exposure(self):
        # Rebuild from events (event sourcing)
        exposure = {}
        for event in self._events:
            exposure[event.market] = exposure.get(event.market, 0) + event.delta
        return exposure
```

**Key Pattern:** Event sourcing or transactional state, never shared mutable state.

---

### 4. Unbounded Context & Explainability Bloat

**Problem:**
LLM critic/explainer agents append logs/transcripts indefinitely, hit context limits, silently drop constraints.

**Example:**
```python
# DANGEROUS - Unbounded context accumulation
class CriticAgent:
    def __init__(self):
        self.full_transcript = []  # Grows forever
    
    async def critique(self, proposal):
        self.full_transcript.append(proposal)
        # Send ALL history to LLM (eventually hits 128k token limit)
        response = await llm.complete(
            messages=[{"role": "user", "content": str(self.full_transcript)}]
        )
```

**Defense:**
```python
# SAFE - Sliding window + summarization
class CriticAgent:
    def __init__(self, max_context_items=10):
        self._recent_items = deque(maxlen=max_context_items)
        self._summary = None
    
    async def critique(self, proposal):
        self._recent_items.append(proposal)
        
        # Every N items, summarize and reset
        if len(self._recent_items) == self._recent_items.maxlen:
            self._summary = await self._summarize(list(self._recent_items))
            self._recent_items.clear()
        
        context = [self._summary] if self._summary else []
        context.extend(list(self._recent_items))
        
        response = await llm.complete(messages=context)
```

**Key Pattern:** Sliding window + periodic summarization, bounded context.

---

### 5. Rate-Limit Starvation & Herd Effects

**Problem:**
Many agents independently poll/place orders, one noisy component exhausts venue's rate budget.

**Kalshi Rate Limits (per tier):**
| Tier     | Read/s | Write/s |
|----------|--------|---------|
| Basic    | 20     | 10      |
| Advanced | 30     | 30      |
| Premier  | 100    | 100     |
| Prime    | 400    | 400     |

**Example:**
```python
# DANGEROUS - No coordination
async def scanner_agent():
    while True:
        for market in ALL_MARKETS:  # 200 markets
            await kalshi.get_market(market)  # Hammers API!
        await asyncio.sleep(1)

async def trader_agent():
    await kalshi.place_order(...)  # Gets 429 because scanner exhausted budget
```

**Defense:**
```python
# SAFE - Global token bucket rate limiter
class KalshiRateLimiter:
    def __init__(self, tier="premier"):
        limits = {
            "basic": {"read": 20, "write": 10},
            "premier": {"read": 100, "write": 100},
        }
        self._read_bucket = TokenBucket(rate=limits[tier]["read"])
        self._write_bucket = TokenBucket(rate=limits[tier]["write"])
    
    async def acquire(self, action_type: str, priority: int = 5) -> bool:
        bucket = self._read_bucket if action_type == "read" else self._write_bucket
        return await bucket.acquire(priority=priority)

# Usage
limiter = KalshiRateLimiter(tier="premier")

async def scanner_agent():
    if await limiter.acquire("read", priority=3):  # Low priority
        await kalshi.get_market(market)

async def trader_agent():
    if await limiter.acquire("write", priority=10):  # High priority
        await kalshi.place_order(...)
```

**Key Pattern:** Shared token bucket, priority queuing, graceful degradation.

---

### 6. Failure to Verify Agent Outputs

**Problem:**
Agents skip verification, repeat steps, don't notice termination conditions.

**Example:**
```python
# DANGEROUS - No verification
async def trading_agent():
    signal = await forecaster.predict(market)
    # Blindly execute without checking signal quality
    await kalshi.place_order(signal.market, signal.qty)
```

**Defense:**
```python
# SAFE - Multi-stage verification
async def trading_agent():
    signal = await forecaster.predict(market)
    
    # Stage 1: Signal quality check
    if signal.confidence < MIN_CONFIDENCE:
        return Rejected(reason="low_confidence")
    
    # Stage 2: Risk check
    risk_decision = await risk_engine.assess(signal)
    if not risk_decision.approved:
        return Rejected(reason=risk_decision.reason)
    
    # Stage 3: Critic review (optional)
    if ENABLE_CRITIC:
        critique = await critic.evaluate(signal)
        if critique.veto:
            return Rejected(reason=critique.rationale)
    
    # Only after all checks pass
    await execution_pipeline.execute(signal)
```

**Key Pattern:** Multi-stage verification, explicit rejection reasons, audit trail.

---

## 🏗️ Production-Safe Kalshi Integration Architecture

### Single WS Connection with Topic Routing

```python
# merid_core/kalshi/ws_bridge.py
import asyncio
import json
import time
from typing import Callable, Dict, List, Awaitable
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64

WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"
Handler = Callable[[Dict], Awaitable[None]]


def _sign_pss_text(private_key, text: str) -> str:
    """PSS signature for Kalshi WS auth."""
    message = text.encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _create_headers(private_key, key_id: str) -> Dict[str, str]:
    """Create auth headers for WS connection."""
    ts = str(int(time.time() * 1000))
    path = "/trade-api/ws/v2"
    msg = ts + "GET" + path
    sig = _sign_pss_text(private_key, msg)
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


class KalshiWebSocketBridge:
    """
    Single Kalshi WS connection with topic-based routing to agents.
    
    Prevents:
    - Multiple WS connections per agent (rate limit waste)
    - Direct agent access to venue (coupling)
    - Race conditions on shared socket state
    """
    
    def __init__(self, key_id: str, private_key_path: str):
        self._key_id = key_id
        self._private_key_path = private_key_path
        self._subscribers: Dict[str, List[Handler]] = {}
        self._markets: List[str] = []
        self._stop = asyncio.Event()
        self._reconnect_delay = 1.0
        
    async def subscribe_topic(self, topic: str, handler: Handler) -> None:
        """Subscribe to normalized topic (e.g., 'kalshi.orderbook')."""
        self._subscribers.setdefault(topic, []).append(handler)
    
    def set_markets(self, market_tickers: List[str]) -> None:
        """Set markets to subscribe to on connect/reconnect."""
        self._markets = market_tickers
    
    async def run(self) -> None:
        """Main WS loop with auto-reconnect."""
        with open(self._private_key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        headers = _create_headers(private_key, self._key_id)
        
        while not self._stop.is_set():
            try:
                async with websockets.connect(WS_URL, additional_headers=headers) as ws:
                    await self._subscribe_all(ws)
                    self._reconnect_delay = 1.0  # Reset on successful connect
                    
                    async for raw in ws:
                        await self._route_message(raw)
                        
            except Exception as e:
                print(f"Kalshi WS error, reconnecting in {self._reconnect_delay}s: {e}")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)  # Exp backoff
    
    async def _subscribe_all(self, ws) -> None:
        """Subscribe to all configured markets."""
        for ticker in self._markets:
            msg = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta", "fill", "order_status"],
                    "market_ticker": ticker
                },
            }
            await ws.send(json.dumps(msg))
    
    async def _route_message(self, raw: str) -> None:
        """Route incoming WS message to subscribed handlers."""
        msg = json.loads(raw)
        msg_type = msg.get("type")
        
        # Map Kalshi message types to internal topics
        topic_map = {
            "orderbook_snapshot": "kalshi.orderbook",
            "orderbook_delta": "kalshi.orderbook",
            "fill": "kalshi.fills",
            "order_status": "kalshi.orders",
            "error": "kalshi.errors",
        }
        
        topic = topic_map.get(msg_type)
        if not topic:
            return
        
        handlers = self._subscribers.get(topic, [])
        for handler in handlers:
            try:
                await handler(msg)
            except Exception as e:
                print(f"Handler error for {topic}: {e}")
    
    async def stop(self) -> None:
        """Graceful shutdown."""
        self._stop.set()
```

---

### Execution Pipeline with Risk Gate & Rate Limiting

```python
# merid_core/kalshi/execution_pipeline.py
from dataclasses import dataclass
from typing import Optional
from merid_core.risk.kalshi_risk import KalshiRiskEngine, RiskDecision
from merid_core.kalshi.rest_client import KalshiRestClient
from merid_core.kalshi.rate_limiter import KalshiRateLimiter


@dataclass
class OrderIntent:
    """Agent's trading intention (not yet executed)."""
    session_id: str
    agent_id: str
    market_ticker: str
    side: str         # "buy_yes" | "sell_yes" | "buy_no" | "sell_no"
    qty: int
    price: float      # Kalshi prices in cents (1-99)
    client_tag: str   # Unique per intent (idempotency key)


@dataclass
class ExecutionOutcome:
    """Result of execution attempt."""
    intent: OrderIntent
    risk_decision: RiskDecision
    order_id: Optional[str]
    status: str       # "rejected_risk" | "rejected_rate_limit" | "submitted" | "error"
    error_message: Optional[str] = None


class KalshiExecutionPipeline:
    """
    Single execution path for all Kalshi orders.
    
    Enforces:
    - Risk limits (position, notional, drawdown)
    - Rate limiting (per tier)
    - Idempotency (via client_order_id)
    - Audit trail (all attempts logged)
    """
    
    def __init__(
        self,
        client: KalshiRestClient,
        risk_engine: KalshiRiskEngine,
        rate_limiter: KalshiRateLimiter,
        audit_logger
    ):
        self._client = client
        self._risk = risk_engine
        self._limiter = rate_limiter
        self._audit = audit_logger
    
    async def execute(self, intent: OrderIntent) -> ExecutionOutcome:
        """
        Execute order intent through full safety pipeline.
        
        Stages:
        1. Risk check (limits, exposure, drawdown)
        2. Rate limit check (acquire token)
        3. Submit to Kalshi (idempotent)
        4. Log outcome
        """
        
        # Stage 1: Risk Assessment
        risk_decision = await self._risk.assess(intent)
        
        if not risk_decision.allowed:
            outcome = ExecutionOutcome(
                intent=intent,
                risk_decision=risk_decision,
                order_id=None,
                status="rejected_risk",
            )
            await self._audit.log_rejection(outcome)
            return outcome
        
        # Adjust quantity based on risk limits
        adj_qty = risk_decision.max_size or intent.qty
        if adj_qty <= 0:
            outcome = ExecutionOutcome(
                intent=intent,
                risk_decision=risk_decision,
                order_id=None,
                status="rejected_risk",
                error_message="Adjusted quantity <= 0"
            )
            await self._audit.log_rejection(outcome)
            return outcome
        
        # Stage 2: Rate Limit Check
        priority = 10  # High priority for execution vs polling
        if not await self._limiter.acquire("write", priority=priority):
            outcome = ExecutionOutcome(
                intent=intent,
                risk_decision=risk_decision,
                order_id=None,
                status="rejected_rate_limit",
            )
            await self._audit.log_rejection(outcome)
            return outcome
        
        # Stage 3: Submit to Kalshi (idempotent via client_order_id)
        try:
            order_id = await self._client.place_order(
                market_ticker=intent.market_ticker,
                side=intent.side,
                qty=adj_qty,
                price=intent.price,
                client_order_id=intent.client_tag,  # Idempotency key
            )
            
            outcome = ExecutionOutcome(
                intent=intent,
                risk_decision=risk_decision,
                order_id=order_id,
                status="submitted",
            )
            await self._audit.log_execution(outcome)
            return outcome
            
        except Exception as e:
            outcome = ExecutionOutcome(
                intent=intent,
                risk_decision=risk_decision,
                order_id=None,
                status="error",
                error_message=str(e),
            )
            await self._audit.log_error(outcome)
            return outcome
```

---

### Token Bucket Rate Limiter

```python
# merid_core/kalshi/rate_limiter.py
import asyncio
import time
from dataclasses import dataclass
from typing import Dict
import heapq


@dataclass
class RateLimitRequest:
    """Prioritized rate limit request."""
    priority: int  # Higher = more important
    timestamp: float
    future: asyncio.Future
    
    def __lt__(self, other):
        # Higher priority first, then FIFO
        return (self.priority, -self.timestamp) > (other.priority, -other.timestamp)


class TokenBucket:
    """Token bucket for rate limiting with priority queue."""
    
    def __init__(self, rate: float, burst: float = None):
        self.rate = rate          # tokens/second
        self.burst = burst or rate  # max tokens
        self._tokens = self.burst
        self._last_refill = time.time()
        self._queue: List[RateLimitRequest] = []
        self._lock = asyncio.Lock()
        self._refill_task = None
    
    async def acquire(self, priority: int = 5) -> bool:
        """Acquire a token, blocking if necessary with priority."""
        async with self._lock:
            self._refill_tokens()
            
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            
            # No tokens available, enqueue with priority
            future = asyncio.Future()
            request = RateLimitRequest(
                priority=priority,
                timestamp=time.time(),
                future=future,
            )
            heapq.heappush(self._queue, request)
            
            # Start refill task if not running
            if self._refill_task is None or self._refill_task.done():
                self._refill_task = asyncio.create_task(self._refill_loop())
        
        # Wait for token to become available
        return await future
    
    def _refill_tokens(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.rate
        self._tokens = min(self._burst, self._tokens + new_tokens)
        self._last_refill = now
    
    async def _refill_loop(self):
        """Background task to refill and process queue."""
        while self._queue:
            await asyncio.sleep(1.0 / self.rate)  # Wait for next token
            
            async with self._lock:
                self._refill_tokens()
                
                # Process waiting requests in priority order
                while self._queue and self._tokens >= 1:
                    request = heapq.heappop(self._queue)
                    self._tokens -= 1
                    request.future.set_result(True)


class KalshiRateLimiter:
    """
    Global rate limiter for Kalshi API.
    
    Tier limits:
    - Basic: 20 read/s, 10 write/s
    - Advanced: 30 read/s, 30 write/s
    - Premier: 100 read/s, 100 write/s
    - Prime: 400 read/s, 400 write/s
    """
    
    TIER_LIMITS = {
        "basic": {"read": 20, "write": 10},
        "advanced": {"read": 30, "write": 30},
        "premier": {"read": 100, "write": 100},
        "prime": {"read": 400, "write": 400},
    }
    
    def __init__(self, tier: str = "premier"):
        limits = self.TIER_LIMITS.get(tier, self.TIER_LIMITS["basic"])
        self._read_bucket = TokenBucket(rate=limits["read"])
        self._write_bucket = TokenBucket(rate=limits["write"])
    
    async def acquire(self, action_type: str, priority: int = 5) -> bool:
        """
        Acquire rate limit token.
        
        Args:
            action_type: "read" or "write"
            priority: 0-10, higher = more important (execution > polling)
        
        Returns:
            True when token acquired (may block)
        """
        bucket = self._read_bucket if action_type == "read" else self._write_bucket
        return await bucket.acquire(priority=priority)
    
    async def try_acquire(self, action_type: str) -> bool:
        """Non-blocking acquire - returns False if no tokens available."""
        bucket = self._read_bucket if action_type == "read" else self._write_bucket
        
        bucket._refill_tokens()
        if bucket._tokens >= 1:
            bucket._tokens -= 1
            return True
        return False
```

---

## 🧪 Testing Swarm Safety

### Test Harness for Replay & Chaos

```python
# tests/swarm/test_kalshi_safety.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from merid_core.kalshi.execution_pipeline import KalshiExecutionPipeline, OrderIntent


class TestKalshiSwarmSafety:
    """Test suite for swarm failure mode defenses."""
    
    @pytest.mark.asyncio
    async def test_timeout_retry_idempotency(self):
        """Verify timeouts with retry don't create duplicate orders."""
        client = AsyncMock()
        risk = AsyncMock()
        limiter = AsyncMock()
        audit = AsyncMock()
        
        # Simulate timeout on first attempt, success on retry
        client.place_order.side_effect = [
            asyncio.TimeoutError(),
            "order_123",  # Second attempt succeeds
        ]
        risk.assess.return_value = RiskDecision(allowed=True, max_size=100)
        limiter.acquire.return_value = True
        
        pipeline = KalshiExecutionPipeline(client, risk, limiter, audit)
        
        intent = OrderIntent(
            session_id="test",
            agent_id="agent_1",
            market_ticker="BTC_15M",
            side="buy_yes",
            qty=100,
            price=50.0,
            client_tag="unique_intent_1",
        )
        
        # Execute with retry
        outcome = await pipeline.execute(intent)
        
        # Should succeed on retry
        assert outcome.status == "submitted"
        assert outcome.order_id == "order_123"
        
        # Verify same client_order_id used (idempotency)
        calls = client.place_order.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["client_order_id"] == "unique_intent_1"
        assert calls[1].kwargs["client_order_id"] == "unique_intent_1"  # Same!
    
    @pytest.mark.asyncio
    async def test_race_condition_prevention(self):
        """Verify multiple agents can't overshoot position limits."""
        # ... test implementation
    
    @pytest.mark.asyncio
    async def test_rate_limit_priority_queue(self):
        """Verify high-priority requests (execution) bypass polling."""
        # ... test implementation
    
    @pytest.mark.asyncio
    async def test_out_of_order_events(self):
        """Verify price-then-fill vs fill-then-price handling."""
        # Simulate WS message reordering
        messages = [
            {"type": "fill", "market": "BTC_15M", "price": 50},
            {"type": "orderbook_delta", "market": "BTC_15M", "mid": 49},  # Arrives late
        ]
        # ... test that execution used correct price
```

---

## 📋 Integration Checklist

### Phase 4 (Monorepo Structure)
- [ ] Create `merid_core/kalshi/ws_bridge.py` with single WS connection
- [ ] Create `merid_core/kalshi/execution_pipeline.py` with risk gates
- [ ] Create `merid_core/kalshi/rate_limiter.py` with token bucket
- [ ] Create `merid_core/risk/kalshi_risk.py` with venue limits
- [ ] Add auth module with PSS signing

### Phase 5 (Swarm Architecture)
- [ ] Wire agents to WS bridge via topic subscriptions
- [ ] Agents emit `OrderIntent` events only (no direct execution)
- [ ] Venue Controller consumes intents → execution pipeline
- [ ] Add audit logger for all execution attempts
- [ ] Add tests for failure modes:
  - [ ] Timeout retry idempotency
  - [ ] Race condition prevention
  - [ ] Out-of-order event handling
  - [ ] Rate limit exhaustion
  - [ ] Unbounded context accumulation

### Production Readiness
- [ ] Monitor rate limit rejections (429s)
- [ ] Alert on execution pipeline errors
- [ ] Dashboard showing: position limits, rate limit usage, agent activity
- [ ] Replay capability from audit logs
- [ ] Circuit breaker for venue degradation

---

**Last Updated:** 2026-02-16  
**Next:** Implement rate limiter + test harness  
**Reference:** SWARM_MIGRATION_ROADMAP.md
