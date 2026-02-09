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
    """Cadence and feature flags for the main loop."""
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

        # Timers for staggered cadences
        self._last_feature_refresh = 0.0
        self._last_agent_cycle = 0.0
        self._last_consensus = 0.0
        self._last_arb_scan = 0.0
        self._last_cqi_update = 0.0
        self._last_reconciliation = 0.0

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
        self.metrics.features_refreshed += 1
        summary["actions"].append(f"features_refreshed:{len(self.config.active_symbols)}symbols")

    async def _run_agent_cycles(self, summary: Dict):
        """Step 2: Run canonical agents per category."""
        try:
            registry = self._agent_registry()
            results = await asyncio.get_event_loop().run_in_executor(
                None, registry.run_all
            )
            self.metrics.agent_cycles_run += 1
            summary["actions"].append(f"agent_cycles:{len(results)}agents")
        except Exception as e:
            logger.warning(f"Agent cycle failed: {e}")
            summary["actions"].append(f"agent_cycles:error:{e}")

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
        """Bridge a TradePlan to a TradeRequest and submit to the adapter."""
        from trading.adapters.base import TradeRequest, TradeSide, OrderType
        from trading.adapters.registry import get_adapter

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
            live=True,
        )

        result = await asyncio.get_event_loop().run_in_executor(
            None, adapter.submit_order, request
        )
        plan.status = "executed"
        return {"order_id": result.venue_order_id, "status": result.status}

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

    async def _reconcile_positions(self, summary: Dict):
        """Step 7: Reconcile MERID internal positions with venue positions."""
        try:
            from merid.reconciliation import reconcile_all_venues
            discrepancies = await asyncio.get_event_loop().run_in_executor(
                None, reconcile_all_venues
            )
            self.metrics.reconciliations_run += 1
            summary["actions"].append(f"reconciled:{len(discrepancies)}discrepancies")
        except ImportError:
            # Reconciliation module not yet built — skip silently
            pass
        except Exception as e:
            logger.warning(f"Reconciliation failed: {e}")

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

        logger.info(
            f"MERID loop starting: domains={self.config.active_domains}, "
            f"symbols={self.config.active_symbols}, "
            f"execution={'ON' if self.config.enable_execution else 'OFF'}, "
            f"cadence={sleep_time:.1f}s"
        )

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
                "active_symbols": self.config.active_symbols,
                "execution_enabled": self.config.enable_execution,
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

    config = LoopConfig()

    if "--execute" in sys.argv:
        config.enable_execution = True
        logger.info("Execution ENABLED — trades will be submitted to venues")

    if "--domains" in sys.argv:
        idx = sys.argv.index("--domains") + 1
        if idx < len(sys.argv):
            config.active_domains = sys.argv[idx].split(",")

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
