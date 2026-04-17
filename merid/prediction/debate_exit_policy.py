"""
Debate-Driven Stop-Loss and Exit Policy
Implements intelligent exit rules based on debate performance degradation.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio

from merid.prediction.debate_position_sizing import get_debate_position_sizer, DebatePerformanceProfile
from merid.prediction.backtest_scheduler import get_backtest_scheduler
from merid.prediction.debate_deployment import get_debate_deployment_manager, is_debate_enabled
from core.slo_monitor import SLOMonitor

logger = logging.getLogger("merid.prediction.debate_exit_policy")


class ExitAction(Enum):
    """Possible exit actions for positions."""
    HOLD = "hold"
    TRIM = "trim"  # Reduce position size
    EXIT = "exit"  # Close position entirely


@dataclass
class PositionState:
    """Current state of a trading position."""
    symbol: str
    entry_price: float
    current_price: float
    position_size: float
    entry_time: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    base_kelly_fraction: float
    debate_multiplier: float
    current_kelly_fraction: float


@dataclass
class ExitRecommendation:
    """Exit recommendation for a position."""
    action: ExitAction
    reason: str
    confidence: float
    suggested_kelly_fraction: Optional[float] = None
    stop_loss_price: Optional[float] = None
    debate_performance: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class DebateDrivenExitPolicy:
    """Manages stop-loss and exit decisions based on debate performance."""
    
    def __init__(self):
        self.slo_monitor = SLOMonitor.get_instance()
        self.position_sizer = get_debate_position_sizer()
        self.deployment_manager = get_debate_deployment_manager()
        self.position_states: Dict[str, PositionState] = {}
        self.exit_history: List[Dict[str, Any]] = []
        self.max_history_size = 10000
        
        # Policy parameters
        self.debate_performance_threshold = -2.0  # % improvement threshold
        self.confidence_threshold = 0.7  # Confidence level for debate decisions
        self.trim_factor = 0.5  # Reduce position by this factor
        self.max_position_age_hours = 72  # Maximum hours before review
        self.pnl_loss_threshold = -5.0  # % loss threshold for forced exit
        
        # Performance degradation detection
        self.performance_window_days = 14  # Look back period for performance trends
        self.degradation_threshold = -3.0  # % degradation threshold
    
    async def evaluate_position_exit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        position_size: float,
        entry_time: float,
        base_kelly_fraction: float,
        current_kelly_fraction: float
    ) -> ExitRecommendation:
        """
        Evaluate whether to exit or adjust a position based on debate performance.
        
        Args:
            symbol: Kalshi symbol
            entry_price: Entry price of position
            current_price: Current market price
            position_size: Current position size
            entry_time: Entry timestamp
            base_kelly_fraction: Original Kelly fraction
            current_kelly_fraction: Current Kelly fraction (may be debate-adjusted)
            
        Returns:
            ExitRecommendation with action and reasoning
        """
        try:
            # Calculate PnL
            unrealized_pnl = (current_price - entry_price) * position_size
            unrealized_pnl_pct = (current_price - entry_price) / entry_price * 100
            
            # Update position state
            position_state = PositionState(
                symbol=symbol,
                entry_price=entry_price,
                current_price=current_price,
                position_size=position_size,
                entry_time=entry_time,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                base_kelly_fraction=base_kelly_fraction,
                debate_multiplier=current_kelly_fraction / base_kelly_fraction if base_kelly_fraction > 0 else 1.0,
                current_kelly_fraction=current_kelly_fraction
            )
            
            self.position_states[symbol] = position_state
            
            # Check if debate features are enabled for this symbol
            if not self.deployment_manager.is_debate_enabled(symbol):
                # Log shadow recommendation if needed
                if self.deployment_manager.should_log_shadow_recommendation(symbol):
                    # Calculate what the debate exit recommendation would be
                    debate_profile = await self.position_sizer.get_profile_for_symbol(symbol)
                    if debate_profile:
                        # Create a shadow recommendation
                        shadow_action, shadow_reason, shadow_confidence = await self._evaluate_exit_conditions(
                            position_state, debate_profile
                        )
                        
                        self.deployment_manager.log_shadow_recommendation(
                            symbol=symbol,
                            base_kelly=base_kelly_fraction,
                            debate_multiplier=position_state.debate_multiplier,
                            agent_id=None,  # Exit policy doesn't track specific agents
                            reason=f"Debate exit disabled - shadow recommendation: {shadow_action.value} ({shadow_reason})"
                        )
                
                logger.debug(f"Debate exit features disabled for {symbol}, using base exit rules")
                return ExitRecommendation(
                    action=ExitAction.HOLD,
                    reason="Debate exit system disabled - using base rules",
                    confidence=1.0,
                    suggested_kelly_fraction=current_kelly_fraction,
                    metadata={"deployment_mode": self.deployment_manager.config.mode.value}
                )
            
            # Get current debate performance profile
            debate_profile = await self.position_sizer.get_profile_for_symbol(symbol)
            
            # Evaluate exit conditions
            exit_action, reason, confidence = await self._evaluate_exit_conditions(
                position_state, debate_profile
            )
            
            # Calculate specific recommendations
            recommendation = await self._generate_recommendation(
                exit_action, reason, confidence, position_state, debate_profile
            )
            
            # Track SLO metrics
            self.slo_monitor.track_slo(
                metric_name="debate.exit_policy.evaluation",
                success=True,
                total=1,
                metadata={
                    "symbol": symbol,
                    "action": exit_action.value,
                    "reason": reason,
                    "confidence": confidence,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "debate_performance": debate_profile.avg_improvement_pct if debate_profile else None,
                    "position_age_hours": (time.time() - entry_time) / 3600
                }
            )
            
            logger.info(
                f"Exit policy evaluation for {symbol}: {exit_action.value} "
                f"(reason: {reason}, confidence: {confidence:.2f}, pnl: {unrealized_pnl_pct:.1f}%)"
            )
            
            return recommendation
            
        except Exception as e:
            logger.error(f"Error evaluating exit policy for {symbol}: {e}")
            # Fail-safe: hold position
            return ExitRecommendation(
                action=ExitAction.HOLD,
                reason="Evaluation error - holding position",
                confidence=0.0,
                metadata={"error": str(e)}
            )
    
    async def _evaluate_exit_conditions(
        self,
        position_state: PositionState,
        debate_profile: Optional[DebatePerformanceProfile]
    ) -> Tuple[ExitAction, str, float]:
        """Evaluate all exit conditions and return the most severe action."""
        actions = []
        
        # 1. Forced exit on severe losses
        if position_state.unrealized_pnl_pct <= self.pnl_loss_threshold:
            actions.append((ExitAction.EXIT, f"Severe loss: {position_state.unrealized_pnl_pct:.1f}%", 1.0))
        
        # 2. Debate performance degradation
        if debate_profile:
            if (debate_profile.avg_improvement_pct <= self.debate_performance_threshold and
                debate_profile.confidence_level >= self.confidence_threshold):
                actions.append((
                    ExitAction.TRIM,
                    f"Poor debate performance: {debate_profile.avg_improvement_pct:.1f}% improvement",
                    debate_profile.confidence_level
                ))
            
            # Check for performance degradation
            degradation = await self._check_performance_degradation(position_state.symbol)
            if degradation["degraded"] and degradation["confidence"] >= self.confidence_threshold:
                actions.append((
                    ExitAction.TRIM,
                    f"Debate performance degradation: {degradation['change']:.1f}%",
                    degradation["confidence"]
                ))
        
        # 3. Position age review
        position_age_hours = (time.time() - position_state.entry_time) / 3600
        if position_age_hours >= self.max_position_age_hours:
            actions.append((
                ExitAction.TRIM,
                f"Position age review: {position_age_hours:.0f} hours old",
                0.6  # Medium confidence for age-based action
            ))
        
        # 4. Debate multiplier reduction
        if position_state.debate_multiplier > 1.0 and debate_profile:
            if debate_profile.recommendation in ["reduce", "avoid"]:
                actions.append((
                    ExitAction.TRIM,
                    f"Debate recommendation changed to {debate_profile.recommendation}",
                    debate_profile.confidence_level
                ))
        
        # 5. Moderate losses with poor debate outlook
        if (position_state.unrealized_pnl_pct <= -2.0 and  # Moderate loss
            debate_profile and 
            debate_profile.avg_improvement_pct < 0):  # Poor debate performance
            actions.append((
                ExitAction.TRIM,
                f"Moderate loss with poor debate outlook: {position_state.unrealized_pnl_pct:.1f}%",
                0.7
            ))
        
        # Return the most severe action
        if not actions:
            return ExitAction.HOLD, "No exit conditions met", 1.0
        
        # Priority: EXIT > TRIM > HOLD
        action_priorities = {ExitAction.EXIT: 3, ExitAction.TRIM: 2, ExitAction.HOLD: 1}
        best_action = max(actions, key=lambda x: action_priorities[x[0]])
        
        return best_action
    
    async def _check_performance_degradation(self, symbol: str) -> Dict[str, Any]:
        """Check if debate performance has degraded for a symbol using backtest trends."""
        try:
            scheduler = get_backtest_scheduler()
            
            # Get recent performance trends (last 30 days)
            trends = scheduler.get_performance_trends(days=30)
            
            if not trends or len(trends) < 7:
                return {
                    "degraded": False,
                    "change": 0.0,
                    "confidence": 0.0,
                    "message": "Insufficient trend data"
                }
            
            # Find trends for this specific symbol
            symbol_trends = []
            for trend in trends:
                # This would need to be extended to store per-symbol trends
                # For now, we'll use the overall trend as a proxy
                symbol_trends.append(trend)
            
            if len(symbol_trends) < 7:
                return {
                    "degraded": False,
                    "change": 0.0,
                    "confidence": 0.0,
                    "message": "Insufficient symbol-specific trend data"
                }
            
            # Calculate performance change between recent periods
            recent_7_days = symbol_trends[:7]  # Most recent 7 days
            previous_7_days = symbol_trends[7:14] if len(symbol_trends) >= 14 else symbol_trends[7:]  # Previous 7 days
            
            if not previous_7_days:
                return {
                    "degraded": False,
                    "change": 0.0,
                    "confidence": 0.0,
                    "message": "Insufficient historical data for comparison"
                }
            
            # Calculate average improvement for each period
            recent_avg = sum(t.avg_improvement_pct for t in recent_7_days) / len(recent_7_days)
            previous_avg = sum(t.avg_improvement_pct for t in previous_7_days) / len(previous_7_days)
            
            # Calculate change
            change = recent_avg - previous_avg
            
            # Determine if performance has degraded
            degraded = change < -self.degradation_threshold
            
            # Calculate confidence based on consistency and data quality
            recent_consistency = 1.0 - (max(t.avg_improvement_pct for t in recent_7_days) - 
                                       min(t.avg_improvement_pct for t in recent_7_days)) / 10.0
            previous_consistency = 1.0 - (max(t.avg_improvement_pct for t in previous_7_days) - 
                                         min(t.avg_improvement_pct for t in previous_7_days)) / 10.0
            
            # Higher confidence if both periods are consistent and we have sufficient data
            confidence = min(recent_consistency, previous_consistency) * (len(symbol_trends) / 30.0)
            confidence = max(0.0, min(1.0, confidence))
            
            result = {
                "degraded": degraded,
                "change": change,
                "confidence": confidence,
                "recent_avg": recent_avg,
                "previous_avg": previous_avg,
                "trend_points": len(symbol_trends),
                "message": f"Performance changed by {change:.1f}% (recent: {recent_avg:.1f}%, previous: {previous_avg:.1f}%)"
            }
            
            logger.debug(f"Performance degradation check for {symbol}: {result}")
            return result
            
        except Exception as e:
            logger.warning(f"Error checking performance degradation for {symbol}: {e}")
            return {
                "degraded": False,
                "change": 0.0,
                "confidence": 0.0,
                "message": f"Error: {str(e)}"
            }
    
    async def _generate_recommendation(
        self,
        action: ExitAction,
        reason: str,
        confidence: float,
        position_state: PositionState,
        debate_profile: Optional[DebatePerformanceProfile]
    ) -> ExitRecommendation:
        """Generate detailed exit recommendation."""
        recommendation = ExitRecommendation(
            action=action,
            reason=reason,
            confidence=confidence,
            debate_performance={
                "avg_improvement_pct": debate_profile.avg_improvement_pct if debate_profile else None,
                "debate_count": debate_profile.debate_count if debate_profile else 0,
                "success_rate": debate_profile.success_rate if debate_profile else 0,
                "recommendation": debate_profile.recommendation if debate_profile else "normal",
                "confidence_level": debate_profile.confidence_level if debate_profile else 0
            } if debate_profile else None,
            metadata={
                "position_age_hours": (time.time() - position_state.entry_time) / 3600,
                "unrealized_pnl": position_state.unrealized_pnl,
                "unrealized_pnl_pct": position_state.unrealized_pnl_pct,
                "current_multiplier": position_state.debate_multiplier,
                "base_kelly": position_state.base_kelly_fraction,
                "current_kelly": position_state.current_kelly_fraction
            }
        )
        
        # Calculate specific recommendations based on action
        if action == ExitAction.TRIM:
            # Reduce position size
            recommended_kelly = position_state.current_kelly_fraction * self.trim_factor
            recommendation.suggested_kelly_fraction = recommended_kelly
            
            # Calculate stop loss
            if position_state.unrealized_pnl_pct < 0:
                # Tighten stop loss for losing positions
                stop_loss_pct = max(position_state.unrealized_pnl_pct - 2.0, -8.0)  # 2% tighter, max -8%
                stop_loss_price = position_state.entry_price * (1 + stop_loss_pct / 100)
                recommendation.stop_loss_price = stop_loss_price
                recommendation.metadata["stop_loss_pct"] = stop_loss_pct
            
        elif action == ExitAction.EXIT:
            # Full exit recommendation
            recommendation.suggested_kelly_fraction = 0.0
            
            # Set immediate stop loss at current price
            recommendation.stop_loss_price = position_state.current_price
            recommendation.metadata["immediate_exit"] = True
        
        else:  # HOLD
            recommendation.suggested_kelly_fraction = position_state.current_kelly_fraction
            
            # Keep existing stop loss or set default
            if position_state.unrealized_pnl_pct < -3.0:
                stop_loss_pct = max(position_state.unrealized_pnl_pct - 1.0, -10.0)
                stop_loss_price = position_state.entry_price * (1 + stop_loss_pct / 100)
                recommendation.stop_loss_price = stop_loss_price
                recommendation.metadata["stop_loss_pct"] = stop_loss_pct
        
        return recommendation
    
    def record_exit_decision(
        self,
        symbol: str,
        action: ExitAction,
        reason: str,
        execution_price: Optional[float] = None,
        execution_size: Optional[float] = None
    ):
        """Record an exit decision for later analysis."""
        exit_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": action.value,
            "reason": reason,
            "execution_price": execution_price,
            "execution_size": execution_size,
            "position_state": self.position_states.get(symbol).__dict__ if symbol in self.position_states else None
        }
        
        self.exit_history.append(exit_record)
        
        # Trim history if needed
        if len(self.exit_history) > self.max_history_size:
            self.exit_history = self.exit_history[-self.max_history_size:]
        
        # Track SLO for exit decisions
        self.slo_monitor.track_slo(
            metric_name="debate.exit_policy.decision_recorded",
            success=True,
            total=1,
            metadata={
                "symbol": symbol,
                "action": action.value,
                "reason": reason,
                "executed": execution_price is not None
            }
        )
        
        logger.info(f"Recorded exit decision for {symbol}: {action.value} - {reason}")
    
    def get_exit_analytics(self, days_back: int = 30) -> Dict[str, Any]:
        """Get analytics on exit decisions over time."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        recent_exits = [
            record for record in self.exit_history
            if datetime.fromisoformat(record["timestamp"]) >= cutoff_date
        ]
        
        if not recent_exits:
            return {"message": "No exit decisions in specified period"}
        
        # Analyze exit patterns
        action_counts = {}
        reason_counts = {}
        total_exited = 0
        total_trimmed = 0
        
        for record in recent_exits:
            action = record["action"]
            reason = record["reason"]
            
            action_counts[action] = action_counts.get(action, 0) + 1
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            
            if action == "exit":
                total_exited += 1
            elif action == "trim":
                total_trimmed += 1
        
        return {
            "period_days": days_back,
            "total_decisions": len(recent_exits),
            "action_breakdown": action_counts,
            "top_reasons": sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "exit_rate": total_exited / len(recent_exits) if recent_exits else 0,
            "trim_rate": total_trimmed / len(recent_exits) if recent_exits else 0,
            "decisions_by_day": self._group_decisions_by_day(recent_exits)
        }
    
    def _group_decisions_by_day(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group exit decisions by day."""
        daily_counts = {}
        
        for record in records:
            date = record["timestamp"][:10]  # YYYY-MM-DD
            daily_counts[date] = daily_counts.get(date, 0) + 1
        
        return daily_counts
    
    def update_policy_parameters(
        self,
        debate_performance_threshold: float = None,
        confidence_threshold: float = None,
        trim_factor: float = None,
        max_position_age_hours: float = None,
        pnl_loss_threshold: float = None
    ):
        """Update policy parameters."""
        if debate_performance_threshold is not None:
            self.debate_performance_threshold = debate_performance_threshold
        if confidence_threshold is not None:
            self.confidence_threshold = confidence_threshold
        if trim_factor is not None:
            self.trim_factor = trim_factor
        if max_position_age_hours is not None:
            self.max_position_age_hours = max_position_age_hours
        if pnl_loss_threshold is not None:
            self.pnl_loss_threshold = pnl_loss_threshold
        
        logger.info("Updated exit policy parameters")
    
    def clear_position_states(self):
        """Clear all position states (useful for end-of-day reset)."""
        self.position_states.clear()
        logger.info("Cleared all position states")


# Global instance
_exit_policy_instance: Optional[DebateDrivenExitPolicy] = None


def get_debate_exit_policy() -> DebateDrivenExitPolicy:
    """Get the global debate-driven exit policy instance."""
    global _exit_policy_instance
    if _exit_policy_instance is None:
        _exit_policy_instance = DebateDrivenExitPolicy()
    return _exit_policy_instance


async def evaluate_debate_exit_decision(
    symbol: str,
    entry_price: float,
    current_price: float,
    position_size: float,
    entry_time: float,
    base_kelly_fraction: float,
    current_kelly_fraction: float
) -> ExitRecommendation:
    """
    Evaluate exit decision for a position based on debate performance.
    
    Args:
        symbol: Kalshi symbol
        entry_price: Entry price of position
        current_price: Current market price
        position_size: Current position size
        entry_time: Entry timestamp
        base_kelly_fraction: Original Kelly fraction
        current_kelly_fraction: Current Kelly fraction
        
    Returns:
        ExitRecommendation with action and reasoning
    """
    exit_policy = get_debate_exit_policy()
    return await exit_policy.evaluate_position_exit(
        symbol, entry_price, current_price, position_size,
        entry_time, base_kelly_fraction, current_kelly_fraction
    )
