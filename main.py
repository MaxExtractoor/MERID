"""
MERID Main Entry Point - Production Streaming System

Boots:
1. Streaming data workers (market + news)
2. Agent mesh (8 autonomous agents)
3. Consensus engine (voting + trust + veto)
4. Simulation mining (PoUS blocks)
5. Audit trail (immutable log)
6. Web API + WebSocket streams
"""

import asyncio
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from web.main import create_app
from streams import start_market_stream, stop_market_stream
from streams import start_news_stream, stop_news_stream
from agents.agent_mesh import start_agent_mesh, stop_agent_mesh
from core.consensus_engine import get_consensus_engine
from simulation.continuous_miner import get_continuous_miner
from core.audit_trail import get_audit_trail
from utils.logger import get_logger

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Starts all production components on startup,
    stops them on shutdown.
    """
    logger.info("=" * 60)
    logger.info("MERID PRODUCTION SYSTEM STARTING")
    logger.info("=" * 60)
    
    # Start streaming workers
    logger.info("Starting data ingestion streams...")
    await start_market_stream()
    await start_news_stream()
    
    # Start agent mesh (8 agents)
    logger.info("Starting autonomous agent mesh (8 agents)...")
    await start_agent_mesh()
    
    # Start consensus engine
    logger.info("Starting consensus engine...")
    consensus = get_consensus_engine()
    await consensus.start()
    
    # Start simulation miner
    logger.info("Starting simulation miner (PoUS)...")
    miner = get_continuous_miner()
    await miner.start()
    
    # Start audit trail
    logger.info("Starting immutable audit trail...")
    audit = get_audit_trail()
    await audit.start()
    
    logger.info("=" * 60)
    logger.info("MERID SYSTEM LIVE - All components operational")
    logger.info("  • Data streams: ACTIVE")
    logger.info("  • Agent mesh: 8 AGENTS RUNNING")
    logger.info("  • Consensus: RESOLVING")
    logger.info("  • Simulation: MINING BLOCKS")
    logger.info("  • Audit: RECORDING")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("=" * 60)
    logger.info("MERID SYSTEM SHUTTING DOWN")
    logger.info("=" * 60)
    
    await audit.stop()
    await miner.stop()
    await consensus.stop()
    await stop_agent_mesh()
    await stop_market_stream()
    await stop_news_stream()
    
    logger.info("All components stopped - shutdown complete")


# Create app with lifespan
app = create_app(lifespan=lifespan)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
