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
from core.runtime import TaskManager, SystemController, SystemMode, Subsystem
from merid.execution_guard import get_execution_guard

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager - CANONICAL STARTUP SEQUENCE.
    
    Starts all production components on startup,
    stops them on shutdown.
    """
    logger.info("=" * 60)
    logger.info("MERID PRODUCTION SYSTEM STARTING")
    logger.info("=" * 60)
    task_manager = TaskManager()
    controller = SystemController()
    controller.attach_execution_guard(get_execution_guard())
    app.state.task_manager = task_manager
    app.state.system_controller = controller

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
    from web.services.price_publisher import get_price_publisher
    from web.services.portfolio_publisher import get_portfolio_publisher
    from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
    from web.startup_agents import get_orchestrator_manager
    from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
    from merid.prediction.agent_grid_config import PortfolioRiskConfig

    controller.set_mode(SystemMode.BOOTING)
    price_feed = None

    # Start WebSocket data publishers FIRST (before blocking initialization)
    try:
        logger.info("Starting WebSocket price publisher...")
        price_publisher = get_price_publisher()
        task_manager.create_task(
            "price_publisher", price_publisher.start(), stop=price_publisher.stop, critical=False
        )
        task_manager.create_task(
            "price_publisher_ready",
            controller.watch_readiness(Subsystem.PRICE_PUBLISHER, price_publisher.ready_event, timeout=5),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.PRICE_PUBLISHER, str(e))

    try:
        logger.info("Starting WebSocket portfolio publisher...")
        portfolio_publisher = get_portfolio_publisher()
        task_manager.create_task(
            "portfolio_publisher", portfolio_publisher.start(), stop=portfolio_publisher.stop, critical=False
        )
        task_manager.create_task(
            "portfolio_publisher_ready",
            controller.watch_readiness(Subsystem.PORTFOLIO_PUBLISHER, portfolio_publisher.ready_event, timeout=5),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.PORTFOLIO_PUBLISHER, str(e))

    # Start live price feed streaming
    try:
        logger.info("Starting live price feed...")
        price_feed = get_live_price_feed()
        task_manager.create_task(
            "price_feed", price_feed.start_streaming(), stop=price_feed.stop_streaming, critical=True
        )
        task_manager.create_task(
            "price_feed_ready",
            controller.watch_readiness(Subsystem.PRICE_FEED, price_feed.ready_event, timeout=15),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.PRICE_FEED, str(e))

    # Start health monitor
    try:
        logger.info("Starting health monitor...")
        health_mon = get_health_monitor()
        task_manager.create_task(
            "health_monitor", health_mon.start(), stop=health_mon.stop, critical=True
        )
        task_manager.create_task(
            "health_monitor_ready",
            controller.watch_readiness(Subsystem.HEALTH, health_mon.ready_event, timeout=10),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.HEALTH, str(e))

    # Start execution engine (wired to price feed)
    try:
        logger.info("Starting execution engine...")
        execution = get_optimal_executor()
        task_manager.create_task("execution_engine", execution.start(), stop=execution.stop, critical=True)
        task_manager.create_task(
            "execution_ready",
            controller.watch_readiness(Subsystem.EXECUTION, execution.ready_event, timeout=15),
            critical=False,
        )

        if price_feed:
            def on_execution_price_update(price_data):
                execution.update_price(price_data.symbol, price_data.price)

            price_feed.subscribe(on_execution_price_update)
            logger.info("Execution engine wired to live price feed")
        else:
            logger.warning("Execution engine wiring skipped: price feed unavailable")
    except Exception as e:
        controller.mark_failed(Subsystem.EXECUTION, str(e))

    # Start consensus engine
    try:
        logger.info("Starting consensus engine...")
        consensus = get_consensus_engine()
        task_manager.create_task("consensus_engine", consensus.start(), stop=consensus.stop, critical=True)
        task_manager.create_task(
            "consensus_ready",
            controller.watch_readiness(Subsystem.CONSENSUS, consensus.ready_event, timeout=10),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.CONSENSUS, str(e))

    # Start audit trail
    try:
        logger.info("Starting audit trail...")
        audit = get_audit_trail()
        task_manager.create_task("audit_trail", audit.start(), stop=audit.stop, critical=False)
        controller.mark_ready(Subsystem.AUDIT)
    except Exception as e:
        controller.mark_failed(Subsystem.AUDIT, str(e))

    # Start simulation miner
    try:
        logger.info("Starting simulation miner...")
        miner = get_continuous_miner()
        task_manager.create_task("continuous_miner", miner.start(), stop=miner.stop, critical=False)
        controller.mark_ready(Subsystem.MINER)
    except Exception as e:
        controller.mark_failed(Subsystem.MINER, str(e))

    # Start streaming agent mesh
    try:
        logger.info("Starting streaming agent mesh...")
        await agent_mesh.initialize()
        task_manager.create_task("agent_mesh", agent_mesh.start(), stop=agent_mesh.stop, critical=False)
        task_manager.create_task(
            "agent_mesh_ready",
            controller.watch_readiness(Subsystem.AGENT_MESH, agent_mesh.ready_event, timeout=20),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.AGENT_MESH, str(e))

    # Start agent orchestrator
    try:
        logger.info("Starting agent orchestrator...")
        orchestrator = get_agent_orchestrator()
        task_manager.create_task("agent_orchestrator", orchestrator.start(), stop=orchestrator.stop, critical=False)
        task_manager.create_task(
            "orchestrator_ready",
            controller.watch_readiness(Subsystem.ORCHESTRATOR, orchestrator.ready_event, timeout=10),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.ORCHESTRATOR, str(e))

    # Start prediction markets aggregator
    try:
        logger.info("Starting prediction markets aggregator...")
        prediction_agg = get_prediction_aggregator()
        task_manager.create_task("prediction_aggregator", prediction_agg.start(), stop=prediction_agg.stop, critical=False)
        task_manager.create_task(
            "prediction_aggregator_ready",
            controller.watch_readiness(Subsystem.PREDICTION, prediction_agg.ready_event, timeout=10),
            critical=False,
        )
        app.state.prediction_aggregator = prediction_agg
        logger.info("Prediction aggregator stored in app.state (id=%s)", id(prediction_agg))
    except Exception as e:
        controller.mark_failed(Subsystem.PREDICTION, str(e))

    # Start intelligence news aggregation
    try:
        logger.info("Starting intelligence news aggregation...")
        task_manager.create_task("intelligence_news", aggregate_news(), stop=None, critical=False)
        controller.mark_ready(Subsystem.NEWS_INTELLIGENCE)
    except Exception as e:
        controller.mark_failed(Subsystem.NEWS_INTELLIGENCE, str(e))

    # Start API live data fetching
    try:
        logger.info("Starting API live data feed...")
        task_manager.create_task("api_live_prices", fetch_api_prices(), stop=None, critical=False)
        controller.mark_ready(Subsystem.API_PRICE)
    except Exception as e:
        controller.mark_failed(Subsystem.API_PRICE, str(e))

    # Start alert manager
    try:
        logger.info("Starting alert manager...")
        alert_mgr = get_alert_manager()
        task_manager.create_task("alert_manager", alert_mgr.start(), stop=alert_mgr.stop, critical=False)
        task_manager.create_task(
            "alert_manager_ready",
            controller.watch_readiness(Subsystem.ALERTS, alert_mgr.ready_event, timeout=10),
            critical=False,
        )

        price_feed = price_feed or get_live_price_feed()

        if price_feed:
            def on_price_update(price_data):
                alert_mgr.update_price(price_data.symbol, price_data.price)

            price_feed.subscribe(on_price_update)
        else:
            logger.warning("Alert manager wiring skipped: price feed unavailable")
    except Exception as e:
        controller.mark_failed(Subsystem.ALERTS, str(e))

    # ── Kalshi subsystems ────────────────────────────────────────────────
    # Start Kalshi WS bridge (live market data feed)
    try:
        logger.info("Starting Kalshi WS bridge...")
        ws_bridge = get_ws_bridge()
        task_manager.create_task("kalshi_ws_bridge", ws_bridge.start(), stop=ws_bridge.stop, critical=False)
        task_manager.create_task(
            "kalshi_ws_ready",
            controller.watch_readiness(Subsystem.WS_BRIDGE, ws_bridge.ready_event, timeout=15),
            critical=False,
        )
    except Exception as e:
        controller.mark_failed(Subsystem.WS_BRIDGE, str(e))

    # Start OrchestratorAgentManager (news monitor, twitter, telegram, Kalshi grid)
    try:
        logger.info("Starting orchestrator agent manager...")
        orch_mgr = get_orchestrator_manager()
        await orch_mgr.start_all()
        controller.mark_ready(Subsystem.ORCHESTRATOR_MANAGER)
        app.state.orchestrator_manager = orch_mgr
    except Exception as e:
        controller.mark_failed(Subsystem.ORCHESTRATOR_MANAGER, str(e))

    # Start PortfolioRiskAgent (cross-asset exposure caps, drawdown, margin monitoring)
    try:
        logger.info("Starting portfolio risk agent...")
        portfolio_risk = PortfolioRiskAgent(config=PortfolioRiskConfig())
        task_manager.create_task("portfolio_risk_agent", portfolio_risk.start(), stop=portfolio_risk.stop, critical=True)
        task_manager.create_task(
            "portfolio_risk_ready",
            controller.watch_readiness(Subsystem.PORTFOLIO_RISK, portfolio_risk.ready_event, timeout=15),
            critical=False,
        )
        app.state.portfolio_risk_agent = portfolio_risk
    except Exception as e:
        controller.mark_failed(Subsystem.PORTFOLIO_RISK, str(e))

    controller.set_mode(SystemMode.WARMUP)
    critical_ready = await controller.wait_for_critical(timeout=20)
    if critical_ready:
        controller.set_mode(SystemMode.LIVE_TRADING)
        controller.allow_trading()
    else:
        controller.set_mode(SystemMode.DEGRADED)
        controller.block_trading("critical subsystems not ready")

    logger.info("=" * 60)
    logger.info("MERID SYSTEM LIVE - mode=%s | readiness=%s", controller.mode.value, controller.snapshot())
    logger.info("=" * 60)
    
    yield
    
    # Shutdown sequence
    logger.info("=" * 60)
    logger.info("MERID SYSTEM SHUTTING DOWN")
    logger.info("=" * 60)
    controller.block_trading("shutdown")
    controller.set_mode(SystemMode.SHUTTING_DOWN)

    # Stop components in reverse registration order
    await task_manager.stop_all()

    # Explicit clean-up for orchestrator manager and WS bridge tied to app state
    try:
        if hasattr(app.state, "orchestrator_manager"):
            await app.state.orchestrator_manager.stop_all()
    except Exception as e:
        logger.debug("shutdown: orchestrator_manager stop error: %s", e)
    try:
        if hasattr(app.state, "portfolio_risk_agent"):
            await app.state.portfolio_risk_agent.stop()
    except Exception as e:
        logger.debug("shutdown: portfolio_risk_agent stop error: %s", e)

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
