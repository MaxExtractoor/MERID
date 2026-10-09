# MERID Trading System - Comprehensive Architecture Audit

## Executive Summary

The MERID trading system is a sophisticated multi-asset prediction market trading platform primarily focused on Kalshi venue crypto contracts (BTC, ETH, SOL, XRP, DOGE 15-minute binaries). The system follows a layered architecture with clear separation between upstream (signal generation), midstream (order management), and downstream (execution & settlement) components.

---

## 1. Component Hierarchy Tree

```
MERID Trading System
├── UPSTREAM (Signal Generation)
│   ├── Market Data Ingestion
│   │   ├── UnifiedSpotService (data/unified_spot_service.py)
│   │   ├── KalshiMarketStateStore (merid/event_venues/kalshi/market_state.py)
│   │   ├── KalshiWebSocketBridge (merid/event_venues/kalshi/ws_bridge.py)
│   │   └── Crypto15mIndicatorStack (merid/signals/crypto_15m_indicators.py)
│   ├── Signal Generation
│   │   ├── AgentGrid15m (merid/prediction/agent_grid_15m.py)
│   │   ├── LeanAgent15m (per-asset agents)
│   │   ├── MomentumFVGSignalGenerator
│   │   └── CryptoSignalsAgent (merid/agents/crypto_signals_agent.py)
│   ├── Strategy Execution
│   │   ├── KalshiTrader (merid/event_venues/kalshi/trading.py)
│   │   ├── Top3EdgeAllocator (merid/trading/top3_edge_allocator.py)
│   │   └── Top3BatchManager (merid/trading/top3_batch_manager.py)
│   └── Candidate Generation
│       ├── CandidateOptimizer (merid/prediction/candidate_optimizer.py)
│       └── KalshiMarketCatalog (merid/event_venues/kalshi/market_catalog.py)
│
├── MIDSTREAM (Order Management)
│   ├── Order Routing
│   │   ├── OrderRouter (merid/event_venues/kalshi/order_router.py) - PRIMARY ROUTER
│   │   ├── ExecutionRouter (merid/execution/router.py)
│   │   └── OrderGate (merid/event_venues/kalshi/order_gate.py)
│   ├── Risk Management
│   │   ├── KalshiRiskManager (merid/event_venues/kalshi/kalshi_risk.py)
│   │   ├── RiskController (merid/risk/kill_switches.py)
│   │   ├── VenueGate (merid/prediction/venue_gate.py)
│   │   ├── GlobalExecutionGuard (merid/guards/global_execution_guard.py)
│   │   └── TradingGuard (trading/guards/trading_guard.py)
│   ├── Position Management
│   │   ├── PositionCache (merid/event_venues/kalshi/position_cache.py)
│   │   ├── PositionMonitor (merid/position_management/position_monitor.py)
│   │   └── ExitPolicy (merid/position_management/exit_policy.py)
│   └── Validation Gates
│       ├── OrderDeduplication (merid/event_venues/kalshi/order_deduplication.py)
│       ├── OrderConstraints (merid/event_venues/kalshi/order_constraints.py)
│       └── ToxicityDetection (merid/event_venues/kalshi/toxicity_detection.py)
│
└── DOWNSTREAM (Execution & Settlement)
    ├── Order Execution
    │   ├── KalshiExecutor (merid/execution/executors/kalshi.py)
    │   ├── KalshiVenueClient (merid/event_venues/kalshi/client.py)
    │   ├── OrderManager (merid/event_venues/kalshi/order_manager.py)
    │   └── ExecutionQueue (merid/execution/execution_queue.py)
    ├── Fill Processing
    │   ├── FillsLedger (merid/event_venues/kalshi/fills_ledger.py)
    │   ├── FillsPoller (merid/event_venues/kalshi/fills_poller.py)
    │   └── FillsPersistence (merid/event_venues/kalshi/fills_persistence.py)
    ├── Position Updates
    │   ├── PositionCache (WS-driven updates)
    │   ├── PositionReconciliation (merid/event_venues/kalshi/active_reconciliation.py)
    │   └── PositionDriftDetector (merid/event_venues/kalshi/position_drift_detector.py)
    ├── Exit Logic
    │   ├── ExitPolicyEngine (merid/position_management/unified_exit_policy_engine.py)
    │   ├── AgentExitIntelligence (merid/position_management/agent_exit_intelligence.py)
    │   ├── ExitOrderUtils (merid/event_venues/kalshi/exit_order_utils.py)
    │   └── RestingOrderMonitor (merid/event_venues/kalshi/resting_order_monitor.py)
    └── Settlement
        ├── KalshiSettlementExecutionGuard
        └── RoundTripMonitor
```

---

## 2. Data Flow Diagram (Text-Based)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              UPSTREAM LAYER                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Coinbase API ──► UnifiedSpotService ──► Spot Price (BTC/ETH/SOL/XRP/DOGE) │
│       │                      │                                           │
│       │                      ▼                                           │
│  Kalshi WS ──► KalshiWebSocketBridge ──► Orderbook Deltas                  │
│       │                      │                                           │
│       │                      ▼                                           │
│  Kalshi REST ──► KalshiMarketStateStore ──► Unified Market State          │
│       │                      │                                           │
│       │                      ▼                                           │
│                    Crypto15mIndicatorStack ──► Technical Indicators        │
│                                             (MACD, RSI, Velocity, FVG)    │
│                                             │                             │
│                                             ▼                             │
│                          AgentGrid15m.run_cycle()                          │
│                                             │                             │
│                                             ▼                             │
│                          Signal Generation (Momentum+FVG)                  │
│                                             │                             │
│                                             ▼                             │
│                          Top3EdgeAllocator.select_top3()                  │
│                                             │                             │
│                                             ▼                             │
│                          TradeIntent (signal + metadata)                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            MIDSTREAM LAYER                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                          OrderIntent                                        │
│                                   │                                         │
│                                   ▼                                         │
│                    OrderGate.check() ──► GateVerdict                       │
│                    (dedup, fill awareness, caps)                           │
│                                   │                                         │
│                                   ▼                                         │
│                 KalshiRiskManager.check_order() ──► Risk Verdict            │
│                 (position limits, category caps, drawdown)                 │
│                                   │                                         │
│                                   ▼                                         │
│                 RiskController.can_trade() ──► Kill Switch Check            │
│                                   │                                         │
│                                   ▼                                         │
│                 VenueGate.check_venue() ──► US Compliance Check            │
│                                   │                                         │
│                                   ▼                                         │
│                 GovernorAgent.approve_trade() ──► Governance Veto           │
│                                   │                                         │
│                                   ▼                                         │
│                          OrderRouter.route_order()                          │
│                                   │                                         │
│                                   ▼                                         │
│                 GlobalAllocator.allocate() ──► Chosen Orders               │
│                 (per-asset limits, $1 cap, edge ranking)                  │
│                                   │                                         │
│                                   ▼                                         │
│                 SlotAllocator.request_allocation() ──► Slot ID             │
│                 (atomic check-and-allocate, exposure tracking)             │
│                                   │                                         │
│                                   ▼                                         │
│                 OrderRouter Validation Gates                                │
│                 (side-aware check, window check, exposure check)            │
│                                   │                                         │
│                                   ▼                                         │
│                          OrderIntent (validated)                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DOWNSTREAM LAYER                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                          OrderIntent (validated)                            │
│                                   │                                         │
│                                   ▼                                         │
│                    KalshiExecutor.execute_order()                            │
│                                   │                                         │
│                                   ▼                                         │
│                 KalshiVenueClient.create_order() ──► OrderResult            │
│                 (REST API call to Kalshi)                                   │
│                                   │                                         │
│                                   ▼                                         │
│                          OrderResult                                        │
│                    (success/failure, fill data)                             │
│                                   │                                         │
│                                   ▼                                         │
│                 FillsLedger.record_fill() ──► Fill Recorded                │
│                 (canonical fill history)                                    │
│                                   │                                         │
│                                   ▼                                         │
│                 PositionCache.update_position() ──► Position Updated       │
│                 (WS-driven + fill-driven updates)                          │
│                                   │                                         │
│                                   ▼                                         │
│                 SlotAllocator.release_slot() ──► Slot Released             │
│                 (on fill or order failure)                                 │
│                                   │                                         │
│                                   ▼                                         │
│                 PositionMonitor.check_exit_conditions()                     │
│                 (take profit, stop loss, time-based exits)                │
│                                   │                                         │
│                                   ▼                                         │
│                 ExitPolicyEngine.generate_exit_order()                     │
│                                   │                                         │
│                                   ▼                                         │
│                          Exit Order (submitted)                             │
│                                   │                                         │
│                                   ▼                                         │
│                 Fill Processing (same as entry)                             │
│                                   │                                         │
│                                   ▼                                         │
│                 PositionCache.close_position() ──► Position Closed         │
│                                   │                                         │
│                                   ▼                                         │
│                          Settlement                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. State Store Inventory

### In-Memory State (Lost on Restart)
- **OrderRouter._asset_entry_windows**: Dict[str, int] - 15-minute window tracking
- **GlobalAllocator._pending_orders**: Dict[str, str] - Pending order tracking
- **GlobalAllocator._asset_positions**: Dict[str, float] - Internal position tracking
- **SlotAllocator._slots**: Dict[str, AllocatedSlot] - Allocated slots
- **PositionCache._positions**: Dict[str, CachedPosition] - Position cache (primary)
- **KalshiMarketStateStore._market_state**: Dict[str, MarketState] - Market state cache

### Persistent State (Survives Restart)
- **FillsLedger._fills**: Dict[str, KalshiFill] - Fill history (canonical source)
- **FillsLedger._intents**: Dict[str, OrderIntent] - Order intent history
- **RiskController._kill_switch_state**: Dict - Kill switch state
- **PositionCache._persisted_positions**: Optional - Position persistence (if enabled)

### External State (Exchange/API)
- **Kalshi REST API**: Positions, orders, fills (source of truth)
- **Kalshi WebSocket**: Real-time orderbook, position updates
- **Coinbase API**: Spot prices (external data source)

---

## 4. Enforcement Point Inventory

### Upstream Enforcement
1. **Top3EdgeAllocator.select_top3()**: Edge threshold filtering
2. **CandidateOptimizer.validate_candidate()**: Candidate validation
3. **AgentGrid15m.run_cycle()**: Signal quality checks

### Midstream Enforcement
4. **OrderGate.check()**: Deduplication, fill awareness, caps
5. **KalshiRiskManager.check_order()**: Position limits, category caps, drawdown
6. **RiskController.can_trade()**: Kill switch check
7. **VenueGate.check_venue()**: US compliance check
8. **GovernorAgent.approve_trade()**: Governance veto
9. **GlobalAllocator.allocate()**: Per-asset limits, $1 cap, edge ranking
10. **SlotAllocator.request_allocation()**: Atomic check-and-allocate
11. **OrderRouter validation gates**: Side-aware check, window check, exposure check
12. **OrderDeduplication.check_duplicate()**: Duplicate order prevention
13. **OrderConstraints.validate()**: Order constraint validation
14. **ToxicityDetection.check_toxicity()**: Toxic market detection

### Downstream Enforcement
15. **KalshiExecutor.execute_order()**: Execution validation
16. **FillsLedger.record_fill()**: Fill validation
17. **PositionCache.update_position()**: Position validation
18. **PositionMonitor.check_exit_conditions()**: Exit condition validation
19. **ExitPolicyEngine.generate_exit_order()**: Exit order validation
20. **KalshiSettlementExecutionGuard**: Settlement validation

---

## 5. Known Issues and Potential Bugs

### Critical Issues (Already Identified)
1. **Corrupted Position Data**: Positions with avg_price_cents = 0 causing deadlock
2. **No Single Source of Truth**: Position state scattered across 6+ components
3. **In-Memory Window Tracking**: Lost on restart, no recovery mechanism
4. **No Atomic Operations**: Sequential checks without rollback
5. **No Data Validation Layer**: Ad-hoc validation only

### Potential Bugs (To Be Investigated)
1. **Race Conditions**: Multiple enforcement layers checking state concurrently
2. **Slot Leak**: Slots not released on all error paths
3. **Window Leak**: Windows not cleared on position exit
4. **Fill Loss**: Fills not recorded in all failure scenarios
5. **Position Drift**: Position cache desync from exchange
6. **Exit Failure**: Exit orders not generated when conditions met
7. **Settlement Failure**: Positions not closed on settlement
8. **Data Corruption**: No validation of external data sources
9. **Memory Leak**: In-memory state growing unbounded
10. **Deadlock**: Circular dependencies between components

### Test Coverage Gaps
1. **End-to-End Tests**: Missing comprehensive flow tests
2. **Race Condition Tests**: Missing concurrent access tests
3. **Failure Scenario Tests**: Missing error path tests
4. **Restart Recovery Tests**: Missing state recovery tests
5. **Data Corruption Tests**: Missing corrupted data handling tests
6. **Performance Tests**: Missing load and stress tests

---

## 6. Component Interface Documentation

### Key Interfaces

#### OrderIntent → OrderRouter
```python
def route_order(intent: OrderIntent) -> OrderResult:
    """Route order through validation gates and execution."""
```

#### OrderIntent → GlobalAllocator
```python
def allocate(candidates: List[OrderCandidate], current_positions: Dict[str, float]) -> List[OrderCandidate]:
    """Allocate orders based on edge ranking under $1 cap."""
```

#### AllocationRequest → SlotAllocator
```python
def request_allocation(request: AllocationRequest) -> Tuple[bool, str, Optional[str]]:
    """Atomically check and allocate slot for position."""
```

#### KalshiFill → FillsLedger
```python
def record_fill(fill: KalshiFill) -> None:
    """Record fill in canonical ledger."""
```

#### KalshiFill → PositionCache
```python
def on_fill(fill: KalshiFill) -> None:
    """Update position cache on fill notification."""
```

#### Position → ExitPolicyEngine
```python
def should_exit(position: Position) -> Tuple[bool, str]:
    """Check if position should be exited."""
```

---

## 7. High-Leverage Bug Categories

Based on the architecture audit, the following categories represent high-leverage bugs that could have system-wide impact:

### Category 1: State Synchronization (Highest Leverage)
- Position cache desync from exchange
- Slot allocator state drift
- Window state corruption
- Pending order state staleness

### Category 2: Enforcement Gaps (High Leverage)
- Race conditions between enforcement layers
- Inconsistent limit enforcement
- Missing validation in error paths
- Bypass of enforcement gates

### Category 3: Data Integrity (High Leverage)
- Corrupted position data
- Invalid fill data
- Stale market data
- Missing data validation

### Category 4: Resource Management (Medium Leverage)
- Slot leaks
- Window leaks
- Memory leaks
- Connection leaks

### Category 5: Failure Handling (Medium Leverage)
- Incomplete error handling
- Missing rollback logic
- Inconsistent failure recovery
- No dead letter queue

---

## Next Steps

This architecture audit provides the foundation for identifying specific high-leverage bugs and critical gaps across the entire stack. The next phase will involve:

1. **Deep dive into each component** to identify specific bugs
2. **Research best practices** for each identified issue
3. **Implement fixes** across upstream, midstream, and downstream
4. **Add comprehensive tests** for all changes
5. **Ensure all tests pass** before deployment

The focus will be on Category 1 and Category 2 issues (State Synchronization and Enforcement Gaps) as they have the highest leverage and system-wide impact.
