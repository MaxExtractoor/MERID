# Kalshi 15m Execution Pipeline and Guardrails Documentation

## Overview

The Kalshi 15m execution pipeline handles order routing, pre-trade risk checks, and order lifecycle management for the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE). The pipeline enforces idempotency, fill awareness, and centralized risk checks before any order reaches the venue.

## Architecture

### Component Hierarchy

```
OrderIntent (Order Request)
├── PreTradeGate (Idempotent Order Store + Risk Checks)
│   ├── IdempotentOrderStore (Deduplication)
│   ├── Fill Awareness (Position Satisfaction Check)
│   └── Risk Envelope (Window Limits, Caps)
├── OrderRouter (Mode-Aware Dispatch)
│   ├── Fee-Aware Edge Calculation
│   ├── Market Microstructure Filters
│   ├── Resting Order Tracking
│   └── Exit Policy Resolution
└── KalshiVenueClient (Venue Execution)
    ├── Mock Mode (Testing)
    ├── Paper Mode (Simulation)
    └── Live Mode (Production)
```

### Key Files

- **Order Gate**: `merid/event_venues/kalshi/order_gate.py`
- **Order Router**: `merid/event_venues/kalshi/order_router.py`
- **Venue Client**: `merid/event_venues/kalshi/client.py`
- **Position Cache**: `merid/event_venues/kalshi/position_cache.py`
- **Unified Fees**: `merid/event_venues/kalshi/unified_fees.py`

## Order Gate (PreTradeGate)

### Purpose

The pre-trade gate enforces three non-negotiable invariants before ANY order leaves the process:

1. **Idempotency** — Every order has a deterministic `client_order_id` derived from (agent_id, strategy_group, contract_id, side, target_qty, decision_ts_bucket). If that ID already exists as PENDING/LIVE/FILLED, the order is rejected (duplicate).

2. **Fill awareness** — If the current position for (contract, strategy) already satisfies the desired net quantity, the order is rejected as "already_satisfied".

3. **Single risk module** — `PreTradeGate.check()` is the ONE synchronous call that the order router and CT must invoke before any external API call. It runs: lease check → dedup → fill awareness → caps (delegates to KalshiRiskManager).

### Order Status Lifecycle

```python
class OrderStatus(str, Enum):
    """Lifecycle states for an idempotent order record."""
    PENDING = "pending"       # Intent created, not yet submitted to venue
    SUBMITTED = "submitted"   # Sent to venue, awaiting ack
    LIVE = "live"             # Resting on venue order book
    PARTIAL = "partial"       # Partially filled
    FILLED = "filled"         # Fully filled
    CANCELED = "canceled"     # Canceled (by us or venue)
    REJECTED = "rejected"     # Rejected by venue or risk gate
    EXPIRED = "expired"       # TTL expired without fill
```

**Terminal States**: FILLED, CANCELED, REJECTED, EXPIRED (no further venue interaction expected)

**Block Duplicate States**: PENDING, SUBMITTED, LIVE, PARTIAL, FILLED (duplicate intents blocked)

### Deterministic Client Order ID

```python
def deterministic_client_order_id(
    agent_id: str,
    strategy_group: str,
    contract_id: str,
    side: str,
    target_qty: int,
    decision_ts: float,
    price_cents: int = 0,
    bucket_width_s: Optional[int] = None,
) -> str:
    """Generate a deterministic, collision-resistant client_order_id.
    
    The ID is a truncated SHA-256 hex digest of the canonical key components.
    Two calls with the same logical decision (within the same time bucket)
    will always produce the same ID → safe to retry.
    """
    # Auto-detect market makers and 15m crypto agents for shorter bucket width
    # 15m crypto agents run at 5s cadence, need 5s bucket to avoid duplicate rejection
    if bucket_width_s is None:
        if _is_market_maker_agent(agent_id):
            bucket_width_s = 5  # 5s for MMs
        elif _is_15m_crypto_agent(agent_id):
            bucket_width_s = 5  # 5s for 15m crypto agents (matches cadence)
        else:
            bucket_width_s = 60  # 60s default
    
    bucket = int(decision_ts) // bucket_width_s
    preimage = f"{agent_id}|{strategy_group}|{contract_id}|{side}|{target_qty}|{price_cents}|{bucket}"
    digest = hashlib.sha256(preimage.encode()).hexdigest()[:32]
    return f"merid-{digest}"
```

**Bucket Widths**:
- **Market makers**: 5 seconds (need to refresh quotes frequently)
- **15m crypto agents**: 5 seconds (matches 5s cadence)
- **Default**: 60 seconds

### Idempotent Order Store

```python
class IdempotentOrderStore:
    """In-memory idempotent order store keyed by client_order_id.
    
    Thread-safe and async-safe. Entries are pruned after a configurable TTL.
    """
    
    PRUNE_TTL_S: float = 86400.0  # 24 hours
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None  # Async lock for concurrent async submissions
        self._orders: Dict[str, OrderRecord] = {}
        self._metrics = GateMetrics()
        # Track price execution history to prevent repeat price execution
        self._price_execution_history: Dict[Tuple[str, str, int], float] = {}
        self._price_repeat_window_s: float = 900.0  # 15 minutes
```

**Features**:
- Thread-safe and async-safe (dual locks)
- TTL-based pruning (24 hours)
- Price execution history tracking (prevents repeat price execution)
- Metrics tracking for observability

### Gate Verdict

```python
@dataclass
class GateVerdict:
    """Result of PreTradeGate.check()."""
    allowed: bool
    client_order_id: str
    reason: str = ""
    is_duplicate: bool = False
    existing_status: Optional[str] = None
```

### Gate Metrics

```python
@dataclass
class GateMetrics:
    """Observable counters for the pre-trade gate."""
    checks: int = 0
    allowed: int = 0
    blocked_duplicate: int = 0
    blocked_already_satisfied: int = 0
    blocked_lease_conflict: int = 0
    blocked_risk: int = 0
    blocked_stale_data: int = 0
    blocked_invalid_transition: int = 0
    blocked_price_guard: int = 0
    blocked_price_repeat: int = 0
    blocked_window_limit: int = 0
    blocked_window_limit_entry: int = 0
    blocked_window_limit_exit: int = 0
    blocked_exit_policy: int = 0
    blocked_exit_policy_invalid: int = 0
    blocked_sequential_trading: int = 0
    submitted: int = 0
    filled: int = 0
    canceled: int = 0
```

### Pre-Trade Check Flow

```python
def check(self, intent: OrderIntent) -> GateVerdict:
    """Run all pre-trade checks in order:
    
    1. Lease check (venue capacity)
    2. Deduplication (client_order_id collision)
    3. Fill awareness (position already satisfied)
    4. Price guard (deep OTM or high price)
    5. Price repeat (same ticker+side+price within window)
    6. Window limit (3% per agent, 5% total per 15m)
    7. Exit policy (metadata validation)
    8. Sequential trading (block new entries when positions exist)
    """
    
    # 1. Lease check
    if not self._check_lease(intent):
        return GateVerdict(allowed=False, client_order_id="", reason="lease_conflict")
    
    # 2. Deduplication
    client_order_id = deterministic_client_order_id(...)
    existing = self._store.lookup(client_order_id)
    if existing and existing.status in _BLOCK_DUPLICATE_STATES:
        return GateVerdict(allowed=False, client_order_id=client_order_id, 
                          reason="duplicate", is_duplicate=True, existing_status=existing.status)
    
    # 3. Fill awareness
    if self._is_already_satisfied(intent):
        return GateVerdict(allowed=False, client_order_id=client_order_id, 
                          reason="already_satisfied")
    
    # 4. Price guard
    if not self._check_price_guard(intent):
        return GateVerdict(allowed=False, client_order_id=client_order_id, 
                          reason="price_guard")
    
    # 5. Price repeat
    if self._is_price_repeat(intent):
        return GateVerdict(allowed=False, client_order_id=client_order_id, 
                          reason="price_repeat")
    
    # 6. Window limit
    allowed, reason = self.risk_envelope.check_window_limit(...)
    if not allowed:
        return GateVerdict(allowed=False, client_order_id=client_order_id, reason=reason)
    
    # 7. Exit policy
    if not self._check_exit_policy(intent):
        return GateVerdict(allowed=False, client_order_id=client_order_id, 
                          reason="exit_policy")
    
    # 8. Sequential trading
    if not self._check_sequential_trading(intent):
        return GateVerdict(allowed=False, client_order_id=client_order_id, 
                          reason="sequential_trading")
    
    return GateVerdict(allowed=True, client_order_id=client_order_id)
```

### Price Repeat Prevention

```python
def _is_price_repeat(self, intent: OrderIntent) -> bool:
    """Check if this is a repeat price execution (same ticker+side+price within window).
    
    Prevents placing multiple orders at the same price for the same contract and side
    within a 15-minute window. This addresses the issue where agents place multiple
    identical resting limit orders for the same contract price.
    """
    price_cents = intent.price_cents
    key = (intent.contract_id, intent.side, price_cents)
    
    current_ts = time.time()
    last_execution_ts = self._store._price_execution_history.get(key, 0)
    
    if current_ts - last_execution_ts < self._store._price_repeat_window_s:
        return True
    
    return False
```

**Window**: 15 minutes (900 seconds)

### Sequential Trading Guard

```python
def _check_sequential_trading(self, intent: OrderIntent) -> bool:
    """Check if this is a new entry when positions already exist.
    
    CRITICAL FIX 2026-07-08: Block new entries when positions exist to enforce
    sequential trading. Total exposure across all positions must be ≤ $1.00.
    New entries are blocked until existing positions exit to free up capacity.
    """
    
    # Get current total exposure
    total_exposure = self.position_cache.get_total_exposure()
    
    # If total exposure > 0, block new entries
    if total_exposure > 0 and intent.action == "buy":
        return False
    
    return True
```

**Rationale**: Sequential trading ensures total exposure never exceeds $1.00. New entries are blocked until existing positions exit.

## Order Router

### Purpose

The order router routes `OrderIntent` through risk checks and dispatches to the appropriate execution path based on `TradingMode` (mock/paper/live).

### Order Intent

```python
@dataclass
class OrderIntent:
    """Order request from agent."""
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    count: int
    agent_id: str
    strategy_group: str
    exit_policy: Optional[ExitPolicyResolution] = None
    edge_pct: Optional[float] = None
    confidence: Optional[float] = None
```

### Fee-Aware Edge Calculation

```python
def calculate_kalshi_fee(contract_price_cents: int) -> float:
    """Calculate Kalshi taker fee for a single contract.
    
    Uses unified fees module for canonical tiered fee calculation.
    Fee formula: ceil(rate × C × P × (1-P)) where rate depends on contract tier.
    """
    return float(calculate_kalshi_fee_cents(contracts=1, price_cents=contract_price_cents))

def check_fee_aware_edge(
    edge_pct: float,
    contract_price_cents: int,
    min_edge_cents: float = 2.0,
    fee_per_contract: Optional[float] = None
) -> tuple[bool, str]:
    """Check if edge clears fee-aware gate.
    
    Edge gate: (estimated_probability - market_price) > fees + min_edge_cents
    """
    # Calculate fee in cents using unified fees module
    if fee_per_contract is None:
        fee_cents = calculate_kalshi_fee(contract_price_cents)
    else:
        fee_cents = fee_per_contract
    
    # Convert edge_pct to cents
    edge_cents = edge_pct * contract_price_cents
    
    # Check if edge clears fee + minimum buffer
    net_edge_cents = edge_cents - fee_cents
    required_edge_cents = min_edge_cents
    
    if net_edge_cents < required_edge_cents:
        return (
            False,
            f"fee_aware_gate: edge={edge_cents:.2f}c - fee={fee_cents:.2f}c = {net_edge_cents:.2f}c < required={required_edge_cents:.2f}c"
        )
    
    return True, "ok"
```

**Minimum Edge**: 2.0 cents after fees

### Market Microstructure Filters

```python
def check_market_microstructure(
    yes_bid_cents: int,
    yes_ask_cents: int,
    no_bid_cents: int,
    no_ask_cents: int,
    yes_depth: int,
    no_depth: int,
    max_spread_cents: float = 100.0,  # Updated from 30c to 100c for wider spreads
    min_depth_usd: float = 10.0,  # Lowered from $200 to $10 for low-volume liquidity
    min_yes_depth: int = 1,
    min_no_depth: int = 1
) -> tuple[bool, str]:
    """Check if market microstructure meets quality thresholds.
    
    Filters based on research: avoid wide spreads and thin books.
    """
    # Check YES spread
    yes_spread_cents = yes_ask_cents - yes_bid_cents
    if yes_spread_cents > max_spread_cents:
        return (False, f"yes_spread_too_wide: {yes_spread_cents}c > {max_spread_cents}c")
    
    # Check NO spread
    no_spread_cents = no_ask_cents - no_bid_cents
    if no_spread_cents > max_spread_cents:
        return (False, f"no_spread_too_wide: {no_spread_cents}c > {max_spread_cents}c")
    
    # Check minimum depth thresholds
    if yes_depth < min_yes_depth:
        return (False, f"yes_depth_too_low: {yes_depth} < {min_yes_depth}")
    
    if no_depth < min_no_depth:
        return (False, f"no_depth_too_low: {no_depth} < {min_no_depth}")
    
    # Check depth in USD (DISABLED for 15m crypto - system uses limit orders)
    if min_depth_usd > 0.0:
        yes_mid_cents = (yes_bid_cents + yes_ask_cents) / 2
        no_mid_cents = (no_bid_cents + no_ask_cents) / 2
        yes_depth_usd = yes_depth * (yes_mid_cents / 100.0) * 1.0
        no_depth_usd = no_depth * (no_mid_cents / 100.0) * 1.0
        
        if yes_depth_usd < min_depth_usd:
            return (False, f"yes_depth_usd_too_low: ${yes_depth_usd:.0f} < ${min_depth_usd:.0f}")
        
        if no_depth_usd < min_depth_usd:
            return (False, f"no_depth_usd_too_low: ${no_depth_usd:.0f} < ${min_depth_usd:.0f}")
    
    return True, "ok"
```

**Thresholds**:
- **Max spread**: 100 cents (updated from 30c for wider spreads)
- **Min depth USD**: $10 (lowered from $200 for low-volume liquidity)
- **Min depth contracts**: 1 contract

### Resting Order Tracking

```python
@dataclass
class RestingOrder:
    """Track resting orders for edge decay monitoring and auto-cancel."""
    order_id: str
    ticker: str
    side: str
    action: str
    limit_price_cents: int
    placed_at_ts: float
    edge_at_placement: float
    min_live_edge: float
    max_live_seconds: int
    aggressiveness: float
    
    def should_cancel(self, current_edge: float, current_ts: float) -> tuple[bool, str]:
        """Check if order should be canceled based on edge decay or time limit."""
        # Check time limit
        age_seconds = current_ts - self.placed_at_ts
        if age_seconds > self.max_live_seconds:
            return True, f"max_live_seconds_exceeded:{age_seconds:.0f}s>{self.max_live_seconds}s"
        
        # Check edge decay
        if current_edge < self.min_live_edge:
            return True, f"edge_decay:{current_edge:.3f}<{self.min_live_edge:.3f}"
        
        return False, "ok"
```

**Purpose**: Track resting orders for edge decay monitoring and auto-cancel when edge deteriorates or time limit exceeded.

### Duplicate Order Prevention

```python
def _check_duplicate_order(intent: OrderIntent) -> Optional[str]:
    """Check if this order is a duplicate of a recently placed order.
    
    Prevents placing multiple identical orders for the same ticker, side, action, and price
    within a short time window.
    """
    price_cents = intent.price_cents
    duplicate_key = (intent.ticker.upper(), intent.side.upper(), intent.action.upper(), price_cents)
    
    current_ts = time.time()
    
    with _duplicate_order_lock:
        last_order_ts = _duplicate_order_tracker.get(duplicate_key)
        
        if last_order_ts is not None:
            time_since_last = current_ts - last_order_ts
            if time_since_last < _DUPLICATE_ORDER_WINDOW_SECONDS:
                return f"duplicate_order:{time_since_last:.1f}s < {_DUPLICATE_ORDER_WINDOW_SECONDS}s"
    
    return None
```

**Window**: 60 seconds

### Exit Policy Resolution

```python
@dataclass
class ExitPolicyResolution:
    """Exit policy resolution for a trade.
    
    Defines the complete exit plan including TP, SL, trailing, scale-out, and max hold time.
    """
    policy_id: str
    asset: str
    regime: str
    
    # Take profit configuration
    tp_mode: TakeProfitMode
    tp_r_multiple: float
    tp_min_cents: int
    tp_time_based_r: Dict[str, float]
    
    # Stop loss configuration
    sl_mode: StopLossMode
    sl_cents: Optional[int]
    sl_r_multiple: Optional[float]
    
    # Trailing stop configuration
    trailing_enabled: bool
    trailing_activation_r: float
    trailing_giveback_cents: int
    
    # Scale-out configuration
    scale_out_enabled: bool
    scale_out_trigger_r: float
    scale_out_fraction: float
    
    # Hold time configuration
    max_hold_seconds: int
    max_round_trips: int
    
    # Entry constraints
    min_price_move_for_reentry: int
    min_edge_after_fees_cents: float
    
    # Edge context
    edge_confidence: Optional[float]
    net_edge_cents_at_entry: Optional[float]
```

### Exit Policy Resolution Function

```python
def resolve_exit_policy(
    edge_result: Any,
    asset: str,
    regime: str,
    strip_context: Optional[Dict[str, Any]] = None,
) -> ExitPolicyResolution:
    """Resolve exit policy for a trade based on edge, asset, and regime.
    
    This is the single function that creates ExitPolicyResolution.
    """
    # Default TP configuration (time-based dynamic R-multiple)
    tp_time_based_r = {
        "over_7_min": 1.0,
        "between_4_7_min": 0.75,
        "under_4_min": 0.5,
    }
    
    # Regime adjustments
    if regime == "conservative":
        tp_r_multiple = 0.75
        tp_min_cents = 5
        max_hold_seconds = 900  # 15 min
    elif regime == "aggressive":
        tp_r_multiple = 1.2
        tp_min_cents = 2
        max_hold_seconds = 600  # 10 min
    else:  # normal
        tp_r_multiple = 1.0
        tp_min_cents = 3
        max_hold_seconds = 600  # 10 min
    
    # Align max_hold_seconds with strip expiry
    expiry_ts = strip_context.get("expiry")
    if expiry_ts:
        tte_seconds = expiry_ts - time.time()
        max_hold_seconds = min(max_hold_seconds, tte_seconds)
    
    # Asset-specific adjustments
    if asset in ("SOL", "XRP", "DOGE"):
        tp_min_cents = max(tp_min_cents, 4)
    
    return ExitPolicyResolution(...)
```

**Time-Based R-Multiple**:
- **> 7 min to expiry**: 1.0R
- **4-7 min to expiry**: 0.75R
- **< 4 min to expiry**: 0.5R

**Regime Adjustments**:
- **Conservative**: 0.75R TP, 5c min, 15min max hold
- **Normal**: 1.0R TP, 3c min, 10min max hold
- **Aggressive**: 1.2R TP, 2c min, 10min max hold

## Order Routing Flow

### Main Route Function

```python
def route_order(intent: OrderIntent) -> OrderResult:
    """Route order through risk checks and dispatch to venue.
    
    Flow:
    1. Pre-trade gate check (idempotency, fill awareness, risk)
    2. Fee-aware edge check
    3. Market microstructure check
    4. Duplicate order check
    5. Mode-aware dispatch (mock/paper/live)
    6. Record order in dedup cache
    7. Track resting order if applicable
    8. Return result
    """
    
    # 1. Pre-trade gate check
    gate = get_pre_trade_gate()
    verdict = gate.check(intent)
    if not verdict.allowed:
        return OrderResult(success=False, reason=verdict.reason)
    
    # 2. Fee-aware edge check
    fee_ok, fee_reason = check_fee_aware_edge(intent.edge_pct, intent.price_cents)
    if not fee_ok:
        return OrderResult(success=False, reason=fee_reason)
    
    # 3. Market microstructure check
    market_state = get_kalshi_market_state_store().get(intent.ticker)
    micro_ok, micro_reason = check_market_microstructure(...)
    if not micro_ok:
        return OrderResult(success=False, reason=micro_reason)
    
    # 4. Duplicate order check
    dup_reason = _check_duplicate_order(intent)
    if dup_reason:
        return OrderResult(success=False, reason=dup_reason)
    
    # 5. Mode-aware dispatch
    trade_mode = get_trade_mode()
    if trade_mode == TradingMode.MOCK:
        result = _route_mock(intent)
    elif trade_mode == TradingMode.PAPER:
        result = _route_paper(intent)
    else:  # LIVE
        result = _route_live(intent)
    
    # 6. Record order in dedup cache
    if result.success:
        _record_order_placed(intent)
    
    # 7. Track resting order if applicable
    if result.success and intent.action == "buy":
        resting_order = RestingOrder(...)
        track_resting_order(resting_order)
    
    return result
```

### Mode-Aware Dispatch

```python
def _route_mock(intent: OrderIntent) -> OrderResult:
    """Mock mode: Simulate order execution without venue interaction."""
    # Simulate fill
    fill_count = intent.count
    fill_price = intent.price_cents
    
    return OrderResult(
        success=True,
        venue_order_id="mock-order-id",
        filled_count=fill_count,
        fill_price_cents=fill_price,
        reason="mock_fill"
    )

def _route_paper(intent: OrderIntent) -> OrderResult:
    """Paper mode: Simulate order execution with realistic fill simulation."""
    # Simulate partial fills based on market depth
    market_state = get_kalshi_market_state_store().get(intent.ticker)
    depth = market_state.yes_depth if intent.side == "yes" else market_state.no_depth
    
    # Simulate fill based on depth
    fill_count = min(intent.count, depth)
    fill_price = intent.price_cents
    
    return OrderResult(
        success=True,
        venue_order_id="paper-order-id",
        filled_count=fill_count,
        fill_price_cents=fill_price,
        reason="paper_fill"
    )

def _route_live(intent: OrderIntent) -> OrderResult:
    """Live mode: Submit order to Kalshi venue."""
    client = get_kalshi_client()
    
    # Submit order
    response = client.create_order(
        ticker=intent.ticker,
        side=intent.side,
        action=intent.action,
        price_cents=intent.price_cents,
        count=intent.count,
        client_order_id=verdict.client_order_id
    )
    
    return OrderResult(
        success=True,
        venue_order_id=response.order_id,
        filled_count=response.filled_count,
        fill_price_cents=response.fill_price,
        reason="live_fill"
    )
```

## Critical Fixes

### Fix 1: Async Lock for Concurrent Submissions (PHASE1-DUP-4)

**Problem**: Concurrent async submissions could bypass deduplication due to threading lock not being async-safe.

**Solution**: Added `asyncio.Lock` for async dedup to prevent concurrent duplicate submissions in async contexts.

### Fix 2: State Transition Validation (PHASE1-DUP-5)

**Problem**: Invalid state transitions (e.g., FILLED → SUBMITTED) could occur due to race conditions.

**Solution**: Added state transition validation to enforce:
1. No status regressions
2. Terminal state immutability

### Fix 3: Price Repeat Prevention

**Problem**: Agents placed multiple identical resting limit orders for the same contract price.

**Solution**: Track price execution history and block repeat price execution within 15-minute window.

### Fix 4: Sequential Trading Guard (2026-07-08)

**Problem**: New entries could exceed $1.00 total exposure when positions already existed.

**Solution**: Block new entries when positions exist to enforce sequential trading. Total exposure must be ≤ $1.00.

### Fix 5: Exit Policy Validation (2026-07-06)

**Problem**: Orders without exit policy metadata could be submitted, leading to unmanaged positions.

**Solution**: Block orders without exit policy metadata. Validate exit policy values.

### Fix 6: Spread Threshold Update (2026-07-10)

**Problem**: 30c spread threshold was too strict for current market conditions.

**Solution**: Updated max spread from 30c to 100c to accommodate wider spreads.

### Fix 7: Depth Threshold Update (2026-07-05)

**Problem**: $200 depth threshold was too high for weekend/low-volume liquidity.

**Solution**: Lowered min depth USD from $200 to $10 based on research.

## Guardrails

### Pre-Trade Guardrails

1. **Idempotency**: Duplicate orders blocked via deterministic client_order_id
2. **Fill Awareness**: Orders blocked if position already satisfied
3. **Lease Check**: Venue capacity check before submission
4. **Price Guard**: Deep OTM or high price orders blocked
5. **Price Repeat**: Same ticker+side+price blocked within 15-minute window
6. **Window Limit**: 3% per agent, 5% total per 15m window (HARD STOP)
7. **Exit Policy**: Orders without valid exit policy blocked
8. **Sequential Trading**: New entries blocked when positions exist

### Post-Trade Guardrails

1. **Resting Order Tracking**: Edge decay monitoring and auto-cancel
2. **Position Monitoring**: Take-profit and stop-loss enforcement
3. **Window Exposure Tracking**: Cumulative exposure tracking per window
4. **Drawdown Tracking**: Adaptive risk scaling based on drawdown bands

## Monitoring and Observability

### Key Log Messages

- `[PRE-TRADE-GATE]`: Pre-trade gate events (check, block, allow)
- `[DUPLICATE-ORDER-REJECTED]`: Duplicate order rejections
- `[DUPLICATE-ORDER-TRACK]`: Duplicate order tracking
- `[RESTING-ORDER-CANCEL]`: Resting order cancellations
- `[FEE-AWARE-GATE]`: Fee-aware edge gate events
- `[MICROSTRUCTURE-GATE]`: Market microstructure gate events

### Metrics

- **Gate checks**: Total pre-trade gate checks
- **Gate blocks**: Blocks by reason (duplicate, already_satisfied, risk, etc.)
- **Order submissions**: Total orders submitted to venue
- **Order fills**: Total orders filled
- **Order cancellations**: Total orders canceled
- **Resting orders**: Current resting order count
- **Edge decay cancellations**: Orders canceled due to edge decay

## References

- **Order Gate**: `merid/event_venues/kalshi/order_gate.py`
- **Order Router**: `merid/event_venues/kalshi/order_router.py`
- **Venue Client**: `merid/event_venues/kalshi/client.py`
- **Position Cache**: `merid/event_venues/kalshi/position_cache.py`
- **Unified Fees**: `merid/event_venues/kalshi/unified_fees.py`
