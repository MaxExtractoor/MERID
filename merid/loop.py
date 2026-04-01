"""§3 MERID Main Loop — persistent async orchestrator.

Drives the full swarm cycle on a configurable cadence:

  1. Refresh features (news/macro/onchain/social) with decay
  2. Run agent cycles per domain
  3. Run consensus aggregation (decay-aware)
  4. Run arb/dislocation scans
  5. Generate plans → risk checks → pass to execution
  6. Update CQI / drift metrics
  7. Reconcile positions with venues
  8. Push events to subscribers

Usage:
    # Run the loop
    python -m merid.loop

    # Test one iteration
    from merid.loop import MeridLoop
    loop = MeridLoop()
    await loop.tick()
"""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.loop")


# ── Configuration ─────────────────────────────────────────────────────

@dataclass
class LoopConfig:
    """Cadence and feature flags for the main loop.

    Prefer constructing via ``LoopConfig.from_paper_config()`` so that
    domains, symbols, cadences, and limits are driven by the single
    config matrix in ``merid.paper_config``.
    """
    # Cadence (seconds)
    feature_refresh_interval: float = 30.0
    agent_cycle_interval: float = 60.0
    consensus_interval: float = 15.0
    arb_scan_interval: float = 10.0
    cqi_interval: float = 300.0
    reconciliation_interval: float = 120.0

    # Feature flags
    enable_execution: bool = False        # Must be explicitly enabled
    enable_arb_execution: bool = False
    enable_reconciliation: bool = True
    enable_notifications: bool = True

    # Domains to run
    active_domains: List[str] = field(default_factory=lambda: ["crypto", "prediction"])
    active_symbols: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])

    # Per-domain mode map (populated by from_paper_config)
    domain_modes: Dict[str, str] = field(default_factory=dict)

    # Reconciliation venues (populated by from_paper_config)
    reconciliation_venues: List[str] = field(default_factory=list)

    @classmethod
    def from_paper_config(cls) -> "LoopConfig":
        """Build LoopConfig from the paper_config matrix.

        This is the preferred constructor — it ensures the loop is
        driven by the single source of truth in merid.paper_config.
        """
        from merid.paper_config import get_paper_config
        pc = get_paper_config()

        # Derive active symbols for feature refresh (short names for macro/signal layer)
        price_symbols = []
        for d in pc.active_domains():
            if d.feed_type == "price":
                for s in d.symbols:
                    # "BTC/USDT" -> "BTC", "AAPL" -> "AAPL"
                    short = s.split("/")[0] if "/" in s else s
                    price_symbols.append(short)

        return cls(
            feature_refresh_interval=pc.tick_interval * 6,   # ~30s at 5s tick
            agent_cycle_interval=pc.agent_cycle_interval,
            consensus_interval=pc.consensus_interval,
            arb_scan_interval=pc.arb_scan_interval,
            cqi_interval=pc.cqi_interval,
            reconciliation_interval=pc.reconciliation_interval,
            enable_execution=pc.enable_execution,
            enable_arb_execution=pc.enable_arb_execution,
            enable_reconciliation=pc.enable_reconciliation,
            enable_notifications=pc.enable_notifications,
            active_domains=pc.active_domain_names(),
            active_symbols=sorted(set(price_symbols)),
            domain_modes={d.name: d.mode.value for d in pc.active_domains()},
            reconciliation_venues=pc.reconciliation_venues(),
        )


# ── Loop state ────────────────────────────────────────────────────────

@dataclass
class LoopMetrics:
    """Tracks loop performance and health."""
    total_ticks: int = 0
    total_errors: int = 0
    last_tick_at: float = 0.0
    last_tick_duration_ms: float = 0.0
    last_error: str = ""
    features_refreshed: int = 0
    agent_cycles_run: int = 0
    consensus_cycles_run: int = 0
    arb_scans_run: int = 0
    plans_generated: int = 0
    plans_executed: int = 0
    cqi_updates: int = 0
    reconciliations_run: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ticks": self.total_ticks,
            "total_errors": self.total_errors,
            "last_tick_at": self.last_tick_at,
            "last_tick_duration_ms": round(self.last_tick_duration_ms, 1),
            "last_error": self.last_error,
            "features_refreshed": self.features_refreshed,
            "agent_cycles_run": self.agent_cycles_run,
            "consensus_cycles_run": self.consensus_cycles_run,
            "arb_scans_run": self.arb_scans_run,
            "plans_generated": self.plans_generated,
            "plans_executed": self.plans_executed,
            "cqi_updates": self.cqi_updates,
            "reconciliations_run": self.reconciliations_run,
        }


# ── Main Loop ─────────────────────────────────────────────────────────

class MeridLoop:
    """Persistent orchestrator that drives the MERID swarm.

    Each `tick()` runs one full cycle. The `run()` method drives
    ticks continuously on the configured cadence.
    """

    def __init__(self, config: Optional[LoopConfig] = None):
        self.config = config or LoopConfig()
        self.metrics = LoopMetrics()
        self._running = False
        self._subscribers: Set[Callable] = set()
        self._matching_engines: Dict[str, Any] = {}
        self._agent_errors: Dict[str, int] = {}  # per-agent consecutive error count

        # Timers for staggered cadences
        self._last_feature_refresh = 0.0
        self._last_agent_cycle = 0.0
        self._last_consensus = 0.0
        self._last_arb_scan = 0.0
        self._last_cqi_update = 0.0
        self._last_reconciliation = 0.0
        self._last_promotion_sync = 0.0
        self._promotion_sync_interval = 300.0  # 5 minutes
        self._last_betting_refresh = 0.0
        self._betting_refresh_interval = 120.0  # 2 minutes
        self._last_reflection_cycle = 0.0
        self._reflection_cycle_interval = 300.0  # 5 minutes — run after enough fills accumulate
        self._last_liquidity_refresh = 0.0
        self._liquidity_refresh_interval = 30.0  # 30 seconds — orderbook health sweep
        self._last_config_reload = 0.0
        self._config_reload_interval = 300.0  # 5 minutes — hot-reload risk limits / reality assertions
        self._last_order_group_sync = 0.0
        self._order_group_sync_interval = 30.0  # 30 seconds — Kalshi order group lifecycle sync

        # Tick processing lag tracking
        self._tick_in_progress = False
        self._last_tick_duration_ms = 0.0
        self._step_durations: Dict[str, float] = {}  # Track per-step timing

        # Feature refresh batching (process N symbols per tick, round-robin)
        self._feature_batch_size = 2  # symbols per tick
        self._feature_symbol_idx = 0  # round-robin cursor
        self._macro_features_cache = None  # cache macro features (low change frequency)
        self._macro_features_cache_ts = 0.0

        # W6: pre-initialise ws_bridge so _refresh_liquidity can safely reference it
        # before run() is called (e.g. in tests or if tick() is called standalone).
        self._ws_bridge = None

        # Initialize matching engines for domains that have them configured
        try:
            from merid.matching_engine import init_matching_engines
            self._matching_engines = init_matching_engines()
            if self._matching_engines:
                logger.info(
                    f"Matching engines active: {list(self._matching_engines.keys())}"
                )
        except Exception as e:
            logger.warning(f"Matching engine init skipped: {e}")

    # ── Lazy service accessors ────────────────────────────────────────

    def _feature_service(self):
        from merid.signals.features import get_feature_service
        return get_feature_service()

    def _scanner(self):
        from merid.signals.arbitrage import get_dislocation_scanner
        return get_dislocation_scanner()

    def _drift_detector(self):
        from merid.signals.drift import get_drift_detector
        return get_drift_detector()

    def _signal_store(self):
        from merid.signals.store import get_signal_store
        return get_signal_store()

    def _consensus_coordinator(self):
        from consensus.taco_consensus import TaCoConsensusCoordinator
        return TaCoConsensusCoordinator.get_instance()

    def _risk_manager(self):
        from merid.pipeline.risk_manager import get_global_risk_manager
        return get_global_risk_manager()

    def _agent_registry(self):
        from merid.agents.base import get_canonical_registry
        return get_canonical_registry()

    def _execution_guard(self):
        from merid.execution_guard import get_execution_guard
        return get_execution_guard()

    def _risk_context(self):
        from merid.pipeline.risk_context import build_risk_context
        return build_risk_context()

    def _betting_odds_client(self):
        from merid.betting.odds_client import get_odds_client
        return get_odds_client()

    def _betting_store(self):
        from merid.betting.store import get_betting_store
        return get_betting_store()

    def _order_group_lifecycle(self):
        if not hasattr(self, '_og_lifecycle'):
            from merid.event_venues.kalshi.order_group_lifecycle import OrderGroupLifecycleManager
            from merid.event_venues.kalshi.client import get_kalshi_client
            self._og_lifecycle = OrderGroupLifecycleManager(get_kalshi_client())
        return self._og_lifecycle

    def _liquidity_monitor(self):
        if not hasattr(self, '_liq_monitor'):
            from merid.event_venues.kalshi.liquidity_monitor import LiquidityMonitor
            self._liq_monitor = LiquidityMonitor()
            # Log critical alerts so operators see them in the loop log
            self._liq_monitor.on_alert(
                lambda a: logger.warning(
                    "liquidity_alert %s %s %s: %s",
                    a.severity, a.kind, a.market_id, a.msg,
                ) if a.severity == "critical" else logger.debug(
                    "liquidity_alert %s %s %s: %s",
                    a.severity, a.kind, a.market_id, a.msg,
                )
            )
        return self._liq_monitor

    # ── Core tick ─────────────────────────────────────────────────────

    async def _run_step_with_timeout(
        self,
        coro,
        step_name: str,
        timeout_ms: Optional[float] = None,
    ) -> bool:
        """Run a tick step with optional timeout and timing tracking.

        Args:
            coro: The coroutine to run
            step_name: Name for logging and metrics
            timeout_ms: Optional timeout in milliseconds

        Returns:
            True if step completed successfully, False if timed out
        """
        step_start = time.perf_counter()
        try:
            if timeout_ms:
                await asyncio.wait_for(coro, timeout=timeout_ms / 1000.0)
            else:
                await coro
            step_elapsed_ms = (time.perf_counter() - step_start) * 1000
            self._step_durations[step_name] = step_elapsed_ms
            return True
        except asyncio.TimeoutError:
            step_elapsed_ms = (time.perf_counter() - step_start) * 1000
            self._step_durations[step_name] = step_elapsed_ms
            logger.error(
                f"Step {step_name} exceeded timeout of {timeout_ms}ms "
                f"(elapsed: {step_elapsed_ms:.1f}ms)"
            )
            return False
        except Exception as e:
            step_elapsed_ms = (time.perf_counter() - step_start) * 1000
            self._step_durations[step_name] = step_elapsed_ms
            logger.error(f"Step {step_name} failed: {e}")
            raise

    async def tick(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Run one full cycle of the swarm loop.

        Returns a summary dict of what happened this tick.
        """
        now = now or time.time()
        start = time.perf_counter()
        summary: Dict[str, Any] = {"tick": self.metrics.total_ticks + 1, "actions": []}

        # Tick overlap detection
        if self._tick_in_progress:
            logger.warning(
                f"Tick overlap detected - previous tick still running "
                f"(last duration: {self._last_tick_duration_ms:.1f}ms)"
            )
            summary["tick_overlap"] = True
            summary["skipped"] = "tick_overlap"
            return summary

        self._tick_in_progress = True
        self._step_durations.clear()

        try:
            # Step 1: Refresh features
            if now - self._last_feature_refresh >= self.config.feature_refresh_interval:
                await self._refresh_features(now, summary)
                self._last_feature_refresh = now

            # Step 2: Run agent cycles
            if now - self._last_agent_cycle >= self.config.agent_cycle_interval:
                await self._run_agent_cycles(summary)
                self._last_agent_cycle = now

            # Step 2b: Reflection / learning cycle (post-agent-cycle, every 5 min)
            if now - self._last_reflection_cycle >= self._reflection_cycle_interval:
                await self._run_reflection_cycle(summary)
                self._last_reflection_cycle = now

            # Step 3: Consensus aggregation
            if now - self._last_consensus >= self.config.consensus_interval:
                await self._run_consensus(summary)
                self._last_consensus = now

            # Step 4: Arb/dislocation scan
            if now - self._last_arb_scan >= self.config.arb_scan_interval:
                await self._run_arb_scan(now, summary)
                self._last_arb_scan = now

            # Step 4b: Liquidity monitor sweep
            if now - self._last_liquidity_refresh >= self._liquidity_refresh_interval:
                await self._refresh_liquidity(now, summary)
                self._last_liquidity_refresh = now

            # Step 5: Execute approved plans
            if self.config.enable_execution:
                await self._execute_plans(summary)

            # Step 6: CQI / drift update
            if now - self._last_cqi_update >= self.config.cqi_interval:
                await self._update_cqi(now, summary)
                self._last_cqi_update = now

            # Step 6b: Promotion sync (refresh guard's view of eligible domains)
            if now - self._last_promotion_sync >= self._promotion_sync_interval:
                self._sync_promotion(summary)
                self._last_promotion_sync = now

            # Step 7a: Sports betting odds refresh
            if now - self._last_betting_refresh >= self._betting_refresh_interval:
                await self._refresh_betting_odds(now, summary)
                self._last_betting_refresh = now

            # Step 7: Position reconciliation
            if self.config.enable_reconciliation and now - self._last_reconciliation >= self.config.reconciliation_interval:
                await self._reconcile_positions(summary)
                self._last_reconciliation = now

            # Step 7b: Order group lifecycle sync (for prediction domain)
            if "prediction" in self.config.active_domains:
                if now - self._last_order_group_sync >= self._order_group_sync_interval:
                    await self._sync_order_groups(summary)
                    self._last_order_group_sync = now

            # Step 7c: Config hot-reload — re-register live assertions in RealityAuditor
            if now - self._last_config_reload >= self._config_reload_interval:
                await self._reload_config(summary)
                self._last_config_reload = now

            # Step 8: Notify subscribers
            await self._notify("tick_complete", summary)

        except Exception as e:
            self.metrics.total_errors += 1
            self.metrics.last_error = str(e)
            logger.error(f"Loop tick error: {e}\n{traceback.format_exc()}")
            summary["error"] = str(e)
        finally:
            self._tick_in_progress = False

        elapsed_ms = (time.perf_counter() - start) * 1000
        self.metrics.total_ticks += 1
        self.metrics.last_tick_at = now
        self.metrics.last_tick_duration_ms = elapsed_ms
        self._last_tick_duration_ms = elapsed_ms
        summary["duration_ms"] = round(elapsed_ms, 1)
        if self._step_durations:
            summary["step_durations"] = {
                k: round(v, 1) for k, v in self._step_durations.items()
            }

        return summary

    # ── Step implementations ──────────────────────────────────────────

    async def _refresh_features(self, now: float, summary: Dict):
        """Step 1: Refresh decay-aware features for active symbols.

        Uses symbol batching (2 symbols per tick, round-robin) and parallel
        feature fetching to reduce per-tick cost from ~4,700ms to ~1,500ms.

        First tries live API feeds (Finnhub, FRED, CoinGecko).
        Then reads aggregated features through the feature service.
        For prediction domain: generates Kalshi-specific signals.
        """
        # Determine which symbols to process this tick (round-robin batching)
        if not self.config.active_symbols:
            summary["actions"].append("features_refreshed:no_symbols")
            return

        symbols_to_process = []
        for i in range(self._feature_batch_size):
            idx = (self._feature_symbol_idx + i) % len(self.config.active_symbols)
            symbols_to_process.append(self.config.active_symbols[idx])

        # Advance cursor for next tick
        self._feature_symbol_idx = (
            self._feature_symbol_idx + self._feature_batch_size
        ) % len(self.config.active_symbols)

        # Try live data first (for the batch)
        try:
            from merid.signals.live_feeds import get_live_feed_manager
            mgr = get_live_feed_manager()
            await mgr.refresh_all(symbols_to_process, now)
        except Exception as e:
            logger.warning(f"Live feed refresh failed (using cached/synthetic): {e}")

        # Fetch features for each symbol in parallel
        svc = self._feature_service()
        store = self._signal_store()

        async def fetch_symbol_features(symbol: str):
            """Fetch all features for a single symbol."""
            try:
                news = svc.get_news_features(symbol, now=now)
                social = svc.get_social_features(symbol, now=now)
                chain = "solana" if symbol in ("SOL", "BONK", "WIF") else "ethereum"
                onchain = svc.get_onchain_features(chain, symbol, now=now)

                # Store each feature snapshot
                for fs in [news, social, onchain]:
                    store.store_feature_snapshot(fs.to_dict())

                return symbol, True
            except Exception as e:
                logger.warning(f"Feature refresh failed for {symbol}: {e}")
                return symbol, False

        # Process batch in parallel
        tasks = [fetch_symbol_features(sym) for sym in symbols_to_process]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes
        success_count = sum(
            1 for r in results
            if not isinstance(r, Exception) and r[1]
        )

        # Fetch macro features (cached for 60s since they change slowly)
        if now - self._macro_features_cache_ts >= 60.0:
            try:
                macro = svc.get_macro_features(now=now)
                store.store_feature_snapshot(macro.to_dict())
                self._macro_features_cache = macro
                self._macro_features_cache_ts = now
            except Exception as e:
                logger.warning(f"Macro feature refresh failed: {e}")

        # Generate Kalshi signals if prediction domain is active
        if "prediction" in self.config.active_domains:
            await self._refresh_kalshi_signals(now, summary, store)

        self.metrics.features_refreshed += 1
        summary["actions"].append(
            f"features_refreshed:{success_count}/{len(symbols_to_process)}symbols_batch"
            f"(coverage:{len(self.config.active_symbols)}total)"
        )

    async def _refresh_kalshi_signals(self, now: float, summary: Dict, store):
        """Generate and store Kalshi-specific signals for prediction domain."""
        try:
            from merid.signals.kalshi_signals import get_kalshi_signal_generator
            
            generator = get_kalshi_signal_generator()
            signals = await generator.generate_all(now)
            
            # Store each signal
            for signal in signals:
                store.store_signal(signal.to_dict())
            
            if signals:
                logger.info(f"Generated {len(signals)} Kalshi signals")
                summary["actions"].append(f"kalshi_signals:{len(signals)}")
        except Exception as exc:
            logger.warning(f"Kalshi signal generation failed (graceful degradation): {exc}")
    
    async def _run_agent_cycles(self, summary: Dict):
        """Step 2: Run canonical agents per category (with 30s timeout).
        
        For prediction domain: also run KalshiTradingAgent cycle and collect
        signals for potential consensus submission.
        """
        try:
            # Run canonical agents (crypto domain)
            registry = self._agent_registry()
            results = await asyncio.wait_for(registry.run_all(), timeout=30.0)
            self.metrics.agent_cycles_run += 1
            summary["actions"].append(f"agent_cycles:{len(results)}agents")
            
            # Reset consecutive error counters for agents that succeeded
            for agent_id in (getattr(r, "agent_id", None) for r in (results or [])):
                if agent_id:
                    self._agent_errors.pop(agent_id, None)
            
            # Run Kalshi agents if prediction domain is active
            if "prediction" in self.config.active_domains:
                await self._run_kalshi_agent_cycle(summary)
                
        except asyncio.TimeoutError:
            logger.error("Agent cycle timed out after 30s")
            summary["actions"].append("agent_cycles:timeout")
        except Exception as e:
            logger.warning(f"Agent cycle failed: {e}")
            summary["actions"].append(f"agent_cycles:error:{e}")

    async def _run_kalshi_agent_cycle(self, summary: Dict):
        """Run KalshiTradingAgent decision cycle and collect signals.
        
        Note: For now, agents execute directly via their own cycle.
        Future: Submit signals to consensus for multi-agent voting.
        """
        try:
            from merid.prediction.agent_grid import get_agent_grid
            
            grid = get_agent_grid()
            
            # Check if grid is running
            if not grid.is_running:
                logger.debug("Kalshi agent grid not running, skipping agent cycle")
                return
            
            # Collect recent signals from active agents
            signal_count = 0
            for agent in grid.agents:
                if agent.state.enabled and agent.state.signal_log:
                    # Get most recent signals (last cycle)
                    recent = [s for s in agent.state.signal_log[-10:] 
                             if s.get("action") not in ("NO_ACTION", "HOLD")]
                    signal_count += len(recent)
            
            if signal_count > 0:
                logger.info(f"Kalshi agents generated {signal_count} actionable signals this cycle")
                summary["actions"].append(f"kalshi_agents:{signal_count}signals")

            # Submit actionable signals to TaCoConsensusCoordinator as AgentOpinions
            opinions_submitted = 0
            try:
                from consensus.taco_consensus import (
                    TaCoConsensusCoordinator,
                    AgentOpinion,
                    AgentRole,
                )
                import uuid as _uuid
                coordinator = TaCoConsensusCoordinator.get_instance()
                for agent in grid.agents:
                    if not (agent.state.enabled and agent.state.signal_log):
                        continue
                    recent_signals = [
                        s for s in agent.state.signal_log[-5:]
                        if s.get("action") not in ("NO_ACTION", "HOLD")
                    ]
                    for sig in recent_signals:
                        action = sig.get("action", "").lower()
                        if action in ("buy", "yes", "long"):
                            score = sig.get("edge", 0.05)
                            stance = "bull"
                        elif action in ("sell", "no", "short"):
                            score = -(sig.get("edge", 0.05))
                            stance = "bear"
                        else:
                            continue
                        confidence = float(sig.get("confidence", sig.get("edge", 0.5)))
                        confidence = max(0.1, min(1.0, confidence))
                        opinion = AgentOpinion(
                            opinion_id=f"op_{_uuid.uuid4().hex[:12]}",
                            agent_id=agent.agent_id,
                            role=AgentRole.TRADER.value,
                            symbol=sig.get("market_id", sig.get("ticker", "KALSHI")),
                            venue="kalshi",
                            stance=stance,
                            score=float(score),
                            confidence=confidence,
                            rationale=sig.get("reason", sig.get("signal_type", "kalshi_signal"))[:200],
                            horizon="short",
                        )
                        await coordinator.submit_opinion(opinion)
                        opinions_submitted += 1
            except Exception as _ce:
                logger.debug(f"Consensus opinion submission failed (non-fatal): {_ce}")

            if opinions_submitted:
                summary["actions"].append(f"consensus_opinions_submitted:{opinions_submitted}")
            
        except Exception as exc:
            logger.warning(f"Kalshi agent cycle failed (graceful degradation): {exc}")
    
    async def _run_reflection_cycle(self, summary: Dict):
        """Step 2b: Run post-task reflection and learning for Kalshi agents.

        For each active Kalshi agent, pulls its recent reflections from the
        ReflectionSystem, generates learning insights, and surfaces any
        critical recommendations (overconfidence, low accuracy) to the summary.
        Runs every 5 minutes — lightweight, all in-memory.
        """
        if "prediction" not in self.config.active_domains:
            return
        try:
            from agents.reflection.integration import get_reflection_system
            from merid.prediction.agent_grid import get_agent_grid

            reflection_sys = get_reflection_system()
            grid = get_agent_grid()

            total_reflections = 0
            total_insights = 0
            critical_agents: list = []

            for agent in grid.agents:
                agent_id = agent.agent_id
                reflections = reflection_sys.core.get_agent_reflections(agent_id, limit=200)
                if not reflections:
                    continue
                total_reflections += len(reflections)

                insights = reflection_sys.learning.generate_insights(
                    agent_id, reflections, force_refresh=True
                )
                total_insights += len(insights)

                # Surface critical recommendations
                for ins in insights:
                    if ins.insight_type == "recommendation" and "critical" in ins.title.lower():
                        critical_agents.append({
                            "agent": agent_id,
                            "issue": ins.title,
                            "confidence": ins.confidence,
                        })
                        logger.warning(
                            f"Reflection CRITICAL [{agent_id}]: {ins.title} "
                            f"(evidence={ins.evidence_count}, conf={ins.confidence:.2f})"
                        )

            summary["actions"].append(
                f"reflection_cycle:{total_reflections}reflections,{total_insights}insights"
            )
            if critical_agents:
                summary["reflection_critical"] = critical_agents

        except Exception as exc:
            logger.warning(f"Reflection cycle failed (graceful degradation): {exc}")
            summary["actions"].append(f"reflection_cycle:error:{exc}")

    async def _reload_config(self, summary: Dict) -> None:
        """Step 7c: Hot-reload config — re-register live assertions in RealityAuditor
        and re-bootstrap PortfolioRebalancer targets so risk limit changes propagate
        without a server restart.
        """
        reloaded: list = []

        # 1. RealityAuditor hot-reload
        try:
            from core.reality_auditor import get_reality_auditor
            auditor = get_reality_auditor()
            ok = auditor.reload_from_persistent_store()
            reloaded.append(f"reality_auditor:{'ok' if ok else 'noop'}")
        except Exception as exc:
            logger.debug("config_reload: reality_auditor skipped: %s", exc)

        # 2. PortfolioRebalancer target re-bootstrap
        try:
            from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
            rebalancer = get_portfolio_rebalancer()
            rebalancer._bootstrap_targets()
            reloaded.append("rebalancer:bootstrapped")
        except Exception as exc:
            logger.debug("config_reload: rebalancer bootstrap skipped: %s", exc)

        # 3. RewardEngine — ensure singleton is alive (no-op if already running)
        try:
            from merid.rewards.engine import get_reward_engine
            get_reward_engine()
            reloaded.append("reward_engine:ok")
        except Exception as exc:
            logger.debug("config_reload: reward_engine skipped: %s", exc)

        if reloaded:
            summary["actions"].append("config_reload:" + ",".join(reloaded))
            logger.debug("config_reload: %s", reloaded)

    async def _run_consensus(self, summary: Dict):
        """Step 3: Run consensus for active symbols (decay-aware).

        Prunes expired plans from _active_plans and forces a consensus
        cycle for any symbol that has accumulated pending opinions since
        the last tick but hasn't yet crossed the min_opinions threshold
        (opinion-triggered cycles handle the normal path).
        """
        coordinator = self._consensus_coordinator()

        # Prune expired plans so _execute_plans never sees stale entries
        # Use public prune_expired_plans() if available, else fall back to direct access
        if hasattr(coordinator, 'prune_expired_plans'):
            coordinator.prune_expired_plans()
            expired_ids = []
        else:
            _active_plans = getattr(coordinator, '_active_plans', {})
            expired_ids = [
                pid for pid, plan in list(_active_plans.items())
                if plan.is_expired()
            ]
            for pid in expired_ids:
                _active_plans.pop(pid, None)

        # Force a consensus cycle for any symbol with pending opinions
        # that hasn't yet reached min_opinions (catches slow-accumulating symbols)
        _opinions = getattr(coordinator, '_opinions', {})
        pending_symbols = [
            sym for sym, ops in _opinions.items()
            if ops and len(ops) >= 1
        ]

        # Parallelize consensus cycles for independent symbols (with timeout)
        async def run_consensus_with_timeout(sym: str):
            """Run consensus cycle for a single symbol with timeout."""
            try:
                plan = await asyncio.wait_for(
                    coordinator._run_consensus_cycle(sym),
                    timeout=2.0  # 2s per symbol
                )
                return (sym, plan)
            except asyncio.TimeoutError:
                logger.warning(f"Consensus cycle timeout for {sym}")
                return (sym, None)
            except Exception as _ce:
                logger.debug(f"Consensus cycle error for {sym}: {_ce}")
                return (sym, None)

        # Run consensus cycles in parallel (limit to 5 concurrent)
        semaphore = asyncio.Semaphore(5)

        async def run_with_semaphore(sym: str):
            async with semaphore:
                return await run_consensus_with_timeout(sym)

        tasks = [run_with_semaphore(sym) for sym in pending_symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful cycles
        forced = sum(
            1 for r in results
            if not isinstance(r, Exception) and r[1] is not None
        )

        self.metrics.consensus_cycles_run += 1

        # === Debate Protocol Integration ===
        # For each forced consensus plan, open a DebateSession so agents can
        # argue for/against before execution.  Close open debates whose symbol
        # now has a fresh consensus probability.
        debates_opened = 0
        debates_closed = 0
        try:
            from merid.prediction.debate import get_debate_store, DebateSession
            debate_store = get_debate_store()

            # Pre-fetch all open debates once (avoid N+1 queries)
            all_open_debates = debate_store.list_debates(status="open", limit=50)
            open_debates_by_symbol = {}
            for debate in all_open_debates:
                symbol = debate.symbol
                if symbol not in open_debates_by_symbol:
                    open_debates_by_symbol[symbol] = []
                open_debates_by_symbol[symbol].append(debate)

            # Open a debate for each freshly-forced plan (high-conviction only)
            _active_plans = getattr(coordinator, '_active_plans', {})
            for plan in list(_active_plans.values()):
                prob = getattr(plan, 'consensus_probability', None) or getattr(plan, 'probability', None)
                if prob is None:
                    continue
                # Only open debates for high-conviction signals (edge > 5%)
                edge = abs(float(prob) - 0.5)
                if edge < 0.05:
                    continue
                symbol = getattr(plan, 'symbol', None) or getattr(plan, 'market_id', None)
                if not symbol:
                    continue
                # Avoid duplicate open debates for the same symbol (using pre-fetched data)
                if symbol in open_debates_by_symbol:
                    continue
                session = DebateSession(
                    symbol=symbol,
                    pre_debate_prob=float(prob),
                )
                debate_store.create_debate(session)
                debates_opened += 1
                logger.debug("debate opened: %s pre_prob=%.3f", symbol, float(prob))

            # Close open debates whose symbol has a fresh consensus probability
            for debate in all_open_debates:
                sym_opinions = _opinions.get(debate.symbol, [])
                if not sym_opinions:
                    continue
                # Use latest opinion confidence as post-debate probability
                latest = sym_opinions[-1]
                post_prob = getattr(latest, 'probability', None) or getattr(latest, 'confidence', None)
                if post_prob is None:
                    continue
                debate_store.close_debate(debate.id, float(post_prob))
                debates_closed += 1
                logger.debug("debate closed: %s post_prob=%.3f", debate.symbol, float(post_prob))

        except Exception as _de:
            logger.debug("debate integration skipped: %s", _de)

        summary["actions"].append(
            f"consensus_check:expired_pruned={len(expired_ids)},forced={forced},"
            f"debates_opened={debates_opened},debates_closed={debates_closed}"
        )

    async def _refresh_liquidity(self, now: float, summary: Dict) -> None:
        """Step 4b: Poll orderbook snapshots for active Kalshi markets.

        Feeds each snapshot into LiquidityMonitor which emits alerts on
        wide spreads, thin books, and sudden depth drops.  Critical alerts
        are logged at WARNING level so operators see them immediately.
        """
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.event_venues.kalshi.liquidity_monitor import OrderBookSnapshot

            monitor = self._liquidity_monitor()
            client = get_kalshi_client()

            # Collect active tickers from the agent grid
            tickers: List[str] = []
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()
                for agent in grid.agents:
                    tickers.extend(agent.state.active_tickers)
            except Exception as _age:
                logger.debug("liquidity_sweep agent_grid skipped: %s", _age)

            if not tickers:
                summary["actions"].append("liquidity_sweep:no_active_tickers")
                return

            # Deduplicate
            tickers = list(dict.fromkeys(tickers))[:20]  # cap at 20 markets per sweep

            # D13: Subscribe WS bridge to any new tickers discovered this sweep
            if getattr(self, '_ws_bridge', None) is not None:
                try:
                    await self._ws_bridge.subscribe(tickers)
                except Exception as _wse:
                    logger.debug("ws_bridge mid-session subscribe skipped: %s", _wse)

            # Parallel orderbook fetching with timeout and concurrency limit
            semaphore = asyncio.Semaphore(10)  # max 10 concurrent fetches

            async def fetch_orderbook_with_timeout(ticker: str):
                """Fetch orderbook for a single ticker with timeout and concurrency control."""
                async with semaphore:
                    try:
                        ob = await asyncio.wait_for(
                            client.get_orderbook(ticker),
                            timeout=0.5  # 500ms per market
                        )
                        if not ob:
                            return None
                        return (ticker, ob)
                    except asyncio.TimeoutError:
                        logger.debug(f"Orderbook timeout for {ticker}")
                        return None
                    except Exception as _te:
                        logger.debug(f"liquidity_sweep {ticker} skipped: {_te}")
                        return None

            # Fetch all orderbooks in parallel
            tasks = [fetch_orderbook_with_timeout(t) for t in tickers]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            alerts_total = 0
            for result in results:
                if result is None or isinstance(result, Exception):
                    continue
                ticker, ob = result
                try:
                    bid = float(ob.bids[0][0]) if ob.bids else 0.0
                    ask = float(ob.asks[0][0]) if ob.asks else 1.0
                    bid_sz = int(ob.bids[0][1]) if ob.bids else 0
                    ask_sz = int(ob.asks[0][1]) if ob.asks else 0
                    snap = OrderBookSnapshot(
                        market_id=ticker,
                        best_bid=bid,
                        best_ask=ask,
                        bid_size=bid_sz,
                        ask_size=ask_sz,
                        ts=now,
                    )
                    alerts = monitor.process(snap)
                    alerts_total += len(alerts)

                    # D2: Push mid-price into agent TrackedPositions so
                    # stop-loss price-invalidation rules see live prices
                    mid_cents = int(round((bid + ask) / 2 * 100))
                    if mid_cents > 0:
                        try:
                            from merid.prediction.agent_grid import get_agent_grid as _gg
                            for _agent in _gg().agents:
                                for _pos in _agent._tracked_positions.values():
                                    if _pos.ticker == ticker:
                                        _pos.current_price_cents = mid_cents
                        except Exception as _pe:
                            logger.debug("stop_loss price update skipped for %s: %s", ticker, _pe)
                except Exception as _pe:
                    logger.debug("orderbook processing failed for %s: %s", ticker, _pe)

            summary["actions"].append(
                f"liquidity_sweep:{len(tickers)}markets,{alerts_total}alerts"
            )
        except Exception as exc:
            logger.debug("_refresh_liquidity skipped: %s", exc)

    async def _run_arb_scan(self, now: float, summary: Dict):
        """Step 4: Scan for cross-venue arbitrage/dislocations."""
        scanner = self._scanner()
        store = self._signal_store()
        try:
            signals = scanner.scan(now)
            if not signals:
                signals = scanner.synthetic_scan(now)
            for sig in signals:
                store.store_arb_signal(sig.to_dict())
            # Validate existing plans
            scanner.validate_plans(now)
            self.metrics.arb_scans_run += 1
            summary["actions"].append(f"arb_scan:{len(signals)}signals")
        except Exception as e:
            logger.warning(f"Arb scan failed: {e}")

    async def _execute_plans(self, summary: Dict):
        """Step 5: Execute approved trade plans through the venue adapter.

        Every plan passes through the ExecutionGuard before submission.
        RiskContext further scales sizes based on system-level stress
        (CQI, drawdown, exposure).
        """
        guard = self._execution_guard()

        # Global kill switch short-circuit
        if guard.kill_switch_active:
            summary["actions"].append("execution:blocked_by_kill_switch")
            return

        # Hard reconciliation gate — refuse to execute if positions are out of sync
        try:
            from merid.reconciliation import has_critical_discrepancies
            if has_critical_discrepancies():
                logger.warning(
                    "Execution BLOCKED: critical reconciliation discrepancies detected. "
                    "Resolve with force_align_from_venue() or fix positions manually."
                )
                summary["actions"].append("execution:blocked_by_reconciliation")
                return
        except ImportError:
            pass

        # Build risk context once per tick for system-level sizing
        try:
            risk_ctx = self._risk_context()
        except Exception as _rctx_exc:
            logger.debug("_risk_context unavailable (using None): %s", _rctx_exc)
            risk_ctx = None

        coordinator = self._consensus_coordinator()
        _active_plans = getattr(coordinator, '_active_plans', {})
        plans = list(_active_plans.values())
        approved = [p for p in plans if p.status == "approved" and not p.is_expired()]

        for plan in approved:
            domain = getattr(plan, "domain", "crypto")
            if isinstance(domain, str):
                pass
            else:
                domain = getattr(domain, "value", "crypto")

            size_usd = getattr(plan, "approved_size_usd", None) or plan.target_size_usd

            # Apply RiskContext size scaling before guard check
            if risk_ctx is not None and risk_ctx.size_scale_factor < 1.0:
                size_usd = size_usd * risk_ctx.size_scale_factor
                if size_usd <= 0:
                    summary["actions"].append(
                        f"blocked:{plan.symbol}:risk_context_scale=0"
                    )
                    continue

            # Pre-trade safety check
            verdict = guard.pre_trade_check(
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                domain=domain,
                size_usd=size_usd,
                direction=plan.direction,
            )

            if not verdict.allowed:
                summary["actions"].append(f"blocked:{plan.symbol}:{verdict.reason}")
                continue

            try:
                # Use guard-adjusted size
                plan.approved_size_usd = verdict.adjusted_size_usd
                result = await self._execute_single_plan(plan)
                if result:
                    guard.record_execution(domain, verdict.adjusted_size_usd)
                    self.metrics.plans_executed += 1
                    summary["actions"].append(
                        f"executed:{plan.symbol}:{plan.direction}"
                        f":${verdict.adjusted_size_usd:.0f}"
                        f"(throttle={verdict.throttle_pct:.0%})"
                    )
            except Exception as e:
                logger.error(f"Plan execution failed {plan.plan_id}: {e}")
                summary["actions"].append(f"plan_failed:{plan.plan_id}:{plan.symbol}:{e}")

    async def _execute_single_plan(self, plan) -> Optional[Dict]:
        """Bridge a TradePlan to a TradeRequest and submit to the adapter.

        For domains with an active matching engine (e.g. prediction in paper
        mode), orders are routed internally instead of to an external venue.
        """
        domain = getattr(plan, "domain", "crypto")
        if isinstance(domain, str):
            plan_domain = domain
        else:
            plan_domain = getattr(domain, "value", "crypto")

        # Route to internal matching engine if available for this domain
        engine = self._matching_engines.get(plan_domain)
        if engine and engine.enabled:
            return await self._execute_via_matching_engine(plan, engine)

        # Otherwise route to external venue adapter
        from trading.adapters.base import TradeRequest, TradeSide, OrderType
        from trading.adapters.registry import get_adapter
        from trading.trade_mode import is_paper_or_mock

        venue = plan.venue or "alpaca"
        adapter = get_adapter(venue)
        if not adapter:
            logger.warning(f"No adapter for venue {venue}")
            return None

        side = TradeSide.BUY if plan.direction in ("long", "buy") else TradeSide.SELL
        qty = plan.approved_size_usd or plan.target_size_usd

        request = TradeRequest(
            venue=venue,
            symbol=plan.symbol,
            side=side,
            quantity=qty,
            order_type=OrderType.MARKET,
            notional_usd=qty,
            client_reference=plan.plan_id,
            live=not is_paper_or_mock(),
        )

        result = await asyncio.get_running_loop().run_in_executor(
            None, adapter.submit_order, request
        )
        if result is None:
            logger.warning("adapter.submit_order returned None for plan %s", plan.plan_id)
            return None
        plan.status = "executed"
        return {"order_id": result.venue_order_id, "status": result.status}

    async def _execute_via_matching_engine(self, plan, engine) -> Optional[Dict]:
        """Execute a plan through the internal matching engine (paper mode)."""
        from merid.matching_engine import Order, OrderSide

        side = OrderSide.BUY if plan.direction in ("long", "buy") else OrderSide.SELL
        notional = plan.approved_size_usd or plan.target_size_usd

        order = Order(
            instrument_id=plan.symbol,
            side=side,
            notional_usd=notional,
            domain=engine.domain,
            agent_id=getattr(plan, "agent_id", ""),
            plan_id=plan.plan_id,
        )

        fill = await asyncio.get_running_loop().run_in_executor(
            None, engine.submit_order, order
        )

        if order.status.value == "filled":
            plan.status = "executed"
            return {
                "order_id": order.order_id,
                "fill_id": fill.fill_id,
                "price": fill.price,
                "quantity": fill.quantity,
                "notional_usd": fill.notional_usd,
                "engine": "internal_matching",
                "status": "filled",
            }
        else:
            logger.warning(
                f"Matching engine rejected {order.order_id}: {order.status.value}"
            )
            return None

    async def _update_cqi(self, now: float, summary: Dict):
        """Step 6: Update drift metrics and CQI per domain.

        Also feeds CQI scores into the ExecutionGuard for throttling.
        """
        detector = self._drift_detector()
        store = self._signal_store()
        guard = self._execution_guard()
        cqi_scores: Dict[str, float] = {}
        for domain in self.config.active_domains:
            try:
                cqi = detector.compute_cqi(domain, now=now)
                store.store_cqi(cqi.to_dict())
                score = cqi.score if hasattr(cqi, 'score') else cqi.get('score', 0.5) if isinstance(cqi, dict) else 0.5
                guard.update_cqi(domain, score)
                cqi_scores[domain] = score
            except Exception as e:
                logger.warning(f"CQI update failed for {domain}: {e}")
        self.metrics.cqi_updates += 1
        summary["actions"].append(f"cqi_updated:{len(self.config.active_domains)}domains")
        summary["cqi_scores"] = cqi_scores

    def _sync_promotion(self, summary: Dict):
        """Step 6b: Sync promotion report into the ExecutionGuard.

        Reads the cached promotion report and updates the guard's view
        of which domains/agents are eligible.  Runs every 5 minutes.
        """
        guard = self._execution_guard()
        try:
            guard.sync_promotion_report()
            n_eligible = len(getattr(guard, '_promotion_eligible_domains', None) or set())
            n_blocked = len(getattr(guard, '_promotion_blocked_agents', None) or set())
            summary["actions"].append(
                f"promotion_synced:{n_eligible}eligible,{n_blocked}blocked_agents"
            )
            summary["promotion_sync"] = {
                "eligible_domains": n_eligible,
                "blocked_agents": n_blocked,
                "report_ts": getattr(guard, '_promotion_report_ts', None),
            }
        except Exception as e:
            logger.warning(f"Promotion sync failed: {e}")
            summary["actions"].append(f"promotion_sync:error:{e}")

    async def _refresh_betting_odds(self, now: float, summary: Dict):
        """Step 7a: Refresh sports betting odds and rebuild consensus."""
        try:
            client = self._betting_odds_client()
            store = self._betting_store()

            events = await asyncio.get_running_loop().run_in_executor(
                None, client.fetch_events
            )
            for event in events:
                store.upsert_event(event)

            odds = await asyncio.get_running_loop().run_in_executor(
                None, client.fetch_all_odds
            )
            for event, snapshot in odds:
                store.store_odds_snapshot(snapshot)

            # Rebuild consensus for all events with fresh odds
            consensus_list = store.build_all_consensus()
            summary["actions"].append(
                f"betting_refreshed:{len(events)}events,{len(odds)}odds,{len(consensus_list)}consensus"
            )
        except ImportError:
            pass  # betting module not installed

    async def _reconcile_positions(self, summary: Dict):
        """Step 7: Compare internal vs venue positions.
        
        For domains with venue reconcilers, run deep comparison and gate
        execution if critical issues are detected.
        """
        try:
            # Run Kalshi reconciliation if prediction domain is active
            if "prediction" in self.config.active_domains:
                from merid.reconciliation import reconcile_venue, has_critical_discrepancies
                
                # Reconcile Kalshi positions
                discrepancies = reconcile_venue("kalshi")
                
                critical_count = sum(1 for d in discrepancies if d.severity == "critical")
                warning_count = sum(1 for d in discrepancies if d.severity == "warning")
                
                logger.info(
                    f"Kalshi reconciliation complete: "
                    f"{len(discrepancies)} discrepancies ({critical_count} critical, {warning_count} warnings)"
                )
                
                summary["actions"].append(
                    f"kalshi_reconciliation:{len(discrepancies)}total,{critical_count}critical"
                )
                
                # Gate execution if critical issues detected
                if has_critical_discrepancies():
                    logger.error(
                        f"CRITICAL reconciliation issues detected for Kalshi. "
                        f"Blocking new executions until resolved."
                    )
                    # Execution will be blocked by the check in _execute_plans
                    guard = self._execution_guard()
                    if guard:
                        reason = f"{critical_count} critical discrepancies detected"
                        try:
                            guard.activate_domain_kill_switch("prediction", reason=reason)
                        except Exception as _ks_exc:
                            logger.debug("activate_domain_kill_switch failed: %s", _ks_exc)

                    summary["actions"].append(f"reconciliation:CRITICAL:blocked_prediction_domain")
                elif warning_count > 0:
                    logger.warning(f"Reconciliation warnings for Kalshi: {warning_count} issues")
                    summary["actions"].append(f"reconciliation:WARNING:{warning_count}issues")
                else:
                    summary["actions"].append("reconciliation:OK")

                # Store summary for API exposure
                summary["reconciliation"] = {
                    "kalshi": {
                        "total": len(discrepancies),
                        "critical": critical_count,
                        "warnings": warning_count,
                    }
                }

                self.metrics.reconciliations_run += 1
            else:
                summary["actions"].append("reconciliation:skipped")
                
        except Exception as exc:
            logger.error(f"Reconciliation failed: {exc}")
            summary["actions"].append(f"reconciliation:failed:{exc}")

    async def _sync_order_groups(self, summary: Dict):
        """Step 7b: Sync order group lifecycle state for Kalshi.
        
        Ensures order groups are tracked, validates active groups,
        and records fills for accurate utilization metrics.
        """
        try:
            og_lifecycle = self._order_group_lifecycle()
            
            # Start lifecycle manager if not running
            if not getattr(og_lifecycle, '_running', False):
                await og_lifecycle.start()
                summary["actions"].append("order_groups:lifecycle_started")
            
            # Get current state summary
            state = og_lifecycle.get_lifecycle_state()
            
            # Add order group metrics to summary
            summary["order_groups"] = {
                "total_tracked": state.get("total_groups", 0),
                "active": state.get("active_groups", 0),
                "triggered_groups": len(state.get("triggered_groups", [])),
                "recent_errors": len(state.get("recent_errors", [])),
            }
            
            # Log status if there are triggered groups
            triggered = state.get("triggered_groups", [])
            if triggered:
                logger.warning(f"Order groups triggered: {triggered}")
                summary["actions"].append(f"order_groups:triggered:{len(triggered)}")
            else:
                summary["actions"].append("order_groups:synced")
                
        except Exception as exc:
            logger.warning(f"Order group sync failed: {exc}")
            summary["actions"].append(f"order_groups:sync_failed:{exc}")

    # ── Subscriber pattern ────────────────────────────────────────────

    def subscribe(self, callback: Callable):
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable):
        self._subscribers.discard(callback)

    async def _notify(self, event_type: str, data: Any):
        for cb in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(event_type, data)
                else:
                    cb(event_type, data)
            except Exception as e:
                logger.warning(f"Subscriber notification failed: {e}")

    # ── Run forever ───────────────────────────────────────────────────

    async def run(self, max_ticks: Optional[int] = None):
        """Run the loop continuously until stopped or max_ticks reached."""
        self._running = True
        tick_count = 0
        min_interval = min(
            self.config.feature_refresh_interval,
            self.config.consensus_interval,
            self.config.arb_scan_interval,
        )
        # Run at least every 5s, at most every min_interval
        sleep_time = max(1.0, min(5.0, min_interval))

        # Log full domain coverage
        mode_str = ", ".join(
            f"{d}={self.config.domain_modes.get(d, 'paper')}"
            for d in self.config.active_domains
        ) if self.config.domain_modes else ", ".join(self.config.active_domains)
        recon_str = f", reconciliation_venues={self.config.reconciliation_venues}" if self.config.reconciliation_venues else ""
        logger.info(
            f"MERID loop starting: domains=[{mode_str}], "
            f"symbols={len(self.config.active_symbols)} active, "
            f"execution={'ON' if self.config.enable_execution else 'OFF'}, "
            f"cadence={sleep_time:.1f}s{recon_str}"
        )
        logger.info(f"  Active symbols: {self.config.active_symbols}")

        from merid.tick_log import build_tick_record, get_tick_log
        tick_log = get_tick_log()

        # Start HashtagMonitor for real-time hashtag + news sentiment ingestion
        self._hashtag_monitor = None
        try:
            from merid.sentiment.hashtag_monitor import get_hashtag_monitor
            self._hashtag_monitor = get_hashtag_monitor()
            await self._hashtag_monitor.start()
            logger.info("HashtagMonitor started alongside loop")
        except Exception as _hme:
            logger.warning("HashtagMonitor start skipped: %s", _hme)
            self._hashtag_monitor = None

        # Start Kalshi WebSocket bridge for push-based market updates
        self._ws_bridge = None
        if "prediction" in self.config.active_domains:
            try:
                from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
                self._ws_bridge = KalshiWebSocketBridge()
                # Collect initial tickers from agent grid (best-effort)
                _ws_tickers: List[str] = []
                try:
                    from merid.prediction.agent_grid import get_agent_grid as _wsg
                    for _a in _wsg().agents:
                        _ws_tickers.extend(_a.state.active_tickers)
                    _ws_tickers = list(dict.fromkeys(_ws_tickers))[:50]
                except Exception as _wste:
                    logger.debug("ws_bridge ticker collection skipped: %s", _wste)
                await self._ws_bridge.start(tickers=_ws_tickers or None)
                logger.info(
                    "KalshiWebSocketBridge started alongside loop (%d tickers)",
                    len(_ws_tickers),
                )
            except Exception as _wse:
                logger.warning("KalshiWebSocketBridge start skipped: %s", _wse)
                self._ws_bridge = None

        while self._running:
            summary = await self.tick()
            tick_count += 1

            # Persist structured tick record
            try:
                record = build_tick_record(summary)
                record.kill_switch_active = self._execution_guard().kill_switch_active
                tick_log.append(record)
            except Exception as e:
                logger.warning(f"Tick log write failed: {e}")

            if max_ticks and tick_count >= max_ticks:
                logger.info(f"Reached max_ticks={max_ticks}, stopping")
                self._running = False
                break

            await asyncio.sleep(sleep_time)

        self._running = False
        logger.info(f"MERID loop stopped after {tick_count} ticks")

        # Stop WebSocket bridge on loop exit
        if getattr(self, "_hashtag_monitor", None) is not None:
            try:
                await self._hashtag_monitor.stop()
                logger.info("HashtagMonitor stopped")
            except Exception as _hme:
                logger.debug("HashtagMonitor stop error: %s", _hme)
            self._hashtag_monitor = None

        if self._ws_bridge is not None:
            try:
                await self._ws_bridge.stop()
                logger.info("KalshiWebSocketBridge stopped")
            except Exception as _wse:
                logger.debug("KalshiWebSocketBridge stop error: %s", _wse)
            self._ws_bridge = None

    def stop(self):
        """Signal the loop to stop after the current tick."""
        self._running = False

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "config": {
                "active_domains": self.config.active_domains,
                "domain_modes": self.config.domain_modes,
                "active_symbols": self.config.active_symbols,
                "execution_enabled": self.config.enable_execution,
                "reconciliation_venues": self.config.reconciliation_venues,
            },
            "metrics": self.metrics.to_dict(),
        }


# ── Singleton ─────────────────────────────────────────────────────────

_loop: Optional[MeridLoop] = None


def get_merid_loop() -> MeridLoop:
    global _loop
    if _loop is None:
        try:
            config = LoopConfig.from_paper_config()
        except Exception as _cfg_exc:
            logger.warning(f"LoopConfig.from_paper_config() failed, using defaults: {_cfg_exc}")
            config = LoopConfig()
        _loop = MeridLoop(config)
    return _loop


# ── CLI entrypoint ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Default: load from paper_config matrix (single source of truth)
    if "--legacy" in sys.argv:
        config = LoopConfig()
    else:
        config = LoopConfig.from_paper_config()

    if "--execute" in sys.argv:
        config.enable_execution = True
        logger.info("Execution ENABLED — trades will be submitted to venues")

    if "--domains" in sys.argv:
        idx = sys.argv.index("--domains") + 1
        if idx < len(sys.argv):
            requested = sys.argv[idx].split(",")
            config.active_domains = [d for d in config.active_domains if d in requested]
            config.domain_modes = {k: v for k, v in config.domain_modes.items() if k in requested}

    if "--symbols" in sys.argv:
        idx = sys.argv.index("--symbols") + 1
        if idx < len(sys.argv):
            config.active_symbols = sys.argv[idx].split(",")

    loop = MeridLoop(config)

    try:
        asyncio.run(loop.run())
    except KeyboardInterrupt:
        logger.info("MERID loop interrupted")
        loop.stop()
