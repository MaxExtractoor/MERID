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

        self._running = False
        self._started_at: Optional[datetime] = None
        self._volume_poll_task: Optional[asyncio.Task] = None

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

        # Start volume monitor polling loop
        self._volume_poll_task = asyncio.create_task(
            self._volume_poll_loop(), name="kalshi-volume-monitor"
        )
        logger.info("✓ Volume monitor polling started")

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

        # Flush ReflectionSystem persistence buffer on shutdown
        try:
            from agents.reflection.integration import get_reflection_system
            get_reflection_system().shutdown()
            logger.info("✓ ReflectionSystem flushed on AgentGrid stop")
        except Exception as exc:
            logger.warning(f"ReflectionSystem shutdown skipped: {exc}")

        # Stop volume monitor
        if self._volume_poll_task and not self._volume_poll_task.done():
            self._volume_poll_task.cancel()
            try:
                await self._volume_poll_task
            except asyncio.CancelledError:
                pass

        logger.info("AgentGrid stopped")

    # ── Volume monitor loop ────────────────────────────────────────────

    async def _volume_poll_loop(self) -> None:
        """Background task: poll volume monitor every 60 seconds + apply regime gating."""
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

            try:
                await asyncio.wait_for(asyncio.sleep(60), timeout=65)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                break

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
    def agents(self) -> List[KalshiTradingAgent]:
        return self._agents

    @property
    def config(self) -> AgentGridConfig:
        return self._config

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
        except Exception:
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
        except Exception:
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
                "session_id": self._paper_session._session_id,
                "session_hours": round(self._paper_session.session_hours, 2),
                "coverage": self._paper_session.coverage_summary(),
                "live_promoted": sorted(self._paper_session.live_agents),
            }
        except Exception:
            paper_session_data = {"active": False}

        # Sentiment summary
        try:
            sentiment_data = self._sentiment.summary()
        except Exception:
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
