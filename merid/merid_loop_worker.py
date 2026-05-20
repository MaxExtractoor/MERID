#!/usr/bin/env python3
"""
MeridLoop Standalone Worker

Runs the MeridLoop orchestrator in a separate process with its own asyncio loop,
completely isolated from uvicorn. This bypasses Windows event-loop starvation issues
that occur when MeridLoop runs as a uvicorn background task.

Usage:
    python -m merid.merid_loop_worker
    or
    python merid/merid_loop_worker.py
"""

import asyncio
import logging
import signal
import sys
import time
from typing import Optional

# Configure logging to match main app
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def setup_signal_handlers(merid_loop):
    """Setup graceful shutdown on SIGINT/SIGTERM."""
    def signal_handler(signum, frame):
        logger.info(f"[WORKER] Received signal {signum}, initiating graceful shutdown...")
        merid_loop._running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main_loop(max_ticks: Optional[int] = None):
    """
    Main worker loop with clean asyncio context (no uvicorn).
    
    This runs MeridLoop with its own event loop, avoiding the Windows
    event-loop starvation issues that occur when running as a uvicorn
    background task.
    """
    logger.info("[WORKER] Starting MeridLoop worker process")
    
    try:
        from merid.loop import get_merid_loop
        merid_loop = get_merid_loop()
        logger.info("[WORKER] MeridLoop instance loaded successfully")
    except Exception as e:
        logger.error(f"[WORKER-ERROR] Failed to load MeridLoop: {e}")
        raise
    
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers(merid_loop)
    
    # Run the loop with its own asyncio context
    try:
        await merid_loop.run(max_ticks=max_ticks)
    except asyncio.CancelledError:
        logger.info("[WORKER] MeridLoop cancelled, shutting down")
    except KeyboardInterrupt:
        logger.info("[WORKER] Keyboard interrupt, shutting down")
    except Exception as e:
        logger.exception(f"[WORKER-ERROR] MeridLoop failed: {e}")
        raise
    finally:
        logger.info("[WORKER] MeridLoop worker stopped")


def main():
    """Entry point for standalone worker."""
    import os
    
    # Check if running with max_ticks limit (useful for testing)
    max_ticks = None
    if os.environ.get("MERID_LOOP_MAX_TICKS"):
        max_ticks = int(os.environ.get("MERID_LOOP_MAX_TICKS"))
        logger.info(f"[WORKER] Running with max_ticks={max_ticks}")
    
    # Run with clean asyncio loop
    try:
        asyncio.run(main_loop(max_ticks=max_ticks))
    except KeyboardInterrupt:
        logger.info("[WORKER] Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"[WORKER-ERROR] Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
