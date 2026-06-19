"""
MERID Main Entry Point - Production Streaming System

Boots:
1. Streaming data workers (market + news)
2. Agent mesh (8 autonomous agents)
3. Consensus engine (voting + trust + veto)
4. Simulation mining (PoUS blocks)
5. Audit trail (immutable log)
6. Web API + WebSocket streams
7. Execution engine
8. Alert manager
9. Health monitor
"""

import asyncio
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from web.main import create_app
from utils.logger import get_logger
from web.api import test_page

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager - CANONICAL STARTUP SEQUENCE.

    Starts all production components on startup,
    stops them on shutdown.
    """
    from core.task_supervision import get_task_manager
    from core.runtime_state import set_runtime_mode, RuntimeMode, mark_startup_complete

    task_mgr = get_task_manager()
    set_runtime_mode(RuntimeMode.BOOTING)

    logger.info("=" * 60)
    logger.info("MERID PRODUCTION SYSTEM STARTING")
    logger.info("=" * 60)
    
    # Import all components
    from core.agent_orchestrator import get_agent_orchestrator
    from core.consensus_engine import get_consensus_engine
    from simulation.continuous_miner import get_continuous_miner
    from core.audit_trail import get_audit_trail
    from trading.execution import get_optimal_executor
    from data.live_price_feed import get_live_price_feed
    from agents.agent_mesh import agent_mesh
    from monitoring.prediction_markets import get_prediction_aggregator
    from core.alerts import get_alert_manager
    from core.health import get_health_monitor
    from web.api.intelligence import aggregate_news
    from web.api.live_data import fetch_live_prices as fetch_api_prices
    
    # Start WebSocket data publishers FIRST (before any blocking initialization)
    try:
        logger.info("Starting WebSocket price publisher...")
        from web.services.price_publisher import get_price_publisher
        price_publisher = get_price_publisher()
        task_mgr.create_task(price_publisher.start(), name="price-publisher")
        logger.info("Price publisher task created")
    except Exception as e:
        logger.error(f"Failed to start price publisher: {e}", exc_info=True)

    try:
        logger.info("Starting WebSocket portfolio publisher...")
        from web.services.portfolio_publisher import get_portfolio_publisher
        portfolio_publisher = get_portfolio_publisher()
        task_mgr.create_task(portfolio_publisher.start(), name="portfolio-publisher")
        logger.info("Portfolio publisher task created")
    except Exception as e:
        logger.error(f"Failed to start portfolio publisher: {e}", exc_info=True)
    
    # Yield to event loop to allow publishers to start
    await asyncio.sleep(0.1)
    
    # Start agent orchestrator
    try:
        logger.info("Starting agent orchestrator...")
        orchestrator = get_agent_orchestrator()
        task_mgr.create_task(orchestrator.start(), name="agent-orchestrator")
    except Exception as e:
        logger.error(f"Failed to start orchestrator: {e}")

    # Yield to event loop after each major component
    await asyncio.sleep(0)

    # Start consensus engine
    try:
        logger.info("Starting consensus engine...")
        consensus = get_consensus_engine()
        task_mgr.create_task(consensus.start(), name="consensus-engine")
    except Exception as e:
        logger.error(f"Failed to start consensus: {e}")

    # Start simulation miner
    try:
        logger.info("Starting simulation miner...")
        miner = get_continuous_miner()
        task_mgr.create_task(miner.start(), name="simulation-miner")
    except Exception as e:
        logger.error(f"Failed to start miner: {e}")

    # Start audit trail
    try:
        logger.info("Starting audit trail...")
        audit = get_audit_trail()
        task_mgr.create_task(audit.start(), name="audit-trail")
    except Exception as e:
        logger.error(f"Failed to start audit: {e}")

    # Start execution engine
    # TODO(BUG-10): Wire execution engine to readiness flags before allowing execution
    # The execution engine should check:
    # 1. Runtime state is LIVE_TRADING (not BOOTING or OBSERVE_ONLY)
    # 2. Price feed is connected and streaming
    # 3. Consensus engine is operational
    # 4. Risk engine has completed initial checks
    # Currently, the engine starts immediately which could lead to execution
    # attempts before critical dependencies are ready.
    try:
        logger.info("Starting execution engine...")
        execution = get_optimal_executor()
        task_mgr.create_task(execution.start(), name="execution-engine")

        # Wire execution engine to live price feed
        price_feed = get_live_price_feed()
        def on_execution_price_update(price_data):
            execution.update_price(price_data.symbol, price_data.price)
        price_feed.subscribe(on_execution_price_update)
        logger.info("Execution engine wired to live price feed")
    except Exception as e:
        logger.error(f"Failed to start execution: {e}")

    # Start streaming agent mesh
    try:
        logger.info("Starting streaming agent mesh...")
        task_mgr.create_task(agent_mesh.initialize(), name="agent-mesh-init")
        task_mgr.create_task(agent_mesh.start(), name="agent-mesh")
    except Exception as e:
        logger.error(f"Failed to start agent mesh: {e}")

    # Start prediction markets aggregator
    try:
        logger.info("Starting prediction markets aggregator...")
        prediction_agg = get_prediction_aggregator()
        task_mgr.create_task(prediction_agg.start(), name="prediction-aggregator")
        # Store in app state for API access
        app.state.prediction_aggregator = prediction_agg
        logger.info(f"Prediction aggregator stored in app.state (id={id(prediction_agg)})")
    except Exception as e:
        logger.error(f"Failed to start prediction markets: {e}")

    await asyncio.sleep(0)  # Yield to event loop

    # Start live price feed streaming
    try:
        logger.info("Starting live price feed...")
        price_feed = get_live_price_feed()
        task_mgr.create_task(price_feed.start_streaming(), name="live-price-feed")
    except Exception as e:
        logger.error(f"Failed to start price feed: {e}")

    await asyncio.sleep(0)  # Yield to event loop

    # Start intelligence news aggregation
    try:
        logger.info("Starting intelligence news aggregation...")
        task_mgr.create_task(aggregate_news(), name="intelligence-news")
    except Exception as e:
        logger.error(f"Failed to start intelligence: {e}")

    await asyncio.sleep(0)  # Yield to event loop

    # Start API live data fetching
    try:
        logger.info("Starting API live data feed...")
        task_mgr.create_task(fetch_api_prices(), name="api-live-data")
    except Exception as e:
        logger.error(f"Failed to start API live data: {e}")

    await asyncio.sleep(0)  # Yield to event loop

    # Start alert manager
    try:
        logger.info("Starting alert manager...")
        alert_mgr = get_alert_manager()
        task_mgr.create_task(alert_mgr.start(), name="alert-manager")

        price_feed = get_live_price_feed()
        def on_price_update(price_data):
            alert_mgr.update_price(price_data.symbol, price_data.price)
        price_feed.subscribe(on_price_update)
    except Exception as e:
        logger.error(f"Failed to start alerts: {e}")

    await asyncio.sleep(0)  # Yield to event loop

    # Start health monitor
    try:
        logger.info("Starting health monitor...")
        health_mon = get_health_monitor()
        task_mgr.create_task(health_mon.start(), name="health-monitor")
    except Exception as e:
        logger.error(f"Failed to start health monitor: {e}")

    await asyncio.sleep(0)

    # ── Kalshi subsystems ────────────────────────────────────────────────
    # Start Kalshi WS bridge (live market data feed)
    try:
        logger.info("Starting Kalshi WS bridge...")
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        ws_bridge = get_ws_bridge()
        task_mgr.create_task(ws_bridge.start(), name="kalshi-ws-bridge")
        logger.info("✅ Kalshi WS bridge started")
    except Exception as e:
        logger.warning(f"Kalshi WS bridge not started (non-fatal): {e}")

    await asyncio.sleep(0)

    # Start OrchestratorAgentManager (news monitor, twitter, telegram, Kalshi grid)
    try:
        logger.info("Starting orchestrator agent manager...")
        from web.startup_agents import get_orchestrator_manager
        orch_mgr = get_orchestrator_manager()
        await orch_mgr.start_all()
        app.state.orchestrator_manager = orch_mgr
        logger.info("✅ Orchestrator agent manager started")
    except Exception as e:
        logger.warning(f"Orchestrator agent manager not started (non-fatal): {e}")

    await asyncio.sleep(0)

    # Start PortfolioRiskAgent (cross-asset exposure caps, drawdown, margin monitoring)
    try:
        logger.info("Starting portfolio risk agent...")
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
        from merid.prediction.agent_grid_config import load_agent_grid_config
        _grid_cfg = load_agent_grid_config()
        portfolio_risk = PortfolioRiskAgent(config=_grid_cfg.portfolio_risk)
        await portfolio_risk.start()
        app.state.portfolio_risk_agent = portfolio_risk
        logger.info("✅ Portfolio risk agent started")
    except Exception as e:
        logger.warning(f"Portfolio risk agent not started (non-fatal): {e}")

    await asyncio.sleep(0)  # Final yield before completing startup

    # Mark startup complete and transition to LIVE_TRADING
    mark_startup_complete()
    task_status = task_mgr.get_status()
    logger.info(f"Task manager: {task_status['total']} tasks ({task_status['active']} active)")

    logger.info("=" * 60)
    logger.info("MERID SYSTEM LIVE - All components operational")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown sequence
    logger.info("=" * 60)
    logger.info("MERID SYSTEM SHUTTING DOWN")
    logger.info("=" * 60)

    # Transition to SHUTTING_DOWN mode
    set_runtime_mode(RuntimeMode.SHUTTING_DOWN)

    # Import shutdown helper
    from core.task_supervision import shutdown_with_timeout

    # Stop WebSocket publishers
    try:
        from web.services.price_publisher import get_price_publisher
        price_publisher = get_price_publisher()
        await shutdown_with_timeout(price_publisher.stop(), timeout=5.0, component_name="price_publisher")
    except Exception as e:
        logger.debug("shutdown: price_publisher stop error: %s", e)

    try:
        from web.services.portfolio_publisher import get_portfolio_publisher
        portfolio_publisher = get_portfolio_publisher()
        await shutdown_with_timeout(portfolio_publisher.stop(), timeout=5.0, component_name="portfolio_publisher")
    except Exception as e:
        logger.debug("shutdown: portfolio_publisher stop error: %s", e)

    try:
        health_mon = get_health_monitor()
        await shutdown_with_timeout(health_mon.stop(), timeout=5.0, component_name="health_monitor")
    except Exception as e:
        logger.debug("shutdown: health_monitor stop error: %s", e)

    try:
        alert_mgr = get_alert_manager()
        await shutdown_with_timeout(alert_mgr.stop(), timeout=5.0, component_name="alert_manager")
    except Exception as e:
        logger.debug("shutdown: alert_manager stop error: %s", e)

    try:
        prediction_agg = get_prediction_aggregator()
        await shutdown_with_timeout(prediction_agg.stop(), timeout=5.0, component_name="prediction_aggregator")
    except Exception as e:
        logger.debug("shutdown: prediction_aggregator stop error: %s", e)

    try:
        price_feed = get_live_price_feed()
        price_feed.stop_streaming()
    except Exception as e:
        logger.debug("shutdown: price_feed stop error: %s", e)

    try:
        await shutdown_with_timeout(agent_mesh.stop(), timeout=10.0, component_name="agent_mesh")
    except Exception as e:
        logger.debug("shutdown: agent_mesh stop error: %s", e)

    try:
        execution = get_optimal_executor()
        await shutdown_with_timeout(execution.stop(), timeout=10.0, component_name="execution")
    except Exception as e:
        logger.debug("shutdown: execution stop error: %s", e)

    try:
        audit = get_audit_trail()
        await shutdown_with_timeout(audit.stop(), timeout=5.0, component_name="audit_trail")
    except Exception as e:
        logger.debug("shutdown: audit_trail stop error: %s", e)

    try:
        miner = get_continuous_miner()
        await shutdown_with_timeout(miner.stop(), timeout=5.0, component_name="miner")
    except Exception as e:
        logger.debug("shutdown: miner stop error: %s", e)

    try:
        consensus = get_consensus_engine()
        await shutdown_with_timeout(consensus.stop(), timeout=5.0, component_name="consensus")
    except Exception as e:
        logger.debug("shutdown: consensus stop error: %s", e)

    try:
        orchestrator = get_agent_orchestrator()
        orchestrator.stop()
    except Exception as e:
        logger.debug("shutdown: orchestrator stop error: %s", e)

    try:
        from web.startup_agents import get_orchestrator_manager
        orch_mgr = get_orchestrator_manager()
        await shutdown_with_timeout(orch_mgr.stop_all(), timeout=10.0, component_name="orchestrator_manager")
    except Exception as e:
        logger.debug("shutdown: orchestrator_manager stop error: %s", e)

    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        await shutdown_with_timeout(get_ws_bridge().stop(), timeout=5.0, component_name="ws_bridge")
    except Exception as e:
        logger.debug("shutdown: ws_bridge stop error: %s", e)

    try:
        if hasattr(app.state, "portfolio_risk_agent"):
            await shutdown_with_timeout(app.state.portfolio_risk_agent.stop(), timeout=5.0, component_name="portfolio_risk_agent")
    except Exception as e:
        logger.debug("shutdown: portfolio_risk_agent stop error: %s", e)

    # Cancel remaining background tasks with timeout
    logger.info("Cancelling remaining background tasks...")
    await task_mgr.shutdown(timeout=10.0)

    logger.info("All components stopped - shutdown complete")


# Create app WITH lifespan — boots all streaming components on startup
app = create_app(lifespan=lifespan)

# Add test page router
app.include_router(test_page.router, tags=["test"])


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
