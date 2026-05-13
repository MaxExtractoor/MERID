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

import os
import sys
import threading
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ═══════════════════════════════════════════════════════════════════════
# DEBUGGING: Enable faulthandler to capture stack traces on hangs
# ═══════════════════════════════════════════════════════════════════════
import faulthandler
faulthandler.enable(sys.stderr)
# Dump stack traces every 30 seconds if process appears stuck
faulthandler.dump_traceback_later(30, repeat=True)

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

# Cross-asset arbiter integration
from merid.prediction.crypto_top_edge import (
    CRYPTO_ASSETS,
    MEAN_REVERSION_TIMEFRAMES,
    get_crypto_top_edge_arbiter,
)

try:
    from services.crypto_surface_loader import get_crypto_surface_loader
except (ImportError, AttributeError):
    def get_crypto_surface_loader():  # type: ignore[misc]
        return None

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

        # Initialize PredictionMarketRisk singleton once before agents (prevents warnings)
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        _ = get_prediction_risk(PredictionRiskConfig())  # Initialize with defaults

        # Create trading agents from config
        self._agents: List[KalshiTradingAgent] = []
        for agent_cfg in self._config.agents:
            if agent_cfg.enabled:
                agent = KalshiTradingAgent(agent_cfg)
                self._agents.append(agent)

        # Core crypto PM lanes: guardrails profile kalshi_pm (live scope + Kalshi tools)
        try:
            from merid.guardrails.capabilities import get_capability_store
            from merid.pm_crypto_ops import is_core_crypto_pm_config

            _caps = get_capability_store()
            for _ag in self._agents:
                if is_core_crypto_pm_config(_ag.config):
                    _caps.register_from_profile(_ag.agent_id, "kalshi_pm")
        except Exception as _cap_exc:
            logger.warning("Crypto PM capability registration failed: %s", _cap_exc)

        # Agents paused solely due to FeedStalenessMonitor — resumed on on_recovered only
        self._feed_stale_paused_names: set[str] = set()

        # Create portfolio risk agent
        self._portfolio_risk = PortfolioRiskAgent(
            config=self._config.portfolio_risk,
            trading_agents=self._agents,
        )

        # Wire 1: CryptoSurfaceLoader → subscribe each crypto agent for live
        # near-spot Kalshi market updates.  Non-crypto agents are unaffected.
        try:
            self._surface_loader = get_crypto_surface_loader()
        except Exception as _sl_exc:
            logger.warning(
                "CryptoSurfaceLoader unavailable (non-fatal): %s", _sl_exc
            )
            self._surface_loader = None

        # Social broadcaster (log-only event consumer)
        self._broadcaster = get_social_broadcaster()

        # Paper session tracker
        self._paper_session = get_paper_session()
        
        # Startup state tracking for health endpoint semantics
        self._startup_complete = False
        self._agents_ready = False
        self._ws_ready = False
        self._startup_timestamp: Optional[datetime] = None
        # Deferred-start observability (API can be up while grid fails in background)
        self._startup_phase: str = "not_started"  # not_started | starting | running | failed
        self._startup_last_error: Optional[str] = None
        self._startup_finished_at: Optional[datetime] = None

        # BUG-019: Auto-graduation task handle (started in start())
        self._auto_graduation_task: Optional[asyncio.Task] = None

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

        # AutoPromoter — promotion pipeline with operator confirmation
        from merid.promotion.auto_promoter import get_auto_promoter, PromotionState
        self._auto_promoter = get_auto_promoter()
        self._register_promotion_callbacks()

        # Per-asset regime agents (ETH/SOL/XRP/DOGE/BTC1H) — produce opinions for TaCo consensus
        self._regime_agents: list = []
        self._opinion_loop_task: Optional[asyncio.Task] = None
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.kalshi.market_registry import KalshiMarketRegistry
            from merid.risk.crypto_rti_monitor import CryptoRTIMonitor
            from core.event_bus import event_stream
            _client = get_kalshi_client()
            _market_reg = KalshiMarketRegistry(_client)
            _rti_monitor = CryptoRTIMonitor(event_stream, self._portfolio_risk)
            from merid.agents.eth_15m_agent import Eth15mAgent
            from merid.agents.sol_15m_agent import Sol15mAgent
            from merid.agents.xrp_15m_agent import Xrp15mAgent
            from merid.agents.doge_15m_agent import Doge15mAgent
            from merid.agents.btc_1h_agent import Btc1hAgent
            self._regime_agents = [
                Eth15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
                Sol15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
                Xrp15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
                Doge15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
                Btc1hAgent(_market_reg, _rti_monitor, self._portfolio_risk),
            ]
            logger.info("✓ Regime agents initialised: %s", [a.agent_id for a in self._regime_agents])
        except Exception as _ra_exc:
            # Regime agents are REQUIRED for crypto PM mode - fail-closed
            _is_crypto_pm = any(
                getattr(a.config, 'category', '').lower() == 'crypto' 
                for a in self._agents
            ) if self._agents else False
            if _is_crypto_pm:
                raise RuntimeError(
                    f"Regime agents required for crypto PM mode but failed to initialize: {_ra_exc}"
                ) from _ra_exc
            logger.warning("Regime agents unavailable (non-crypto mode): %s", _ra_exc)

        self._running = False
        self._start_lock = asyncio.Lock()
        self._draining = False  # L5/L8: set during graceful drain phase
        self._started_at: Optional[datetime] = None
        self._volume_poll_task: Optional[asyncio.Task] = None
        self._reconciliation_task: Optional[asyncio.Task] = None
        self._outcome_resolver = None
        self._ct_coordination_task: Optional[asyncio.Task] = None
        # Cross-asset arbiter cycle runner (for momentum scalping)
        self._arbiter_cycle_task: Optional[asyncio.Task] = None
        # WebSocket subscription refresh task (auto-refresh when markets roll over)
        self._ws_subscription_refresh_task: Optional[asyncio.Task] = None

        logger.info(
            f"AgentGrid initialized: {len(self._agents)} agents, "
            f"assets={self._config.all_assets}, "
            f"demo={self._config.venue.use_demo}"
        )

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def _prefetch_all_positions(self) -> Dict[str, Any]:
        """BUG-L9 FIX: Pre-fetch all Kalshi positions once before starting agents.
        
        This prevents 35+ sequential API calls during agent startup, which was
        causing 13.5s event-loop lag (halt threshold: 2s).
        
        Returns:
            Dict mapping agent_id -> positions list for that agent's markets
        """
        try:
            from merid.prediction.kalshi_tools import _kalshi_get_positions
            result = await _kalshi_get_positions()
            if not result.success:
                logger.warning("_prefetch_all_positions: failed to fetch positions: %s", result.error_message)
                return {}
            
            all_positions = result.payload.get("positions", []) if result.payload else []
            
            # Map positions to agents by ticker/asset matching
            prefetched: Dict[str, List[Any]] = {}
            for agent in self._agents:
                agent_positions = []
                agent_tickers = set()
                
                # Build set of tickers this agent trades
                try:
                    for asset in agent.config.assets:
                        asset_upper = asset.upper()
                        for ticker in self._catalog.get_tickers_for_asset(asset_upper):
                            agent_tickers.add(ticker)
                except Exception as _e:
                    logger.debug("_prefetch_all_positions: catalog lookup for %s: %s", agent.config.name, _e)
                
                # Find positions matching this agent's tickers
                for pos in all_positions:
                    ticker = getattr(pos, 'ticker', None) or getattr(pos, 'market_id', '')
                    if ticker in agent_tickers:
                        agent_positions.append(pos)
                    # Yield control briefly while processing large position lists
                    if len(all_positions) > 50:
                        await asyncio.sleep(0)
                
                prefetched[agent.agent_id] = agent_positions
                # Yield after each agent to allow other tasks to run
                await asyncio.sleep(0)
            
            total_positions = sum(len(p) for p in prefetched.values())
            logger.info("✓ Pre-fetched %d total positions for %d agents", total_positions, len(self._agents))
            return prefetched
            
        except Exception as exc:
            # Fail-closed: require position prefetch in live mode
            _pm_mode = os.environ.get("MERID_PM_TRADING_MODE", "paper").lower()
            if _pm_mode == "live":
                raise RuntimeError(
                    f"_prefetch_all_positions failed in live mode: {exc} — "
                    "cannot start without position snapshot"
                ) from exc
            logger.warning("_prefetch_all_positions failed (paper mode): %s", exc)
            return {}

    async def start(self) -> None:
        """Start all trading agents and the portfolio risk monitor."""
        async with self._start_lock:
            if self._running:
                logger.warning("AgentGrid already running")
                return

            # _running stays False until all required services are up (medium-risk flag ordering)
            self._draining = False
            self._started_at = datetime.now(timezone.utc)
            self._startup_timestamp = datetime.now(timezone.utc)
            self._startup_complete = False
            self._agents_ready = False
            self._ws_ready = False

            try:
                from merid.pm_runtime import (
                    assert_production_agent_grid_preconditions,
                    log_grid_start_banner,
                )

                assert_production_agent_grid_preconditions(len(self._agents))
                log_grid_start_banner(self)
            except RuntimeError:
                raise
            except Exception as _pre_exc:
                logger.warning("AgentGrid production preflight skipped: %s", _pre_exc)

            # DYNAMIC ENTRY WINDOW POLICY HEADER: Log loaded policies on startup
            try:
                from merid.prediction.dynamic_entry_window import get_policies
                import os

                policies = get_policies()
                policy_version = os.getenv("MERID_ENTRY_WINDOW_POLICY_VERSION", "v1")

                # Build policy summary for logging
                policy_summary = {}
                for asset, policy in policies.items():
                    policy_summary[asset] = {
                        "policy_name": policy.policy_name,
                        "base_window": f"{policy.base_window_start_minutes}-{policy.base_window_end_minutes}min",
                        "terminal_enabled": policy.terminal_config.enabled,
                        "terminal_edge_threshold": f"{policy.terminal_config.edge_threshold_pct}%" if policy.terminal_config.enabled else "N/A"
                    }

                logger.info(
                    "[DYNAMIC_WINDOW_POLICY_HEADER] version=%s policies=%s",
                    policy_version,
                    policy_summary
                )
            except Exception as exc:
                logger.warning("[DYNAMIC_WINDOW_POLICY_HEADER] Failed to log policy header: %s", exc)

            self._startup_phase = "starting"
            self._startup_last_error = None
            self._startup_finished_at = None

            try:
                await self._start_grid_services()
            except Exception as exc:
                self._startup_phase = "failed"
                self._startup_last_error = f"{type(exc).__name__}: {exc}"
                self._startup_finished_at = datetime.now(timezone.utc)
                self._running = False
                self._startup_complete = False
                raise

    async def _start_grid_services(self) -> None:
        """Core grid boot (catalog, agents, background tasks). Separated for startup health tracking."""
        # Start market catalog
        await self._catalog.start()

        # Start bankroll service v2 first - required for all risk calculations
        # CRITICAL: This must start before PortfolioRiskAgent and trading agents
        try:
            from merid.event_venues.kalshi import get_bankroll_service
            _bankroll_service = await get_bankroll_service()
            await _bankroll_service.start()
            logger.info("✓ BankrollServiceV2: started background refresh")
            
            # CRITICAL FIX v8 (2026-04-26): Register bankroll service as equity provider
            # for GlobalRiskGuard. This ensures the guard uses actual Kalshi balance
            # instead of falling back to MERID_INITIAL_CAPITAL env var.
            from merid.guards.global_risk_guard import set_equity_provider
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            
            def _equity_provider() -> int:
                """Return equity in cents for GlobalRiskGuard."""
                equity = get_equity_for_risk_calc_sync()
                if equity is not None and equity > 0:
                    return int(equity * 100)  # Convert USD to cents
                return 0  # Fail-closed if no equity
            
            set_equity_provider(_equity_provider)
            
            # PRODUCTION AUDIT (Step 2): Print canonical bankroll line at startup
            initial_equity = get_equity_for_risk_calc_sync()
            logger.critical(
                "[BANKROLL_ALIGNMENT] GlobalRiskGuard STARTUP with real balance: "
                f"equity_usd={initial_equity} source=KalshiPortfolio.get_balance via bankroll_service_v2 "
                "(single source of truth - NO fallbacks)"
            )
            
            # CRITICAL FIX (2026-05-05): Register existing risk provider for GlobalRiskGuard
            # This ensures the guard knows about open positions and enforces 2% cycle cap
            from merid.guards.global_risk_guard import set_existing_risk_provider
            
            def _existing_risk_provider() -> int:
                """Return existing open position risk in cents for GlobalRiskGuard.
                
                CRITICAL FIX (2026-05-09): Use fills_ledger.get_open_exposure_usd() as PRIMARY source
                because it filters out manually closed positions. The position_cache is populated
                from fills_ledger when REST returns empty, which includes stale/test fills and
                manually closed positions that incorrectly inflate existing_risk_cents beyond
                actual equity.
                
                Previous approach (position_cache) caused GLOBAL RISK GUARD BLOCK because
                129 contracts across 8 positions = $64.45 exposure on $34.81 equity (185%),
                which is 23x over the 8% total risk cap ($2.78).
                """
                try:
                    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                    ledger = get_fills_ledger()
                    _open_notional_usd = ledger.get_open_exposure_usd()
                    return int(_open_notional_usd * 100)  # Convert USD to cents
                except Exception:
                    # Fallback: try position cache (less accurate due to stale fills)
                    try:
                        from merid.event_venues.kalshi.position_cache import get_position_cache
                        cache = get_position_cache()
                        _positions = cache.get_all_positions(validate_freshness=False)
                        _total = 0.0
                        for pos in _positions.values():
                            if pos.contracts > 0:
                                _total += pos.contracts * (pos.avg_price_cents / 100.0)
                        return int(_total * 100)  # Convert to cents
                    except Exception:
                        return 0  # Fail-closed if can't determine exposure
            
            set_existing_risk_provider(_existing_risk_provider)
            logger.info("✓ GlobalRiskGuard: existing risk provider registered")
        except Exception as _be:
            logger.critical("[AGENT_GRID] BankrollServiceV2 failed to start: %s", _be)
            raise RuntimeError(f"BankrollServiceV2 startup failed: {_be}") from _be

        # Start portfolio risk agent first, then wait for its first snapshot
        # before allowing any trading agent to execute orders. (BUG-L1)
        await self._portfolio_risk.start()
        # 15m scalper: shorter timeout (5s vs 15s) for faster startup
        _timeout = 5.0 if os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER" else 15.0
        _risk_ready = await self._portfolio_risk.wait_ready(timeout=_timeout)
        if _risk_ready:
            logger.info("✓ PortfolioRiskAgent: first snapshot complete — safe to start agents")
        else:
            logger.warning(
                "PortfolioRiskAgent did not complete first check within 15s — "
                "continuing with caution (positions may be unknown)"
            )

        # Purge stale consensus opinions from before this startup (BUG-L8)
        try:
            from consensus.consensus_coordinator import EnhancedConsensusCoordinator
            EnhancedConsensusCoordinator.get_instance().clear_stale_opinions(max_age_s=60)
            logger.info("✓ Stale consensus opinions purged (>60s)")
        except Exception as _cce:
            logger.error("[STALE_OPINION_PURGE_FAILED] Stale consensus opinion purge failed: %s", _cce)

        # L6: Register all agents with DeploymentController (starts each in PAPER mode)
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller
            from merid.pm_crypto_ops import (
                is_core_crypto_pm_agent,
                log_crypto_pm_agent_matrix,
                warn_missing_kalshi_pm_capabilities,
            )

            _dc = get_deployment_controller()
            for _a in self._agents:
                _dc.register_agent(_a.agent_id)
            logger.info("✓ DeploymentController: %d agents registered (all PAPER)", len(self._agents))

            log_crypto_pm_agent_matrix(self._agents, logger)
            warn_missing_kalshi_pm_capabilities(self._agents, logger)

            from merid.settings import settings as _grid_settings
            from merid.pm_runtime import is_production_pm_profile

            if (
                is_production_pm_profile()
                and str(_grid_settings.MERID_PM_TRADING_MODE).lower() == "live"
                and _grid_settings.MERID_PM_LIVE_ENABLED
            ):
                _n_force = 0
                for _a in self._agents:
                    if is_core_crypto_pm_agent(_a):
                        _dc.force_live_for_production_profile(_a.agent_id)
                        _n_force += 1
                logger.info(
                    "✓ [deploy] FORCE-LIVE-PRODUCTION: %d core crypto PM agents (DeploymentController → LIVE)",
                    _n_force,
                )
        except Exception as _dce:
            logger.warning("DeploymentController registration failed (non-fatal): %s", _dce)

        # BUG-L9 FIX: Pre-fetch all positions once before starting agents
        # This prevents 35+ sequential API calls that were causing 13.5s event-loop lag
        import time as _timing
        _t_prefetch_start = _timing.time()
        logger.info("[TIMING] Pre-fetching positions for all agents (one API call)...")
        _prefetched_positions = await self._prefetch_all_positions()
        _t_prefetch_elapsed = (_timing.time() - _t_prefetch_start) * 1000
        logger.info(f"[TIMING] Pre-fetch completed in {_t_prefetch_elapsed:.0f}ms")

        # Start trading agents using run_in_executor (BUG-L9 FIX)
        # This runs agent.start() in thread pool without creating new event loops
        _t_agents_start = _timing.time()
        logger.info(f"[TIMING] Starting {len(self._agents)} Kalshi trading agents via run_in_executor...")
        
        async def _start_single_agent(agent: KalshiTradingAgent) -> KalshiTradingAgent:
            """Start agent directly (async method - no executor needed)."""
            _t_agent_start = _timing.time()
            await agent.start(prefetched_positions=_prefetched_positions.get(agent.agent_id))
            _t_agent_elapsed = (_timing.time() - _t_agent_start) * 1000
            logger.info(f"  ✓ {agent.config.name}: init_time={_t_agent_elapsed:.0f}ms")
            return agent
        
        # Use semaphore to limit concurrent agents
        _init_semaphore = asyncio.Semaphore(5)
        
        async def _start_with_semaphore(agent: KalshiTradingAgent, idx: int) -> KalshiTradingAgent:
            """Start agent directly with staggered delay to prevent thundering herd."""
            async with _init_semaphore:
                # BUG-L13 FIX: Add staggered delay between agent starts
                # Spread 35 agents over ~3.5 seconds (100ms each)
                await asyncio.sleep(idx * 0.1)
                return await _start_single_agent(agent)
        
        try:
            _started_agents = await asyncio.gather(
                *[_start_with_semaphore(agent, idx) for idx, agent in enumerate(self._agents)],
                return_exceptions=False
            )
            _t_agents_elapsed = (_timing.time() - _t_agents_start) * 1000
            logger.info(f"[TIMING] All {len(_started_agents)} agents started in {_t_agents_elapsed:.0f}ms")
            self._agents_ready = True
        except Exception as _agent_exc:
            logger.error(
                "AgentGrid.start() failed during concurrent agent startup — rolling back: %s",
                _agent_exc,
            )
            # Rollback: stop any agents that did start
            for _a in self._agents:
                if _a.state.running:
                    try:
                        await _a.stop()
                    except Exception as _stop_exc:
                        logger.debug("Rollback stop failed for %s: %s", _a.config.name, _stop_exc)
            await self._portfolio_risk.stop()
            try:
                await self._catalog.stop()
            except Exception:
                pass
            raise

        # Wire 1: subscribe each crypto agent to CryptoSurfaceLoader now that agents are running
        # BANDWIDTH-FIX: Skip signal-only agents (they don't execute, don't need live surface updates)
        if self._surface_loader is not None:
            for _agent in self._agents:
                if getattr(_agent.config, "category", None) == "crypto" and not getattr(_agent.config, 'signalonly', False):
                    self._surface_loader.subscribe_updates(_agent.on_surface_update)
                    logger.debug("Surface loader subscribed: %s", _agent.config.name)

        # Wire 2: Subscribe agents to Kalshi WS via series tickers (market_selector)
        # This ensures proper market discovery via AGENT_SERIES_MAP
        # BANDWIDTH-FIX: Skip signal-only agents (they don't execute, don't need live market data)
        try:
            from merid.event_venues.kalshi.market_selector import enable_kalshi_agent
            _subscribed_count = 0
            for _agent in self._agents:
                # Skip signal-only agents - they don't need live market data
                if getattr(_agent.config, 'signalonly', False):
                    logger.debug("Kalshi series subscription skipped (signal-only): %s", _agent.config.name)
                    continue
                if _agent.config.series_tickers:
                    await enable_kalshi_agent(_agent.config.name, _agent.config.series_tickers)
                    logger.debug("Kalshi series subscription: %s -> %s", _agent.config.name, _agent.config.series_tickers)
                    _subscribed_count += 1
            logger.info("✓ Kalshi series ticker subscriptions wired for %d agents (%d signal-only skipped)", 
                       _subscribed_count, len(self._agents) - _subscribed_count)
        except Exception as _exc:
            logger.warning("Kalshi series subscription wiring skipped (non-fatal): %s", _exc)

        # Start social broadcaster
        _t_broadcast_start = _timing.time()
        await self._broadcaster.start()
        _t_broadcast_elapsed = (_timing.time() - _t_broadcast_start) * 1000
        logger.info(f"[TIMING] Social broadcaster started in {_t_broadcast_elapsed:.0f}ms")

        # Auto-start paper session for PnL tracking
        _t_paper_start = _timing.time()
        self._paper_session.start_session()
        _t_paper_elapsed = (_timing.time() - _t_paper_start) * 1000
        logger.info(f"[TIMING] Paper session started in {_t_paper_elapsed:.0f}ms")

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
        _t_sentiment_start = _timing.time()
        await self._sentiment.start()
        _t_sentiment_elapsed = (_timing.time() - _t_sentiment_start) * 1000
        logger.info(f"[TIMING] Sentiment service started in {_t_sentiment_elapsed:.0f}ms")

        # Start market mood bus (unified sentiment aggregation)
        _t_mood_start = _timing.time()
        await self._mood_bus.start()
        _t_mood_elapsed = (_timing.time() - _t_mood_start) * 1000
        logger.info(f"[TIMING] Market Mood Bus started in {_t_mood_elapsed:.0f}ms")

        # Start insight pipeline (Kalshi → insights → social)
        # DISABLED FOR VALIDATION: Skip non-essential insight pipeline to reduce startup lag
        _skip_insight = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        if not _skip_insight:
            _t_insight_start = _timing.time()
            await self._insight_pipeline.start()
            _t_insight_elapsed = (_timing.time() - _t_insight_start) * 1000
            logger.info(f"[TIMING] Insight Pipeline started in {_t_insight_elapsed:.0f}ms")
        else:
            logger.info("[VALIDATION MODE] Insight Pipeline skipped")

        def _bg_task_done_cb(task: asyncio.Task) -> None:
            """Log unhandled exceptions from AgentGrid background tasks."""
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error("AgentGrid background task %s crashed: %s", task.get_name(), exc, exc_info=exc)

        self._running = True

        # Start volume monitor polling loop
        self._volume_poll_task = asyncio.create_task(
            self._volume_poll_loop(), name="kalshi-volume-monitor"
        )
        self._volume_poll_task.add_done_callback(_bg_task_done_cb)
        logger.info("✓ Volume monitor polling started")

        # Start per-asset regime agent opinion loop (non-critical — guarded)
        if self._regime_agents:
            self._opinion_loop_task = asyncio.create_task(
                self._opinion_loop(), name="kalshi-regime-opinions"
            )
            self._opinion_loop_task.add_done_callback(_bg_task_done_cb)
            logger.info("✓ Regime agent opinion loop started (%d agents)", len(self._regime_agents))

        # Start reconciliation loop (auto-fix critical discrepancies)
        self._reconciliation_task = asyncio.create_task(
            self._reconciliation_loop(), name="kalshi-reconciliation"
        )
        self._reconciliation_task.add_done_callback(_bg_task_done_cb)
        logger.info("✓ Reconciliation loop started (auto-fix enabled)")

        # Start cross-asset arbiter cycle runner (momentum scalping)
        self._arbiter_cycle_task = asyncio.create_task(
            self._arbiter_cycle_loop(), name="crypto-top-edge-arbiter"
        )
        self._arbiter_cycle_task.add_done_callback(_bg_task_done_cb)
        logger.info("✓ Cross-asset arbiter cycle runner started")

        # Start WebSocket subscription refresh (auto-refresh when markets roll over)
        self._ws_subscription_refresh_task = asyncio.create_task(
            self._ws_subscription_refresh_loop(), name="ws-subscription-refresh"
        )
        self._ws_subscription_refresh_task.add_done_callback(_bg_task_done_cb)
        logger.info("✓ WebSocket subscription refresh started (13s interval)")

        # Start outcome resolver (Brier calibration + realized edge resolution)
        _skip_nonessential = __import__("os").environ.get("MERID_VALIDATION_MODE", "") == "1"
        if not _skip_nonessential:
            try:
                from merid.metrics.outcome_resolver import get_outcome_resolver
                self._outcome_resolver = get_outcome_resolver()
                await self._outcome_resolver.start(interval_s=300.0)
                logger.info("✓ Outcome resolver started (Brier + edge resolution every 5m)")
            except Exception as exc:
                logger.warning(f"Outcome resolver start failed (non-fatal): {exc}")
        else:
            logger.info("[VALIDATION MODE] Outcome resolver skipped")

        # Start edge recalibrator (Sprint G/K — auto-adjust edge thresholds every 30m)
        if not _skip_nonessential:
            try:
                from merid.prediction.edge_recalibrator import get_edge_recalibrator
                self._edge_recalibrator = get_edge_recalibrator()
                await self._edge_recalibrator.start()
                logger.info("✓ Edge recalibrator started (threshold adjustment every 30m)")
            except Exception as exc:
                logger.warning(f"Edge recalibrator start failed (non-fatal): {exc}")
        else:
            logger.info("[VALIDATION MODE] Edge recalibrator skipped")

        # Start critic agent (Sprint H/K — staleness + liquidity → Critique messages)
        if not _skip_nonessential:
            try:
                from merid.swarm.critic_agent import get_critic_agent
                self._critic_agent = get_critic_agent()
                await self._critic_agent.start()
                logger.info("✓ Critic agent started (staleness + liquidity sweep every 30s)")
            except Exception as exc:
                logger.warning(f"Critic agent start failed (non-fatal): {exc}")
        else:
            logger.info("[VALIDATION MODE] Critic agent skipped")

        # Start execution subscriber (Sprint M — Decision bus → execution routing)
        try:
            from merid.swarm.execution_subscriber import get_execution_subscriber
            self._execution_subscriber = get_execution_subscriber()
            await self._execution_subscriber.start()
            logger.info("✓ Execution subscriber started (Decision bus → order routing)")
        except Exception as exc:
            logger.warning(f"Execution subscriber start failed (non-fatal): {exc}")

        # Wire FeedStalenessMonitor → agent pause on stale data (blind-spot fix)
        try:
            from core.feed_staleness_monitor import get_feed_staleness_monitor
            _fsm = get_feed_staleness_monitor()

            def _on_feed_stale(feed_id: str, instrument: str, age_seconds: float) -> None:
                """Pause agents that trade the stale instrument."""
                instrument_upper = instrument.upper()
                paused = []
                for _agent in self._agents:
                    assets_upper = [a.upper() for a in _agent.config.assets]
                    if instrument_upper in assets_upper:
                        if _agent.state.enabled:
                            _agent.pause()
                            self._feed_stale_paused_names.add(_agent.config.name)
                            paused.append(_agent.config.name)
                if paused:
                    logger.warning(
                        "FeedStalenessMonitor: feed=%s instrument=%s age=%.1fs — "
                        "paused agents: %s",
                        feed_id, instrument, age_seconds, paused,
                    )

            def _on_feed_recovered(feed_id: str, instrument: str) -> None:
                """Resume only agents we paused for staleness (not operator/error pauses)."""
                instrument_upper = instrument.upper()
                resumed: List[str] = []
                for _agent in self._agents:
                    assets_upper = [a.upper() for a in _agent.config.assets]
                    if instrument_upper not in assets_upper:
                        continue
                    if _agent.config.name not in self._feed_stale_paused_names:
                        continue
                    self._feed_stale_paused_names.discard(_agent.config.name)
                    if not _agent.state.enabled:
                        _agent.resume()
                        resumed.append(_agent.config.name)
                if resumed:
                    logger.info(
                        "FeedStalenessMonitor recovered: feed=%s instrument=%s — resumed agents: %s",
                        feed_id,
                        instrument,
                        resumed,
                    )

            _fsm.on_stale(_on_feed_stale)
            _fsm.on_recovered(_on_feed_recovered)
            logger.info("✓ FeedStalenessMonitor on_stale/on_recovered wired to agent pause/resume")
        except Exception as exc:
            logger.warning(f"FeedStalenessMonitor wiring failed (non-fatal): {exc}")

        # Kalshi CT ↔ Universal Agent metrics bridge (CT runs from server lifespan;
        # this task keeps grid observability aligned with ``ua_ct_metrics``).
        if self._should_start_ct_coordination():
            self._ct_coordination_task = asyncio.create_task(
                self._ct_coordination_loop(), name="ua-ct-coordination"
            )
            self._ct_coordination_task.add_done_callback(_bg_task_done_cb)
            logger.info("✓ UA–CT coordination loop started (metrics bridge)")

        # BUG-019: Auto-graduation loop — feeds paper performance into AutoPromoter
        if not _skip_nonessential:
            self._auto_graduation_task = asyncio.create_task(
                self._auto_graduation_loop(), name="kalshi-auto-graduation"
            )
            self._auto_graduation_task.add_done_callback(_bg_task_done_cb)
            logger.info("✓ Auto-graduation loop started (promotion check every 5m)")

        # ── Grid coverage self-check ─────────────────────────────────
        # Validate every expected (asset, timeframe) cell has at least one
        # enabled agent.  Missing cells are logged as warnings so operators
        # catch config drift before it silently drops coverage.
        self._run_grid_coverage_check()

        self._startup_complete = True
        self._startup_phase = "running"
        self._startup_finished_at = datetime.now(timezone.utc)
        logger.info(
            f"✅ AgentGrid fully operational: {len(self._agents)} agents running, "
            f"mode={'DEMO' if self._config.venue.use_demo else 'LIVE'}"
        )

    # ── Expected crypto coverage matrix ─────────────────────────────
    _EXPECTED_CRYPTO_CELLS = {
        ("BTC", "15m"), ("BTC", "1h"), ("BTC", "daily"), ("BTC", "weekly"),
        ("BTC", "monthly"), ("BTC", "annual"),
        ("ETH", "15m"), ("ETH", "1h"), ("ETH", "daily"), ("ETH", "weekly"),
        ("ETH", "monthly"), ("ETH", "annual"),
        ("SOL", "15m"), ("SOL", "1h"), ("SOL", "daily"), ("SOL", "weekly"),
        ("SOL", "monthly"), ("SOL", "annual"),
        ("XRP", "15m"), ("XRP", "1h"), ("XRP", "daily"), ("XRP", "weekly"),
        ("XRP", "monthly"), ("XRP", "annual"),
        ("DOGE", "15m"), ("DOGE", "1h"), ("DOGE", "daily"), ("DOGE", "weekly"),
        ("DOGE", "monthly"), ("DOGE", "annual"),
    }

    def _run_grid_coverage_check(self) -> None:
        """Validate that every expected (asset, timeframe) cell has at least one agent."""
        covered: set = set()
        for agent in self._agents:
            if not agent.config.enabled:
                continue
            for asset in agent.config.assets:
                for tf in agent.config.timeframes:
                    covered.add((asset.upper(), tf.lower()))

        missing = self._EXPECTED_CRYPTO_CELLS - covered
        if missing:
            missing_str = ", ".join(f"{a}/{tf}" for a, tf in sorted(missing))
            logger.warning(
                "[GRID_COVERAGE] %d missing cells (no enabled agent): %s",
                len(missing), missing_str,
            )
        else:
            logger.info(
                "[GRID_COVERAGE] ✓ All %d expected crypto cells covered",
                len(self._EXPECTED_CRYPTO_CELLS),
            )

        # Also check for strike selection config presence on crypto agents
        _no_strike_cfg = []
        for agent in self._agents:
            if not agent.config.enabled:
                continue
            if getattr(agent.config, "category", "") != "crypto":
                continue
            if getattr(agent.config, "strike_selection", None) is None:
                _no_strike_cfg.append(agent.config.name)
        if _no_strike_cfg:
            logger.info(
                "[GRID_COVERAGE] %d crypto agents using default strike selection: %s",
                len(_no_strike_cfg), ", ".join(_no_strike_cfg[:10]),
            )

    async def _arbiter_cycle_loop(self) -> None:
        """Background task to run cross-asset arbiter cycles.
        
        This runs the arbiter selection cycle periodically, collecting
        signals from all crypto agents and selecting top N winners.
        """
        arbiter = get_crypto_top_edge_arbiter()
        cycle_interval = 15.0  # Run every 15 seconds (aligned with 15m timeframe)
        
        logger.info("[ARBITER] Cycle runner started (interval=%.1fs)", cycle_interval)
        
        from merid.guards.global_risk_guard import get_global_risk_guard
        _risk_guard = get_global_risk_guard()

        while self._running:
            try:
                # Reset the GlobalRiskGuard cycle accumulator so each 15s arbiter
                # cycle gets a fresh per-cycle risk budget.  Without this the
                # accumulator grows forever and blocks all orders after the first
                # few (cycle_cap=$2.21 on $44.35 equity fills in ~4 orders).
                _risk_guard.reset_cycle()
                
                # Reset the GlobalExecutionGuard notional accumulator so each cycle
                # gets a fresh 2% bankroll allocation. Without this, the notional
                # accumulator grows forever and triggers GLOBAL_CAP_EXCEEDED errors.
                try:
                    from merid.guards.global_execution_guard import get_global_execution_guard
                    _exec_guard = get_global_execution_guard()
                    _exec_guard.reset_cycle()
                except Exception as e:
                    logger.debug("[ARBITER] Failed to reset GlobalExecutionGuard: %s", e)

                # Run the arbiter cycle
                cycle_id = f"grid_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                result = arbiter.run_cycle(cycle_id=cycle_id)
                
                if result.winners:
                    logger.info(
                        "[ARBITER] Cycle %s: %d winners, floor=%.4f, assets=%s",
                        cycle_id,
                        len(result.winners),
                        result.final_floor,
                        ",".join(sorted(result.assets_selected))
                    )
                    for w in result.winners:
                        logger.debug(
                            "[ARBITER_WINNER] %s %s edge=%.4f pos=%d incr=%d",
                            w.asset, w.ticker, w.net_edge,
                            w.existing_position_contracts, w.incremental_contracts
                        )
                else:
                    logger.debug(
                        "[ARBITER] Cycle %s: no winners (candidates=%d, floor=%.4f)",
                        cycle_id, result.total_signals, result.final_floor
                    )
                
                # Wait for next cycle
                await asyncio.sleep(cycle_interval)
                
            except asyncio.CancelledError:
                logger.info("[ARBITER] Cycle runner cancelled")
                raise
            except Exception as e:
                logger.error("[ARBITER] Cycle runner error: %s", e)
                await asyncio.sleep(5)  # Short sleep on error

    async def _ws_subscription_refresh_loop(self) -> None:
        """Background task to refresh WebSocket subscriptions when markets roll over.
        
        Kalshi markets expire every 15 minutes (for 15M timeframe). The WS subscription
        is static at startup, so when markets roll over to new expiry times, the WS
        stays subscribed to old/expired markets and doesn't receive data for new ones.
        
        This loop periodically re-subscribes agents to their current markets via
        enable_kalshi_agent(), which resolves new markets from the catalog and updates
        the WS bridge subscription. The WS bridge handles rotation/unsubscription of
        old tickers automatically.
        """
        refresh_interval = 13.0  # Refresh every 13 seconds (de-synced from 10s heartbeat)
        
        logger.info("[WS-SUBSCRIPTION-REFRESH] Started (interval=%.1fs)", refresh_interval)
        
        while self._running:
            try:
                # Refresh subscriptions for all agents with series_tickers
                from merid.event_venues.kalshi.market_selector import enable_kalshi_agent
                
                refresh_count = 0
                for agent in self._agents:
                    # Skip signal-only agents - they don't need live market data
                    if getattr(agent.config, 'signalonly', False):
                        continue
                    
                    # Only refresh agents with series_tickers configured
                    if agent.config.series_tickers:
                        try:
                            result = await enable_kalshi_agent(
                                agent.config.name, 
                                agent.config.series_tickers
                            )
                            if result.get("subscribed", 0) > 0:
                                refresh_count += 1
                                logger.debug(
                                    "[WS-SUBSCRIPTION-REFRESH] Refreshed %s: %d markets",
                                    agent.config.name, result.get("subscribed", 0)
                                )
                        except Exception as agent_exc:
                            logger.warning(
                                "[WS-SUBSCRIPTION-REFRESH] Failed to refresh %s: %s",
                                agent.config.name, agent_exc
                            )
                
                if refresh_count > 0:
                    logger.info(
                        "[WS-SUBSCRIPTION-REFRESH] Refreshed %d agents (total=%d)",
                        refresh_count, len(self._agents)
                    )
                
                # Wait for next refresh cycle
                await asyncio.sleep(refresh_interval)
                
            except asyncio.CancelledError:
                logger.info("[WS-SUBSCRIPTION-REFRESH] Cancelled")
                raise
            except Exception as e:
                logger.error("[WS-SUBSCRIPTION-REFRESH] Error: %s", e)
                await asyncio.sleep(10)  # Longer sleep on error to avoid tight loop

    def mark_startup_failure(self, exc: Any) -> None:
        """Record failure when deferred start catches an error outside ``start()`` internals."""
        msg = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        self._startup_phase = "failed"
        self._startup_last_error = msg
        self._startup_finished_at = datetime.now(timezone.utc)
        self._running = False
        self._startup_complete = False

    def startup_health(self) -> Dict[str, Any]:
        """Compact grid boot state for operator / readiness probes (API up vs grid up)."""
        agents_running = sum(1 for a in self._agents if getattr(a.state, "running", False))
        skip = _DEFERRED_GRID_SKIP_REASON
        return {
            "phase": self._startup_phase,
            "running": self._running,
            "startup_complete": self._startup_complete,
            "started": bool(self._running and self._startup_complete),
            "last_error": self._startup_last_error,
            "agents_enabled": len(self._agents),
            "agents_running": agents_running,
            "finished_at": self._startup_finished_at.isoformat() if self._startup_finished_at else None,
            "deferred_start_skipped_reason": skip,
        }

    async def stop(self) -> None:
        """Gracefully stop all agents (idempotent)."""
        if not self._running:
            return
        self._running = False
        self._draining = True

        # Stop market catalog
        await self._catalog.stop()

        # BUG-L5: Drain trading agents first (completes current cycle + final stop-loss sweep),
        # then stop them. PortfolioRiskAgent stays alive until all agents are drained.
        # HANG-FIX: Add 10s timeout to each drain to prevent indefinite shutdown hangs
        for agent in self._agents:
            try:
                await asyncio.wait_for(agent.drain(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(f"Agent {agent.config.name} drain timed out after 10s, forcing stop")
        for agent in self._agents:
            await agent.stop()

        # Then portfolio risk — runs one final check after all agents are drained
        await self._portfolio_risk.stop()
        self._draining = False

        # Stop bankroll service v2 (after all agents stopped, before catalog)
        try:
            from merid.event_venues.kalshi import get_bankroll_service
            _bankroll_service = await get_bankroll_service()
            await _bankroll_service.stop()
            logger.info("✓ BankrollServiceV2: stopped")
        except Exception as _be:
            logger.warning("[AGENT_GRID] BankrollServiceV2 stop failed: %s", _be)

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

        # Stop regime opinion loop
        if self._opinion_loop_task and not self._opinion_loop_task.done():
            self._opinion_loop_task.cancel()
            try:
                await self._opinion_loop_task
            except asyncio.CancelledError:
                pass
            finally:
                self._opinion_loop_task = None  # CLEAR-FIX: Prevent double-cancel

        if self._ct_coordination_task and not self._ct_coordination_task.done():
            self._ct_coordination_task.cancel()
            try:
                await self._ct_coordination_task
            except asyncio.CancelledError:
                pass
            finally:
                self._ct_coordination_task = None  # CLEAR-FIX: Prevent double-cancel

        # Stop execution subscriber (Sprint M)
        if hasattr(self, '_execution_subscriber') and self._execution_subscriber:
            try:
                await self._execution_subscriber.stop()
                logger.info("✓ Execution subscriber stopped")
            except Exception as exc:
                logger.debug(f"Execution subscriber stop error: {exc}")

        # Stop edge recalibrator (Sprint K)
        if hasattr(self, '_edge_recalibrator') and self._edge_recalibrator:
            try:
                await self._edge_recalibrator.stop()
                logger.info("✓ Edge recalibrator stopped")
            except Exception as exc:
                logger.debug(f"Edge recalibrator stop error: {exc}")

        # Stop critic agent (Sprint K)
        if hasattr(self, '_critic_agent') and self._critic_agent:
            try:
                await self._critic_agent.stop()
                logger.info("✓ Critic agent stopped")
            except Exception as exc:
                logger.debug(f"Critic agent stop error: {exc}")

        # Stop volume monitor
        if self._volume_poll_task and not self._volume_poll_task.done():
            self._volume_poll_task.cancel()
            try:
                await self._volume_poll_task
            except asyncio.CancelledError:
                pass
            finally:
                self._volume_poll_task = None  # CLEAR-FIX: Prevent double-cancel

        # Stop reconciliation loop
        if self._reconciliation_task and not self._reconciliation_task.done():
            self._reconciliation_task.cancel()
            try:
                await self._reconciliation_task
            except asyncio.CancelledError:
                pass
            finally:
                self._reconciliation_task = None  # CLEAR-FIX: Prevent double-cancel

        # Stop cross-asset arbiter cycle runner
        if self._arbiter_cycle_task and not self._arbiter_cycle_task.done():
            self._arbiter_cycle_task.cancel()
            try:
                await self._arbiter_cycle_task
            except asyncio.CancelledError:
                pass
            finally:
                self._arbiter_cycle_task = None  # CLEAR-FIX: Prevent double-cancel
            logger.info("✓ Cross-asset arbiter cycle runner stopped")

        # Stop WebSocket subscription refresh
        if self._ws_subscription_refresh_task and not self._ws_subscription_refresh_task.done():
            self._ws_subscription_refresh_task.cancel()
            try:
                await self._ws_subscription_refresh_task
            except asyncio.CancelledError:
                pass
            finally:
                self._ws_subscription_refresh_task = None  # CLEAR-FIX: Prevent double-cancel
            logger.info("✓ WebSocket subscription refresh stopped")

        # BUG-019: Stop auto-graduation loop
        if self._auto_graduation_task and not self._auto_graduation_task.done():
            self._auto_graduation_task.cancel()
            try:
                await self._auto_graduation_task
            except asyncio.CancelledError:
                pass
            finally:
                self._auto_graduation_task = None  # CLEAR-FIX: Prevent double-cancel

        logger.info("AgentGrid stopped")

    # ── Auto-graduation loop (BUG-019) ────────────────────────────────

    async def _auto_graduation_loop(self) -> None:
        """Background task: feed paper performance into AutoPromoter every 5 minutes.

        For each agent in PENDING or GAUNTLET_PASS state, extract win_rate and
        profit_factor from the agent's performance_metrics() and call
        record_paper_performance().  If the agent is AWAITING_CONFIRMATION,
        log a reminder for the operator.
        """
        from merid.promotion.auto_promoter import PromotionState

        while self._running:
            try:
                for agent in self._agents:
                    agent_id = getattr(agent, "agent_id", None) or getattr(agent.config, "name", None)
                    if not agent_id:
                        continue

                    status = self._auto_promoter.get_status(agent_id)
                    if status is None:
                        continue

                    # Only feed metrics if not yet live or killed
                    if status.state in (PromotionState.LIVE, PromotionState.KILLED):
                        continue

                    try:
                        perf = agent.performance_metrics() if hasattr(agent, "performance_metrics") else {}
                    except Exception:
                        perf = {}

                    if not perf:
                        continue

                    trades = int(perf.get("total_trades", 0) or 0)
                    wins = int(perf.get("winning_trades", 0) or perf.get("wins", 0) or 0)
                    win_rate = float(perf.get("win_rate", wins / trades if trades > 0 else 0.0))
                    # profit_factor: gross_profit / gross_loss (or from perf dict)
                    profit_factor = float(perf.get("profit_factor", 1.0) or 1.0)

                    self._auto_promoter.record_paper_performance(
                        agent_id=agent_id,
                        trades=trades,
                        win_rate=win_rate,
                        profit_factor=profit_factor,
                    )

                    # Refreshed status after recording
                    new_status = self._auto_promoter.get_status(agent_id)
                    if new_status and new_status.state == PromotionState.AWAITING_CONFIRMATION:
                        logger.info(
                            "[AUTO-GRADUATION] Agent %s is AWAITING_CONFIRMATION for live "
                            "(trades=%d win_rate=%.2f pf=%.2f) — operator approval required",
                            agent_id, trades, win_rate, profit_factor,
                        )

            except Exception as exc:
                logger.warning("Auto-graduation loop error (non-fatal): %s", exc)

            try:
                await asyncio.sleep(300)  # 5-minute interval
            except asyncio.CancelledError:
                break

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
                # 15m scalper: faster mood updates (15s vs 60s)
                _sleep = 15 if os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER" else 60
                await asyncio.wait_for(asyncio.sleep(_sleep), timeout=_sleep + 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                break

    async def _feed_mood_bus(self) -> None:
        """Feed live Kalshi market data into MarketMoodBus for sentiment aggregation."""
        try:
            # Get active markets from catalog
            markets = self._catalog.get_all_markets()

            # Group by asset/timeframe and feed data
            for market in markets[:20]:  # Limit to top 20 markets to avoid rate limits
                try:
                    # Extract asset from Kalshi ticker prefix (e.g., "KXBTUPDOWN-15M" -> "BTC")
                    ticker = market.market.market_id
                    t = ticker.upper()
                    if t.startswith(("KXBT", "KXBTC", "KXBTCD")):
                        asset = "BTC"
                    elif t.startswith("KXETH"):
                        asset = "ETH"
                    elif t.startswith("KXSOL"):
                        asset = "SOL"
                    elif t.startswith("KXXRP"):
                        asset = "XRP"
                    elif t.startswith("KXDOGE"):
                        asset = "DOGE"
                    else:
                        continue

                    # Infer timeframe (for now use "15m" as default)
                    timeframe = "15m"

                    # Feed Kalshi data — attributes live on inner EventMarket / raw_data
                    _em = market.market
                    _raw = _em.raw_data or {}
                    _yes_bid = float(_raw.get("yes_bid", 0) or 0) / 100.0 if _raw.get("yes_bid") else 0.5
                    _yes_ask = float(_raw.get("yes_ask", 0) or 0) / 100.0 if _raw.get("yes_ask") else 0.5
                    _volume = float(_em.volume or 0)
                    _oi = float(_em.open_interest or 0)
                    self._mood_bus.update_kalshi_data(
                        asset=asset,
                        timeframe=timeframe,
                        price=_yes_bid,
                        volume_24h=_volume,
                        spread_bps=(_yes_ask - _yes_bid) * 10000,
                        open_interest=_oi,
                    )

                    # Feed fear/greed from sentiment service
                    global_sentiment = self._sentiment.global_score()
                    self._mood_bus.update_fear_greed(asset, global_sentiment.score)

                except Exception as exc:
                    logger.debug(f"Error feeding market {market.market.market_id} to mood bus: {exc}")
                
                # Yield control after each market to allow other tasks
                await asyncio.sleep(0)

            logger.debug("MarketMoodBus fed with latest Kalshi data")

        except Exception as exc:
            logger.warning(f"Failed to feed mood bus: {exc}")

    async def _opinion_loop(self) -> None:
        """Background loop: collect per-asset regime opinions and submit to TaCo consensus."""
        import asyncio as _aio
        while self._running:
            try:
                await self._collect_regime_opinions()
            except Exception as _exc:
                logger.debug("Opinion loop error (ignored): %s", _exc)
            try:
                # 15m scalper: faster opinion collection (15s vs 60s)
                _sleep = 15 if os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER" else 60
                await _aio.wait_for(_aio.sleep(_sleep), timeout=_sleep + 5)
            except (_aio.TimeoutError, _aio.CancelledError):
                break

    async def _collect_regime_opinions(self) -> None:
        """Call get_opinion() on every regime agent and submit non-None results to TaCo."""
        try:
            from consensus.taco_consensus import get_consensus_coordinator
            coordinator = get_consensus_coordinator()
        except Exception as _exc:
            logger.debug("TaCo coordinator unavailable: %s", _exc)
            return

        for agent in self._regime_agents:
            try:
                opinion = await agent.get_opinion()
                if opinion is None:
                    continue
                # Yield control after each agent to prevent blocking
                await asyncio.sleep(0)
                # Map AgentOpinion → TaCo opinion and submit
                from consensus.taco_consensus import AgentOpinion as TaCoOpinion, Stance
                import uuid as _uuid
                score = round((opinion.edge_estimate), 4)
                if score >= 0.3:
                    stance = Stance.BULL.value
                elif score <= -0.3:
                    stance = Stance.BEAR.value
                else:
                    stance = Stance.NEUTRAL.value
                taco_op = TaCoOpinion(
                    opinion_id=f"op_{_uuid.uuid4().hex[:12]}",
                    agent_id=opinion.agent_id,
                    role="regime",
                    symbol=opinion.market_id,
                    venue="kalshi",
                    stance=stance,
                    score=score,
                    confidence=opinion.confidence,
                    rationale=f"regime_signal:{opinion.side}",
                    horizon=opinion.horizon,
                    data_sources=["rti", "vol"],
                    supporting_data=opinion.metadata,
                )
                await coordinator.submit_opinion(taco_op)
                logger.debug("Regime opinion submitted: %s → %s (%.3f)", agent.agent_id, stance, score)
            except Exception as _aexc:
                logger.debug("Regime agent %s error: %s", agent.agent_id, _aexc)

    def _apply_regime_gating(self) -> None:
        """Tighten or relax agent activity based on global sentiment regime.

        Rules:
          extreme_fear / extreme_greed  → pause vol_breakout agents (too noisy)
          extreme_greed                 → pause regime_switch agents (momentum exhausted)
          fear / greed (moderate)       → resume all sentiment-driven agents

        BUG-7 fix: before resuming any agent the gate checks:
          1. DeploymentController.get_mode() — do not resume HALTED agents.
          2. PortfolioRiskAgent._paused_agents — do not resume agents paused by
             a portfolio risk breach.
        This prevents the regime gate from undoing safety-driven pauses.
        """
        glob = self._sentiment.global_score()
        regime = glob.regime
        score  = glob.score

        # BUG-2 fix: update adaptive risk limits every gating cycle and push
        # the computed caps into ExecutionGuard so they actually take effect.
        try:
            from governance.adaptive_risk_limits import (
                get_adaptive_risk_limit_manager,
                MarketRegime as _MR,
            )
            _arm = get_adaptive_risk_limit_manager()
            # Build a MarketRegime from the available sentiment data
            _pnl_trend = 0.0
            if self._portfolio_risk is not None and self._portfolio_risk.latest_snapshot is not None:
                _pnl_trend = float(self._portfolio_risk.latest_snapshot.daily_pnl_usd)
            _mr = _MR(
                volatility=getattr(glob, "volatility", 0.0) or 0.0,
                liquidity_score=getattr(glob, "liquidity_score", 1.0) or 1.0,
                pnl_trend=_pnl_trend,
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            )
            for _agent in self._agents:
                _lim = _arm.update_limits(_agent.agent_id, _mr)
                _arm.push_to_execution_guard(_agent.agent_id, venue="kalshi")
        except Exception as _arm_exc:
            logger.debug("AdaptiveRiskLimitManager update skipped: %s", _arm_exc)

        # Build the set of agents that are safety-paused so we never resume them
        _safety_paused: set = set()
        try:
            if self._portfolio_risk is not None:
                _safety_paused = set(self._portfolio_risk._paused_agents)
        except Exception:
            pass

        def _safe_to_resume(agent) -> bool:
            """Return False if deployment controller or portfolio risk has blocked this agent."""
            name = agent.config.name
            if name in _safety_paused:
                logger.debug(
                    "Regime gate: skipping resume of %s — held by portfolio risk breach", name
                )
                return False
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller
                from merid.event_venues.kalshi.deployment import AgentMode
                mode = get_deployment_controller().get_mode(name)
                if mode == AgentMode.HALTED:
                    logger.debug(
                        "Regime gate: skipping resume of %s — deployment mode is HALTED", name
                    )
                    return False
            except Exception:
                pass
            return True

        for agent in self._agents:
            archetype = agent.config.archetype

            if archetype == "vol_breakout":
                # vol_breakout needs elevated sentiment — pause when market is calm
                if 35 <= score <= 65:
                    if agent.state.enabled:
                        agent.pause()
                        logger.info(f"Regime gate: paused {agent.config.name} (vol_breakout, calm market score={score:.0f})")
                else:
                    if not agent.state.enabled and _safe_to_resume(agent):
                        agent.resume()
                        logger.info(f"Regime gate: resumed {agent.config.name} (vol_breakout, score={score:.0f})")

            elif archetype == "regime_switch":
                # regime_switch only useful when sentiment is clearly directional
                if 40 <= score <= 60:
                    if agent.state.enabled:
                        agent.pause()
                        logger.info(f"Regime gate: paused {agent.config.name} (regime_switch, neutral score={score:.0f})")
                else:
                    if not agent.state.enabled and _safe_to_resume(agent):
                        agent.resume()
                        logger.info(f"Regime gate: resumed {agent.config.name} (regime_switch, score={score:.0f})")

            elif archetype == "contrarian":
                # contrarian only active in extreme regimes
                if regime not in ("extreme_fear", "extreme_greed"):
                    if agent.state.enabled:
                        agent.pause()
                        logger.info(f"Regime gate: paused {agent.config.name} (contrarian, regime={regime})")
                else:
                    if not agent.state.enabled and _safe_to_resume(agent):
                        agent.resume()
                        logger.info(f"Regime gate: resumed {agent.config.name} (contrarian, regime={regime})")

    def _should_start_ct_coordination(self) -> bool:
        if os.getenv("MERID_AGENT_GRID_CT_COORD", "1").lower() not in ("1", "true", "yes"):
            return False
        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            if ct_loop_suppressed():
                return False
        except Exception:
            pass
        vname = getattr(self._config.venue, "name", "") or ""
        return vname.lower() == "kalshi"

    async def _ct_coordination_loop(self) -> None:
        """Periodic bridge log so CT-driven ``ua_ct_metrics`` are visible next to grid ops."""
        while self._running:
            try:
                await asyncio.sleep(60.0)
                from merid.prediction.ua_ct_metrics import snapshot as _ua_snap
                from merid.trading.kalshi_continuous_trader import get_continuous_trader

                snap = _ua_snap()
                ct = get_continuous_trader()
                logger.info(
                    "[UA-GRID] ct_running=%s ct_cycle=%s ua_ct_evaluated=%s "
                    "ua_ct_orders_accepted=%s ua_ct_orders_rejected=%s",
                    ct.is_running(),
                    getattr(ct, "_cycle", 0),
                    snap.get("evaluated"),
                    snap.get("orders_accepted"),
                    snap.get("orders_rejected"),
                )
            except asyncio.CancelledError:
                break
            except Exception as _ce:
                logger.debug("ct coordination loop: %s", _ce)

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
                # 15m scalper: faster regime collection (1 min vs 5 min)
                _sleep = 60 if os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER" else 300
                await asyncio.wait_for(asyncio.sleep(_sleep), timeout=_sleep + 10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                break

    # ── Agent management ───────────────────────────────────────────────

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
        """Register Twitter/Telegram sinks for prediction alerts.
        
        SOCIAL-TRUTH (2026-05-13): Twitter/Telegram sinks disabled for lean 15m Kalshi trading.
        """
        # def twitter_alert_sink(alert):
        #     """Send alert to Twitter."""
        #     try:
        #         from agents.twitter_agent import get_twitter_agent
        #         twitter = get_twitter_agent()

        #         severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        #         emoji = severity_emoji.get(alert.severity.value, "")

        #         message = (
        #             f"{emoji} [{alert.category.value.upper()}]\n"
        #             f"{alert.title}\n"
        #             f"{alert.message[:150]}"
        #         )
        #         twitter.post_tweet(message)
        #     except Exception:
        #         pass

        # def telegram_alert_sink(alert):
        #     """Send alert to Telegram."""
        #     try:
        #         from agents.telegram_agent import get_telegram_agent
        #         telegram = get_telegram_agent()

        #         severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        #         emoji = severity_emoji.get(alert.severity.value, "")

        #         message = (
        #             f"{emoji} <b>[{alert.category.value.upper()}]</b>\n"
        #             f"{alert.title}\n"
        #             f"{alert.message[:200]}"
        #         )
        #         telegram.send_message(message, parse_mode="HTML")
        #     except Exception:
        #         pass

        # # Register sinks
        # self._alert_router.add_sink(twitter_alert_sink)
        # self._alert_router.add_sink(telegram_alert_sink)
        # NOTE: Telegram sink is already registered by the PredictionAlertManager
        # singleton (via _make_telegram_sink in alerts.py).  Do NOT add a second
        # Telegram sink here — it causes every alert to be sent twice to TG,
        # triggering rate-limit cascades and 19s+ event-loop lag.
        # self._alert_manager.add_sink(twitter_alert_sink)
        # logger.info("✓ Alert sinks registered (Twitter)")
        pass

    def _register_promotion_callbacks(self) -> None:
        """Register AutoPromoter callbacks for gauntlet and promotion events.
        
        Wires promotion state transitions to:
        - Kill switch recommendations on gauntlet failure
        - Operator notifications on promotion proposals
        - Demotion handling for live agents that fail gauntlet
        """
        def on_promotion_transition(agent_id: str, old_state: Any, new_state: Any) -> None:
            """Handle promotion state transitions."""
            from merid.promotion.auto_promoter import PromotionState
            
            # Gauntlet failure - recommend kill switch
            if new_state == PromotionState.DEMOTED:
                logger.critical(
                    f"Agent {agent_id} DEMOTED - recommending kill switch",
                    extra={"previous_state": old_state.value, "action": "review_kill_switch"}
                )
                # Find markets for this agent and recommend kill
                for agent in self._agents:
                    if agent.agent_id == agent_id:
                        for asset in agent.config.assets:
                            for tf in agent.config.timeframes:
                                market_id = f"KX{asset}-{tf.upper()}"
                                self._auto_promoter.block_market(
                                    agent_id=agent_id,
                                    market=market_id,
                                    reason=f"gauntlet_failure_demotion"
                                )
            
            # Ready for live - notify operator
            if new_state == PromotionState.AWAITING_CONFIRMATION:
                logger.info(
                    f"Agent {agent_id} AWAITING_CONFIRMATION for live trading",
                    extra={"action": "operator_approval_required"}
                )
                # Could trigger notification to operator dashboard here
        
        # LEAN 15m KALSHI STACK (2026-05-13): Skip auto-promoter when ENABLE_AUTO_PROMOTER=false
        # to prevent loading thousands of promotion states on each agent grid init/cycle
        import os as _ap_os
        _ap_disabled = _ap_os.getenv("ENABLE_AUTO_PROMOTER", "false").lower() == "false"
        if _ap_disabled:
            logger.info("[LEAN KALSHI] AutoPromoter disabled (ENABLE_AUTO_PROMOTER=false)")
            return

        # Register the callback
        self._auto_promoter.register_callback(on_promotion_transition)
        
        # Initialize promotion tracking for all agents (single persist — avoids N disk writes)
        new_tracking = 0
        for agent in self._agents:
            aid = agent.agent_id
            existed = self._auto_promoter.get_status(aid) is not None
            self._auto_promoter.initialize_agent(
                agent_id=aid,
                asset=agent.config.assets[0] if agent.config.assets else "UNKNOWN",
                timeframe=agent.config.timeframes[0] if agent.config.timeframes else "UNKNOWN",
                persist=False,
                log=False,
            )
            if not existed:
                new_tracking += 1
        self._auto_promoter.persist_states()
        logger.info(
            "✓ AutoPromoter callbacks registered for %s agents (%s new promotion records)",
            len(self._agents),
            new_tracking,
        )

    def summary(self) -> Dict[str, Any]:
        """Full grid status for API consumption."""
        # Grid-wide metrics
        total_fills = sum(len(a.state.fill_log) for a in self._agents)
        total_orders = sum(a.state.orders_placed for a in self._agents)

        # Category PnL breakdown — sourced from per-agent risk manager if available,
        # falling back to fill-log notional as a proxy.
        pnl_by_category: Dict[str, float] = {}
        for agent in self._agents:
            cat = agent.config.category
            pnl = 0.0
            try:
                pnl = float(agent._risk.summary().get("daily_realized_pnl_usd", 0.0))
            except Exception:
                # Fallback: sum fill notional from fill_log as best-effort proxy
                for fill in agent.state.fill_log:
                    pc = fill.get("price_cents") or 0
                    ct = fill.get("contracts") or 0
                    try:
                        pnl += float(pc) * float(ct) / 100.0
                    except Exception:
                        pass
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

        ua_ct: Dict[str, Any] = {}
        try:
            from merid.prediction.ua_ct_metrics import snapshot as _ua_snap

            ua_ct = _ua_snap()
        except Exception as _ua_exc:
            logger.debug("ua_ct_metrics snapshot skipped: %s", _ua_exc)

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
                "ua_ct": ua_ct,
            },
            "agent_count": len(self._agents),
            "assets": self._catalog.assets() if self._catalog else self._config.all_assets,
            "session": self._session_guard.summary(),
            "agents": [a.summary() for a in self._agents],
            "portfolio_risk": self._portfolio_risk.summary(),
            "social_broadcaster": self._broadcaster.summary(),
            "paper_session": paper_session_data,
        }

    def get_agent(self, agent_name: str) -> Optional["KalshiTradingAgent"]:
        """Return the KalshiTradingAgent for API/dashboard lookups.

        The grid matrix exposes ``covering_agent.config.name`` (e.g. ``BTC_WEEKLY``).
        ``KalshiTradingAgent.agent_id`` is uniquified (``BTC_WEEKLY_<instance>``), so
        we must match ``config.name`` *before* the property id — the old implementation
        only compared the uniquified id and returned 404 for every cell.
        """
        if not agent_name or not agent_name.strip():
            return None
        want = agent_name.strip()
        want_l = want.lower()
        for agent in self._agents:
            cfg = agent.config
            cfg_name = (getattr(cfg, "name", None) or "").strip()
            cfg_agent_id = (getattr(cfg, "agent_id", None) or "").strip()
            try:
                inst_id = (agent.agent_id or "").strip()
            except Exception:
                inst_id = ""
            if cfg_name and (cfg_name == want or cfg_name.lower() == want_l):
                return agent
            if cfg_agent_id and (cfg_agent_id == want or cfg_agent_id.lower() == want_l):
                return agent
            if inst_id and (inst_id == want or inst_id.lower() == want_l):
                return agent
            if cfg_name and inst_id.lower().startswith(cfg_name.lower() + "_") and want_l == cfg_name.lower():
                return agent
            if (
                cfg_agent_id
                and inst_id.lower().startswith(cfg_agent_id.lower() + "_")
                and want_l == cfg_agent_id.lower()
            ):
                return agent
        return None

    def get_performance_summary(self) -> Dict[str, Any]:
        """Return {agent_name: {metrics...}} for all agents."""
        result: Dict[str, Any] = {}
        for agent in self._agents:
            name = getattr(agent, "agent_id", None) or getattr(agent, "name", None) or getattr(agent.config, "name", None)
            if not name:
                continue
            try:
                perf = agent.performance_metrics() if hasattr(agent, "performance_metrics") else {}
            except Exception:
                perf = {}
            if perf:
                result[name] = perf
        return result

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
_grid_lock = threading.Lock()

# Set when web lifespan skips deferred grid (e.g. MERID_VALIDATION_MODE=1).
_DEFERRED_GRID_SKIP_REASON: Optional[str] = None


def note_agent_grid_deferred_skipped(reason: str) -> None:
    """Call from app lifespan when AgentGrid ``start()`` is intentionally not run."""
    global _DEFERRED_GRID_SKIP_REASON
    _DEFERRED_GRID_SKIP_REASON = reason


def clear_agent_grid_deferred_skip() -> None:
    global _DEFERRED_GRID_SKIP_REASON
    _DEFERRED_GRID_SKIP_REASON = None


def get_agent_grid() -> AgentGrid:
    """Return the module-level AgentGrid singleton."""
    global _grid
    if _grid is None:
        with _grid_lock:
            if _grid is None:
                _grid = AgentGrid()
    return _grid
