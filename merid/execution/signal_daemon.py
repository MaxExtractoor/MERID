"""
Signal Execution Daemon

Production-ready daemon that executes unified signals as orders
with proper signal handling, configuration, and logging.
"""

import time
import signal
import os
from typing import Optional

from utils.logger import get_logger
from merid.signals.execution_bridge import (
    ExecutionConfig,
    get_signal_execution_bridge,
)

logger = get_logger("execution.signal_daemon")

_shutdown = False

def _handle_sigterm(signum, frame):
    """Handle shutdown signals gracefully"""
    global _shutdown
    logger.info("Received shutdown signal, stopping signal execution loop...")
    _shutdown = True

def _load_config_from_env() -> ExecutionConfig:
    """Load execution bridge configuration from environment variables"""
    return ExecutionConfig(
        min_confidence=float(os.getenv("MERID_EXECUTION_MIN_CONFIDENCE", "0.5")),
        min_strength=float(os.getenv("MERID_EXECUTION_MIN_STRENGTH", "0.4")),
        max_notional=float(os.getenv("MERID_EXECUTION_MAX_NOTIONAL", "1000.0")),
        lookback_minutes=int(os.getenv("MERID_EXECUTION_LOOKBACK_MINUTES", "60")),
        target_domains=os.getenv("MERID_EXECUTION_TARGET_DOMAINS", "prediction").split(","),
        target_signal_types=os.getenv("MERID_EXECUTION_TARGET_SIGNAL_TYPES", "kalshi_edge").split(","),
    )

def run_signal_execution_daemon(config: Optional[ExecutionConfig] = None):
    """Main daemon loop for signal execution"""
    global _shutdown
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    
    # Load configuration
    if config is None:
        config = _load_config_from_env()
    
    # Initialize execution bridge
    bridge = get_signal_execution_bridge(config)
    
    logger.info("Starting signal execution daemon loop")
    logger.info(
        f"Configuration: min_confidence={config.min_confidence:.2f}, "
        f"min_strength={config.min_strength:.2f}, max_notional=${config.max_notional:.2f}, "
        f"lookback_minutes={config.lookback_minutes}"
    )
    logger.info(f"Target domains: {config.target_domains}")
    logger.info(f"Target signal types: {config.target_signal_types}")
    
    run_count = 0
    
    while not _shutdown:
        start_time = time.time()
        
        try:
            # Run signal execution
            executed_count = bridge.run_once()
            run_count += 1
            
            # Calculate duration for logging
            duration = time.time() - start_time
            
            # Log results with key metrics
            logger.info(
                f"Signal execution run #{run_count}: executed={executed_count} orders "
                f"duration={duration:.2f}s"
            )
            
            # Get execution statistics periodically
            if run_count % 10 == 0:
                stats = bridge.get_execution_stats()
                logger.info(
                    f"Execution stats: total={stats['total_executions']}, "
                    f"recent_1h={stats['recent_executions_1h']}, "
                    f"avg_notional=${stats['avg_notional']:.2f}"
                )
            
        except Exception as e:
            logger.error(f"Signal execution run failed: {e}")
        
        # Calculate sleep time (minimum 5 seconds, maximum 30 seconds)
        elapsed = time.time() - start_time
        base_interval = 5.0
        max_interval = 30.0
        sleep_for = max(base_interval - elapsed, 0.5)
        sleep_for = min(sleep_for, max_interval)
        
        if not _shutdown:
            logger.debug(f"Sleeping for {sleep_for:.1f}s before next run")
            time.sleep(sleep_for)
    
    logger.info(f"Signal execution daemon loop stopped after {run_count} runs")

if __name__ == "__main__":
    run_signal_execution_daemon()
