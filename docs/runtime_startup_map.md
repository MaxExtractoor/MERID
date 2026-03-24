# MERID Runtime Startup/Shutdown Map

## Components booted from `main.py` lifespan

- **WebSocket publishers**: `price_publisher.start` / `stop`, `portfolio_publisher.start` / `stop`; ready when their internal loop is scheduled.
- **Live price feed**: `LivePriceFeed.start_streaming` / `stop_streaming`; publishes to execution + alerts; readiness when first cache fill succeeds.
- **Health monitor**: `HealthMonitor.start` / `stop`; periodic component checks; readiness on start.
- **Execution engine**: `get_optimal_executor().start` / `stop`; wired to price feed; readiness on start completion.
- **Consensus engine**: `ConsensusEngine.start` / `stop`; subscribes to agent outputs; readiness on start completion.
- **Audit trail**: `AuditTrail.start` / `stop`; subscribes to consensus/agent/execution streams.
- **Simulation miner**: `ContinuousMiner.start` / `stop`; consumes consensus events.
- **Agent mesh**: `agent_mesh.initialize` → `agent_mesh.start` / `stop`; readiness when agents started.
- **Agent orchestrator**: `get_agent_orchestrator().start` / `stop`; orchestrates agents; readiness on loop start.
- **Prediction aggregator**: `get_prediction_aggregator().start` / `stop`; readiness on loop start; stored on `app.state`.
- **Intelligence/news**: `aggregate_news()` task (no stop hook).
- **API live data**: `fetch_live_prices()` task (no stop hook).
- **Alert manager**: `get_alert_manager().start` / `stop`; wired to price feed for price updates.
- **Kalshi WS bridge**: `get_ws_bridge().start` / `stop`; readiness after WS tasks scheduled.
- **Orchestrator manager**: `start_all` / `stop_all`; stored on `app.state`.
- **Portfolio risk agent**: `PortfolioRiskAgent.start` / `stop`; readiness after loop scheduled; stored on `app.state`.

## Startup sequence (simplified)

1. Instantiate `TaskManager` + `SystemController`; execution guard is set to `system_block`.
2. Start WebSocket publishers.
3. Start live price feed (critical).
4. Start health monitor (critical).
5. Start execution engine (critical) and wire to price feed if available.
6. Start consensus engine (critical).
7. Start audit trail and simulation miner.
8. Initialize + start agent mesh; start agent orchestrator.
9. Start prediction aggregator; news aggregator; API live prices.
10. Start alert manager (wired to price feed).
11. Start Kalshi WS bridge.
12. Start orchestrator manager and portfolio risk agent (critical).
13. Wait for critical readiness (price feed, consensus, execution, health, portfolio risk); transition to `LIVE_TRADING` and clear system block if all ready, otherwise remain `DEGRADED` with trading blocked.

## Shutdown sequence (deterministic)

1. System mode set to `SHUTTING_DOWN`; trading blocked via execution guard.
2. `TaskManager.stop_all()` invokes registered stop hooks in reverse order and cancels running tasks.
3. Explicit cleanup for orchestrator manager and portfolio risk agent stored on `app.state`.

## Global invariants enforced

- Trading remains blocked until critical subsystems (price feed, consensus, execution, health, portfolio risk) report readiness.
- Execution guard carries a `system_block` reason whenever the system is booting, degraded, or shutting down.
- Readiness events are tracked per subsystem to avoid “task created” being treated as “ready”.
