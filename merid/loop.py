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

    # ── Core tick ─────────────────────────────────────────────────────

    async def tick(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Run one full cycle of the swarm loop.

        Returns a summary dict of what happened this tick.
        """
        now = now or time.time()
        start = time.perf_counter()
        summary: Dict[str, Any] = {"tick": self.metrics.total_ticks + 1, "actions": []}

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

            # Step 8: Notify subscribers
            await self._notify("tick_complete", summary)

        except Exception as e:
            self.metrics.total_errors += 1
            self.metrics.last_error = str(e)
            logger.error(f"Loop tick error: {e}\n{traceback.format_exc()}")
            summary["error"] = str(e)

        elapsed_ms = (time.perf_counter() - start) * 1000
        self.metrics.total_ticks += 1
        self.metrics.last_tick_at = now
        self.metrics.last_tick_duration_ms = elapsed_ms
        summary["duration_ms"] = round(elapsed_ms, 1)

        return summary

    # ── Step implementations ──────────────────────────────────────────

    async def _refresh_features(self, now: float, summary: Dict):
        """Step 1: Refresh decay-aware features for active symbols.

        First tries live API feeds (Finnhub, FRED, CoinGecko).
        Then reads aggregated features through the feature service.
        For prediction domain: generates Kalshi-specific signals.
        """
        # Try live data first
        try:
            from merid.signals.live_feeds import get_live_feed_manager
            mgr = get_live_feed_manager()
            await mgr.refresh_all(self.config.active_symbols, now)
        except Exception as e:
            logger.warning(f"Live feed refresh failed (using cached/synthetic): {e}")

        # Now read features (live-ingested or synthetic fallback)
        svc = self._feature_service()
        store = self._signal_store()
        for symbol in self.config.active_symbols:
            try:
                news = svc.get_news_features(symbol, now=now)
                social = svc.get_social_features(symbol, now=now)
                chain = "solana" if symbol in ("SOL", "BONK", "WIF") else "ethereum"
                onchain = svc.get_onchain_features(chain, symbol, now=now)
                for fs in [news, social, onchain]:
                    store.store_feature_snapshot(fs.to_dict())
            except Exception as e:
                logger.warning(f"Feature refresh failed for {symbol}: {e}")
        macro = svc.get_macro_features(now=now)
        store.store_feature_snapshot(macro.to_dict())
        
        # Generate Kalshi signals if prediction domain is active
        if "prediction" in self.config.active_domains:
            await self._refresh_kalshi_signals(now, summary, store)
        
        self.metrics.features_refreshed += 1
        summary["actions"].append(f"features_refreshed:{len(self.config.active_symbols)}symbols")

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
            if not grid._running:
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
            
            # Future: Submit signals to consensus
            # adapter = get_kalshi_consensus_adapter()
            # for signal, market in collected_signals:
            #     energy = adapter.signal_to_energy(signal, market, agent.config.agent_id)
            #     vote_result = await core_orchestrator.run_cycle(energy)
            
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

    async def _run_consensus(self, summary: Dict):
        """Step 3: Run consensus for active symbols (decay-aware)."""
        coordinator = self._consensus_coordinator()
        # Consensus is triggered by opinion submission, but we can
        # also force a cycle for symbols with pending opinions
        self.metrics.consensus_cycles_run += 1
        summary["actions"].append("consensus_check")

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
        except Exception:
            risk_ctx = None

        coordinator = self._consensus_coordinator()
        plans = list(coordinator._active_plans.values())
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

        result = await asyncio.get_event_loop().run_in_executor(
            None, adapter.submit_order, request
        )
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

        fill = await asyncio.get_event_loop().run_in_executor(
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
            n_eligible = len(guard._promotion_eligible_domains or set())
            n_blocked = len(guard._promotion_blocked_agents or set())
            summary["actions"].append(
                f"promotion_synced:{n_eligible}eligible,{n_blocked}blocked_agents"
            )
            summary["promotion_sync"] = {
                "eligible_domains": n_eligible,
                "blocked_agents": n_blocked,
                "report_ts": guard._promotion_report_ts,
            }
        except Exception as e:
            logger.warning(f"Promotion sync failed: {e}")
            summary["actions"].append(f"promotion_sync:error:{e}")

    async def _refresh_betting_odds(self, now: float, summary: Dict):
        """Step 7a: Refresh sports betting odds and rebuild consensus."""
        try:
            client = self._betting_odds_client()
            store = self._betting_store()

            events = await asyncio.get_event_loop().run_in_executor(
                None, client.fetch_events
            )
            for event in events:
                store.upsert_event(event)

            odds = await asyncio.get_event_loop().run_in_executor(
                None, client.fetch_all_odds
            )
            for snapshot in odds:
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
                            guard.block_domain("prediction", reason=reason)
                        except Exception:
                            pass

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
        _loop = MeridLoop()
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
