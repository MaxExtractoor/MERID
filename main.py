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
    
    # Start agent orchestrator
    try:
        logger.info("Starting agent orchestrator...")
        orchestrator = get_agent_orchestrator()
        asyncio.create_task(orchestrator.start())
    except Exception as e:
        logger.error(f"Failed to start orchestrator: {e}")
    
    # Start consensus engine
    try:
        logger.info("Starting consensus engine...")
        consensus = get_consensus_engine()
        asyncio.create_task(consensus.start())
    except Exception as e:
        logger.error(f"Failed to start consensus: {e}")
    
    # Start simulation miner
    try:
        logger.info("Starting simulation miner...")
        miner = get_continuous_miner()
        asyncio.create_task(miner.start())
    except Exception as e:
        logger.error(f"Failed to start miner: {e}")
    
    # Start audit trail
    try:
        logger.info("Starting audit trail...")
        audit = get_audit_trail()
        asyncio.create_task(audit.start())
    except Exception as e:
        logger.error(f"Failed to start audit: {e}")
    
    # Start execution engine
    try:
        logger.info("Starting execution engine...")
        execution = get_optimal_executor()
        asyncio.create_task(execution.start())
        
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
        asyncio.create_task(agent_mesh.initialize())
        asyncio.create_task(agent_mesh.start())
    except Exception as e:
        logger.error(f"Failed to start agent mesh: {e}")
    
    # Start prediction markets aggregator
    try:
        logger.info("Starting prediction markets aggregator...")
        prediction_agg = get_prediction_aggregator()
        asyncio.create_task(prediction_agg.start())
        # Store in app state for API access
        app.state.prediction_aggregator = prediction_agg
        logger.info(f"Prediction aggregator stored in app.state (id={id(prediction_agg)})")
    except Exception as e:
        logger.error(f"Failed to start prediction markets: {e}")
    
    # Start live price feed streaming
    try:
        logger.info("Starting live price feed...")
        price_feed = get_live_price_feed()
        asyncio.create_task(price_feed.start_streaming())
    except Exception as e:
        logger.error(f"Failed to start price feed: {e}")
    
    # Start intelligence news aggregation
    try:
        logger.info("Starting intelligence news aggregation...")
        asyncio.create_task(aggregate_news())
    except Exception as e:
        logger.error(f"Failed to start intelligence: {e}")
    
    # Start API live data fetching
    try:
        logger.info("Starting API live data feed...")
        asyncio.create_task(fetch_api_prices())
    except Exception as e:
        logger.error(f"Failed to start API live data: {e}")
    
    # Start alert manager
    try:
        logger.info("Starting alert manager...")
        alert_mgr = get_alert_manager()
        asyncio.create_task(alert_mgr.start())
        
        price_feed = get_live_price_feed()
        def on_price_update(price_data):
            alert_mgr.update_price(price_data.symbol, price_data.price)
        price_feed.subscribe(on_price_update)
    except Exception as e:
        logger.error(f"Failed to start alerts: {e}")
    
    # Start health monitor
    try:
        logger.info("Starting health monitor...")
        health_mon = get_health_monitor()
        asyncio.create_task(health_mon.start())
    except Exception as e:
        logger.error(f"Failed to start health monitor: {e}")
    
    logger.info("=" * 60)
    logger.info("MERID SYSTEM LIVE - All components operational")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown sequence
    logger.info("=" * 60)
    logger.info("MERID SYSTEM SHUTTING DOWN")
    logger.info("=" * 60)
    
    try:
        health_mon = get_health_monitor()
        await health_mon.stop()
    except: pass
    
    try:
        alert_mgr = get_alert_manager()
        await alert_mgr.stop()
    except: pass
    
    try:
        prediction_agg = get_prediction_aggregator()
        await prediction_agg.stop()
    except: pass
    
    try:
        price_feed = get_live_price_feed()
        price_feed.stop_streaming()
    except: pass
    
    try:
        await agent_mesh.stop()
    except: pass
    
    try:
        execution = get_optimal_executor()
        await execution.stop()
    except: pass
    
    try:
        audit = get_audit_trail()
        await audit.stop()
    except: pass
    
    try:
        miner = get_continuous_miner()
        await miner.stop()
    except: pass
    
    try:
        consensus = get_consensus_engine()
        await consensus.stop()
    except: pass
    
    try:
        orchestrator = get_agent_orchestrator()
        orchestrator.stop()
    except: pass
    
    logger.info("All components stopped - shutdown complete")


# Create app with lifespan
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
