"""
Startup module for orchestrator agents.

Initializes and starts all orchestrator agents (news monitor, social media, 
data feeds, etc.) as background tasks when the application starts.
"""

from __future__ import annotations

import threading
import asyncio
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger("web.startup_agents")

# Lazy imports — these modules may not exist in Kalshi-only deployments
try:
    from agents.news_monitor_agent import NewsMonitorAgent as _NewsMonitorAgent
    _NEWS_MONITOR_AVAILABLE = True
except ImportError:
    _NewsMonitorAgent = None  # type: ignore[assignment,misc]
    _NEWS_MONITOR_AVAILABLE = False
    logger.debug("news_monitor_agent not available — skipping")

try:
    from agents.twitter_agent import get_twitter_agent as _get_twitter_agent
    _TWITTER_AVAILABLE = True
except ImportError:
    _get_twitter_agent = None  # type: ignore[assignment]
    _TWITTER_AVAILABLE = False
    logger.debug("twitter_agent not available — skipping")

try:
    from agents.telegram_agent import get_telegram_agent as _get_telegram_agent
    _TELEGRAM_AVAILABLE = True
except ImportError:
    _get_telegram_agent = None  # type: ignore[assignment]
    _TELEGRAM_AVAILABLE = False
    logger.debug("telegram_agent not available — skipping")


class OrchestratorAgentManager:
    """Manages lifecycle of orchestrator agents."""

    def __init__(self):
        self.news_monitor = None
        self.twitter_agent = None
        self.telegram_agent = None
        self.kalshi_agent_grid = None
        self.portfolio_risk_agent = None
        self.insight_pipeline = None
        self.kalshi_news_agent = None
        self.social_broadcaster = None
        self.reflection_system = None
        self.background_tasks: List[asyncio.Task] = []
        self.running = False

    async def start_all(self):
        """Start all orchestrator agents."""
        if self.running:
            logger.warning("Orchestrator agents already running")
            return

        self.running = True
        logger.info("Starting orchestrator agents...")

        # News monitor (optional)
        if _NEWS_MONITOR_AVAILABLE and _NewsMonitorAgent is not None:
            try:
                self.news_monitor = _NewsMonitorAgent(importance_threshold=0.7)
                news_task = asyncio.create_task(
                    self.news_monitor.start_monitoring(),
                    name="news_monitor",
                )
                self.background_tasks.append(news_task)
                logger.info("✅ News monitor agent started")
            except Exception as exc:
                logger.warning(f"News monitor failed to start (non-fatal): {exc}")

        # Twitter agent (optional)
        if _TWITTER_AVAILABLE and _get_twitter_agent is not None:
            try:
                self.twitter_agent = _get_twitter_agent()
                logger.info("✅ Twitter agent initialized")
            except Exception as exc:
                logger.warning(f"Twitter agent failed to initialize (non-fatal): {exc}")

        # Telegram agent (optional)
        if _TELEGRAM_AVAILABLE and _get_telegram_agent is not None:
            try:
                self.telegram_agent = _get_telegram_agent()
                logger.info("✅ Telegram agent initialized")
            except Exception as exc:
                logger.warning(f"Telegram agent failed to initialize (non-fatal): {exc}")

        # Inject social agents into NewsMonitorAgent (it posts after consensus)
        if self.news_monitor is not None:
            if self.twitter_agent is not None:
                self.news_monitor.twitter_agent = self.twitter_agent
            if self.telegram_agent is not None:
                self.news_monitor.telegram_agent = self.telegram_agent
        
        # Grab reference to Kalshi agent grid (already started by _app_lifespan Phase 0.5).
        # The grid internally manages its own PortfolioRiskAgent — no need to duplicate.
        try:
            from merid.prediction.agent_grid import get_agent_grid
            self.kalshi_agent_grid = get_agent_grid()
            if not self.kalshi_agent_grid._running:
                await self.kalshi_agent_grid.start()
                logger.info("✅ Kalshi agent grid started (fallback)")
            else:
                logger.info("✅ Kalshi agent grid already running (started by lifespan)")
        except Exception as exc:
            logger.warning(f"Kalshi agent grid not available (graceful degradation): {exc}")
        
        # Start price feed monitoring (if configured)
        # price_feed_task = asyncio.create_task(
        #     self._run_price_feed_monitor(),
        #     name="price_feed"
        # )
        # self.background_tasks.append(price_feed_task)
        
        # Start Kalshi insight pipeline → news/X publishing
        # BUG-L13 FIX: Skip in VALIDATION_MODE to reduce startup lag
        _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        if _is_validation:
            logger.info("[VALIDATION MODE] Kalshi insight pipeline skipped (11 category loops deferred)")
        else:
            try:
                from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline
                from merid.publishing.kalshi_news_agent import get_kalshi_news_agent
                self.kalshi_news_agent = get_kalshi_news_agent()
                self.insight_pipeline = get_insight_pipeline()
                self.insight_pipeline.add_consumer(self.kalshi_news_agent.handle_insight)
                await self.insight_pipeline.start()
                logger.info("✅ Kalshi insight pipeline started (Kalshi → consensus → News/X)")
            except Exception as exc:
                logger.warning(f"Kalshi insight pipeline not started (non-fatal): {exc}")

        # Start AgentMesh — 8 mandatory streaming agents (market analyst, news, risk, skeptic,
        # synthesizer, strategy, archivist, meta-audit). Requires WSFeedManager to be running
        # first so streaming_bus.MARKET_DATA receives live price events.
        # BUG-L13 FIX: Skip in VALIDATION_MODE to reduce startup lag
        _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        if _is_validation:
            logger.info("[VALIDATION MODE] AgentMesh skipped (8 streaming agents deferred)")
        else:
            try:
                from agents.agent_mesh import start_agent_mesh
                await start_agent_mesh()
                logger.info("✅ AgentMesh started (8 streaming agents operational)")
            except Exception as exc:
                logger.warning(f"AgentMesh not started (non-fatal): {exc}")

        # Start KalshiSocialBroadcaster — consumes kalshi:order_filled/placed/resolved events
        try:
            from merid.prediction.social_broadcaster import get_social_broadcaster
            self.social_broadcaster = get_social_broadcaster()
            await self.social_broadcaster.start()
            logger.info("✅ KalshiSocialBroadcaster started (trade event → social log)")
        except Exception as exc:
            logger.warning(f"KalshiSocialBroadcaster not started (non-fatal): {exc}")

        # Start ReflectionSystem — loads persisted reflections, starts background flush
        try:
            from agents.reflection.integration import get_reflection_system
            self.reflection_system = get_reflection_system()
            logger.info("✅ ReflectionSystem started (persistence, learning, analytics active)")
        except Exception as exc:
            logger.warning(f"ReflectionSystem not started (non-fatal): {exc}")

        # Start LaneOrchestrator — BTC 15m primary lane + phase-gated additional lanes
        try:
            from merid.lanes.btc15m_lane import get_lane_orchestrator
            from merid.risk.promotion_engine import get_promotion_engine
            _promo = get_promotion_engine()
            _lane_orch = get_lane_orchestrator(base_equity=10.52)
            await _lane_orch.start()
            self._lane_orchestrator = _lane_orch
            logger.info(
                "✅ LaneOrchestrator started (BTC 15m primary | phase=%s)",
                _promo.current_phase.name,
            )
        except Exception as exc:
            logger.warning(f"LaneOrchestrator not started (non-fatal): {exc}")
            self._lane_orchestrator = None

        logger.info(f"✅ {len(self.background_tasks)} orchestrator agents running")
        
    async def stop_all(self):
        """Stop all orchestrator agents."""
        if not self.running:
            return
            
        logger.info("Stopping orchestrator agents...")
        self.running = False
        
        # Stop news monitor
        if self.news_monitor:
            self.news_monitor.stop_monitoring()
        
        # Kalshi agent grid stop is handled by _app_lifespan shutdown.
        # grid.stop() is idempotent, so calling it here is safe but redundant.
        if self.kalshi_agent_grid and self.kalshi_agent_grid._running:
            try:
                await self.kalshi_agent_grid.stop()
                logger.info("✅ Kalshi agent grid stopped (via orchestrator)")
            except Exception as exc:
                logger.warning(f"Kalshi agent grid stop failed: {exc}")

        # Stop LaneOrchestrator
        if getattr(self, "_lane_orchestrator", None):
            try:
                await self._lane_orchestrator.stop()
                logger.info("✅ LaneOrchestrator stopped")
            except Exception as exc:
                logger.warning(f"LaneOrchestrator stop failed: {exc}")

        # Stop insight pipeline
        if self.insight_pipeline:
            try:
                await self.insight_pipeline.stop()
                logger.info("✅ Kalshi insight pipeline stopped")
            except Exception as exc:
                logger.warning(f"Insight pipeline stop failed: {exc}")

        # Stop AgentMesh
        try:
            from agents.agent_mesh import stop_agent_mesh
            await stop_agent_mesh()
            logger.info("✅ AgentMesh stopped")
        except Exception as exc:
            logger.warning(f"AgentMesh stop failed: {exc}")

        # Stop KalshiSocialBroadcaster
        if self.social_broadcaster:
            try:
                await self.social_broadcaster.stop()
                logger.info("✅ KalshiSocialBroadcaster stopped")
            except Exception as exc:
                logger.warning(f"KalshiSocialBroadcaster stop failed: {exc}")

        # Shutdown ReflectionSystem — flushes persistence buffer
        if self.reflection_system:
            try:
                self.reflection_system.shutdown()
                logger.info("✅ ReflectionSystem shutdown complete")
            except Exception as exc:
                logger.warning(f"ReflectionSystem shutdown failed: {exc}")
        
        # Cancel all background tasks
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.background_tasks.clear()
        logger.info("✅ All orchestrator agents stopped")
    
    async def _run_price_feed_monitor(self):
        """Monitor price feeds and generate signals."""
        while self.running:
            try:
                # Price feed monitoring logic here
                await asyncio.sleep(10)
            except Exception as exc:
                logger.error(f"Error in price feed monitor: {exc}")
                await asyncio.sleep(10)


# Global instance
_manager: Optional[OrchestratorAgentManager] = None
_manager_lock = threading.Lock()


def get_orchestrator_manager() -> OrchestratorAgentManager:
    """Get the global orchestrator agent manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = OrchestratorAgentManager()
    return _manager
