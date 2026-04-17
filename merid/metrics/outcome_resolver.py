"""Outcome Resolver — Periodic job to resolve expired Kalshi contracts.

Connects the calibration store and realized edge store to actual Kalshi
settlement outcomes.  Runs as a periodic task (or end-of-day pass):

1. Find all unresolved market IDs from both stores.
2. For each, check if the Kalshi contract has settled.
3. If settled, read the outcome (YES=1, NO=0) and resolve both stores.

Usage::

    resolver = get_outcome_resolver()
    resolved = await resolver.resolve_all()
    >>> print(f"Resolved {resolved} markets")

    # Or run as a periodic background task:
    await resolver.start(interval_s=300)
    ...
    await resolver.stop()
"""

from __future__ import annotations

import threading
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.metrics.outcome_resolver")


@dataclass
class ResolutionResult:
    """Result of a single market resolution attempt."""
    market_id: str
    resolved: bool
    outcome: Optional[int] = None
    forecasts_resolved: int = 0
    trades_resolved: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "resolved": self.resolved,
            "outcome": self.outcome,
            "forecasts_resolved": self.forecasts_resolved,
            "trades_resolved": self.trades_resolved,
            "error": self.error,
        }


@dataclass
class ResolverStats:
    """Cumulative resolver statistics."""
    runs: int = 0
    markets_checked: int = 0
    markets_resolved: int = 0
    markets_pending: int = 0
    markets_errored: int = 0
    forecasts_resolved: int = 0
    trades_resolved: int = 0
    last_run_at: float = 0.0
    last_run_duration_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runs": self.runs,
            "markets_checked": self.markets_checked,
            "markets_resolved": self.markets_resolved,
            "markets_pending": self.markets_pending,
            "markets_errored": self.markets_errored,
            "forecasts_resolved": self.forecasts_resolved,
            "trades_resolved": self.trades_resolved,
            "last_run_at": self.last_run_at,
            "last_run_duration_s": round(self.last_run_duration_s, 2),
        }


class OutcomeResolver:
    """Resolves expired Kalshi contracts against calibration and edge stores.

    Uses the KalshiVenueClient to check settlement status.  Falls back to
    a stub resolver for paper/sim modes.
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._stats = ResolverStats()
        self._client = None
        self._calibration_store = None
        self._edge_store = None
        self._brier_tracker = None

    def _ensure_stores(self) -> None:
        """Lazy-load stores to avoid circular imports."""
        if self._calibration_store is None:
            from merid.metrics.calibration import get_calibration_store
            self._calibration_store = get_calibration_store()
        if self._edge_store is None:
            from merid.metrics.realized_edge import get_realized_edge_store
            self._edge_store = get_realized_edge_store()
        if self._brier_tracker is None:
            try:
                from monitoring.brier_metrics import get_brier_tracker
                self._brier_tracker = get_brier_tracker()
            except Exception:
                self._brier_tracker = None

    def _ensure_client(self) -> bool:
        """Try to get a Kalshi client.  Returns False if unavailable."""
        if self._client is not None:
            return True
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            self._client = get_kalshi_client()
            return self._client is not None
        except (ImportError, Exception):
            return False

    # ── Core resolution ──────────────────────────────────────────────────

    async def resolve_all(self) -> List[ResolutionResult]:
        """Check all unresolved markets and resolve any that have settled.

        Returns list of ResolutionResult for each market checked.
        """
        self._ensure_stores()
        start = time.time()
        self._stats.runs += 1

        # Collect all unresolved market IDs from both stores
        cal_markets = set(self._calibration_store.get_unresolved_markets())
        edge_markets = set(self._edge_store.get_unresolved_markets())
        all_markets = cal_markets | edge_markets

        if not all_markets:
            self._stats.last_run_at = start
            self._stats.last_run_duration_s = time.time() - start
            return []

        self._stats.markets_checked += len(all_markets)
        results: List[ResolutionResult] = []

        for market_id in all_markets:
            result = await self._resolve_market(market_id)
            results.append(result)

            if result.resolved:
                self._stats.markets_resolved += 1
                self._stats.forecasts_resolved += result.forecasts_resolved
                self._stats.trades_resolved += result.trades_resolved
            elif result.error:
                self._stats.markets_errored += 1
            else:
                self._stats.markets_pending += 1

        self._stats.last_run_at = start
        self._stats.last_run_duration_s = time.time() - start

        resolved_count = sum(1 for r in results if r.resolved)
        if resolved_count > 0:
            logger.info(
                f"Outcome resolver: {resolved_count}/{len(all_markets)} markets resolved, "
                f"{sum(r.forecasts_resolved for r in results)} forecasts, "
                f"{sum(r.trades_resolved for r in results)} trades"
            )

        return results

    async def _resolve_market(self, market_id: str) -> ResolutionResult:
        """Attempt to resolve a single market."""
        outcome = await self._get_outcome(market_id)

        if outcome is None:
            return ResolutionResult(market_id=market_id, resolved=False)

        try:
            forecasts_resolved = self._calibration_store.resolve_outcome(
                market_id, outcome
            )
            trades_resolved = self._edge_store.resolve_market(
                market_id, outcome
            )

            # BUG-03 fix: keep BrierMetricsTracker in sync with CalibrationStore
            # so the monitoring dashboard reflects the same rankings that drive
            # consensus vote weighting.
            if self._brier_tracker is not None:
                try:
                    forecasts = self._calibration_store.get_forecasts_for_market(market_id)
                    for fc in forecasts:
                        if not fc.resolved:
                            continue
                        pred_id = f"{fc.forecaster_id}:{fc.market_id}:{fc.timestamp}"
                        if pred_id not in self._brier_tracker._predictions:
                            from monitoring.brier_metrics import PredictionSource
                            self._brier_tracker.record_prediction(
                                prediction_id=pred_id,
                                source=PredictionSource.AGENT,
                                source_id=fc.forecaster_id,
                                question=market_id,
                                forecast=fc.p_model,
                            )
                        self._brier_tracker.resolve_prediction(pred_id, outcome)
                except Exception as _bt_exc:
                    logger.debug("BrierMetricsTracker sync skipped for %s: %s", market_id, _bt_exc)

            # BUG-02 fix: settle any open paper trades with the real binary outcome
            self._settle_paper_trades(market_id, outcome)

            # BUG-04 fix: propagate realized PnL to CT bankroll (KalshiRiskEngine).
            # The edge store now holds realized_pnl_cents for each resolved trade.
            # Feed those into record_trade_result() so win_rate, total_pnl_cents,
            # and the bankroll invariant check reflect true settlement outcomes.
            self._notify_bankroll_of_settlement(market_id)

            return ResolutionResult(
                market_id=market_id,
                resolved=True,
                outcome=outcome,
                forecasts_resolved=forecasts_resolved,
                trades_resolved=trades_resolved,
            )
        except Exception as exc:
            logger.warning(f"Error resolving market {market_id}: {exc}")
            return ResolutionResult(
                market_id=market_id,
                resolved=False,
                error=str(exc),
            )

    def _settle_paper_trades(self, market_id: str, outcome: int) -> None:
        """Propagate a real settlement outcome to PaperSession open trades."""
        try:
            from merid.prediction.paper_session import get_paper_session
            session = get_paper_session()
            if session.is_active:
                results = session.record_settlement(market_id, outcome)
                if results:
                    logger.info(
                        "paper_session: settled %d trade(s) for %s outcome=%d",
                        len(results), market_id, outcome,
                    )
        except Exception as exc:
            logger.debug("paper_session settlement skipped for %s: %s", market_id, exc)

    def _notify_bankroll_of_settlement(self, market_id: str) -> None:
        """Feed realized PnL for a settled market into bankroll trackers.

        Updates both:
        1. CT Bankroll (KalshiRiskEngine) - if CT is running
        2. AgentPerformanceTracker - canonical source for agent PnL

        After the edge store resolves trades for market_id, each TradeEdgeRecord
        has a populated realized_pnl_cents. We call record_trade_result() once
        per resolved trade so bankroll managers have accurate win_rate,
        total_pnl_cents, and total_trades statistics.
        """
        self._ensure_stores()
        trades = self._edge_store.get_trades_for_market(market_id)
        resolved_trades = [t for t in trades if t.resolved and t.realized_pnl_cents is not None]
        if not resolved_trades:
            return

        total_pnl = sum(t.realized_pnl_cents for t in resolved_trades)

        # --- Update CT Bankroll (best-effort, CT may not be running) ---
        ct_updated = False
        try:
            from merid.trading.kalshi_continuous_trader import get_continuous_trader
            ct = get_continuous_trader()
            engine = getattr(ct, "bankroll", None)
            if engine is not None:
                for trade in resolved_trades:
                    engine.record_trade_result(trade.realized_pnl_cents)
                ct_updated = True
                logger.info(
                    "bankroll_settlement: CT bankroll updated market=%s trades=%d pnl=%+d¢",
                    market_id, len(resolved_trades), total_pnl,
                )
            else:
                logger.debug("bankroll_settlement: CT bankroll not available for %s", market_id)
        except ImportError:
            logger.debug("bankroll_settlement: CT module not available")
        except Exception as exc:
            logger.warning("bankroll_settlement: CT update failed for %s: %s", market_id, exc)

        # --- Update AgentPerformanceTracker (canonical, always required) ---
        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            apt = get_agent_performance_tracker()

            for trade in resolved_trades:
                # APT record_outcome computes PnL from settlement price
                # Use settlement price derived from realized_pnl
                # YES wins -> 100c, NO wins -> 0c
                settled_yes = trade.realized_pnl_cents > 0 if trade.side == "yes" else trade.realized_pnl_cents < 0
                settlement_cents = 100 if settled_yes else 0

                apt.record_outcome(
                    market_id=market_id,
                    settled_yes=settled_yes,
                    settlement_price_cents=settlement_cents,
                )
            logger.info(
                "apt_settlement: market=%s trades=%d pnl=%+d¢",
                market_id, len(resolved_trades), total_pnl,
            )
        except Exception as exc:
            logger.warning("apt_settlement: failed for %s: %s", market_id, exc)

    async def _get_outcome(self, market_id: str) -> Optional[int]:
        """Get the settlement outcome for a market from Kalshi.

        Returns 1 if YES won, 0 if NO won, None if not yet settled.
        """
        # Try the live Kalshi client first
        if self._ensure_client():
            try:
                return await self._get_outcome_from_kalshi(market_id)
            except Exception as exc:
                logger.debug(f"Kalshi outcome fetch failed for {market_id}: {exc}")

        # Fallback: try the market catalog for cached settlement data
        try:
            return self._get_outcome_from_catalog(market_id)
        except Exception as _cat_exc:
            logger.debug("Catalog outcome lookup failed for %s: %s", market_id, _cat_exc)

        return None

    async def _get_outcome_from_kalshi(self, market_id: str) -> Optional[int]:
        """Fetch settlement outcome from the Kalshi REST API."""
        client = self._client
        if client is None:
            return None

        # Skip API call if circuit breaker is open
        if getattr(client, "is_circuit_open", False):
            return None

        try:
            await client.connect()
            # Use the client's get_market method to check settlement
            result = await client.get_market_result(market_id)
            if not result.success or result.data is None:
                return None

            market_data = result.data
            raw = market_data.raw_data or {}

            # Kalshi markets have a 'result' field when settled.
            # Normalize to lowercase to handle API casing variations
            # (e.g. "YES", "yes", "No", "NO" are all valid).
            settlement = (raw.get("result") or "").strip().lower()
            if settlement == "yes":
                return 1
            elif settlement == "no":
                return 0

            # Check settlement status to determine if we should wait or warn.
            status = (raw.get("status") or "").strip().lower()
            if status not in ("settled", "finalized", "closed"):
                return None  # Not yet settled — check again next cycle

            # Status indicates settled but result field is missing or unrecognized.
            # Log a WARNING so operators can investigate; return None to retry.
            if status in ("settled", "finalized"):
                logger.warning(
                    "Market %s has status=%r but unrecognized result=%r "
                    "— cannot resolve outcome; will retry next cycle",
                    market_id, status, raw.get("result"),
                )
            return None
        except Exception as exc:
            logger.debug(f"Kalshi API error for {market_id}: {exc}")
            return None

    def _get_outcome_from_catalog(self, market_id: str) -> Optional[int]:
        """Try to get outcome from the cached market catalog."""
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            cm = catalog.get_market(market_id)
            if cm is None:
                return None

            raw = cm.market.raw_data or {}
            settlement = raw.get("result")
            if settlement is not None:
                settlement = str(settlement).strip().lower()
            if settlement == "yes":
                return 1
            elif settlement == "no":
                return 0
            return None
        except Exception:
            return None

    # ── Manual resolution (for paper/sim modes) ─────────────────────────

    def resolve_manual(self, market_id: str, outcome: int) -> ResolutionResult:
        """Manually resolve a market (useful for paper trading and tests).

        Args:
            market_id: Kalshi market ticker.
            outcome: 1 for YES, 0 for NO.

        Returns:
            ResolutionResult.
        """
        self._ensure_stores()

        if outcome not in (0, 1):
            return ResolutionResult(
                market_id=market_id,
                resolved=False,
                error=f"Invalid outcome: {outcome}",
            )

        try:
            forecasts_resolved = self._calibration_store.resolve_outcome(
                market_id, outcome
            )
            trades_resolved = self._edge_store.resolve_market(
                market_id, outcome
            )

            # BUG-02 fix: settle open paper trades with the real binary outcome
            self._settle_paper_trades(market_id, outcome)

            # BUG-04 fix: propagate realized PnL to CT bankroll
            self._notify_bankroll_of_settlement(market_id)

            return ResolutionResult(
                market_id=market_id,
                resolved=True,
                outcome=outcome,
                forecasts_resolved=forecasts_resolved,
                trades_resolved=trades_resolved,
            )
        except Exception as exc:
            return ResolutionResult(
                market_id=market_id,
                resolved=False,
                error=str(exc),
            )

    # ── Background task ──────────────────────────────────────────────────

    async def start(self, interval_s: float = 300.0) -> None:
        """Start periodic resolution loop."""
        if self._task and not self._task.done():
            return
        self._shutdown.clear()
        self._task = asyncio.create_task(
            self._run_loop(interval_s),
            name="outcome-resolver",
        )
        logger.info(f"Outcome resolver started (interval={interval_s}s)")

    async def stop(self) -> None:
        """Stop the periodic resolution loop."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Outcome resolver stopped")

    async def _run_loop(self, interval_s: float) -> None:
        while not self._shutdown.is_set():
            try:
                await self.resolve_all()
            except Exception as exc:
                logger.warning(f"Outcome resolver error: {exc}")
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=interval_s
                )
                break  # shutdown was set
            except asyncio.TimeoutError:
                pass  # normal: interval elapsed, loop again

    # ── Status ───────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Get resolver status for the API."""
        self._ensure_stores()
        cal_pending = len(self._calibration_store.get_unresolved_markets())
        edge_pending = len(self._edge_store.get_unresolved_markets())

        return {
            "running": self._task is not None and not self._task.done(),
            "stats": self._stats.to_dict(),
            "pending_forecast_markets": cal_pending,
            "pending_trade_markets": edge_pending,
        }


# ── Singleton ────────────────────────────────────────────────────────────

_resolver: Optional[OutcomeResolver] = None
_resolver_lock = threading.Lock()


def get_outcome_resolver() -> OutcomeResolver:
    """Get or create the singleton OutcomeResolver."""
    global _resolver
    if _resolver is None:
        with _resolver_lock:
            if _resolver is None:
                _resolver = OutcomeResolver()
    return _resolver
