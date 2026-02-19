"""
Startup module for orchestrator agents.

Initializes and starts all orchestrator agents (news monitor, social media, 
data feeds, etc.) as background tasks when the application starts.
"""

from __future__ import annotations

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
        
        # Start Kalshi agent grid for prediction domain
        try:
            from merid.prediction.agent_grid import get_agent_grid
            self.kalshi_agent_grid = get_agent_grid()
            await self.kalshi_agent_grid.start()
            logger.info("✅ Kalshi agent grid started")
        except Exception as exc:
            logger.warning(f"Kalshi agent grid not started (graceful degradation): {exc}")

        # Start PortfolioRiskAgent — feeds live Kalshi balance/positions into
        # KalshiRiskManager and PositionSizer so vol & sizing show live data.
        try:
            from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
            from merid.prediction.agent_grid_config import PortfolioRiskConfig
            trading_agents = (
                list(self.kalshi_agent_grid._agents.values())
                if self.kalshi_agent_grid and hasattr(self.kalshi_agent_grid, "_agents")
                else []
            )
            self.portfolio_risk_agent = PortfolioRiskAgent(
                config=PortfolioRiskConfig(),
                trading_agents=trading_agents,
            )
            await self.portfolio_risk_agent.start()
            logger.info("✅ Portfolio risk agent started")
        except Exception as exc:
            logger.warning(f"Portfolio risk agent not started (non-fatal): {exc}")
        
        # Start price feed monitoring (if configured)
        # price_feed_task = asyncio.create_task(
        #     self._run_price_feed_monitor(),
        #     name="price_feed"
        # )
        # self.background_tasks.append(price_feed_task)
        
        # Start Kalshi insight pipeline → news/X publishing
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

        # Start ReflectionSystem — loads persisted reflections, starts background flush
        try:
            from agents.reflection.integration import get_reflection_system
            self.reflection_system = get_reflection_system()
            logger.info("✅ ReflectionSystem started (persistence, learning, analytics active)")
        except Exception as exc:
            logger.warning(f"ReflectionSystem not started (non-fatal): {exc}")

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
        
        # Stop Kalshi agent grid
        if self.kalshi_agent_grid:
            try:
                await self.kalshi_agent_grid.stop()
                logger.info("✅ Kalshi agent grid stopped")
            except Exception as exc:
                logger.warning(f"Kalshi agent grid stop failed: {exc}")

        # Stop portfolio risk agent
        if self.portfolio_risk_agent:
            try:
                await self.portfolio_risk_agent.stop()
                logger.info("✅ Portfolio risk agent stopped")
            except Exception as exc:
                logger.warning(f"Portfolio risk agent stop failed: {exc}")

        # Stop insight pipeline
        if self.insight_pipeline:
            try:
                await self.insight_pipeline.stop()
                logger.info("✅ Kalshi insight pipeline stopped")
            except Exception as exc:
                logger.warning(f"Insight pipeline stop failed: {exc}")

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


def get_orchestrator_manager() -> OrchestratorAgentManager:
    """Get the global orchestrator agent manager."""
    global _manager
    if _manager is None:
        _manager = OrchestratorAgentManager()
    return _manager
