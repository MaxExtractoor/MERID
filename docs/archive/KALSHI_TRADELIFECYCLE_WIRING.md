# TradeLifecycle ID Wiring Guide

This document describes how to wire TradeLifecycle IDs through the signal → order → fill → settlement pipeline for end-to-end trade tracing.

## Overview

Every trade should be traceable from signal generation to settlement using a single `trade_id`, mirroring the Kalshi market lifecycle (creation → trading → determination → settlement).

## Implementation Plan

### 1. Signal Generation (Trade ID Creation)

**Location:** Signal generation in trading agents (e.g., `merid/prediction/trading_agent.py`)

**Action:** Generate unique `trade_id` at the earliest point where a trade intent exists.

```python
import uuid
from merid.event_venues.kalshi.trade_lifecycle import record_lifecycle_event, LifecycleStage

# In signal generation path
trade_id = str(uuid.uuid4())

# Record initial lifecycle event
record_lifecycle_event(
    trade_id=trade_id,
    stage=LifecycleStage.SIGNAL_GENERATED,
    ticker=market.ticker,
    metadata={
        "agent_id": agent_id,
        "signal_time": datetime.utcnow().isoformat(),
        "rationale": rationale,
    }
)
```

### 2. Strategy Gating

**Location:** Strategy gating logic in trading agents

**Action:** Thread `trade_id` through strategy gating and record stage transition.

```python
# After passing strategy gates
record_lifecycle_event(
    trade_id=trade_id,
    stage=LifecycleStage.STRATEGY_GATED,
    ticker=market.ticker,
    metadata={
        "edge_pct": edge_pct,
        "confidence": confidence,
    }
)
```

### 3. Risk Approval

**Location:** Risk check logic in trading agents or risk modules

**Action:** Thread `trade_id` through risk checks and record stage transition.

```python
# After passing risk checks
record_lifecycle_event(
    trade_id=trade_id,
    stage=LifecycleStage.RISK_APPROVED,
    ticker=market.ticker,
    metadata={
        "risk_checks_passed": True,
    }
)
```

### 4. Order Placement

**Location:** Order routing in `merid/event_venues/kalshi/order_router.py`

**Action:** Add `trade_id` to `OrderIntent` dataclass and record order placement.

```python
# Add to OrderIntent dataclass
@dataclass
class OrderIntent:
    # ... existing fields ...
    trade_id: Optional[str] = None  # NEW FIELD

# In order routing
record_lifecycle_event(
    trade_id=intent.trade_id,
    stage=LifecycleStage.ORDER_PLACED,
    ticker=intent.ticker,
    metadata={
        "order_id": kalshi_order_id,
        "side": intent.side,
        "action": intent.action,
        "price_cents": intent.price_cents,
        "count": intent.count,
    }
)
```

### 5. Fill Reception

**Location:** Fill handling in `merid/event_venues/kalshi/fills_poller.py`

**Action:** Thread `trade_id` through fill processing and record fill receipt.

```python
# In fill processing
record_lifecycle_event(
    trade_id=trade_id,
    stage=LifecycleStage.FILL_RECEIVED,
    ticker=ticker,
    metadata={
        "fill_id": fill_id,
        "filled_size": filled_size,
        "fill_price_cents": fill_price,
    }
)
```

### 6. Settlement

**Location:** Settlement processing in `merid/event_venues/kalshi/fills_poller.py`

**Action:** Record final settlement with outcome and P&L.

```python
# In settlement processing
record_lifecycle_event(
    trade_id=trade_id,
    stage=LifecycleStage.SETTLED,
    ticker=ticker,
    metadata={
        "outcome": internal_outcome.value,
        "market_result": market_result,
        "pnl_cents": realized_pnl_cents,
        "settlement_timestamp": settlement_timestamp,
    }
)
```

## Validation Script

Create a validation script to verify wiring:

```python
# scripts/validate_trade_lifecycle_wiring.py
import json
from collections import defaultdict

def validate_lifecycle_sequence(lifecycle_logs):
    """Validate that lifecycle events form sensible sequences."""
    trades_by_id = defaultdict(list)
    
    for event in lifecycle_logs:
        trade_id = event['trade_id']
        trades_by_id[trade_id].append(event)
    
    errors = []
    
    for trade_id, events in trades_by_id.items():
        # Sort by timestamp
        events = sorted(events, key=lambda x: x['timestamp'])
        
        # Check for complete sequence
        stages = [e['stage'] for e in events]
        
        expected_sequence = [
            'SIGNAL_GENERATED',
            'STRATEGY_GATED',
            'RISK_APPROVED',
            'ORDER_PLACED',
            'FILL_RECEIVED',
            'SETTLED'
        ]
        
        # Validate monotonic progression
        for i in range(len(stages) - 1):
            current_idx = expected_sequence.index(stages[i])
            next_idx = expected_sequence.index(stages[i + 1])
            if next_idx <= current_idx:
                errors.append(f"Trade {trade_id}: Non-monotonic stage progression {stages[i]} -> {stages[i + 1]}")
        
        # Check for duplicates
        if len(stages) != len(set(stages)):
            errors.append(f"Trade {trade_id}: Duplicate stages detected")
    
    return errors
```

## Integration Points

### Files to Modify

1. **`merid/prediction/trading_agent.py`**
   - Generate `trade_id` in signal generation
   - Pass `trade_id` through gating logic
   - Add `trade_id` to order intent construction

2. **`merid/event_venues/kalshi/order_router.py`**
   - Add `trade_id` field to `OrderIntent` dataclass
   - Log lifecycle event at ORDER_PLACED stage
   - Ensure `trade_id` is passed to fill processing

3. **`merid/event_venues/kalshi/fills_poller.py`**
   - Extract `trade_id` from order/fill data
   - Log lifecycle event at FILL_RECEIVED stage
   - Log lifecycle event at SETTLED stage with outcome

### Data Flow

```
Signal Generation
    ↓ (trade_id generated)
Strategy Gating
    ↓ (trade_id threaded)
Risk Approval
    ↓ (trade_id threaded)
OrderIntent (with trade_id)
    ↓ (trade_id logged)
Kalshi Order
    ↓ (trade_id in metadata)
Fill Received
    ↓ (trade_id extracted)
Settlement
    ↓ (trade_id logged)
TradeLifecycle Complete
```

## Testing

### Unit Tests

1. **Trade ID Uniqueness:** Verify that generated trade IDs are unique
2. **Stage Sequence:** Validate that stages progress monotonically
3. **Metadata Completeness:** Ensure required metadata is present at each stage
4. **ID Threading:** Verify trade_id is preserved through all stages

### Integration Tests

1. **End-to-End Trace:** Pick a sample trade_id and trace through all stages
2. **Missing Stages:** Detect trades that don't reach SETTLED stage
3. **Orphaned Events:** Detect lifecycle events without corresponding trade completion

## Monitoring

Add metrics to track:

- **Trade ID Generation Rate:** How many trade_ids are generated per hour
- **Lifecycle Completion Rate:** Percentage of trades that reach SETTLED stage
- **Stage Drop-off Rates:** Percentage of trades that drop off at each stage
- **Duplicate Detection:** Alert on duplicate (trade_id, stage) pairs

## Rollout Plan

1. **Phase 1:** Add trade_id generation and logging in signal generation path only
2. **Phase 2:** Thread trade_id through strategy and risk gating
3. **Phase 3:** Add trade_id to OrderIntent and order routing
4. **Phase 4:** Thread trade_id through fill processing
5. **Phase 5:** Complete settlement logging with trade_id
6. **Phase 6:** Enable validation script and monitor for errors

## Backward Compatibility

This change is backward compatible:
- Existing code that doesn't use trade_id will continue to work (trade_id is Optional)
- Lifecycle logging is additive and doesn't affect core trading logic
- Validation is opt-in via separate script
