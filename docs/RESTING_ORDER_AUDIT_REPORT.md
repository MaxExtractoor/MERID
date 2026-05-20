# Resting Order Audit Report

**Date:** 2026-05-13  
**Scope:** Audit of MERID's resting order implementation against Kalshi V2 API/engine specification  
**Reference:** [Kalshi API Docs](https://docs.kalshi.com/api-reference/orders/create-order-v2)

---

## Executive Summary

Our current `RestingOrderMonitor` implementation operates on **internal intent tracking** rather than **actual Kalshi engine state**. This creates a fundamental gap: we monitor what we *think* is resting, not what is *actually* resting on the exchange.

**Critical Finding:** Our resting order monitor does not integrate with Kalshi's server-side order tracking, making it impossible to accurately detect resting orders, partial fills, or order lifecycle changes.

---

## Gap Analysis

### 1. Order Tracking Mechanism

| Aspect | Kalshi Engine | Our Implementation | Gap |
|--------|--------------|-------------------|-----|
| **Primary identifier** | Server-side `order_id` | Internal `intent_id` | **Critical** - We track by intent_id, not order_id |
| **Order lifecycle source** | Portfolio endpoints, orderbook events | Internal registration | **Critical** - No polling of Kalshi's actual state |
| **Rest detection** | Engine determines based on matching logic | Manual registration | **Critical** - We don't know what actually rests |

**Impact:** We cannot reliably detect which orders are actually resting on the exchange. Our monitor operates on assumptions rather than facts.

---

### 2. Order Type & Time-in-Force Handling

| Aspect | Kalshi Engine | Our Implementation | Gap |
|--------|--------------|-------------------|-----|
| **Market orders** | IOC by definition, never rest | Not differentiated from limit | **High** - IOC orders should not be tracked as resting |
| **Limit + GTC** | Can rest indefinitely or with expiration | Tracked by registration only | **Medium** - No expiration enforcement |
| **Limit + IOC** | Remainder canceled immediately, never rests | May be incorrectly tracked | **High** - IOC orders shouldn't register as resting |
| **expiration_time** | Auto-expire at Unix timestamp | `order_expiration_ts` exists but not used | **Medium** - Not integrated with monitor |

**Impact:** We may incorrectly track IOC orders as resting, and we don't enforce expiration times.

---

### 3. Matching & Partial Fills

| Aspect | Kalshi Engine | Our Implementation | Gap |
|--------|--------------|-------------------|-----|
| **Price-time priority** | Standard matching engine | Not accounted for | **Low** - Not relevant for monitoring |
| **Partial fills** | Adjusts remaining_size, order stays resting | Not tracked | **Critical** - We don't detect partial fills |
| **Full fill** | Order removed from book, status=filled | Not detected | **Critical** - We don't detect when orders fully fill |
| **Order status** | `open`, `partially_filled`, `filled`, `canceled`, `expired` | No status polling | **Critical** - We don't know actual order status |

**Impact:** We cannot detect when resting orders are partially or fully filled, leading to stale tracking.

---

### 4. Self-Trade Prevention (STP)

| Aspect | Kalshi Engine | Our Implementation | Gap |
|--------|--------------|-------------------|-----|
| **taker_at_cross** | Stops at own rest, cancels incoming | Not handled | **Medium** - Could cause unexpected cancellations |
| **maker** | Cancels own rest, continues matching | Not handled | **Medium** - Could cancel resting orders unexpectedly |

**Impact:** STP events could cause resting orders to disappear without our knowledge.

---

### 5. Order Book Integration

| Aspect | Kalshi Engine | Our Implementation | Gap |
|--------|--------------|-------------------|-----|
| **Public orderbook** | Aggregate size per price level | Not polled | **Medium** - Could detect resting liquidity |
| **Portfolio endpoints** | Per-order detail, status, remaining_size | Not polled | **Critical** - This is the source of truth |
| **WebSocket events** | Real-time order/fill/cancel events | Partial integration | **Medium** - WS bridge exists but not used by monitor |

**Impact:** We don't use the available data sources to track actual resting order state.

---

## Critical Issues

### Issue 1: No Server-Side Order Tracking
**Severity:** Critical  
**Description:** `RestingOrderMonitor` tracks by `intent_id` (our internal ID) instead of Kalshi's `order_id`. This means:
- We cannot query Kalshi's portfolio endpoints to get actual order status
- We cannot detect when orders are filled, canceled, or expired by the engine
- We have no way to sync our internal state with exchange state

**Recommendation:** 
- Store Kalshi's `order_id` when orders are placed
- Poll `/portfolio/orders/{order_id}` to check status
- Unregister orders when status changes to `filled`, `canceled`, or `expired`

---

### Issue 2: IOC Orders Incorrectly Tracked
**Severity:** High  
**Description:** Orders with `time_in_force = "ioc"` (or `immediate_or_cancel`) should never rest. Our monitor doesn't filter these out.

**Recommendation:**
- Only register orders with `time_in_force = "gtc"` (good_till_canceled)
- Exclude IOC and FOK orders from resting order tracking

---

### Issue 3: No Partial Fill Detection
**Severity:** Critical  
**Description:** When a resting order is partially filled, the remaining size stays resting. Our monitor doesn't detect this, so we may cancel orders that still have valid remaining size.

**Recommendation:**
- Poll order status to get `remaining_quantity`
- Update resting order record when partial fills occur
- Only cancel when remaining_size = 0 or order is canceled/expired

---

### Issue 4: No Expiration Enforcement
**Severity:** Medium  
**Description:** `OrderIntent` has `order_expiration_ts` but it's not used by the monitor. Kalshi's engine will auto-expire GTC orders with `expiration_time`, but we won't know about it.

**Recommendation:**
- Use `order_expiration_ts` when registering resting orders
- Check if order is expired before re-checking
- Unregister expired orders

---

## Recommended Architecture

### Phase 1: Server-Side Order Tracking (Critical)

1. **Store order_id in RestingOrderRecord:**
```python
@dataclass
class RestingOrderRecord:
    intent_id: str
    kalshi_order_id: Optional[str]  # NEW: Server-side order ID
    # ... existing fields
```

2. **Update order placement to capture order_id:**
```python
# In order_router.py after order placement
if result.status == "success":
    kalshi_order_id = getattr(result.fill, "order_id")
    # Register with kalshi_order_id
```

3. **Poll portfolio endpoints for status:**
```python
async def _sync_order_status(self, record: RestingOrderRecord) -> bool:
    if not record.kalshi_order_id:
        return False
    
    order_data = await client.get_order_result(record.kalshi_order_id, record.ticker)
    status = order_data.data.get("status")
    
    if status in ("filled", "canceled", "expired"):
        self.unregister_order(record.intent_id)
        return True
    
    # Update remaining_size if partial fill
    return False
```

---

### Phase 2: Time-in-Force Filtering (High)

1. **Filter IOC orders at registration:**
```python
def register_order(self, record: RestingOrderRecord) -> None:
    # Don't register IOC orders - they never rest
    if record.time_in_force in ("ioc", "immediate_or_cancel", "fill_or_kill"):
        logger.debug(f"[RESTING_ORDER] Skipping IOC order: {record.intent_id}")
        return
    
    self._resting_orders[record.intent_id] = record
```

2. **Add time_in_force to RestingOrderRecord:**
```python
@dataclass
class RestingOrderRecord:
    # ... existing fields
    time_in_force: str = "gtc"
```

---

### Phase 3: Partial Fill Handling (Critical)

1. **Track remaining_quantity:**
```python
@dataclass
class RestingOrderRecord:
    # ... existing fields
    remaining_quantity: int  # NEW: Track remaining size
```

2. **Update on partial fills:**
```python
async def _sync_order_status(self, record: RestingOrderRecord) -> bool:
    # ... get order data
    remaining_qty = order_data.data.get("remaining_quantity")
    
    if remaining_qty != record.remaining_quantity:
        logger.info(f"[RESTING_ORDER] Partial fill: {record.intent_id} {record.remaining_quantity} -> {remaining_qty}")
        record.remaining_quantity = remaining_qty
    
    if remaining_qty == 0:
        self.unregister_order(record.intent_id)
        return True
```

---

### Phase 4: Expiration Enforcement (Medium)

1. **Check expiration before re-check:**
```python
async def _recheck_order(self, record: RestingOrderRecord) -> RecheckResult:
    # Check expiration first
    if record.expiration_ts:
        now = int(time.time())
        if now > record.expiration_ts:
            return RecheckResult(
                intent_id=record.intent_id,
                ticker=record.ticker,
                action="cancel",
                reason="expired",
            )
    
    # ... existing re-check logic
```

---

### Phase 5: STP Awareness (Medium)

1. **Log STP events:**
```python
# In order_router.py, handle STP scenarios
if result.status == "rejected" and "self_trade" in result.reason.lower():
    logger.warning(f"[STP] Self-trade prevention triggered: {intent.intent_id}")
    # Unregister from resting monitor if applicable
```

---

## Integration Points

### 1. Order Router Integration

**Current:** Order router places orders but doesn't register resting orders.  
**Required:** Register GTC limit orders after successful placement.

```python
# In route_order_async, after successful order placement
if result.status == "success":
    kalshi_order_id = getattr(result.fill, "order_id")
    
    # Register if it's a GTC limit order
    if intent.order_type == "limit" and intent.time_in_force in ("gtc", "good_till_canceled"):
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        monitor = get_resting_order_monitor()
        
        record = RestingOrderRecord(
            intent_id=intent.intent_id,
            kalshi_order_id=kalshi_order_id,
            ticker=intent.ticker,
            side=intent.side,
            action=intent.action,
            count=intent.count,
            price_cents=intent.price_cents,
            created_at=datetime.utcnow(),
            asset=extract_asset(intent.ticker),
            window_resolution_id=intent.window_resolution_id,
            exit_policy_id=intent.exit_policy_id,
            risk_tier=intent.risk_tier,
            max_hold_seconds=intent.max_hold_seconds,
            time_in_force=intent.time_in_force,
            expiration_ts=intent.order_expiration_ts,
            remaining_quantity=intent.count,
        )
        monitor.register_order(record)
```

---

### 2. WebSocket Event Integration

**Current:** WS bridge processes order/fill events but doesn't update resting monitor.  
**Required:** Update resting monitor on fill/cancel events.

```python
# In ws_bridge.py, on order filled
async def on_order_filled(self, event):
    order_id = event.order_id
    # Update resting monitor
    monitor = get_resting_order_monitor()
    # Find record by kalshi_order_id and update
```

---

## Testing Recommendations

### 1. Unit Tests for Server-Side Tracking
- Test registration with kalshi_order_id
- Test status polling and state sync
- Test partial fill detection
- Test expiration handling

### 2. Integration Tests with Mock Kalshi
- Simulate order placement with order_id
- Simulate partial fills
- Simulate order cancellation
- Verify monitor state matches mock exchange

### 3. End-to-End Tests
- Place GTC limit order, verify it's registered
- Place IOC order, verify it's NOT registered
- Simulate partial fill, verify remaining_quantity updated
- Simulate expiration, verify order unregistered

---

## Priority Matrix

| Issue | Severity | Effort | Priority |
|-------|----------|--------|----------|
| Server-side order tracking | Critical | High | **P0** |
| IOC order filtering | High | Low | **P0** |
| Partial fill detection | Critical | Medium | **P0** |
| Expiration enforcement | Medium | Low | **P1** |
| STP awareness | Medium | Low | **P2** |
| Order book polling | Medium | Medium | **P2** |

---

## Conclusion

Our current `RestingOrderMonitor` is a **proof-of-concept** that demonstrates the logic for dynamic re-checking, but it lacks the critical integration with Kalshi's actual order tracking system. Without server-side order tracking, we cannot reliably know what is actually resting on the exchange.

**Immediate Actions:**
1. Add `kalshi_order_id` to `RestingOrderRecord`
2. Integrate registration with order router after successful placement
3. Implement status polling via portfolio endpoints
4. Filter out IOC orders from resting tracking
5. Handle partial fills and expiration

**Long-term Actions:**
1. Integrate with WebSocket events for real-time updates
2. Add STP awareness and logging
3. Consider order book polling as backup data source
