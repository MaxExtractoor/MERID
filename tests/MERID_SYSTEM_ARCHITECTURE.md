# MERID System Architecture

## High-Level Architecture Overview

MERID is a sophisticated, multi-layered trading platform designed as a "sovereign, local-first decision organism" with unrestricted internal cognition but strictly constrained execution. The system operates with a complex swarm intelligence architecture, multiple execution venues, and comprehensive risk management.

### Core Philosophy
- **Unrestricted Cognition / Constrained Execution**: Internal reasoning is free; actions are gated through guards and human approval
- **Local-First**: Operates entirely offline with optional API ports via credential proxy  
- **Emotionless / Narrative-Immune**: Evidence-based decisions; price/structure as truth
- **Anti-Manipulation / Pro-Human**: Rejects nudging and hidden stakeholders

### Technology Stack
- **Backend**: Python with FastAPI, AsyncIO, SQLite
- **Frontend**: Flutter (mobile), React (web dashboard)
- **ML/AI**: ONNX Runtime + Phi-3 Mini for local LLM, DeepSeek integration
- **Quantum**: Qiskit/Pennylane for simulation (local only)
- **Blockchain**: Web3.dart, Ethereum/Solana/Polkadot integrations
- **Security**: PQC (ML-KEM/ML-DSA), QKD simulation

## Subsystem Breakdown

### 1. MERID Execution Layer (`merid/`)
Primary execution and venue management subsystem.

**Key Components:**
- `merid/execution/router.py` - ExecutionRouter: Unified entrypoint for all trade intents
- `merid/execution/base.py` - TradeExecutor base classes and interfaces
- `merid/execution/portfolio.py` - PortfolioAggregator for position management
- `merid/settings.py` - Core MERID settings and configuration
- `merid/whales.py` - Whale tracking and large trader monitoring

**Event Venues (`merid/event_venues/`):**
- `kalshi/` - Kalshi prediction market integration (client, executor, ws)
- `polymarket/` - Polymarket integration (client, executor, websocket)
- `metaculus/` - Metaculus forecasting platform integration

### 2. Trading System (`trading/`)
Core trading engine with guards, adapters, and execution.

**Key Components:**
- `trading/execution.py` - ExecutionEngine with order and position management
- `trading/router.py` - Trading router bridging to MERID execution
- `trading/paper_trading.py` - Paper trading simulation engine
- `trading/mode_controller.py` - Trading mode management
- `trading/merid_adapter.py` - Adapter bridging trading to MERID

**Guards (`trading/guards/`):**
- Risk checks and pre-trade validation
- Circuit breakers and exposure limits
- Anti-rug pull protection for Solana

**Adapters (`trading/adapters/`):**
- Base adapter interfaces
- Venue-specific implementations
- Order routing logic

**Integrations (`trading/integrations/`):**
- External broker/exchange connections
- API client implementations

### 3. Core Infrastructure (`core/`)
Foundational system components and orchestration.

**Swarm Intelligence:**
- `core/swarm_intelligence.py` - TradingSwarm multi-agent orchestration
- `core/agent_orchestrator.py` - AgentOrchestrator managing 7+ agent types
- `core/agent_swarm.py` - Swarm coordination mechanisms
- `core/dev_swarm.py` - Development swarm for code generation
- `core/consensus_engine.py` - Consensus formation for agent decisions

**System Management:**
- `core/health_monitor.py` - HealthMonitor with periodic checks
- `core/mode_manager.py` - Mode transitions and state management  
- `core/system_orchestrator.py` - High-level system coordination
- `core/orchestrator.py` - Core orchestration logic

**Risk & Governance:**
- `core/automated_risk_controls.py` - Automated risk management
- `core/constitution_enforcer.py` - Charter enforcement
- `core/merid_governance.py` - Governance mechanisms
- `core/error_handling.py` - Comprehensive error management

**Data & State:**
- `core/cache_manager.py` - Caching infrastructure
- `core/persistence_manager.py` - State persistence
- `core/state_recovery.py` - State recovery mechanisms
- `core/offline_data_store.py` - Offline data management

### 4. Data Layer (`data/`)
Market data, feeds, and caching.

**Key Components:**
- `data/live_price_feed.py` - Real-time price feeds from multiple sources
- `data/enhanced_market_feed.py` - Enhanced market data processing
- `data/feed_handlers.py` - Feed handler implementations
- `data/websocket_feed_manager.py` - WebSocket connection management
- `data/geo_aware_venue_system.py` - Geo-aware venue routing
- `data/us_compliant_data_sources.py` - Compliant data source management

### 5. Web Interface (`web/`)
API endpoints and web dashboard.

**Main Application:**
- `web/main.py` - FastAPI application with 30+ router modules
- WebSocket support for real-time updates
- CORS middleware for cross-origin requests

**API Routers (`web/api/`):**
- Trading endpoints (trading, betting, paper_trading)
- System control (system_control, monitoring, compliance)
- Data endpoints (data_endpoints, live_stream, schemas)
- Agent management (agents, governance)
- Financial operations (wallet, treasury, sniping)
- Infrastructure (backup, recovery, notifications)

**Frontend (`web/react/`):**
- React-based trading dashboard
- Real-time market data visualization
- Position and P&L tracking
- Strategy configuration

### 6. Agent System (`agents/`)
Autonomous agents for various functions.

**Agent Types:**
- Twitter monitoring agent
- Telegram bot agent
- News monitor agent
- Arbitrage detection agent
- Execution optimization agent
- Slippage management agent

**Infrastructure:**
- `agents/core/` - Core agent functionality
- `agents/streaming/` - Streaming data processing
- `agents/reflection/` - Agent self-reflection mechanisms

### 7. Swarm Orchestration (`swarm/`)
Multi-agent swarm coordination.

**Components:**
- Agent charters and constitutions
- Performance tracking
- Consensus mechanisms
- Swarm governance

### 8. Analytics & Monitoring (`analytics/`, `monitoring/`)
Analytics computation and system monitoring.

**Analytics:**
- Brier score computation
- Performance metrics
- Risk analytics
- Strategy backtesting

**Monitoring:**
- Health checks
- Performance monitoring
- Alert generation
- Telemetry collection

### 9. Cognitive Core (`cognitive_core/`)
Advanced cognitive capabilities.

**Components:**
- `cognitive_core/agents/` - Cognitive agent implementations
- `cognitive_core/memory/` - Memory management
- `cognitive_core/governance/` - Cognitive governance
- `cognitive_core/simulation/` - Simulation capabilities
- `cognitive_core/spine/` - Message bus implementation

## End-to-End Flows

### Flow 1: Trade Execution (User → Venue)
1. **User Input**: User submits trade intent via Web UI (`web/react/`) or API (`web/api/trading.py`)
2. **Authentication**: Request authenticated via JWT/OAuth2 (`web/api/auth.py`)
3. **Trading Router**: Request routed to `trading/router.py` → `get_execution_router()`
4. **Guard Checks**: `trading/guards/trading_guard.py` validates:
   - Risk limits (max 2% per trade)
   - Portfolio heat checks
   - Position sizing
   - Anti-rug checks for Solana
5. **Execution Router**: `merid/execution/router.py` processes intent:
   - Creates TradeIntent with trader identity
   - Runs explainability service
   - Logs to spectator
6. **Venue Dispatch**: Router selects appropriate executor:
   - `merid/event_venues/kalshi/executor.py` for Kalshi
   - `merid/event_venues/polymarket/executor.py` for Polymarket
   - Via `trading/adapters/` for traditional venues
7. **Order Execution**: Venue executor submits order via API/WebSocket
8. **Result Processing**: TradeResult returned through chain
9. **Portfolio Update**: `merid/execution/portfolio.py` updates positions
10. **Event Publishing**: Result published to event stream for UI updates

### Flow 2: Swarm Intelligence Decision
1. **Signal Generation**: Market data ingested via `data/live_price_feed.py`
2. **Agent Activation**: `core/agent_orchestrator.py` activates relevant agents:
   - MarketAnalyst agent analyzes technicals/sentiment
   - News monitor checks relevant news
   - Arbitrage agent detects opportunities
3. **Consensus Formation**: `core/consensus_engine.py` aggregates decisions:
   - Each agent provides decision with confidence score
   - Weighted voting based on agent performance
   - Requires threshold consensus (e.g., 70% agreement)
4. **Risk Validation**: RiskGuardian agent (`core/swarm_intelligence.py`) validates:
   - Portfolio exposure limits
   - Correlation checks
   - Market regime appropriateness
5. **Execution Decision**: If consensus achieved and risk approved:
   - ExecutionEngine agent optimizes execution strategy
   - Trade intent submitted to ExecutionRouter
6. **Monitoring**: `core/health_monitor.py` tracks:
   - Agent performance metrics
   - Consensus success rate
   - Execution quality

### Flow 3: Real-time Data → Portfolio Management
1. **Data Ingestion**: Multiple data sources connect:
   - `data/websocket_feed_manager.py` maintains WebSocket connections
   - `data/feed_handlers.py` normalizes data formats
2. **Price Aggregation**: `data/enhanced_market_feed.py`:
   - Aggregates prices from multiple venues
   - Calculates VWAP, spread, depth
   - Detects anomalies
3. **Position Marking**: `merid/execution/portfolio.py`:
   - Real-time mark-to-market
   - P&L calculation
   - Risk metric updates
4. **Risk Monitoring**: `core/automated_risk_controls.py`:
   - Continuous exposure monitoring
   - Drawdown limits
   - Correlation risk
5. **Alert Generation**: `core/alerts.py`:
   - Risk limit breaches
   - Unusual market conditions
   - System issues
6. **Dashboard Update**: WebSocket push to UI:
   - Position updates
   - P&L changes
   - Risk metrics

## System Wiring Gaps

### Identified Gaps
1. **Swarm-to-Execution Bridge**: While swarm makes decisions, the connection from `core/swarm_intelligence.py` to `merid/execution/router.py` appears indirect
2. **Data Feed Redundancy**: Multiple data feed implementations without clear primary/fallback designation
3. **Web3 Integration**: Web3 components exist but integration with main trading flow unclear
4. **Quantum Simulation**: Quantum libraries referenced but not wired into decision flow

### Partial Implementations
1. **Dev Swarm**: `core/dev_swarm.py` exists but integration with main system unclear
2. **Offline Mode**: Offline components present but switching mechanism not evident
3. **Flutter Mobile**: Flutter mentioned in docs but `flutter/` directory appears to be build artifacts

### Dead Islands (Modules Not Imported)
Based on import analysis, the following modules appear to be orphaned or not integrated:
1. **lib/merid/** modules - No imports found for `merid_core.py`, `merid_trading.py`, `relay.py`
2. **lib/agents/** modules - Standalone agent implementations not imported in main system
3. **merid/execution/router.py** - ExecutionRouter class not directly imported (accessed via trading/router.py shim)

### Import Path Verification
✅ **Verified Working Imports**:
- `from merid.execution` used in trading/router.py, trading/agents/execution_agent.py
- Trading system properly imports from merid execution layer
- Core modules properly cross-reference each other

⚠️ **Stale or Missing Imports**:
- No direct imports of swarm modules from main execution paths
- lib/ directory modules appear isolated from main codebase
- Some test files have import conflicts due to duplicate names

## Critical Path Components

### Order Placement Path
1. `web/api/trading.py` → API endpoint
2. `trading/router.py` → Trading router
3. `trading/guards/trading_guard.py` → Risk checks
4. `merid/execution/router.py` → Execution routing
5. `merid/event_venues/*/executor.py` → Venue execution

### Risk Check Path
1. `trading/guards/trading_guard.py` → Pre-trade checks
2. `core/automated_risk_controls.py` → Continuous monitoring
3. `core/constitution_enforcer.py` → Charter compliance
4. Circuit breakers → Emergency stops

### Data Flow Path
1. `data/websocket_feed_manager.py` → Raw data
2. `data/feed_handlers.py` → Normalization
3. `data/enhanced_market_feed.py` → Enhancement
4. `core/cache_manager.py` → Caching
5. Distribution to consumers

## Security & Compliance

### Security Layers
- JWT/OAuth2 authentication
- Role-based access control
- Credential proxy for external APIs
- Audit logging for all actions
- Encrypted storage for sensitive data

### Compliance Features
- US compliance configuration
- Immutable audit trail
- Risk limit enforcement
- Position limit controls
- Regulatory reporting capability

## Deployment Architecture

### Kubernetes Layout (from docs/ARCHITECTURE_DESIGN.md)
```
Namespace: merid-prod
├── api-gateway/ (3 replicas, Ingress)
├── core/
│   ├── orchestrator/ (2 replicas)
│   ├── strategy-engine/ (HPA: 2-10)
│   └── risk-service/ (2 replicas, anti-affinity)
├── execution/
│   ├── order-router/ (2 replicas)
│   └── position-manager/ (2 replicas)
├── data/
│   ├── ingestion/ (HPA: 2-8)
│   └── redis-cluster/ (cache + pub/sub)
└── observability/
    ├── prometheus/
    ├── grafana/
    └── distributed-tracing/
```

### Scalability Features
- Horizontal pod autoscaling
- Redis caching layer
- Async/await throughout
- Connection pooling
- Circuit breakers for external services

## Summary

MERID is a production-grade trading platform with:
- **50+ Python packages** implementing core functionality
- **30+ API endpoints** for comprehensive control
- **7+ agent types** in swarm intelligence
- **3 prediction market venues** integrated
- **Multi-layer risk management** with guards and circuit breakers
- **Real-time data processing** from multiple sources
- **Comprehensive monitoring** and observability

The architecture emphasizes safety through constrained execution while allowing sophisticated internal reasoning through the swarm intelligence layer.
