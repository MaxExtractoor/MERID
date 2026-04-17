"""Final size reconciliation layer — aggregates all sizing constraints.

Ensures order sizes respect the full hierarchy:
  1. Kelly sizing with conviction
  2. Guardian size caps
  3. Per-asset risk budgets
  4. CapitalEngine limits

Logs which layer actually clips the size for observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.risk.size_reconciliation")


@dataclass
class SizeConstraint:
    """A single sizing constraint with metadata."""
    layer: str  # e.g., "kelly", "guardian", "risk_budget", "capital_engine"
    max_size: float
    reason: str


class SizeReconciler:
    """Reconciles sizing constraints from multiple layers.
    
    Usage:
        reconciler = SizeReconciler()
        reconciler.add_kelly_size(proposed_size=1000.0, conviction=0.75)
        reconciler.add_guardian_cap(cap=0.25)  # 25% of normal
        reconciler.add_risk_budget(asset="BTC", timeframe="intraday")
        reconciler.add_capital_engine_limit(asset="BTC")
        
        final_size, clip_layer = reconciler.reconcile()
        if clip_layer:
            logger.info(f"Size clipped by {clip_layer}")
    """
    
    def __init__(self) -> None:
        self._constraints: List[SizeConstraint] = []
        self._kelly_size: Optional[float] = None
        self._asset: Optional[str] = None
        self._timeframe: Optional[str] = None
    
    def add_kelly_size(self, proposed_size: float, conviction: float) -> None:
        """Add Kelly/strategy sizing layer."""
        self._kelly_size = proposed_size
        self._constraints.append(SizeConstraint(
            layer="kelly",
            max_size=proposed_size,
            reason=f"Kelly sizing with conviction={conviction:.2f}"
        ))
    
    def add_guardian_cap(self, cap: float, reason: str = "size_cap") -> None:
        """Add guardian size cap (e.g., 0.25 for LIVE_SMALL)."""
        if self._kelly_size is None:
            raise ValueError("Must call add_kelly_size before add_guardian_cap")
        capped = self._kelly_size * cap
        self._constraints.append(SizeConstraint(
            layer="guardian",
            max_size=capped,
            reason=f"{reason}={cap:.0%}"
        ))
    
    def add_risk_budget(
        self,
        asset: str,
        timeframe: str,
        capital_engine=None
    ) -> None:
        """Add per-asset/timeframe risk budget constraint."""
        self._asset = asset
        self._timeframe = timeframe
        
        if capital_engine is None:
            from merid.risk.capital_engine import CapitalEngine
            capital_engine = CapitalEngine()
        
        budget = capital_engine.get_risk_budget(asset, timeframe)
        if budget:
            risk_cap = capital_engine.get_risk_capital(asset)
            budget_cap = risk_cap * budget.max_risk_pct_risk_capital
            self._constraints.append(SizeConstraint(
                layer="risk_budget",
                max_size=budget_cap,
                reason=f"{asset}/{timeframe} budget={budget.max_risk_pct_risk_capital:.1%}"
            ))
    
    def add_capital_engine_limit(
        self,
        asset: str,
        capital_engine=None
    ) -> None:
        """Add CapitalEngine per-asset limit."""
        if capital_engine is None:
            from merid.risk.capital_engine import CapitalEngine
            capital_engine = CapitalEngine()
        
        # Get the max allocation for this asset
        max_alloc = capital_engine.allocate_to_trade(
            asset=asset,
            suggested_size=float('inf'),
            timeframe=self._timeframe or "intraday"
        )
        
        self._constraints.append(SizeConstraint(
            layer="capital_engine",
            max_size=max_alloc,
            reason=f"{asset} capital allocation"
        ))
    
    def reconcile(self) -> Tuple[float, Optional[str]]:
        """Reconcile all constraints and return final size + clipping layer.
        
        Returns:
            (final_size, clipped_by_layer)
            clipped_by_layer is None if no clipping occurred.
        """
        if not self._constraints:
            return 0.0, None
        
        # Find the minimum constraint
        min_constraint = min(self._constraints, key=lambda c: c.max_size)
        final_size = max(0.0, min_constraint.max_size)
        
        # Determine if we were clipped
        kelly_size = self._constraints[0].max_size if self._constraints[0].layer == "kelly" else float('inf')
        
        clipped_by = None
        if final_size < kelly_size * 0.999:  # Allow small floating-point tolerance
            clipped_by = min_constraint.layer
            logger.info(
                "[SIZE-RECONCILE] %s/%s: Kelly=%.2f → Final=%.2f (clipped by %s: %s)",
                self._asset or "?",
                self._timeframe or "?",
                kelly_size,
                final_size,
                min_constraint.layer,
                min_constraint.reason
            )
        
        return final_size, clipped_by
    
    def get_all_constraints(self) -> Dict[str, float]:
        """Return all constraints as a dict for logging/debugging."""
        return {c.layer: c.max_size for c in self._constraints}


def reconcile_order_size(
    asset: str,
    timeframe: str,
    kelly_size: float,
    conviction: float,
    guardian_cap: Optional[float] = None,
    capital_engine=None,
) -> Tuple[float, Optional[str]]:
    """Convenience function for one-shot size reconciliation.
    
    Args:
        asset: Asset symbol
        timeframe: Trading timeframe
        kelly_size: Raw Kelly/strategy proposed size
        conviction: Structural conviction score
        guardian_cap: Guardian size cap (e.g., 0.25 for LIVE_SMALL)
        capital_engine: CapitalEngine instance (creates default if None)
    
    Returns:
        (final_size, clipped_by_layer)
    """
    reconciler = SizeReconciler()
    reconciler.add_kelly_size(kelly_size, conviction)
    
    if guardian_cap is not None and guardian_cap < 1.0:
        reconciler.add_guardian_cap(guardian_cap)
    
    reconciler.add_risk_budget(asset, timeframe, capital_engine)
    reconciler.add_capital_engine_limit(asset, capital_engine)
    
    return reconciler.reconcile()
