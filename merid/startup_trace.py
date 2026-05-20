"""MERID Startup Trace Helper — Structured logging for startup sequencing.

This module provides a centralized helper for logging startup phases in a
consistent, grep-friendly format. This makes it easy to trace the exact
execution path from process boot until the main loop begins.

Usage:
    from merid.startup_trace import log_startup_phase

    log_startup_phase("load_profile", "config/profiles/kalshi_crypto_15m.yaml")
    log_startup_phase("init_agents", "merid.prediction.agent_grid")
    log_startup_phase("enter_main_loop", "merid.loop_15m")

The logs are emitted in the format:
    [STARTUP-PHASE] phase=load_profile module=config/profiles/...yaml detail=

This makes it trivial to grep for startup phases and build a timeline of
which modules executed during startup.
"""

import os
from typing import Optional
from utils.logger import get_logger

logger = get_logger("merid.startup_trace")

# Legacy components that should NOT appear in 15m startup
LEGACY_SKIP_COMPONENTS = {
    "KalshiSentimentService",
    "MarketMoodBus",
    "SentimentBus",
    "TwitterStreamHandler",
    "HashtagMonitor",
    "KalshiContinuousTrader",
    "TickerCollector",
    "KalshiInsightPipeline",
    "EnhancedConsensusCoordinator",
    "WatchdogCoordinator",
    "CFGI refresh loop",
    "WSFeedManager",
    "MeridLoop",
    "Agent orchestrator",
    "Execution engine",
    "Agent mesh",
    "Consensus engine streaming",
    "Intelligence news aggregation",
    "API live data feed",
    "Alert manager price feed wire",
    "Signal metrics cache warming",
    "OutcomeResolver",
    "CryptoAlertRouter",
    "SpotBasisTracker",
}


def log_startup_phase(phase: str, module: str, detail: Optional[str] = None) -> None:
    """Log a startup phase in a structured, grep-friendly format.

    Args:
        phase: The phase name (e.g., "load_profile", "init_agents", "enter_main_loop")
        module: The module or file being executed (e.g., "config/profiles/...yaml")
        detail: Optional additional context (e.g., "loaded 5 agents")
    """
    logger.info(
        "[STARTUP-PHASE] phase=%s module=%s detail=%s",
        phase,
        module,
        detail or "",
    )
    
    # Warn if this is a legacy component that should be skipped in 15m profile
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        for skip_component in LEGACY_SKIP_COMPONENTS:
            if skip_component.lower() in module.lower() or skip_component.lower() in (detail or "").lower():
                logger.warning(
                    "[LEGACY-DETECTION] Legacy component '%s' detected in 15m profile startup. "
                    "This component should be skipped for kalshi_crypto_15m_v2. "
                    "Phase=%s Module=%s",
                    skip_component,
                    phase,
                    module,
                )
