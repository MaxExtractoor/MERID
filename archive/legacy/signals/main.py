"""
Unified Signal Daemon Main Entry Point

Production-ready daemon that runs the unified signal pipeline
with proper signal handling, configuration, and logging.
"""

import time
import signal
import os
from typing import Optional

from utils.logger import get_logger
from merid.signals.unified_orchestrator import (
    OrchestratorConfig,
    get_unified_orchestrator,
    run_unified_signal_pipeline,
)

logger = get_logger("signals.main")

_shutdown = False

def _handle_sigterm(signum, frame):
    """Handle shutdown signals gracefully"""
    global _shutdown
    logger.info("Received shutdown signal, stopping unified signal loop...")
    _shutdown = True

def _load_config_from_env() -> OrchestratorConfig:
    """Load orchestrator configuration from environment variables"""
    return OrchestratorConfig(
        enable_crypto_features=os.getenv("MERID_SIGNALS_CRYPTO", "true").lower() == "true",
        enable_debate_integration=os.getenv("MERID_SIGNALS_DEBATE", "true").lower() == "true",
        enable_sentiment_integration=os.getenv("MERID_SIGNALS_SENTIMENT", "true").lower() == "true",
        enable_kalshi_generation=os.getenv("MERID_SIGNALS_KALSHI", "true").lower() == "true",
        enable_cqi_gating=os.getenv("MERID_SIGNALS_CQI", "true").lower() == "true",
        
        # Processing intervals (seconds)
        crypto_interval=int(os.getenv("MERID_SIGNALS_CRYPTO_INTERVAL", "300")),
        debate_interval=int(os.getenv("MERID_SIGNALS_DEBATE_INTERVAL", "600")),
        sentiment_interval=int(os.getenv("MERID_SIGNALS_SENTIMENT_INTERVAL", "300")),
        kalshi_interval=int(os.getenv("MERID_SIGNALS_KALSHI_INTERVAL", "180")),
        cqi_update_interval=int(os.getenv("MERID_SIGNALS_CQI_INTERVAL", "900")),
        
        # Kalshi signal generation thresholds
        kalshi_edge_threshold=float(os.getenv("MERID_SIGNALS_EDGE_THRESHOLD", "5.0")),
        max_signals_per_run=int(os.getenv("MERID_SIGNALS_MAX_PER_RUN", "50")),
    )

def run_signal_daemon(config: Optional[OrchestratorConfig] = None):
    """Main daemon loop for unified signal processing"""
    global _shutdown
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    
    # Load configuration
    if config is None:
        config = _load_config_from_env()
    
    # Initialize orchestrator
    orchestrator = get_unified_orchestrator(config)
    
    logger.info("Starting unified signal daemon loop")
    logger.info(f"Configuration: crypto={config.enable_crypto_features}, "
               f"debate={config.enable_debate_integration}, "
               f"sentiment={config.enable_sentiment_integration}, "
               f"kalshi={config.enable_kalshi_generation}, "
               f"cqi_gating={config.enable_cqi_gating}")
    
    run_count = 0
    
    while not _shutdown:
        start_time = time.time()
        
        try:
            # Run the unified signal pipeline
            results = run_unified_signal_pipeline()
            run_count += 1
            
            # Log results with key metrics
            logger.info(
                f"Unified pipeline run #{run_count}: duration=%.2fs "
                f"crypto=%d debate=%d sentiment=%d kalshi_gen=%d kalshi_suppr=%d "
                f"cqi_allowed=%d cqi_throttled=%d cqi_suppressed=%d errors=%d",
                results.duration,
                results.crypto_processed,
                results.debate_processed,
                results.sentiment_processed,
                results.kalshi_generated,
                results.kalshi_suppressed,
                results.cqi_gated_allowed,
                results.cqi_gated_throttled,
                results.cqi_gated_suppressed,
                len(results.errors),
            )
            
            # Log any errors for debugging
            if results.errors:
                logger.warning(f"Pipeline errors: {results.errors[:3]}")  # Show first 3 errors
            
        except Exception as e:
            logger.error(f"Pipeline run failed: {e}")
        
        # Calculate sleep time (minimum 5 seconds, maximum 60 seconds)
        elapsed = time.time() - start_time
        base_interval = 5.0
        max_interval = 60.0
        sleep_for = max(base_interval - elapsed, 0.5)
        sleep_for = min(sleep_for, max_interval)
        
        if not _shutdown:
            logger.debug(f"Sleeping for {sleep_for:.1f}s before next run")
            time.sleep(sleep_for)
    
    logger.info(f"Unified signal daemon loop stopped after {run_count} runs")

if __name__ == "__main__":
    run_signal_daemon()
