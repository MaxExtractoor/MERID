# Resting Order Market Order Fallback Design
## Preventing Missed Winning Trades by Converting Unfilled Limit Orders to Market Orders

**Design Date:** 2026-06-30  
**Context:** Last 15m window had 2 resting NO orders that never filled, market resolved NO (missed winning trade)

---

## Problem Analysis

### Why Limit Orders Don't Fill

Based on industry research and code audit, limit orders fail to fill due to:

1. **Queue Position (Time-Price Priority)**
   - Other orders at same price ahead in queue
   - Price touches level but liquidity consumed by earlier orders
   - Common at psychological levels (50c, 60c, 75c)

2. **Insufficient Liquidity**
   - Not enough size at matching price
   - Thin order books in 15m crypto markets
   - Market moves before reaching your order

3. **Price Gaps**
   - Market gaps through your price level
   - Rapid price movement skips your level entirely
   - Common in volatile 15m windows

4. **HFT Front-Running**
   - Algorithms place/cancel orders in milliseconds
   - Quote stuffing creates phantom liquidity
   - Orders at round numbers get front-run

### Current System Behavior

**Existing in `resting_order_monitor.py`:**
- ✅ Tracks resting orders via portfolio polling
- ✅ Cancels orders after max hold time (180s for 15m)
- ✅ Cancels orders near expiry (2 minutes before settlement)
- ✅ Re-checks against regime/volatility/model quality
- ❌ **NO market order fallback mechanism**

**The Gap:**
When a limit order is unlikely to fill but the signal is still valid, the system currently:
- Waits for fill (may never happen)
- Cancels after max hold time (too late)
- Does NOT execute market order fallback

---

## Industry Best Practices

### 1. Time-Based Conversion
**Concept:** Convert limit order to market order after X seconds if unfilled.

**Variants:**
- **Fixed timeout:** Convert after 30s, 60s, 90s
- **Dynamic timeout:** Based on volatility, time to expiry, edge
- **Percentage of window:** Convert after 20% of remaining time

**Pros:**
- Simple to implement
- Guarantees fill for high-conviction trades
- Prevents missed winning trades

**Cons:**
- May pay higher price (slippage)
- Converts even when market is illiquid
- Can trigger in adverse conditions

### 2. Market-If-Touched (MIT)
**Concept:** Order becomes market order when price touches level.

**Variants:**
- **True MIT:** Off-book until trigger, then market
- **Stop-based:** Stop order that converts to market
- **Trigger order:** Latent until price met

**Pros:**
- Hidden from order book (no front-running)
- Guarantees fill when price reached
- Better queue position (off-book)

**Cons:**
- Still subject to slippage on conversion
- May not be supported by all venues
- Complex implementation

### 3. Dynamic Price Adjustment
**Concept:** Adjust limit price to stay at top of book.

**Variants:**
- **Chase mode:** Move price toward mid
- **Peg to mid:** Always at midpoint
- **Tick adjustment:** Move by 1 tick toward market

**Pros:**
- Maintains limit order benefits
- Improves fill probability
- Reduces slippage vs market order

**Cons:**
- More complex logic
- May cross spread (becomes taker)
- Still no fill guarantee

### 4. Conditional Fallback
**Concept:** Only fallback to market under specific conditions.

**Conditions:**
- High conviction (edge > threshold)
- Near expiry (time to expiry < threshold)
- Strong signal (confidence > threshold)
- Favorable market conditions (spread < threshold)

**Pros:**
- Selective application
- Reduces unnecessary slippage
- Maintains discipline

**Cons:**
- More complex logic
- Requires accurate signal estimation
- May miss edge cases

---

## Recommended Solution: Conditional Market Order Fallback

### Design Principles

1. **Safety First:** Only fallback when signal is still valid and conviction is high
2. **Time-Aware:** Consider time to expiry and order age
3. **Market-Aware:** Check spread, depth, and volatility before fallback
4. **Configurable:** Allow tuning of thresholds per asset/regime
5. **Audit Trail:** Log all fallback decisions for post-mortem analysis

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RestingOrderMonitor                        │
│  (Existing: tracks orders, polls portfolio, cancels stale)   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ Add new check
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              MarketOrderFallbackEngine                       │
│  (New: evaluates if order should fallback to market)         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ Conditions met?
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              FallbackDecision                                 │
│  - Cancel limit order                                        │
│  - Place market order                                        │
│  - Track outcome                                             │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Plan

#### Phase 1: Core Fallback Engine

**File:** `merid/event_venues/kalshi/market_order_fallback.py`

```python
@dataclass
class FallbackConfig:
    """Configuration for market order fallback."""
    
    # Time-based triggers
    fallback_after_seconds: int = 90  # Convert after 90s (half of max hold)
    min_age_before_fallback: int = 30  # Minimum age before considering fallback
    
    # Conviction thresholds
    min_edge_pct: float = 0.04  # Minimum edge for fallback (4%)
    min_confidence: float = 0.70  # Minimum model confidence
    
    # Time to expiry
    max_tte_for_fallback: int = 300  # Max 5 minutes to expiry
    urgent_tte_threshold: int = 120  # Urgent if < 2 minutes to expiry
    
    # Market conditions
    max_spread_cents: int = 10  # Max spread for fallback
    min_depth_contracts: int = 5  # Minimum depth at best price
    
    # Asset-specific overrides
    asset_overrides: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class FallbackDecision:
    """Decision whether to fallback to market order."""
    
    should_fallback: bool
    reason: str
    original_order: RestingOrderRecord
    current_market_state: Optional[Any] = None
    edge_at_placement: Optional[float] = None
    current_edge: Optional[float] = None
    time_to_expiry: Optional[float] = None
    confidence: Optional[float] = None


class MarketOrderFallbackEngine:
    """Evaluates resting orders and decides on market order fallback."""
    
    def __init__(self, config: Optional[FallbackConfig] = None):
        self.config = config or FallbackConfig()
        self._fallback_count = 0
        self._skip_count = 0
    
    def evaluate_fallback(
        self,
        order: RestingOrderRecord,
        market_state: Optional[Any] = None
    ) -> FallbackDecision:
        """Evaluate if order should fallback to market order."""
        
        # Check 1: Minimum age
        age_seconds = (datetime.utcnow() - order.created_at).total_seconds()
        if age_seconds < self.config.min_age_before_fallback:
            return FallbackDecision(
                should_fallback=False,
                reason=f"too_young:{age_seconds:.0f}s<{self.config.min_age_before_fallback}s",
                original_order=order
            )
        
        # Check 2: Time-based trigger
        if age_seconds >= self.config.fallback_after_seconds:
            # Proceed to conviction checks
            pass
        else:
            # Check urgency (near expiry)
            tte = self._get_time_to_expiry(order)
            if tte and tte > self.config.urgent_tte_threshold:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"not_urgent:{tte:.0f}s>{self.config.urgent_tte_threshold}s",
                    original_order=order
                )
        
        # Check 3: Conviction (edge and confidence)
        if order.original_edge_pct and order.original_edge_pct < self.config.min_edge_pct:
            return FallbackDecision(
                should_fallback=False,
                reason=f"low_edge:{order.original_edge_pct:.3f}<{self.config.min_edge_pct:.3f}",
                original_order=order
            )
        
        # Check 4: Market conditions (spread and depth)
        if market_state:
            spread_cents = getattr(market_state, 'spread_cents', None)
            if spread_cents and spread_cents > self.config.max_spread_cents:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"wide_spread:{spread_cents}c>{self.config.max_spread_cents}c",
                    original_order=order,
                    current_market_state=market_state
                )
            
            depth = getattr(market_state, 'min_depth_yes', 0) + getattr(market_state, 'min_depth_no', 0)
            if depth < self.config.min_depth_contracts:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"thin_depth:{depth}<{self.config.min_depth_contracts}",
                    original_order=order,
                    current_market_state=market_state
                )
        
        # All checks passed - fallback to market
        return FallbackDecision(
            should_fallback=True,
            reason=f"all_checks_passed:age={age_seconds:.0f}s",
            original_order=order,
            current_market_state=market_state,
            edge_at_placement=order.original_edge_pct,
            time_to_expiry=self._get_time_to_expiry(order)
        )
    
    async def execute_fallback(
        self,
        decision: FallbackDecision
    ) -> Dict[str, Any]:
        """Execute market order fallback."""
        
        if not decision.should_fallback:
            self._skip_count += 1
            return {"status": "skipped", "reason": decision.reason}
        
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.event_venues.kalshi.order_router import OrderIntent, route_order
            
            client = get_kalshi_client()
            
            # Cancel original limit order
            await client.cancel_order(
                decision.original_order.kalshi_order_id,
                decision.original_order.ticker
            )
            
            # Place market order
            intent = OrderIntent(
                ticker=decision.original_order.ticker,
                side=decision.original_order.side,
                action=decision.original_order.action,
                price_cents=0,  # Market order
                count=decision.original_order.remaining_size,
                order_type="market",
                time_in_force="ioc",
                source="market_order_fallback",
                intent_id=f"fallback_{decision.original_order.intent_id}",
                agent_id=decision.original_order.intent_id
            )
            
            result = await route_order(intent)
            
            self._fallback_count += 1
            
            logger.info(
                "[MARKET-ORDER-FALLBACK] Executed fallback: kalshi_order_id=%s "
                "ticker=%s side=%s count=%d reason=%s result=%s",
                decision.original_order.kalshi_order_id,
                decision.original_order.ticker,
                decision.original_order.side,
                decision.original_order.remaining_size,
                decision.reason,
                result
            )
            
            return {
                "status": "executed",
                "original_order_id": decision.original_order.kalshi_order_id,
                "fallback_order_id": result.get("order_id"),
                "reason": decision.reason,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"[MARKET-ORDER-FALLBACK] Failed to execute fallback: {e}")
            return {"status": "failed", "error": str(e)}
```

#### Phase 2: Integration with RestingOrderMonitor

**Modify `resting_order_monitor.py`:**

```python
# Add to imports
from merid.event_venues.kalshi.market_order_fallback import (
    MarketOrderFallbackEngine,
    FallbackConfig
)

# Add to RestingOrderMonitor.__init__
self._fallback_engine: Optional[MarketOrderFallbackEngine] = None
self._fallback_enabled: bool = True  # Configurable

# Add method to RestingOrderMonitor
def enable_fallback(self, config: Optional[FallbackConfig] = None) -> None:
    """Enable market order fallback."""
    self._fallback_engine = MarketOrderFallbackEngine(config)
    self._fallback_enabled = True
    logger.info("[RESTING_ORDER_MONITOR] Market order fallback enabled")

# Modify _recheck_order to include fallback check
async def _recheck_order(self, record: RestingOrderRecord) -> RecheckResult:
    # ... existing checks ...
    
    # NEW: Check for market order fallback
    if self._fallback_enabled and self._fallback_engine:
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            market_state_store = get_kalshi_market_state_store()
            market_state = market_state_store.get(record.ticker) if market_state_store else None
            
            fallback_decision = self._fallback_engine.evaluate_fallback(record, market_state)
            
            if fallback_decision.should_fallback:
                # Execute fallback asynchronously (don't block recheck loop)
                asyncio.create_task(self._execute_fallback_async(fallback_decision))
                
                # Unregister order (will be replaced by market order)
                return RecheckResult(
                    intent_id=record.intent_id,
                    ticker=record.ticker,
                    action="cancel",
                    reason=f"market_order_fallback:{fallback_decision.reason}",
                    current_regime=regime,
                    current_vol_tier=window_res.volatility_tier,
                    model_quality_good=model_quality_good,
                )
        except Exception as e:
            logger.error(f"[RESTING_ORDER_MONITOR] Fallback evaluation failed: {e}")
    
    # ... existing keep logic ...

async def _execute_fallback_async(self, decision: FallbackDecision) -> None:
    """Execute market order fallback asynchronously."""
    try:
        result = await self._fallback_engine.execute_fallback(decision)
        logger.info(f"[RESTING_ORDER_MONITOR] Fallback result: {result}")
    except Exception as e:
        logger.error(f"[RESTING_ORDER_MONITOR] Fallback execution failed: {e}")
```

#### Phase 3: Configuration

**Add to `config/kalshi_crypto_config.py`:**

```python
# Market order fallback configuration
MARKET_ORDER_FALLBACK_ENABLED = True  # Enable/disable feature

FALLBACK_CONFIG = {
    "fallback_after_seconds": 90,  # Convert after 90s
    "min_age_before_fallback": 30,  # Minimum age
    "min_edge_pct": 0.04,  # 4% minimum edge
    "min_confidence": 0.70,  # 70% minimum confidence
    "max_spread_cents": 10,  # Max 10 cent spread
    "min_depth_contracts": 5,  # Minimum 5 contracts depth
    "urgent_tte_threshold": 120,  # Urgent if < 2 minutes to expiry
    
    # Asset-specific overrides
    "asset_overrides": {
        "BTC": {
            "min_edge_pct": 0.03,  # Lower threshold for BTC
            "fallback_after_seconds": 60,  # Faster fallback for BTC
        },
        "ETH": {
            "min_edge_pct": 0.03,
            "fallback_after_seconds": 60,
        },
    }
}
```

---

## Risk Mitigation

### 1. Slippage Protection

**Problem:** Market orders may fill at worse prices than limit orders.

**Mitigation:**
- Only fallback when edge is high (≥4%)
- Check spread before fallback (max 10 cents)
- Check depth before fallback (min 5 contracts)
- Log fill price vs expected price for audit

### 2. Over-Fallback

**Problem:** System may fallback too aggressively, increasing costs.

**Mitigation:**
- Minimum age before fallback (30s)
- Configurable per-asset thresholds
- Track fallback success rate
- Alert if fallback rate > threshold

### 3. Race Conditions

**Problem:** Market order placed while limit order still active.

**Mitigation:**
- Cancel limit order BEFORE placing market order
- Use client_order_id for idempotency
- Check order status before fallback
- Handle cancellation failures gracefully

### 4. Market Conditions

**Problem:** Fallback in illiquid markets causes poor fills.

**Mitigation:**
- Check spread before fallback
- Check depth before fallback
- Disable fallback in wide-spread conditions
- Consider volatility regime

---

## Monitoring and Alerting

### Metrics to Track

1. **Fallback Rate**
   - Total fallbacks / total resting orders
   - Per-asset fallback rate
   - Per-regime fallback rate

2. **Fallback Success**
   - Market order fill rate
   - Slippage vs expected price
   - PnL impact of fallbacks

3. **Missed Trade Prevention**
   - Trades that would have been missed without fallback
   - Winning trades captured by fallback
   - Cost of fallback vs benefit

### Alerts

1. **High Fallback Rate**
   - Alert if fallback rate > 20%
   - Indicates potential configuration issue

2. **High Slippage**
   - Alert if slippage > 5 cents
   - Indicates poor market conditions

3. **Fallback Failures**
   - Alert if fallback execution fails
   - Indicates technical issue

---

## Testing Strategy

### Unit Tests

1. **Fallback Decision Logic**
   - Test age-based triggers
   - Test conviction thresholds
   - Test market condition checks
   - Test asset-specific overrides

2. **Fallback Execution**
   - Test order cancellation
   - Test market order placement
   - Test error handling
   - Test idempotency

### Integration Tests

1. **End-to-End Flow**
   - Place limit order
   - Wait for fallback trigger
   - Verify market order placed
   - Verify limit order cancelled

2. **Market Conditions**
   - Test with wide spread (should skip)
   - Test with thin depth (should skip)
   - Test with normal conditions (should fallback)

### Simulation Tests

1. **Historical Replay**
   - Replay past 15m windows
   - Simulate fallback behavior
   - Measure impact on PnL

2. **Monte Carlo**
   - Simulate various market conditions
   - Test fallback robustness
   - Optimize thresholds

---

## Rollout Plan

### Phase 1: Shadow Mode (Week 1)
- Implement fallback engine
- Log fallback decisions but don't execute
- Analyze decision quality
- Tune thresholds

### Phase 2: Limited Rollout (Week 2)
- Enable for BTC only
- Monitor closely
- Adjust thresholds based on results

### Phase 3: Full Rollout (Week 3)
- Enable for all assets
- Monitor metrics
- Adjust as needed

### Phase 4: Optimization (Week 4+)
- Analyze PnL impact
- Optimize thresholds per asset
- Add dynamic threshold adjustment

---

## Expected Impact

### Benefits

1. **Prevent Missed Winning Trades**
   - Capture trades that would have been missed
   - Especially important near expiry
   - High-conviction trades get executed

2. **Improve Fill Rate**
   - Reduce unfilled limit orders
   - Better signal execution
   - Higher win rate

3. **Adapt to Market Conditions**
   - Fallback when appropriate
   - Stay as limit when conditions good
   - Dynamic execution strategy

### Costs

1. **Increased Slippage**
   - Market orders may fill at worse prices
   - Mitigated by conviction thresholds
   - Mitigated by market condition checks

2. **Higher Fees**
   - Market orders pay taker fees
   - Mitigated by selective fallback
   - Cost vs benefit analysis needed

3. **Complexity**
   - Additional code to maintain
   - More configuration to manage
   - Monitoring overhead

---

## Conclusion

The proposed market order fallback system addresses the core issue: missed winning trades due to unfilled limit orders. By implementing a conditional fallback mechanism that considers conviction, time to expiry, and market conditions, the system can capture high-value trades while managing slippage and fee costs.

**Key Features:**
- Conditional fallback (not automatic)
- Time-based triggers with conviction checks
- Market condition awareness
- Per-asset configuration
- Comprehensive monitoring

**Next Steps:**
1. Implement core fallback engine
2. Integrate with RestingOrderMonitor
3. Deploy in shadow mode for validation
4. Gradual rollout with monitoring
5. Optimize thresholds based on results

This solution aligns with 2026 industry best practices while maintaining the system's emphasis on fee-aware, disciplined trading.
