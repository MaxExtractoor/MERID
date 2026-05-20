"""
Parallel Risk Runner — Run old and new pipelines in parallel with diff checks

This module implements Step 5 of the rebuild plan: parallel run with diff checks.
It runs the existing risk pipeline and the new pure-function pipeline side-by-side,
compares their outputs, and alerts on discrepancies.

Usage:
    from merid.event_venues.kalshi.parallel_risk_runner import ParallelRiskRunner
    
    runner = ParallelRiskRunner()
    diff_result = await runner.run_and_diff(snapshot)
    
    if diff_result.has_significant_discrepancy():
        # Alert on diff
        pass
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from merid.event_venues.kalshi.risk_projection import (
    BackendSnapshot,
    RiskProjection,
    RiskProjectionEngine,
)

logger = get_logger("merid.event_venues.kalshi.parallel_risk_runner")


# ═══════════════════════════════════════════════════════════════════════════
# Diff Result
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DiffResult:
    """Result of comparing old and new pipeline outputs."""
    timestamp: datetime
    
    # Position diffs
    position_count_diff: int
    position_details: Dict[str, Dict[str, Any]]
    
    # PnL diffs
    unrealized_pnl_diff_dollars: Decimal
    realized_pnl_diff_dollars: Decimal
    
    # Exposure diffs
    total_exposure_diff_dollars: Decimal
    equity_diff_dollars: Decimal
    
    # Metadata
    old_pipeline_source: str
    new_pipeline_source: str
    backend_timestamp: datetime
    
    # Tolerances (for cutover criteria)
    cash_tolerance_cents: int = 1
    pnl_tolerance_cents: int = 10
    
    @property
    def has_position_discrepancy(self) -> bool:
        return self.position_count_diff != 0
    
    @property
    def has_pnl_discrepancy(self) -> bool:
        return (
            abs(self.unrealized_pnl_diff_dollars) > Decimal(self.pnl_tolerance_cents) / 100
            or abs(self.realized_pnl_diff_dollars) > Decimal(self.pnl_tolerance_cents) / 100
        )
    
    @property
    def has_exposure_discrepancy(self) -> bool:
        return abs(self.total_exposure_diff_dollars) > Decimal(self.cash_tolerance_cents) / 100
    
    @property
    def has_equity_discrepancy(self) -> bool:
        return abs(self.equity_diff_dollars) > Decimal(self.cash_tolerance_cents) / 100
    
    @property
    def has_significant_discrepancy(self) -> bool:
        """True if any discrepancy exceeds tolerance."""
        return (
            self.has_position_discrepancy
            or self.has_pnl_discrepancy
            or self.has_exposure_discrepancy
            or self.has_equity_discrepancy
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "position_count_diff": self.position_count_diff,
            "position_details": self.position_details,
            "unrealized_pnl_diff_dollars": str(self.unrealized_pnl_diff_dollars),
            "realized_pnl_diff_dollars": str(self.realized_pnl_diff_dollars),
            "total_exposure_diff_dollars": str(self.total_exposure_diff_dollars),
            "equity_diff_dollars": str(self.equity_diff_dollars),
            "old_pipeline_source": self.old_pipeline_source,
            "new_pipeline_source": self.new_pipeline_source,
            "backend_timestamp": self.backend_timestamp.isoformat(),
            "has_significant_discrepancy": self.has_significant_discrepancy,
            "cash_tolerance_cents": self.cash_tolerance_cents,
            "pnl_tolerance_cents": self.pnl_tolerance_cents,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Parallel Risk Runner
# ═══════════════════════════════════════════════════════════════════════════

class ParallelRiskRunner:
    """Run old and new risk pipelines in parallel, diff outputs.
    
    This is a temporary tool for the parallel run phase (Step 5).
    Once the new pipeline is stable and cutover criteria are met,
    this can be removed.
    """
    
    def __init__(self):
        self._new_engine = RiskProjectionEngine()
        self._diff_count = 0
        self._significant_diff_count = 0
        logger.info("ParallelRiskRunner initialized")
    
    async def _old_pipeline(self, snapshot: BackendSnapshot) -> Dict[str, Any]:
        """Run existing risk pipeline (legacy path).
        
        This calls the existing position cache, fills ledger, etc.
        Returns a dict in the same shape as RiskProjection for comparison.
        """
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            
            # Get positions from cache
            cache = get_position_cache()
            cached_positions = cache.get_all_positions(validate_freshness=False)
            
            # Convert to dict for comparison
            positions_by_ticker = {}
            total_exposure = Decimal("0")
            unrealized_pnl = Decimal("0")
            realized_pnl = Decimal("0")
            
            for ticker, pos in cached_positions.items():
                positions_by_ticker[ticker] = {
                    "ticker": ticker,
                    "side": pos.side,
                    "count": pos.contracts,
                    "avg_price_dollars": Decimal(pos.avg_price_cents) / 100,
                    "total_cost_dollars": Decimal(pos.contracts * pos.avg_price_cents) / 100,
                    "unrealized_pnl_dollars": pos.unrealized_pnl_usd,
                    "realized_pnl_dollars": pos.realized_pnl_usd,
                }
                total_exposure += Decimal(pos.contracts * pos.avg_price_cents) / 100
                unrealized_pnl += pos.unrealized_pnl_usd
                realized_pnl += pos.realized_pnl_usd
            
            # Get balance
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                client = get_kalshi_client()
                balance_result = await client.get_balance_result()
                if balance_result.success:
                    balance = balance_result.data
                    available_usd = balance.available_usd
                else:
                    available_usd = snapshot.balance.available_usd  # Fallback
            except Exception:
                available_usd = snapshot.balance.available_usd  # Fallback
            
            equity = available_usd + unrealized_pnl
            
            return {
                "positions_by_ticker": positions_by_ticker,
                "total_exposure_dollars": total_exposure,
                "unrealized_pnl_dollars": unrealized_pnl,
                "realized_pnl_dollars": realized_pnl,
                "equity_dollars": equity,
                "position_count": len(cached_positions),
                "source": "legacy_position_cache",
            }
            
        except Exception as e:
            logger.error(f"Old pipeline failed: {e}")
            # Return zeros on failure (graceful degradation)
            return {
                "positions_by_ticker": {},
                "total_exposure_dollars": Decimal("0"),
                "unrealized_pnl_dollars": Decimal("0"),
                "realized_pnl_dollars": Decimal("0"),
                "equity_dollars": snapshot.balance.available_usd,
                "position_count": 0,
                "source": "legacy_failed",
            }
    
    def _compute_diff(
        self,
        old_result: Dict[str, Any],
        new_projection: RiskProjection,
    ) -> DiffResult:
        """Compute diff between old and new pipeline outputs."""
        # Position count diff
        old_count = old_result.get("position_count", 0)
        new_count = new_projection.position_count
        position_count_diff = new_count - old_count
        
        # Position details diff
        position_details = {}
        old_positions = old_result.get("positions_by_ticker", {})
        new_positions = new_projection.positions_by_ticker
        
        # Check for positions only in new
        for ticker in set(new_positions.keys()) - set(old_positions.keys()):
            position_details[f"only_in_new_{ticker}"] = {
                "old": None,
                "new": new_positions[ticker].to_dict(),
            }
        
        # Check for positions only in old
        for ticker in set(old_positions.keys()) - set(new_positions.keys()):
            position_details[f"only_in_old_{ticker}"] = {
                "old": old_positions[ticker],
                "new": None,
            }
        
        # Check for count diffs in common positions
        for ticker in set(old_positions.keys()) & set(new_positions.keys()):
            old_pos = old_positions[ticker]
            new_pos = new_positions[ticker]
            if old_pos.get("count") != new_pos.count:
                position_details[f"count_diff_{ticker}"] = {
                    "old": old_pos,
                    "new": new_pos.to_dict(),
                }
        
        # PnL diffs
        old_unrealized = Decimal(str(old_result.get("unrealized_pnl_dollars", 0)))
        new_unrealized = new_projection.unrealized_pnl_dollars
        unrealized_pnl_diff = new_unrealized - old_unrealized
        
        old_realized = Decimal(str(old_result.get("realized_pnl_dollars", 0)))
        new_realized = new_projection.realized_pnl_dollars
        realized_pnl_diff = new_realized - old_realized
        
        # Exposure diffs
        old_exposure = Decimal(str(old_result.get("total_exposure_dollars", 0)))
        new_exposure = new_projection.total_exposure_dollars
        total_exposure_diff = new_exposure - old_exposure
        
        # Equity diffs
        old_equity = Decimal(str(old_result.get("equity_dollars", 0)))
        new_equity = new_projection.equity_dollars
        equity_diff = new_equity - old_equity
        
        return DiffResult(
            timestamp=datetime.now(timezone.utc),
            position_count_diff=position_count_diff,
            position_details=position_details,
            unrealized_pnl_diff_dollars=unrealized_pnl_diff,
            realized_pnl_diff_dollars=realized_pnl_diff,
            total_exposure_diff_dollars=total_exposure_diff,
            equity_diff_dollars=equity_diff,
            old_pipeline_source=old_result.get("source", "unknown"),
            new_pipeline_source="risk_projection_engine",
            backend_timestamp=new_projection.backend_timestamp,
        )
    
    async def _alert_on_diff(self, diff: DiffResult) -> None:
        """Alert on significant discrepancies."""
        self._diff_count += 1
        if diff.has_significant_discrepancy():
            self._significant_diff_count += 1
            
            logger.warning(
                "[RISK_DIFF_SIGNIFICANT] count_diff=%d unrealized_diff=$%.2f realized_diff=$%.2f "
                "exposure_diff=$%.2f equity_diff=$%.2f source_old=%s source_new=%s",
                diff.position_count_diff,
                diff.unrealized_pnl_diff_dollars,
                diff.realized_pnl_diff_dollars,
                diff.total_exposure_diff_dollars,
                diff.equity_diff_dollars,
                diff.old_pipeline_source,
                diff.new_pipeline_source,
            )
            
            # Try to send to monitoring/alerting
            try:
                from monitoring.metrics import get_metrics_registry
                registry = get_metrics_registry()
                counter = registry.counter(
                    "risk_pipeline_significant_diff_total",
                    help_text="Count of significant discrepancies between old and new risk pipelines",
                )
                counter.inc()
            except Exception:
                pass  # Metrics unavailable
    
    async def run_and_diff(self, snapshot: BackendSnapshot) -> DiffResult:
        """Run old and new pipelines in parallel, diff outputs.
        
        Args:
            snapshot: Backend snapshot from Kalshi API
            
        Returns:
            DiffResult with comparison details
        """
        logger.info("[SOURCE=parallel] Running old and new risk pipelines in parallel")
        
        # Run both pipelines
        old_result = await self._old_pipeline(snapshot)
        new_projection = self._new_engine.compute_projection(snapshot)
        
        # Compute diff
        diff = self._compute_diff(old_result, new_projection)
        
        # Alert on discrepancies
        if diff.has_significant_discrepancy:
            await self._alert_on_diff(diff)
        
        logger.info(
            "[SOURCE=parallel] Diff complete: significant=%s count_diff=%d pnl_diff=$%.2f",
            diff.has_significant_discrepancy,
            diff.position_count_diff,
            diff.unrealized_pnl_diff_dollars + diff.realized_pnl_diff_dollars,
        )
        
        return diff
    
    @property
    def diff_count(self) -> int:
        """Total number of diff runs performed."""
        return self._diff_count
    
    @property
    def significant_diff_count(self) -> int:
        """Number of significant discrepancies found."""
        return self._significant_diff_count


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Access
# ═══════════════════════════════════════════════════════════════════════════

_parallel_risk_runner_instance: Optional[ParallelRiskRunner] = None


def get_parallel_risk_runner() -> ParallelRiskRunner:
    """Get singleton ParallelRiskRunner instance."""
    global _parallel_risk_runner_instance
    if _parallel_risk_runner_instance is None:
        _parallel_risk_runner_instance = ParallelRiskRunner()
    return _parallel_risk_runner_instance
