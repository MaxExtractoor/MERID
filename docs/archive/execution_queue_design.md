# Top-Edge Execution Queue — Design Document

## Overview

The ExecutionQueue module implements a strict, top-edge, single-file, queue-aware trading pipeline for MERID.

**Core Rule:** Only the current best idea that passes bankroll and reconciliation gets to block the pipe. Everything else is dropped or deferred.

## Architecture

### 1. Per-Ticker State Machine

```
IDLE → PENDING → OPEN → IDLE
```

- **IDLE:** No open position, ready for new orders
- **PENDING:** Order submitted to queue, awaiting execution
- **OPEN:** Position confirmed open, no new entries allowed

While PENDING or OPEN, new intents on the same ticker are rejected.

### 2. Components

| Component | File | Purpose |
|-----------|------|---------|
| `TopEdgeExecutionQueue` | `merid/execution/execution_queue.py` | Priority queue with per-ticker state machine |
| `ExecutionQueueHandler` | `merid/execution/execution_queue_handler.py` | Async processor for queue entries |
| `TopEdgeIntegrator` | `merid/execution/top_edge_integrator.py` | Bridge from arbiter to queue |

### 3. Priority Calculation

```
priority_score = -(edge * confidence * 1000)
```

Higher edge * confidence = higher priority (lower negative score).
FIFO tiebreaker for equal scores.

## Usage

### Submit a Winner from CryptoTopEdgeArbiter

```python
from merid.execution.top_edge_integrator import get_top_edge_integrator
from merid.prediction.crypto_top_edge import get_crypto_top_edge_arbiter

# Get the arbiter result
arbiter = get_crypto_top_edge_arbiter()
result = arbiter.run_cycle()

# Submit winners to execution queue
integrator = get_top_edge_integrator()
for winner in result.winners:
    submission = integrator.submit_winner(winner)
    if submission.action.value == "enqueued":
        print(f"Enqueued: {winner.ticker}")
```

### Direct Queue Submission

```python
from decimal import Decimal
from merid.execution.execution_queue import get_execution_queue, QueueAction

queue = get_execution_queue()

result = queue.submit(
    ticker="KXBTC-15M-100000",
    direction="long",
    size_contracts=10,
    edge=0.15,
    confidence=0.8,
    bankroll_snapshot_usd=Decimal("1000"),
    risk_ok=True,      # Must pass bankroll check
    recon_ok=True,     # Must pass reconciliation check
    agent_id="BTC_15M",
)

if result.action == QueueAction.ENQUEUED:
    print(f"Entry {result.entry_id} enqueued")
```

### State Transitions

```python
# After order accepted by venue
queue.mark_executed(entry_id, ticker, success=True)  # PENDING → OPEN

# After position closed/settled
queue.mark_closed(ticker, entry_id)  # OPEN → IDLE

# Emergency reset
queue.reset_ticker(ticker)  # Force to IDLE
```

## Validation Gates

### risk_ok (Bankroll Check)

Validates:
- Bankroll > 0
- Position size <= 50% of equity (configurable)

Implemented in `TopEdgeIntegrator._check_bankroll()`

### recon_ok (Reconciliation Check)

Validates:
- No existing position in ticker (fresh slot)
- Position cache consistent with fills ledger

Implemented in `TopEdgeIntegrator._check_reconciliation()`

## Metrics

```python
queue = get_execution_queue()
metrics = queue.get_metrics()

# Returns:
{
    "submissions": {
        "total": 100,
        "accepted": 45,
        "rejected_risk": 20,
        "rejected_recon": 10,
        "rejected_state": 15,
        "rejected_bankroll": 5,
        "dropped": 5,
    },
    "executions": {
        "completed": 40,
        "failed": 5,
    },
    "queue": {
        "size": 5,
        "max_size": 100,
    },
    "tickers_not_idle": 8,
}
```

## Logging Format

```
[PMSIGNAL] TOP_EDGE_WINNER ticker=KXBTC-15M direction=long size=10 edge=0.1500 conf=0.80
[PMSIGNAL] VALIDATION ticker=KXBTC-15M risk_ok=True recon_ok=True bankroll=$44.35
[PMSIGNAL] ENQUEUED ticker=KXBTC-15M entry=eq_12345 edge=0.1500
[PMSIGNAL] REJECTED ticker=KXETH-15M action=rejected_state reason=ticker_state=pending

[EXEC_QUEUE] ENQUEUED entry=eq_123 ticker=KXBTC-15M edge=0.1500 conf=0.80 priority=120.0 agent=BTC_15M
[EXEC_QUEUE] DEQUEUE entry=eq_123 ticker=KXBTC-15M edge=0.1500 for execution
[EXEC_QUEUE] EXECUTED entry=eq_123 ticker=KXBTC-15M state=PENDING→OPEN
[EXEC_QUEUE] CLOSED entry=eq_123 ticker=KXBTC-15M state=OPEN→IDLE
```

## Thread Safety

- Per-ticker locks prevent race conditions on state transitions
- Global lock protects ticker state registry
- Queue is thread-safe (PriorityQueue from stdlib)
- Designed for concurrent access from multiple agents

## Configuration

Environment variables:

```bash
# Queue size (default: 100)
EXEC_QUEUE_MAX_SIZE=100

# Pending timeout (seconds, default: 30)
EXEC_QUEUE_PENDING_TIMEOUT=30

# Cooldown after rejection (seconds, default: 30)
EXEC_QUEUE_COOLDOWN=30
```

## Integration Points

1. **CryptoTopEdgeArbiter** → `TopEdgeIntegrator.submit_winner()`
2. **TopEdgeIntegrator** → `TopEdgeExecutionQueue.submit()`
3. **ExecutionQueueHandler** → OrderRouter (pending)
4. **PositionCache** → `mark_closed()` on settlement

## Files Created

1. `merid/execution/execution_queue.py` - Core queue with state machine
2. `merid/execution/execution_queue_handler.py` - Async processor
3. `merid/execution/top_edge_integrator.py` - Arbiter bridge
4. `tests/test_execution_queue.py` - Test suite
5. `docs/execution_queue_design.md` - This document

## Future Work

- [ ] Wire ExecutionQueueHandler to OrderRouter
- [ ] Add position settlement callbacks
- [ ] Implement queue persistence for crash recovery
- [ ] Add circuit breaker on high rejection rate
