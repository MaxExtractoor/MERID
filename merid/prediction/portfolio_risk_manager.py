"""
Portfolio-Level Risk Management for Debate-Aware Position Sizing
Implements global guardrails for debate-driven exposure across all Kalshi markets.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio

from core.slo_monitor import SLOMonitor

logger = logging.getLogger("merid.prediction.portfolio_risk_manager")


class RiskLimitType(Enum):
    """Types of risk limits for portfolio management."""
    EQUITY_PERCENT = "equity_percent"
    VAR_PERCENT = "var_percent"
    ABSOLUTE_DOLLAR = "absolute_dollar"
    DEBATE_BOOST_SHARE = "debate_boost_share"


@dataclass
class RiskLimit:
    """Configuration for a portfolio risk limit."""
    limit_type: RiskLimitType
    threshold: float
    action: str  # "warn", "reduce", "stop", "kill"
    description: str
    last_breached: Optional[float] = None
    breach_count: int = 0


@dataclass
class DebateRiskAllocation:
    """Risk allocation tracking for debate-driven positions."""
    symbol: str
    base_risk: float  # Risk at base Kelly
    debate_multiplier: float  # Applied multiplier
    debate_risk: float  # Additional risk from debate boost
    total_risk: float  # Combined risk
    timestamp: float


@dataclass
class PortfolioRiskSnapshot:
    """Current snapshot of portfolio risk with debate breakdown."""
    total_equity: float
    total_var: float
    base_risk_total: float  # Risk without debate multipliers
    debate_risk_total: float  # Additional risk from debate boosts
    total_risk: float  # Combined portfolio risk
    debate_boost_share: float  # % of total risk from debate boosts
    active_positions: int
    boosted_positions: int
    reduced_positions: int
    timestamp: float
    risk_limits_status: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class PortfolioRiskManager:
    """Manages portfolio-level risk caps for debate-aware position sizing."""
    
    def __init__(self):
        self.slo_monitor = SLOMonitor.get_instance()
        self.risk_limits: Dict[str, RiskLimit] = {}
        self.position_allocations: Dict[str, DebateRiskAllocation] = {}
        self.risk_history: List[PortfolioRiskSnapshot] = []
        self.max_history_size = 1000
        self.last_update = 0.0
        
        # Initialize default risk limits
        self._initialize_default_limits()
    
    def _initialize_default_limits(self):
        """Set up default portfolio risk limits from core.settings (SINGLE SOURCE OF TRUTH)."""
        from core.settings import MAX_TOTAL_RISK_PCT
        # Use live bankroll from bankroll_service_v2 (single source of truth)
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity = get_equity_for_risk_calc_sync()
            if equity is not None and equity > 0:
                bankroll_cents = int(equity * 100)
            else:
                # Fail closed - no bankroll available
                logger.error("[PortfolioRiskManager] Bankroll unavailable from bankroll_service_v2")
                bankroll_cents = 0
        except Exception:
            # Fail closed on error
            logger.error("[PortfolioRiskManager] Failed to get bankroll from bankroll_service_v2")
            bankroll_cents = 0
        
        # Derive absolute limit from bankroll (2x max notional as hard ceiling)
        absolute_limit = float(bankroll_cents * MAX_TOTAL_RISK_PCT) / 100 * 2.0
        
        self.risk_limits = {
            "max_equity_risk": RiskLimit(
                limit_type=RiskLimitType.EQUITY_PERCENT,
                threshold=0.08,  # 8% of equity max
                action="reduce",
                description="Maximum total risk as % of portfolio equity"
            ),
            "max_var_risk": RiskLimit(
                limit_type=RiskLimitType.VAR_PERCENT,
                threshold=0.12,  # 12% of VaR max
                action="warn",
                description="Maximum total risk as % of portfolio VaR"
            ),
            "max_debate_boost_share": RiskLimit(
                limit_type=RiskLimitType.DEBATE_BOOST_SHARE,
                threshold=0.40,  # 40% of total risk from debates max
                action="reduce",
                description="Maximum share of total risk from debate boosts"
            ),
            "max_absolute_risk": RiskLimit(
                limit_type=RiskLimitType.ABSOLUTE_DOLLAR,
                threshold=absolute_limit,  # Derived from bankroll, was hardcoded $100K
                action="stop",
                description=f"Maximum absolute risk in dollars (derived: 3x max notional = ${absolute_limit:,.0f})"
            )
        }
    
    async def check_position_risk(
        self, 
        symbol: str, 
        base_risk: float, 
        debate_multiplier: float,
        total_equity: float,
        portfolio_var: float
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Check if a position complies with portfolio risk limits.
        
        Args:
            symbol: Kalshi symbol
            base_risk: Risk at base Kelly (no debate multiplier)
            debate_multiplier: Proposed debate multiplier
            total_equity: Current portfolio equity
            portfolio_var: Current portfolio VaR
            
        Returns:
            Tuple of (adjusted_multiplier, risk_check_result)
        """
        try:
            # Calculate risk allocation
            debate_risk = base_risk * (debate_multiplier - 1.0)
            total_risk = base_risk + debate_risk
            
            # Create allocation record
            allocation = DebateRiskAllocation(
                symbol=symbol,
                base_risk=base_risk,
                debate_multiplier=debate_multiplier,
                debate_risk=debate_risk,
                total_risk=total_risk,
                timestamp=time.time()
            )
            
            # Update current allocation
            self.position_allocations[symbol] = allocation
            
            # Calculate portfolio snapshot
            snapshot = await self._calculate_portfolio_snapshot(total_equity, portfolio_var)
            
            # Check risk limits
            risk_violations = await self._check_risk_limits(snapshot)
            
            # Adjust multiplier if needed
            adjusted_multiplier = self._adjust_multiplier_for_risk(
                debate_multiplier, risk_violations, snapshot
            )
            
            # Track SLO metrics
            self.slo_monitor.track_slo(
                metric_name="portfolio.risk.position_check",
                success=len(risk_violations) == 0,
                total=1,
                metadata={
                    "symbol": symbol,
                    "base_risk": base_risk,
                    "requested_multiplier": debate_multiplier,
                    "adjusted_multiplier": adjusted_multiplier,
                    "risk_violations": len(risk_violations),
                    "debate_boost_share": snapshot.debate_boost_share,
                    "total_risk_pct": snapshot.total_risk / total_equity if total_equity > 0 else 0
                }
            )
            
            risk_check_result = {
                "approved": adjusted_multiplier == debate_multiplier,
                "adjusted_multiplier": adjusted_multiplier,
                "original_multiplier": debate_multiplier,
                "risk_violations": risk_violations,
                "portfolio_snapshot": {
                    "total_risk": snapshot.total_risk,
                    "debate_boost_share": snapshot.debate_boost_share,
                    "risk_pct_equity": snapshot.total_risk / total_equity if total_equity > 0 else 0,
                    "risk_pct_var": snapshot.total_risk / portfolio_var if portfolio_var > 0 else 0
                }
            }
            
            logger.info(
                f"Portfolio risk check for {symbol}: {debate_multiplier:.2f} → {adjusted_multiplier:.2f} "
                f"(violations: {len(risk_violations)})"
            )
            
            return adjusted_multiplier, risk_check_result
            
        except Exception as e:
            logger.error(f"Error in portfolio risk check for {symbol}: {e}")
            # Fail-safe: return base multiplier
            return 1.0, {"approved": False, "error": str(e)}
    
    async def _calculate_portfolio_snapshot(
        self, 
        total_equity: float, 
        portfolio_var: float
    ) -> PortfolioRiskSnapshot:
        """Calculate current portfolio risk snapshot."""
        # Clean old allocations (older than 1 hour)
        cutoff_time = time.time() - 3600
        self.position_allocations = {
            k: v for k, v in self.position_allocations.items() 
            if v.timestamp > cutoff_time
        }
        
        # Sum risk across all positions
        base_risk_total = sum(alloc.base_risk for alloc in self.position_allocations.values())
        debate_risk_total = sum(alloc.debate_risk for alloc in self.position_allocations.values())
        total_risk = base_risk_total + debate_risk_total
        
        # Calculate boosted/reduced position counts
        boosted_positions = sum(1 for alloc in self.position_allocations.values() if alloc.debate_multiplier > 1.0)
        reduced_positions = sum(1 for alloc in self.position_allocations.values() if alloc.debate_multiplier < 1.0)
        
        # Calculate debate boost share
        debate_boost_share = debate_risk_total / total_risk if total_risk > 0 else 0.0
        
        # Create snapshot
        snapshot = PortfolioRiskSnapshot(
            total_equity=total_equity,
            total_var=portfolio_var,
            base_risk_total=base_risk_total,
            debate_risk_total=debate_risk_total,
            total_risk=total_risk,
            debate_boost_share=debate_boost_share,
            active_positions=len(self.position_allocations),
            boosted_positions=boosted_positions,
            reduced_positions=reduced_positions,
            timestamp=time.time()
        )
        
        # Store in history
        self.risk_history.append(snapshot)
        if len(self.risk_history) > self.max_history_size:
            self.risk_history = self.risk_history[-self.max_history_size:]
        
        self.last_update = time.time()
        return snapshot
    
    async def _check_risk_limits(self, snapshot: PortfolioRiskSnapshot) -> List[Dict[str, Any]]:
        """Check all risk limits against current snapshot."""
        violations = []
        
        for limit_name, limit in self.risk_limits.items():
            violation = None
            
            if limit.limit_type == RiskLimitType.EQUITY_PERCENT:
                risk_pct = snapshot.total_risk / snapshot.total_equity if snapshot.total_equity > 0 else 0
                if risk_pct > limit.threshold:
                    violation = {
                        "limit": limit_name,
                        "type": "equity_percent",
                        "current": risk_pct,
                        "threshold": limit.threshold,
                        "action": limit.action,
                        "description": limit.description
                    }
                    
            elif limit.limit_type == RiskLimitType.VAR_PERCENT:
                risk_pct = snapshot.total_risk / snapshot.total_var if snapshot.total_var > 0 else 0
                if risk_pct > limit.threshold:
                    violation = {
                        "limit": limit_name,
                        "type": "var_percent",
                        "current": risk_pct,
                        "threshold": limit.threshold,
                        "action": limit.action,
                        "description": limit.description
                    }
                    
            elif limit.limit_type == RiskLimitType.DEBATE_BOOST_SHARE:
                if snapshot.debate_boost_share > limit.threshold:
                    violation = {
                        "limit": limit_name,
                        "type": "debate_boost_share",
                        "current": snapshot.debate_boost_share,
                        "threshold": limit.threshold,
                        "action": limit.action,
                        "description": limit.description
                    }
                    
            elif limit.limit_type == RiskLimitType.ABSOLUTE_DOLLAR:
                if snapshot.total_risk > limit.threshold:
                    violation = {
                        "limit": limit_name,
                        "type": "absolute_dollar",
                        "current": snapshot.total_risk,
                        "threshold": limit.threshold,
                        "action": limit.action,
                        "description": limit.description
                    }
            
            if violation:
                violations.append(violation)
                
                # Update limit breach tracking
                limit.last_breached = time.time()
                limit.breach_count += 1
                
                # Track SLO for breach
                self.slo_monitor.track_slo(
                    metric_name=f"portfolio.risk.breach.{limit_name}",
                    success=False,
                    total=1,
                    metadata=violation
                )
        
        return violations
    
    def _adjust_multiplier_for_risk(
        self, 
        requested_multiplier: float, 
        violations: List[Dict[str, Any]], 
        snapshot: PortfolioRiskSnapshot
    ) -> float:
        """Adjust multiplier based on risk violations."""
        if not violations:
            return requested_multiplier
        
        # Find the most restrictive action
        actions = [v["action"] for v in violations]
        
        if "kill" in actions or "stop" in actions:
            logger.warning("Portfolio risk limits triggered STOP action - using base Kelly")
            return 1.0
        
        elif "reduce" in actions:
            # Calculate reduction factor based on severity
            max_violation = max(violations, key=lambda v: v["current"] / v["threshold"])
            severity = max_violation["current"] / max_violation["threshold"]
            
            # Reduce multiplier proportionally to severity
            if severity > 2.0:
                adjusted = 1.0  # Back to base Kelly
            elif severity > 1.5:
                adjusted = 1.25  # Minimal boost
            else:
                # Scale down the requested boost
                excess_boost = requested_multiplier - 1.0
                reduction_factor = 1.0 - (severity - 1.0)
                adjusted = 1.0 + (excess_boost * reduction_factor)
                adjusted = max(adjusted, 1.0)  # Never below base
            
            logger.warning(
                f"Portfolio risk reduction: severity={severity:.2f}, "
                f"{requested_multiplier:.2f} → {adjusted:.2f}"
            )
            return adjusted
        
        # For "warn" actions, allow but log
        logger.warning(
            f"Portfolio risk warning triggered - allowing {requested_multiplier:.2f}x"
        )
        return requested_multiplier
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Get current portfolio risk summary."""
        if not self.risk_history:
            return {"message": "No risk data available"}
        
        latest = self.risk_history[-1]
        
        return {
            "timestamp": datetime.fromtimestamp(latest.timestamp, timezone.utc).isoformat(),
            "total_equity": latest.total_equity,
            "total_risk": latest.total_risk,
            "base_risk_total": latest.base_risk_total,
            "debate_risk_total": latest.debate_risk_total,
            "debate_boost_share": latest.debate_boost_share,
            "active_positions": latest.active_positions,
            "boosted_positions": latest.boosted_positions,
            "reduced_positions": latest.reduced_positions,
            "risk_limits": {
                name: {
                    "threshold": limit.threshold,
                    "action": limit.action,
                    "description": limit.description,
                    "last_breached": datetime.fromtimestamp(limit.last_breached, timezone.utc).isoformat() if limit.last_breached else None,
                    "breach_count": limit.breach_count
                }
                for name, limit in self.risk_limits.items()
            },
            "risk_trends": self._calculate_risk_trends()
        }
    
    def _calculate_risk_trends(self) -> Dict[str, Any]:
        """Calculate risk trends over time."""
        if len(self.risk_history) < 2:
            return {"message": "Insufficient data for trends"}
        
        # Last 24 hours
        cutoff_24h = time.time() - 86400
        recent_snapshots = [s for s in self.risk_history if s.timestamp > cutoff_24h]
        
        if len(recent_snapshots) < 2:
            return {"message": "Insufficient recent data"}
        
        # Calculate trends
        first = recent_snapshots[0]
        latest = recent_snapshots[-1]
        
        return {
            "period_hours": 24,
            "snapshots_analyzed": len(recent_snapshots),
            "total_risk_change": latest.total_risk - first.total_risk,
            "total_risk_change_pct": ((latest.total_risk - first.total_risk) / first.total_risk * 100) if first.total_risk > 0 else 0,
            "debate_boost_share_change": latest.debate_boost_share - first.debate_boost_share,
            "active_positions_change": latest.active_positions - first.active_positions,
            "max_risk_24h": max(s.total_risk for s in recent_snapshots),
            "min_risk_24h": min(s.total_risk for s in recent_snapshots)
        }
    
    def update_risk_limit(self, limit_name: str, threshold: float, action: str = None):
        """Update a risk limit configuration."""
        if limit_name not in self.risk_limits:
            raise ValueError(f"Unknown risk limit: {limit_name}")
        
        self.risk_limits[limit_name].threshold = threshold
        if action:
            self.risk_limits[limit_name].action = action
        
        logger.info(f"Updated risk limit {limit_name}: threshold={threshold}, action={action}")
    
    def clear_position_allocations(self):
        """Clear all position allocations (useful for end-of-day reset)."""
        self.position_allocations.clear()
        logger.info("Cleared all portfolio position allocations")


# Global instance
_risk_manager_instance: Optional[PortfolioRiskManager] = None


def get_portfolio_risk_manager() -> PortfolioRiskManager:
    """Get the global portfolio risk manager instance."""
    global _risk_manager_instance
    if _risk_manager_instance is None:
        _risk_manager_instance = PortfolioRiskManager()
    return _risk_manager_instance


async def check_portfolio_risk_limits(
    symbol: str,
    base_risk: float,
    debate_multiplier: float,
    total_equity: float,
    portfolio_var: float
) -> Tuple[float, Dict[str, Any]]:
    """
    Check portfolio risk limits for a debate-adjusted position.
    
    Args:
        symbol: Kalshi symbol
        base_risk: Risk at base Kelly
        debate_multiplier: Proposed debate multiplier
        total_equity: Current portfolio equity
        portfolio_var: Current portfolio VaR
        
    Returns:
        Tuple of (adjusted_multiplier, risk_check_result)
    """
    risk_manager = get_portfolio_risk_manager()
    return await risk_manager.check_position_risk(
        symbol, base_risk, debate_multiplier, total_equity, portfolio_var
    )
