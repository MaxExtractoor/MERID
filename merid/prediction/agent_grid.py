"""Kalshi Agent Grid Orchestrator — Top-level coordinator.

Responsibilities:
1. Load config from YAML
2. Instantiate KalshiTradingAgent per (asset, timeframe) cell
3. Instantiate PortfolioRiskAgent
4. Register Kalshi tools into guardrails ToolRegistry
5. Start/stop all agents
6. Expose grid-wide status for the API layer

Usage::

    grid = get_agent_grid()
    await grid.start()
    ...
    await grid.stop()
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from merid.prediction.agent_grid_config import (
    AgentGridConfig,
    get_agent_grid_config,
)
from merid.prediction.kalshi_tools import register_kalshi_tools
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
from merid.prediction.session_guard import SessionGuard, get_session_guard
from merid.prediction.trading_agent import KalshiTradingAgent
from merid.prediction.social_broadcaster import KalshiSocialBroadcaster, get_social_broadcaster
from merid.prediction.paper_session import PaperSession, get_paper_session
from utils.logger import get_logger

logger = get_logger("merid.prediction.agent_grid")


class AgentGrid:
    """Manages the full Kalshi trading agent grid.

    Lifecycle:
        grid = AgentGrid()          # loads config, creates agents
        await grid.start()          # starts all agent loops + portfolio risk
        await grid.stop()           # graceful shutdown
        grid.summary()              # JSON status for API
    """

    def __init__(self, config: Optional[AgentGridConfig] = None):
        self._config = config or get_agent_grid_config()
        self._session_guard = get_session_guard(self._config.session)
        
        # Market catalog for auto-discovery
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        self._catalog = get_market_catalog()

        # Register typed tools
        register_kalshi_tools()

        # Create trading agents from config
        self._agents: List[KalshiTradingAgent] = []
        for agent_cfg in self._config.agents:
            if agent_cfg.enabled:
                agent = KalshiTradingAgent(agent_cfg)
                self._agents.append(agent)

        # Create portfolio risk agent
        self._portfolio_risk = PortfolioRiskAgent(
            config=self._config.portfolio_risk,
            trading_agents=self._agents,
        )

        # Social broadcaster (log-only event consumer)
        self._broadcaster = get_social_broadcaster()

        # Paper session tracker
        self._paper_session = get_paper_session()

        # Sentiment service (fear/greed index)
        from merid.event_venues.kalshi.sentiment import get_sentiment_service
        self._sentiment = get_sentiment_service()

        # Market Mood Bus (unified sentiment aggregation)
        from merid.swarm.market_mood_bus import get_market_mood_bus
        self._mood_bus = get_market_mood_bus()

        # Insight Pipeline (Kalshi → insights → social)
        from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline
        from merid.publishing.kalshi_news_agent import KalshiNewsAgent
        self._insight_pipeline = get_insight_pipeline()
        self._news_agent = KalshiNewsAgent()
        self._insight_pipeline.add_consumer(self._news_agent.handle_insight)

        # Alert Manager with Twitter/Telegram sinks
        from merid.prediction.alerts import get_alert_manager
        self._alert_manager = get_alert_manager()
        self._register_alert_sinks()

        self._running = False
        self._started_at: Optional[datetime] = None
        self._volume_poll_task: Optional[asyncio.Task] = None
        self._reconciliation_task: Optional[asyncio.Task] = None
        self._outcome_resolver = None

        logger.info(
            f"AgentGrid initialized: {len(self._agents)} agents, "
            f"assets={self._config.all_assets}, "
            f"demo={self._config.venue.use_demo}"
        )

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all trading agents and the portfolio risk monitor."""
        if self._running:
            logger.warning("AgentGrid already running")
            return

        self._running = True
        self._started_at = datetime.now(timezone.utc)

        # Start market catalog
        await self._catalog.start()

        # Start portfolio risk agent first
        await self._portfolio_risk.start()

        # L6: Register all agents with DeploymentController (starts each in PAPER mode)
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller
            _dc = get_deployment_controller()
            for _a in self._agents:
                _dc.register_agent(_a.agent_id)
            logger.info("✓ DeploymentController: %d agents registered (all PAPER)", len(self._agents))
        except Exception as _dce:
            logger.warning("DeploymentController registration failed (non-fatal): %s", _dce)

        # Start trading agents
        logger.info(f"Starting {len(self._agents)} Kalshi trading agents...")
        for agent in self._agents:
            await agent.start()
            logger.info(
                f"  ✓ {agent.config.name}: "
                f"assets={agent.config.assets}, "
                f"timeframes={agent.config.timeframes}, "
                f"archetype={agent.config.archetype}"
            )
            # Small stagger to avoid thundering herd on Kalshi API
            await asyncio.sleep(0.5)

        # Start social broadcaster
        await self._broadcaster.start()
        logger.info("✓ Social broadcaster started")

        # Auto-start paper session for PnL tracking
        self._paper_session.start_session()
        logger.info("✓ Paper session started for PnL tracking")

        # Ensure ReflectionSystem is initialized and persistence is running
        # before agents start producing fills (idempotent — singleton pattern)
        try:
            from agents.reflection.integration import get_reflection_system
            _rs = get_reflection_system()
            logger.info(
                f"✓ ReflectionSystem active: "
                f"{_rs.core.get_stats()['total_reflections']} reflections loaded"
            )
        except Exception as exc:
            logger.warning(f"ReflectionSystem init skipped (non-fatal): {exc}")

        # Start sentiment service background loop
        await self._sentiment.start()
        logger.info("✓ Sentiment service started")

        # Start market mood bus (unified sentiment aggregation)
        await self._mood_bus.start()
        logger.info("✓ Market Mood Bus started")

        # Start insight pipeline (Kalshi → insights → social)
        await self._insight_pipeline.start()
        logger.info("✓ Insight Pipeline started with news agent consumer")

        # Start volume monitor polling loop
        self._volume_poll_task = asyncio.create_task(
            self._volume_poll_loop(), name="kalshi-volume-monitor"
        )
        logger.info("✓ Volume monitor polling started")

        # Start reconciliation loop (auto-fix critical discrepancies)
        self._reconciliation_task = asyncio.create_task(
            self._reconciliation_loop(), name="kalshi-reconciliation"
        )
        logger.info("✓ Reconciliation loop started (auto-fix enabled)")

        # Start outcome resolver (Brier calibration + realized edge resolution)
        try:
            from merid.metrics.outcome_resolver import get_outcome_resolver
            self._outcome_resolver = get_outcome_resolver()
            await self._outcome_resolver.start(interval_s=300.0)
            logger.info("✓ Outcome resolver started (Brier + edge resolution every 5m)")
        except Exception as exc:
            logger.warning(f"Outcome resolver start failed (non-fatal): {exc}")

        logger.info(
            f"✅ AgentGrid fully operational: {len(self._agents)} agents running, "
            f"mode={'DEMO' if self._config.venue.use_demo else 'LIVE'}"
        )

    async def stop(self) -> None:
        """Gracefully stop all agents (idempotent)."""
        if not self._running:
            return
        self._running = False

        # Stop market catalog
        await self._catalog.stop()

        # Stop trading agents first
        for agent in self._agents:
            await agent.stop()

        # Then portfolio risk
        await self._portfolio_risk.stop()

        # Stop social broadcaster
        await self._broadcaster.stop()

        # Stop sentiment service
        await self._sentiment.stop()

        # Stop market mood bus
        await self._mood_bus.stop()

        # Stop insight pipeline
        await self._insight_pipeline.stop()

        # Flush ReflectionSystem persistence buffer on shutdown
        try:
            from agents.reflection.integration import get_reflection_system
            get_reflection_system().shutdown()
            logger.info("✓ ReflectionSystem flushed on AgentGrid stop")
        except Exception as exc:
            logger.warning(f"ReflectionSystem shutdown skipped: {exc}")

        # Stop outcome resolver
        if self._outcome_resolver:
            try:
                await self._outcome_resolver.stop()
                logger.info("✓ Outcome resolver stopped")
            except Exception as exc:
                logger.debug(f"Outcome resolver stop error: {exc}")

        # Stop volume monitor
        if self._volume_poll_task and not self._volume_poll_task.done():
            self._volume_poll_task.cancel()
            try:
                await self._volume_poll_task
            except asyncio.CancelledError:
                pass

        # Stop reconciliation loop
        if self._reconciliation_task and not self._reconciliation_task.done():
            self._reconciliation_task.cancel()
            try:
                await self._reconciliation_task
            except asyncio.CancelledError:
                pass

        logger.info("AgentGrid stopped")

    # ── Volume monitor loop ────────────────────────────────────────────

    async def _volume_poll_loop(self) -> None:
        """Background task: poll volume monitor every 60 seconds + apply regime gating + feed mood bus."""
        try:
            from merid.event_venues.kalshi.volume_monitor import get_volume_monitor
            monitor = get_volume_monitor()
        except Exception as exc:
            logger.warning(f"Volume monitor unavailable: {exc}")
            monitor = None

        while self._running:
            try:
                if monitor:
                    changes = monitor.poll()
                    if changes:
                        logger.debug(f"Volume monitor: {changes} markets changed")
            except Exception as exc:
                logger.warning(f"Volume monitor poll error: {exc}")

            # Regime-based agent gating
            try:
                self._apply_regime_gating()
            except Exception as exc:
                logger.debug(f"Regime gating error (ignored): {exc}")

            # Feed data into MarketMoodBus
            try:
                await self._feed_mood_bus()
            except Exception as exc:
                logger.debug(f"Mood bus feed error (ignored): {exc}")

            try:
                await asyncio.wait_for(asyncio.sleep(60), timeout=65)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                break

    async def _feed_mood_bus(self) -> None:
        """Feed live Kalshi market data into MarketMoodBus for sentiment aggregation."""
        try:
            # Get active markets from catalog
            markets = await self._catalog.get_active_markets()

            # Group by asset/timeframe and feed data
            for market in markets[:20]:  # Limit to top 20 markets to avoid rate limits
                try:
                    # Extract asset from ticker (e.g., "KXBTC-23DEC01-B71000" -> "BTC")
                    ticker = market.market_id
                    asset = None
                    if "BTC" in ticker.upper():
                        asset = "BTC"
                    elif "ETH" in ticker.upper():
                        asset = "ETH"

                    if not asset:
                        continue

                    # Infer timeframe (for now use "15m" as default)
                    timeframe = "15m"

                    # Feed Kalshi data
                    self._mood_bus.update_kalshi_data(
                        asset=asset,
                        timeframe=timeframe,
                        price=float(market.yes_bid or 0.5),
                        volume_24h=float(market.volume or 0),
                        spread_bps=float((market.yes_ask or 0.5) - (market.yes_bid or 0.5)) * 10000,
                        open_interest=float(market.open_interest or 0),
                    )

                    # Feed fear/greed from sentiment service
                    global_sentiment = self._sentiment.global_score()
                    self._mood_bus.update_fear_greed(asset, global_sentiment.score)

                except Exception as exc:
                    logger.debug(f"Error feeding market {market.market_id} to mood bus: {exc}")

            logger.debug("MarketMoodBus fed with latest Kalshi data")

        except Exception as exc:
            logger.warning(f"Failed to feed mood bus: {exc}")

    def _apply_regime_gating(self) -> None:
        """Tighten or relax agent activity based on global sentiment regime.

        Rules:
          extreme_fear / extreme_greed  → pause vol_breakout agents (too noisy)
          extreme_greed                 → pause regime_switch agents (momentum exhausted)
          fear / greed (moderate)       → resume all sentiment-driven agents
        """
        glob = self._sentiment.global_score()
        regime = glob.regime
        score  = glob.score

        for agent in self._agents:
            archetype = agent.config.archetype

            if archetype == "vol_breakout":
                # vol_breakout needs elevated sentiment — pause when market is calm
                if 35 <= score <= 65:
                    if agent.state.enabled:
                        agent.pause()
                        logger.info(f"Regime gate: paused {agent.config.name} (vol_breakout, calm market score={score:.0f})")
                else:
                    if not agent.state.enabled:
                        agent.resume()
                        logger.info(f"Regime gate: resumed {agent.config.name} (vol_breakout, score={score:.0f})")

            elif archetype == "regime_switch":
                # regime_switch only useful when sentiment is clearly directional
                if 40 <= score <= 60:
                    if agent.state.enabled:
                        agent.pause()
                        logger.info(f"Regime gate: paused {agent.config.name} (regime_switch, neutral score={score:.0f})")
                else:
                    if not agent.state.enabled:
                        agent.resume()
                        logger.info(f"Regime gate: resumed {agent.config.name} (regime_switch, score={score:.0f})")

            elif archetype == "contrarian":
                # contrarian only active in extreme regimes
                if regime not in ("extreme_fear", "extreme_greed"):
                    if agent.state.enabled:
                        agent.pause()
                        logger.info(f"Regime gate: paused {agent.config.name} (contrarian, regime={regime})")
                else:
                    if not agent.state.enabled:
                        agent.resume()
                        logger.info(f"Regime gate: resumed {agent.config.name} (contrarian, regime={regime})")

    async def _reconciliation_loop(self) -> None:
        """Background task: run reconciliation every 5 minutes and auto-fix critical issues."""
        while self._running:
            try:
                # Run auto-reconciliation with auto-fix enabled
                from merid.reconciliation import auto_reconcile_and_fix

                result = await asyncio.to_thread(
                    auto_reconcile_and_fix,
                    venue_name="kalshi",
                    user_id="operator",
                    auto_fix_critical=True,
                )

                if result.get("auto_fix_success"):
                    logger.warning(
                        f"Reconciliation auto-fix: aligned {len(result.get('aligned_positions', []))} positions"
                    )
                elif result.get("critical_discrepancies", 0) > 0 and not result.get("auto_fix_attempted"):
                    logger.warning(
                        f"Reconciliation: {result['critical_discrepancies']} critical discrepancies found "
                        "(auto-fix disabled)"
                    )

            except Exception as exc:
                logger.warning(f"Reconciliation loop error: {exc}")

            try:
                # Run every 5 minutes (300 seconds)
                await asyncio.wait_for(asyncio.sleep(300), timeout=310)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                break

    # ── Agent management ───────────────────────────────────────────────

    def get_agent(self, name: str) -> Optional[KalshiTradingAgent]:
        """Look up a trading agent by name."""
        name_lower = name.lower()
        for agent in self._agents:
            if agent.config.name.lower() == name_lower:
                return agent
        return None

    def pause_agent(self, name: str) -> bool:
        """Pause a specific agent."""
        agent = self.get_agent(name)
        if agent:
            agent.pause()
            return True
        return False

    def resume_agent(self, name: str) -> bool:
        """Resume a specific agent."""
        agent = self.get_agent(name)
        if agent:
            agent.resume()
            return True
        return False

    def pause_all(self) -> None:
        """Pause all trading agents."""
        for agent in self._agents:
            agent.pause()
        logger.info("All agents paused")

    def resume_all(self) -> None:
        """Resume all trading agents."""
        for agent in self._agents:
            agent.resume()
        logger.info("All agents resumed")

    # ── Portfolio risk controls ────────────────────────────────────────

    def reset_kill_switch(self) -> None:
        """Reset the portfolio kill switch and resume agents."""
        self._portfolio_risk.reset_kill_switch()

    @property
    def kill_switch_active(self) -> bool:
        return self._portfolio_risk.kill_switch_active

    # ── Status / introspection ─────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """True if the grid has been started and not yet stopped."""
        return self._running

    @property
    def agents(self) -> List[KalshiTradingAgent]:
        return self._agents

    @property
    def config(self) -> AgentGridConfig:
        return self._config

    def _register_alert_sinks(self) -> None:
        """Register Twitter/Telegram sinks for prediction alerts."""
        def twitter_alert_sink(alert):
            """Send alert to Twitter."""
            try:
                from agents.twitter_agent import get_twitter_agent
                twitter = get_twitter_agent()

                severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
                emoji = severity_emoji.get(alert.severity.value, "")

                message = (
                    f"{emoji} [{alert.category.value.upper()}]\n"
                    f"{alert.title}\n"
                    f"{alert.message[:150]}"
                )

                import asyncio
                asyncio.create_task(twitter.post_tweet(message))
            except Exception as exc:
                logger.debug(f"Twitter alert sink failed: {exc}")

        def telegram_alert_sink(alert):
            """Send alert to Telegram."""
            try:
                from agents.telegram_agent import get_telegram_agent
                telegram = get_telegram_agent()

                severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
                emoji = severity_emoji.get(alert.severity.value, "")

                message = (
                    f"{emoji} <b>[{alert.severity.value.upper()}] {alert.category.value}</b>\n"
                    f"<b>{alert.title}</b>\n"
                    f"{alert.message}\n"
                    f"<i>{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
                )
                if alert.market_id:
                    message += f"\n<code>{alert.market_id}</code>"

                import asyncio
                asyncio.create_task(telegram.send_message(message, parse_mode="HTML"))
            except Exception as exc:
                logger.debug(f"Telegram alert sink failed: {exc}")

        # Register both sinks
        self._alert_manager.add_sink(twitter_alert_sink)
        self._alert_manager.add_sink(telegram_alert_sink)
        logger.info("✓ Alert sinks registered (Twitter + Telegram)")

    def summary(self) -> Dict[str, Any]:
        """Full grid status for API consumption."""
        # Grid-wide metrics
        total_fills = sum(len(a.state.fill_log) for a in self._agents)
        total_orders = sum(a.state.orders_placed for a in self._agents)

        # Category PnL breakdown
        pnl_by_category: Dict[str, float] = {}
        for agent in self._agents:
            cat = agent.config.category
            pnl = float(agent.state.to_dict().get("pnl", 0))
            pnl_by_category[cat] = pnl_by_category.get(cat, 0.0) + pnl

        # Market coverage
        try:
            all_discovered = self._catalog.get_all_markets() if self._catalog else []
        except Exception as _ce:
            logger.debug("catalog.get_all_markets skipped: %s", _ce)
            all_discovered = []
        covered_tickers: set = set()
        for agent in self._agents:
            covered_tickers.update(agent.state.active_tickers)

        # Venue health — safe even when client is unavailable
        try:
            from merid.prediction.kalshi_tools import _get_client
            client = _get_client()
            venue_health = {
                "connected": client.is_connected() if hasattr(client, "is_connected") else True,
                "circuit": client.get_circuit_status() if hasattr(client, "get_circuit_status") else {"state": "closed", "failure_count": 0, "last_failure": None},
                "rate_limits": {
                    "read": getattr(getattr(client, "_rate_limiter", None), "read_tokens_available", 100),
                    "write": getattr(getattr(client, "_rate_limiter", None), "write_tokens_available", 30),
                },
                "error_rate": sum(len(a.state.errors) for a in self._agents) / max(1, total_orders),
            }
        except Exception as _vhe:
            logger.debug("venue_health probe skipped: %s", _vhe)
            venue_health = {
                "connected": False,
                "circuit": {"state": "open", "failure_count": 0, "last_failure": None},
                "rate_limits": {"read": 0, "write": 0},
                "error_rate": 0.0,
            }

        # Paper session — safe
        try:
            paper_session_data = {
                "active": self._paper_session.is_active,
                "session_id": self._paper_session.session_id,
                "session_hours": round(self._paper_session.session_hours, 2),
                "coverage": self._paper_session.coverage_summary(),
                "live_promoted": sorted(self._paper_session.live_agents),
            }
        except Exception as _pse:
            logger.debug("paper_session summary skipped: %s", _pse)
            paper_session_data = {"active": False}

        # Sentiment summary
        try:
            sentiment_data = self._sentiment.summary()
        except Exception as _sse:
            logger.debug("sentiment summary skipped: %s", _sse)
            sentiment_data = {}

        return {
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "venue": self._config.venue.name,
            "use_demo": self._config.venue.use_demo,
            "venue_health": venue_health,
            "sentiment": sentiment_data,
            "metrics": {
                "active_markets": len(all_discovered),
                "covered_markets": len(covered_tickers),
                "coverage_pct": (len(covered_tickers) / len(all_discovered) * 100) if all_discovered else 0,
                "total_orders": total_orders,
                "total_fills": total_fills,
                "pnl_by_category": pnl_by_category,
            },
            "agent_count": len(self._agents),
            "assets": self._catalog.assets() if self._catalog else self._config.all_assets,
            "session": self._session_guard.summary(),
            "agents": [a.summary() for a in self._agents],
            "portfolio_risk": self._portfolio_risk.summary(),
            "social_broadcaster": self._broadcaster.summary(),
            "paper_session": paper_session_data,
        }

    def agent_grid_matrix(self) -> Dict[str, Any]:
        """Return the (asset × timeframe) grid matrix for dashboard display.
        
        Uses discovered assets from the catalog and maps agents by category/timeframe.
        """
        matrix: Dict[str, Dict[str, Any]] = {}
        
        # Determine relevant assets and timeframes
        assets = self._catalog.assets() if self._catalog else ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        timeframes = ["15m", "1h", "daily", "weekly", "pre-market"]
        
        for asset in assets:
            matrix[asset] = {}
            for tf in timeframes:
                # Find an agent that covers this cell
                # An agent covers it if it matches category 'crypto' and timeframe 'tf'
                covering_agent = None
                for agent in self._agents:
                    if agent.config.category == "crypto" and tf in agent.config.timeframes:
                        covering_agent = agent
                        break
                
                if covering_agent:
                    # Check if the agent actually has active tickers for this asset/tf combo
                    active_for_cell = [t for t in covering_agent.state.active_tickers if asset in t.upper()]
                    
                    matrix[asset][tf] = {
                        "agent": covering_agent.config.name,
                        "enabled": covering_agent.state.enabled,
                        "running": covering_agent.state.running,
                        "cycles": covering_agent.state.cycles_run,
                        "orders": covering_agent.state.orders_placed,
                        "active_tickers": active_for_cell,
                        "status": "active" if active_for_cell else "covering",
                    }
        
        return {
            "matrix": matrix,
            "assets": assets,
            "timeframes": timeframes,
        }


# ── Singleton ──────────────────────────────────────────────────────────

_grid: Optional[AgentGrid] = None


def get_agent_grid() -> AgentGrid:
    """Return the module-level AgentGrid singleton."""
    global _grid
    if _grid is None:
        _grid = AgentGrid()
    return _grid
