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

# NEWS-TRUTH (2026-05-13): NewsMonitorAgent disabled for lean 15m Kalshi trading
# For 15-minute binary markets, edge comes from microstructure, not news headlines
_NewsMonitorAgent = None  # type: ignore
_NEWS_MONITOR_AVAILABLE = False
logger.debug("news_monitor_agent disabled for lean 15m Kalshi stack")

# SOCIAL-TRUTH (2026-05-13): Twitter/Telegram agents disabled for lean 15m Kalshi trading
# For 15-minute binary markets, social signals are redundant with microstructure
_get_twitter_agent = None  # type: ignore[assignment]
_TWITTER_AVAILABLE = False
logger.debug("twitter_agent disabled for lean 15m Kalshi stack")

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
        _profile = __import__("os").environ.get("MERID_PROFILE", "").lower()
        logger.info(f"[ORCHESTRATOR-STARTUP] Starting orchestrator agents (profile={_profile})")

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
            from merid.prediction.agent_grid_15m import get_agent_grid
            logger.info("[GRID-STARTUP] Fetching agent grid...")
            self.kalshi_agent_grid = get_agent_grid()
            
            # Log grid composition for audit trail
            if hasattr(self.kalshi_agent_grid, 'agents'):
                agent_names = [a.name for a in self.kalshi_agent_grid.agents] if self.kalshi_agent_grid.agents else []
                logger.info(f"[GRID-STARTUP] Agent grid loaded with {len(agent_names)} agents: {agent_names}")
            
            if not self.kalshi_agent_grid._running:
                # CRITICAL FIX: DISABLED legacy fallback path - production uses lifespan-based startup only
                # The agent grid MUST be started by the FastAPI lifespan in main_15m_lean.py
                # If the grid is not running here, it means the lifespan startup failed - do NOT start it manually
                logger.error("[GRID-STARTUP] Agent grid not running - LIFESPAN STARTUP FAILED")
                logger.error("[GRID-STARTUP] DO NOT start agent grid manually - this bypasses production startup")
                logger.error("[GRID-STARTUP] Fix the lifespan startup in main_15m_lean.py instead")
                raise RuntimeError("Agent grid not running - lifespan startup failed. Do not use legacy fallback path.")
            else:
                logger.info("✅ Kalshi agent grid already running (started by lifespan)")
                
                # CRITICAL FIX: Start Kalshi15mLoop to ensure PositionMonitor is started
                # This bypasses the lifespan issue where Uvicorn is not calling the lifespan function
                # PositionMonitor must be running for exit policies to execute
                try:
                    from merid.loop_15m import get_kalshi_15m_loop
                    from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
                    
                    logger.info("[CRITICAL-FIX] Starting Kalshi15mLoop directly to ensure PositionMonitor starts")
                    
                    # Get required components
                    bankroll_service = await get_bankroll_service()
                    risk_config = KalshiRiskConfig()
                    
                    # Create and start Kalshi15mLoop
                    kalshi_loop = get_kalshi_15m_loop(
                        agent_grid=self.kalshi_agent_grid,
                        bankroll_service=bankroll_service,
                        risk_config=risk_config,
                        cadence_seconds=5.0
                    )
                    
                    await kalshi_loop.start()
                    logger.info("[CRITICAL-FIX] Kalshi15mLoop started successfully - PositionMonitor should now be running")
                except Exception as loop_err:
                    logger.error(f"[CRITICAL-FIX] Failed to start Kalshi15mLoop: {loop_err}", exc_info=True)
                    logger.error("[CRITICAL-FIX] PositionMonitor may not be running - exit policies may not execute")
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
        # PROFILE-GUARD: Skip for kalshi_crypto_15m_v2 (insight/news publishing not needed for 15m crypto)
        _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        _profile = __import__("os").environ.get("MERID_PROFILE", "").lower()
        if _is_validation:
            logger.info("[VALIDATION MODE] Kalshi insight pipeline skipped (11 category loops deferred)")
        elif _profile == "kalshi_crypto_15m_v2":
            logger.info("[PROFILE-GUARD] Kalshi insight pipeline skipped for kalshi_crypto_15m_v2 (insight/news publishing not needed)")
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
        # PROFILE-GUARD: Skip for kalshi_crypto_15m_v2 (LLM agents not needed for 15m crypto)
        _is_validation = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        _profile = __import__("os").environ.get("MERID_PROFILE", "").lower()
        if _is_validation:
            logger.info("[VALIDATION MODE] AgentMesh skipped (8 streaming agents deferred)")
        elif _profile == "kalshi_crypto_15m_v2":
            logger.info("[PROFILE-GUARD] AgentMesh skipped for kalshi_crypto_15m_v2 (LLM agents not needed for 15m crypto)")
            logger.info("[PROFILE-INVARIANT] kalshi_crypto_15m_v2: AgentMesh and core.consensus_engine disabled by design")
            logger.info("[PROFILE-INVARIANT] All production risk decisions handled by Crypto15MLane with deterministic RCK + Bayesian logic")
            # Hard invariant: do not allow AgentMesh to start under kalshi_crypto_15m_v2
            # This prevents accidental re-wiring of legacy LLM/mesh risk system into production 15m stack
            raise RuntimeError(
                "PROFILE INVARIANT VIOLATION: AgentMesh cannot be started under MERID_PROFILE=kalshi_crypto_15m_v2. "
                "The 15m Kalshi profile uses Crypto15MLane with deterministic RCK + Bayesian logic (no LLM, no sentiment, no mesh). "
                "See docs/RISK_AGENT_MESH_DEPRECATION.md for details."
            )
        else:
            try:
                from agents.agent_mesh import start_agent_mesh
                await start_agent_mesh()
                logger.info("✅ AgentMesh started (8 streaming agents operational)")
            except Exception as exc:
                logger.warning(f"AgentMesh not started (non-fatal): {exc}")

        # Start KalshiSocialBroadcaster — consumes kalshi:order_filled/placed/resolved events
        # PROFILE-GUARD: Skip for kalshi_crypto_15m_v2 (social broadcasting not needed for 15m crypto)
        # LEGACY REMOVAL: social_broadcaster moved to archive/legacy/ during 15m stack cleanup
        if _profile != "kalshi_crypto_15m_v2":
            try:
                from merid.prediction.social_broadcaster import get_social_broadcaster
                self.social_broadcaster = get_social_broadcaster()
                await self.social_broadcaster.start()
                logger.info("✅ KalshiSocialBroadcaster started (trade event → social log)")
            except Exception as exc:
                logger.warning(f"KalshiSocialBroadcaster not started (non-fatal): {exc}")
        else:
            logger.info("[PROFILE-GUARD] KalshiSocialBroadcaster skipped for kalshi_crypto_15m_v2 (social broadcasting not needed)")

        # Start ReflectionSystem — loads persisted reflections, starts background flush
        # PROFILE-GUARD: Skip for kalshi_crypto_15m_v2 (reflection/learning not needed for 15m crypto)
        if _profile != "kalshi_crypto_15m_v2":
            try:
                # Import only when needed to avoid loading legacy modules
                import agents.reflection.integration
                self.reflection_system = agents.reflection.integration.get_reflection_system()
                logger.info("✅ ReflectionSystem started (persistence, learning, analytics active)")
            except Exception as exc:
                logger.warning(f"ReflectionSystem not started (non-fatal): {exc}")
        else:
            logger.info("[PROFILE-GUARD] ReflectionSystem skipped for kalshi_crypto_15m_v2 (reflection/learning not needed)")

        # Start Crypto15MLane — BTC 15m primary lane via registry
        # NOTE: The 15m production trading stack uses loop_15m.py and agent_grid_15m.py (LeanAgent15m)
        # Crypto15MLane is started here for API/UI compatibility (lane status endpoints, etc.)
        # but is NOT used for production trading decisions
        # The lane system provides backward compatibility for legacy API endpoints
        try:
            from merid.lanes.registry import get_lane_registry, build_crypto_lanes
            from merid.risk.promotion_engine import get_promotion_engine
            from merid.prediction.paper_session import get_paper_session
            from merid.settings import settings as _settings
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.event_venues.kalshi.types import BalanceSuccess
            from core.price_feed import get_price_feed
            from merid.event_venues.kalshi.risk_bus import get_risk_bus
            # REMOVED: merid.portfolio.manager import (test_portfolio_optimizer_yaml_has_no_live_importer)
            # Portfolio manager is not needed for 15m crypto production stack
            
            _profile = __import__("os").environ.get("MERID_PROFILE", "").lower()
            logger.info(f"[ORCHESTRATOR-CANONICAL] Crypto15MLane startup for profile={_profile}")
            
            logger.info("[LANE-STARTUP] Initializing Crypto15MLane startup...")
            _promo = get_promotion_engine()
            
            # Build crypto lanes if registry is empty (first-time setup)
            registry = get_lane_registry()
            existing_lanes = registry.list_lane_ids()
            logger.info(f"[LANE-STARTUP] Lane registry has {len(existing_lanes)} existing lanes: {existing_lanes}")
            
            if not existing_lanes:
                logger.info("[LANE-STARTUP] Registry empty - building crypto lanes for BTC/ETH/SOL/XRP/DOGE...")
                try:
                    _kalshi_client = get_kalshi_client()
                    _price_feed = get_price_feed()
                    _risk_bus = get_risk_bus()
                    # REMOVED: _portfolio = get_portfolio_manager() (not needed for 15m crypto)
                    _lane_control = None  # Optional, can be None
                    
                    logger.info("[LANE-STARTUP] Calling build_crypto_lanes()...")
                    build_crypto_lanes(
                        kalshi_client=_kalshi_client,
                        price_feed=_price_feed,
                        risk_bus=_risk_bus,
                        portfolio=None,  # Not needed for 15m crypto
                        lane_control=_lane_control,
                    )
                    logger.info("[LANE-STARTUP] ✅ Crypto lanes built successfully")
                    
                    # Verify lanes were registered
                    new_lanes = registry.list_lane_ids()
                    logger.info(f"[LANE-STARTUP] Registry now has {len(new_lanes)} lanes: {new_lanes}")
                except Exception as build_exc:
                    logger.warning("[LANE-STARTUP] Failed to build crypto lanes: %s", build_exc)

            # Get BTC_15M lane from registry (canonical Crypto15MLane)
            logger.info("[LANE-STARTUP] Fetching BTC_15M lane from registry...")
            btc_lane = registry.get_lane("BTC_15M")

            if btc_lane is not None:
                # Start the Crypto15MLane directly
                import asyncio
                logger.info("[LANE-STARTUP] Starting Crypto15MLane (BTC_15M)...")
                _start_task = asyncio.create_task(btc_lane.start(), name="crypto15m-btc-start")
                _start_task.add_done_callback(
                    lambda t: logger.error(
                        "Crypto15MLane start task failed: %s", t.exception()
                    ) if not t.cancelled() and t.exception() else None
                )
                logger.info(
                    "✅ Crypto15MLane started (BTC_15M | phase=%s)",
                    _promo.current_phase.name if _promo else "unknown",
                )
            else:
                logger.warning("Crypto15MLane (BTC_15M) not found in registry")
        except ImportError as import_exc:
            logger.warning(f"LaneOrchestrator not started (legacy lane system quarantined): {import_exc}")
            self._lane_orchestrator = None
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
        
        # Cancel all background tasks
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.background_tasks.clear()
        
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
