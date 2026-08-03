"""
Dynamic cross-asset risk routing based on normalized edge.

This module implements dynamic risk allocation across BTC/ETH/SOL/XRP/DOGE
based on normalized edge (edge_R), allowing the risk budget to chase the best
opportunities in real time rather than being pre-split by asset.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    """A trading opportunity with normalized edge metrics."""
    asset: str
    market_id: str
    side: str
    edge_r: float  # Risk-adjusted edge
    edge_slippage_adjusted: float  # Slippage-adjusted edge
    time_to_expiry_seconds: float
    marginal_risk_per_contract: float  # USD risk per additional contract
    current_utilization: float  # Current risk utilization for this asset
    confidence: float
    timestamp: datetime


@dataclass
class RiskAllocation:
    """Risk allocation decision."""
    asset: str
    market_id: str
    contracts: int
    risk_usd: float
    edge_r: float
    reason: str


class DynamicRiskRouter:
    """
    Dynamic cross-asset risk router.
    
    Allocates incremental risk to the highest edge_R opportunities subject to:
    - Per-asset risk caps
    - Correlation/cluster limits (BTC/ETH more correlated than DOGE/XRP)
    - Total risk budget
    """
    
    def __init__(
        self,
        total_risk_budget_usd: float = 300.0,
        per_asset_caps: Optional[Dict[str, float]] = None,
        correlation_groups: Optional[Dict[str, List[str]]] = None,
    ):
        self.total_risk_budget_usd = total_risk_budget_usd
        
        # Default per-asset caps (can be overridden)
        self.per_asset_caps = per_asset_caps or {
            "BTC": 100.0,
            "ETH": 100.0,
            "SOL": 50.0,
            "XRP": 50.0,
            "DOGE": 50.0,
        }
        
        # Correlation groups (assets in same group are treated as correlated)
        self.correlation_groups = correlation_groups or {
            "BTC_ETH": ["BTC", "ETH"],
            "SOL_XRP_DOGE": ["SOL", "XRP", "DOGE"],
        }
        
        # Group-level caps (to limit correlated exposure)
        self.group_caps = {
            "BTC_ETH": 150.0,
            "SOL_XRP_DOGE": 100.0,
        }
    
    def rank_opportunities(
        self,
        opportunities: List[Opportunity]
    ) -> List[Opportunity]:
        """
        Rank opportunities by normalized edge (edge_R).
        
        Args:
            opportunities: List of trading opportunities
        
        Returns:
            Ranked list of opportunities (highest edge_R first)
        """
        # Sort by edge_R descending
        ranked = sorted(opportunities, key=lambda x: x.edge_r, reverse=True)
        
        logger.info(
            "[RISK-ROUTING-RANK] Ranked %d opportunities by edge_R",
            len(ranked)
        )
        
        for i, opp in enumerate(ranked[:5]):  # Log top 5
            logger.info(
                "  [%d] %s %s edge_R=%.3f edge_slip=%.3f conf=%.2f",
                i + 1, opp.asset, opp.market_id, opp.edge_r,
                opp.edge_slippage_adjusted, opp.confidence
            )
        
        return ranked
    
    def check_per_asset_cap(
        self,
        asset: str,
        current_utilization: float,
        additional_risk: float
    ) -> bool:
        """
        Check if adding risk would exceed per-asset cap.
        
        Args:
            asset: Asset symbol
            current_utilization: Current risk utilization for asset
            additional_risk: Additional risk to add
        
        Returns:
            True if within cap, False otherwise
        """
        cap = self.per_asset_caps.get(asset, 50.0)
        new_utilization = current_utilization + additional_risk
        
        within_cap = new_utilization <= cap
        
        if not within_cap:
            logger.debug(
                "[PER-ASSET-CAP-FAIL] %s current=%.2f + add=%.2f > cap=%.2f",
                asset, current_utilization, additional_risk, cap
            )
        
        return within_cap
    
    def check_group_cap(
        self,
        asset: str,
        group_utilizations: Dict[str, float],
        additional_risk: float
    ) -> bool:
        """
        Check if adding risk would exceed correlation group cap.
        
        Args:
            asset: Asset symbol
            group_utilizations: Current utilization per group
            additional_risk: Additional risk to add
        
        Returns:
            True if within group cap, False otherwise
        """
        # Find which group this asset belongs to
        group_name = None
        for group, assets in self.correlation_groups.items():
            if asset in assets:
                group_name = group
                break
        
        if group_name is None:
            # Asset not in any correlation group, no group cap
            return True
        
        cap = self.group_caps.get(group_name, 100.0)
        current_util = group_utilizations.get(group_name, 0.0)
        new_util = current_util + additional_risk
        
        within_cap = new_util <= cap
        
        if not within_cap:
            logger.debug(
                "[GROUP-CAP-FAIL] %s group=%s current=%.2f + add=%.2f > cap=%.2f",
                asset, group_name, current_util, additional_risk, cap
            )
        
        return within_cap
    
    def allocate_risk(
        self,
        opportunities: List[Opportunity],
        current_exposures: Dict[str, float],
        group_utilizations: Dict[str, float],
        remaining_budget: float
    ) -> List[RiskAllocation]:
        """
        Allocate risk to highest edge_R opportunities.
        
        Args:
            opportunities: List of trading opportunities
            current_exposures: Current risk exposure per asset
            group_utilizations: Current utilization per correlation group
            remaining_budget: Remaining risk budget
        
        Returns:
            List of risk allocation decisions
        """
        allocations = []
        total_allocated = 0.0
        
        # Rank opportunities by edge_R
        ranked = self.rank_opportunities(opportunities)
        
        for opp in ranked:
            if remaining_budget <= 0:
                logger.info("[RISK-ROUTING-EXHAUSTED] Budget exhausted")
                break
            
            # Check per-asset cap
            if not self.check_per_asset_cap(
                opp.asset, current_exposures.get(opp.asset, 0.0), opp.marginal_risk_per_contract
            ):
                logger.debug(
                    "[RISK-ROUTING-SKIP] %s per-asset cap exceeded",
                    opp.asset
                )
                continue
            
            # Check group cap
            if not self.check_group_cap(
                opp.asset, group_utilizations, opp.marginal_risk_per_contract
            ):
                logger.debug(
                    "[RISK-ROUTING-SKIP] %s group cap exceeded",
                    opp.asset
                )
                continue
            
            # Check if within remaining budget
            if opp.marginal_risk_per_contract > remaining_budget:
                logger.debug(
                    "[RISK-ROUTING-SKIP] %s marginal risk %.2f > remaining budget %.2f",
                    opp.asset, opp.marginal_risk_per_contract, remaining_budget
                )
                continue
            
            # Allocate risk (single contract for now)
            contracts = 1
            risk_usd = opp.marginal_risk_per_contract * contracts
            
            allocation = RiskAllocation(
                asset=opp.asset,
                market_id=opp.market_id,
                contracts=contracts,
                risk_usd=risk_usd,
                edge_r=opp.edge_r,
                reason=f"Highest edge_R in ranked list ({opp.edge_r:.3f})"
            )
            
            allocations.append(allocation)
            
            # Update tracking
            current_exposures[opp.asset] = current_exposures.get(opp.asset, 0.0) + risk_usd
            remaining_budget -= risk_usd
            total_allocated += risk_usd
            
            # Update group utilization
            for group, assets in self.correlation_groups.items():
                if opp.asset in assets:
                    group_utilizations[group] = group_utilizations.get(group, 0.0) + risk_usd
                    break
            
            logger.info(
                "[RISK-ROUTING-ALLOCATE] %s %s contracts=%d risk=%.2f edge_R=%.3f remaining=%.2f",
                opp.asset, opp.market_id, contracts, risk_usd, opp.edge_r, remaining_budget
            )
        
        # INVARIANT: Sum of allocations ≤ global risk cap
        if total_allocated > self.total_risk_budget_usd:
            logger.error(
                "[RISK-ROUTING-VIOLATION] Total allocated %.2f > global cap %.2f - INVARIANT VIOLATION",
                total_allocated, self.total_risk_budget_usd
            )
            # Safe mode: truncate allocations to cap proportionally
            logger.warning("[RISK-ROUTING-SAFE-MODE] Truncating allocations to global cap")
            scale_factor = self.total_risk_budget_usd / total_allocated if total_allocated > 0 else 0
            for allocation in allocations:
                original_contracts = allocation.contracts
                original_risk = allocation.risk_usd
                allocation.contracts = max(1, int(allocation.contracts * scale_factor))
                allocation.risk_usd = allocation.risk_usd * scale_factor
                logger.info(
                    "[RISK-ROUTING-TRUNCATE] %s: %d->%d contracts, %.2f->%.2f USD (scale=%.3f)",
                    allocation.asset, original_contracts, allocation.contracts,
                    original_risk, allocation.risk_usd, scale_factor
                )
            # Recalculate total after truncation
            total_allocated = sum(a.risk_usd for a in allocations)
        
        # INVARIANT: Per-asset allocation never exceeds cap
        for asset, exposure in current_exposures.items():
            cap = self.per_asset_caps.get(asset, 50.0)
            if exposure > cap:
                logger.error(
                    "[RISK-ROUTING-VIOLATION] %s exposure %.2f > cap %.2f - INVARIANT VIOLATION",
                    asset, exposure, cap
                )
        
        # INVARIANT: Group caps cannot be exceeded
        for group, utilization in group_utilizations.items():
            cap = self.group_caps.get(group, 100.0)
            if utilization > cap:
                logger.error(
                    "[RISK-ROUTING-VIOLATION] Group %s utilization %.2f > cap %.2f - INVARIANT VIOLATION",
                    group, utilization, cap
                )
        
        return allocations
    
    def log_routing_summary(
        self,
        allocations: List[RiskAllocation],
        remaining_budget: float
    ):
        """Log routing summary."""
        total_allocated = sum(a.risk_usd for a in allocations)
        
        logger.info(
            "[RISK-ROUTING-SUMMARY] Allocated %.2f of %.2f budget (%.1f%%) across %d assets",
            total_allocated, self.total_risk_budget_usd,
            (total_allocated / self.total_risk_budget_usd * 100) if self.total_risk_budget_usd > 0 else 0,
            len(set(a.asset for a in allocations))
        )
        
        for allocation in allocations:
            logger.info(
                "  %s: %d contracts @ %.2f USD (edge_R=%.3f)",
                allocation.asset, allocation.contracts, allocation.risk_usd, allocation.edge_r
            )


# Singleton instance
_dynamic_risk_router: Optional[DynamicRiskRouter] = None


def get_dynamic_risk_router() -> DynamicRiskRouter:
    """Get the singleton dynamic risk router instance."""
    global _dynamic_risk_router
    if _dynamic_risk_router is None:
        _dynamic_risk_router = DynamicRiskRouter()
    return _dynamic_risk_router
