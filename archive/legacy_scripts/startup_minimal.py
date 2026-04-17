#!/usr/bin/env python3
"""
MERID Minimal Startup Script - For Soak Test

Initializes core systems that actually exist.
"""

import os
import sys
import logging
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Minimal startup for soak test."""
    logger.info("="*70)
    logger.info("MERID MINIMAL STARTUP - SOAK TEST MODE")
    logger.info("="*70)
    
    start_time = time.time()
    components = []
    errors = []
    
    # 1. Check environment
    logger.info("\n1. Checking environment variables...")
    required_vars = ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"]
    missing = [v for v in required_vars if not os.getenv(v)]
    
    if missing:
        logger.error(f"Missing: {', '.join(missing)}")
        return 1
    logger.info("✓ Environment configured")
    
    # 2. Initialize Neo4j
    logger.info("\n2. Initializing Neo4j GraphService...")
    try:
        from core.graph_service import initialize_graph_service
        
        graph = initialize_graph_service(
            uri=os.getenv("NEO4J_URI"),
            user=os.getenv("NEO4J_USER"),
            password=os.getenv("NEO4J_PASSWORD"),
            database=os.getenv("NEO4J_DATABASE", "neo4j")
        )
        graph.run_init()
        components.append("Neo4j GraphService")
        logger.info("✓ Neo4j initialized")
    except Exception as e:
        logger.error(f"✗ Neo4j failed: {e}")
        errors.append(f"Neo4j: {e}")
    
    # 3. Initialize Reality Registry
    logger.info("\n3. Initializing Reality Registry...")
    try:
        from core.reality_registry import RealityRegistry
        
        registry = RealityRegistry()
        components.append("Reality Registry")
        logger.info("✓ Reality Registry initialized")
    except Exception as e:
        logger.error(f"✗ Reality Registry failed: {e}")
        errors.append(f"RealityRegistry: {e}")
    
    # 4. Initialize Event Bus
    logger.info("\n4. Initializing Event Bus...")
    try:
        from core.event_bus import EventBus
        
        event_bus = EventBus()
        components.append("Event Bus")
        logger.info("✓ Event Bus initialized")
    except Exception as e:
        logger.error(f"✗ Event Bus failed: {e}")
        errors.append(f"EventBus: {e}")
    
    # 5. Initialize Consensus Engine
    logger.info("\n5. Initializing Consensus Engine...")
    try:
        from core.consensus_engine import ConsensusEngine
        
        consensus = ConsensusEngine()
        components.append("Consensus Engine")
        logger.info("✓ Consensus Engine initialized")
    except Exception as e:
        logger.error(f"✗ Consensus Engine failed: {e}")
        errors.append(f"ConsensusEngine: {e}")
    
    # Summary
    duration = time.time() - start_time
    logger.info("\n" + "="*70)
    logger.info("STARTUP SUMMARY")
    logger.info("="*70)
    logger.info(f"✓ Components Initialized ({len(components)}):")
    for comp in components:
        logger.info(f"  - {comp}")
    
    if errors:
        logger.info(f"\n✗ Errors ({len(errors)}):")
        for err in errors:
            logger.info(f"  - {err}")
    
    logger.info(f"\nStartup completed in {duration:.2f} seconds")
    
    if len(components) >= 3:
        logger.info("\n🚀 MERID READY FOR SOAK TEST")
        logger.info("="*70)
        return 0
    else:
        logger.info("\n⚠️  MERID STARTED WITH ERRORS")
        logger.info("="*70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
