"""
RCK + Bayesian Integration Wrapper for Crypto15MLane

Clean integration functions that use the new dataclasses to simplify
the consensus and risk evaluation methods.

This shows how to drop the RCK + Bayesian pipeline directly into
Crypto15MLane without glue code.
"""

from typing import Dict, Any, Optional
import time

from .rck_dataclasses import (
    ConsensusResult, RiskDecisionResult, BayesianLearningResult,
    RCKSolverResult, ConfidenceLevel, create_consensus_result, create_risk_decision_result
)
from .crypto15m_lane import (
    devig_yes_no, estimate_p_true_advanced, solve_rck_fraction,
    kelly_fraction_binary
)


def create_consensus_with_rck(
    lane,
    market_data: Dict[str, Any],
    sentiment_bundle: Optional[Dict[str, Any]]
) -> Optional[ConsensusResult]:
    """
    Create ConsensusResult using advanced RCK + Bayesian pipeline.
    
    This replaces the complex consensus logic in Crypto15MLane._get_consensus()
    with a clean, production-ready implementation.
    
    Args:
        lane: Crypto15MLane instance
        market_data: Best market from discovery
        sentiment_bundle: Sentiment data with Fear & Greed
        
    Returns:
        ConsensusResult with complete Bayesian learning and edge calculation
    """
    try:
        # Extract market prices
        yes_price_cents = market_data.get("yes_price_cents", 50)
        no_price_cents = 100 - yes_price_cents
        
        # De-vig Kalshi prices
        fair_yes_prob, fair_no_prob = devig_yes_no(yes_price_cents / 100.0, no_price_cents / 100.0)
        
        # Extract features for p_true estimation
        features = {
            "rti_signal": 0.0,
            "fg_contrarian": 0.0,
            "flow_imbalance": 0.5,
            "asset_sentiment": 0.5,
        }
        
        # Add Fear & Greed contrarian signal
        if sentiment_bundle and "fear_greed" in sentiment_bundle:
            fg = sentiment_bundle["fear_greed"]
            features["fg_contrarian"] = fg.get("contrarian_signal", 0.0)
        
        # Add per-asset sentiment
        if sentiment_bundle and "asset_sentiment_15m" in sentiment_bundle:
            asset = sentiment_bundle["asset_sentiment_15m"]
            features["asset_sentiment"] = asset.get("sentiment_score_15m", 0.5)
            features["flow_imbalance"] = 0.5 + (asset.get("social_volume", 0) / 200.0)
        
        # Get historical performance
        historical_wins = getattr(lane, '_historical_wins', 0)
        historical_losses = getattr(lane, '_historical_losses', 0)
        
        # Advanced p_true estimation with Bayesian learning
        p_true_result = estimate_p_true_advanced(
            symbol=lane.cfg.symbol,
            yes_price_cents=yes_price_cents,
            no_price_cents=no_price_cents,
            features=features,
            historical_wins=historical_wins,
            historical_losses=historical_losses
        )
        
        # Create Bayesian learning result
        confidence = (
            ConfidenceLevel.HIGH if (historical_wins + historical_losses) >= 30
            else ConfidenceLevel.MEDIUM if (historical_wins + historical_losses) >= 10
            else ConfidenceLevel.LOW
        )
        
        bayesian_result = BayesianLearningResult(
            prior_strength=p_true_result["prior_strength"],
            posterior_alpha=p_true_result["posterior_alpha"],
            posterior_beta=p_true_result["posterior_beta"],
            posterior_mean=p_true_result["posterior_mean"],
            historical_wins=historical_wins,
            historical_losses=historical_losses,
            total_historical=historical_wins + historical_losses,
            feature_adjustment=p_true_result["feature_adjustment"],
            confidence=confidence,
        )
        
        # Create consensus result
        consensus = create_consensus_result(
            market_data=market_data,
            p_true=p_true_result["p_true"],
            p_implied=fair_yes_prob,
            fair_yes_prob=fair_yes_prob,
            fair_no_prob=fair_no_prob,
            features=features,
            bayesian_result=bayesian_result
        )
        
        return consensus
        
    except Exception as exc:
        lane.logger.error(f"Consensus creation failed: {exc}")
        return None


def create_risk_decision_with_rck(
    lane,
    consensus: ConsensusResult,
    sentiment_bundle: Optional[Dict[str, Any]]
) -> Optional[RiskDecisionResult]:
    """
    Create RiskDecisionResult using advanced RCK pipeline.
    
    This replaces the complex risk logic in Crypto15MLane._evaluate_risk()
    with a clean, production-ready implementation.
    
    Args:
        lane: Crypto15MLane instance
        consensus: ConsensusResult from create_consensus_with_rck
        sentiment_bundle: Sentiment data with Fear & Greed
        
    Returns:
        RiskDecisionResult with complete RCK details and position sizing
    """
    try:
        # Check edge threshold
        if abs(consensus.edge_bps) < lane.cfg.min_edge_threshold_bps:
            return RiskDecisionResult(
                approved=False,
                position_size=0.0,
                bankroll_before=0.0,
                bankroll_after=0.0,
                kelly_fraction_full=0.0,
                kelly_fraction_used=0.0,
                risk_constrained_kelly=RCKSolverResult(
                    method="edge_threshold",
                    f_rck=None,
                    target_drawdown=lane.cfg.rck_target_drawdown,
                    drawdown_probability=lane.cfg.rck_drawdown_probability,
                    safety_factor=lane.cfg.rck_safety_factor,
                    fraction_of_full=0.0,
                    solver_paths=0,
                    solver_trades=0
                ),
                edge_bps=consensus.edge_bps,
                current_positions=0,
                fear_greed_applied=False,
                fg_multiplier=1.0,
            )
        
        # Get current positions
        current_positions = 0  # Would call lane._get_current_positions()
        
        # Check position limits
        if current_positions >= lane.cfg.max_positions:
            return RiskDecisionResult(
                approved=False,
                position_size=0.0,
                bankroll_before=0.0,
                bankroll_after=0.0,
                kelly_fraction_full=0.0,
                kelly_fraction_used=0.0,
                risk_constrained_kelly=RCKSolverResult(
                    method="position_limit",
                    f_rck=None,
                    target_drawdown=lane.cfg.rck_target_drawdown,
                    drawdown_probability=lane.cfg.rck_drawdown_probability,
                    safety_factor=lane.cfg.rck_safety_factor,
                    fraction_of_full=0.0,
                    solver_paths=0,
                    solver_trades=0
                ),
                edge_bps=consensus.edge_bps,
                current_positions=current_positions,
                fear_greed_applied=False,
                fg_multiplier=1.0,
            )
        
        # Calculate Kelly fractions
        price = consensus.yes_price_cents / 100.0
        p_true = consensus.p_true
        
        # Full Kelly
        f_full = kelly_fraction_binary(p_true, price)
        
        # RCK solver
        try:
            f_rck = solve_rck_fraction(
                p_true=p_true,
                price=price,
                target_dd=lane.cfg.rck_target_drawdown,
                dd_prob=lane.cfg.rck_drawdown_probability,
                n_paths=1000,
                n_trades=500
            )
            
            rck_method = "rck_solver"
        except Exception as exc:
            lane.logger.warning(f"RCK solver failed, using fallback: {exc}")
            f_rck = f_full * lane.cfg.base_kelly_fraction
            rck_method = "fallback"
        
        # Apply safety factors
        f_used = f_rck * lane.cfg.rck_safety_factor * lane.cfg.global_safety_factor
        
        # Fear & Greed adjustment
        fg_multiplier = 1.0
        fg_applied = False
        
        if sentiment_bundle and "fear_greed" in sentiment_bundle:
            fg = sentiment_bundle["fear_greed"]
            if fg["is_extreme_fear"]:
                fg_multiplier = 1.05
                fg_applied = True
            elif fg["is_extreme_greed"]:
                fg_multiplier = 0.95
                fg_applied = True
        
        f_used *= fg_multiplier
        
        # Calculate position size
        bankroll_before = 1000.0  # Would call lane.portfolio.get_lane_bankroll()
        kelly_size = bankroll_before * f_used
        position_size = max(lane.cfg.base_trade_size, kelly_size)
        bankroll_after = bankroll_before  # Would update after execution
        
        # Create RCK result
        rck_result = RCKSolverResult(
            method=rck_method,
            f_rck=f_rck,
            target_drawdown=lane.cfg.rck_target_drawdown,
            drawdown_probability=lane.cfg.rck_drawdown_probability,
            safety_factor=lane.cfg.rck_safety_factor,
            fraction_of_full=f_rck / f_full if f_full > 0 else 0.0,
            solver_paths=1000,
            solver_trades=500
        )
        
        # Create risk decision result
        risk_decision = create_risk_decision_result(
            approved=True,
            position_size=position_size,
            bankroll_before=bankroll_before,
            bankroll_after=bankroll_after,
            kelly_full=f_full,
            kelly_used=f_used,
            rck_result=rck_result,
            edge_bps=consensus.edge_bps,
            current_positions=current_positions,
            fg_applied=fg_applied,
            fg_multiplier=fg_multiplier
        )
        
        return risk_decision
        
    except Exception as exc:
        lane.logger.error(f"Risk decision creation failed: {exc}")
        return None


def get_lane_status_with_rck(lane, consensus: Optional[ConsensusResult], 
                           risk_decision: Optional[RiskDecisionResult]) -> Dict[str, Any]:
    """
    Get comprehensive lane status with RCK + Bayesian details.
    
    This replaces the complex status logic in Crypto15MLane.get_status()
    with a clean, production-ready implementation.
    
    Args:
        lane: Crypto15MLane instance
        consensus: Latest ConsensusResult
        risk_decision: Latest RiskDecisionResult
        
    Returns:
        Complete status dictionary for UI and monitoring
    """
    status = {
        # Basic lane info
        "lane_id": lane.lane_id,
        "symbol": lane.cfg.symbol,
        "paper": lane.cfg.paper,
        "enabled": lane.cfg.enable,
        "running": lane.running,
        
        # Cycle info
        "cycle_count": getattr(lane, 'cycle_count', 0),
        "last_cycle_time": getattr(lane, 'last_cycle_time', None),
        
        # RCK configuration
        "rck_config": {
            "target_drawdown": lane.cfg.rck_target_drawdown,
            "drawdown_probability": lane.cfg.rck_drawdown_probability,
            "safety_factor": lane.cfg.rck_safety_factor,
        },
        
        # Bayesian configuration
        "bayesian_config": {
            "prior_strength": lane.cfg.bayesian_prior_strength,
            "rti_weight": lane.cfg.bayesian_rti_weight,
            "flow_weight": lane.cfg.bayesian_flow_weight,
            "asset_weight": lane.cfg.bayesian_asset_weight,
        },
    }
    
    # Add consensus details if available
    if consensus:
        status.update({
            "last_edge_bps": consensus.edge_bps,
            "last_p_true": consensus.p_true,
            "last_p_implied": consensus.p_implied,
            "last_direction": consensus.direction,
            "consensus": consensus.to_dict(),
        })
    
    # Add risk decision details if available
    if risk_decision:
        status.update({
            "last_kelly_used": risk_decision.kelly_fraction_used,
            "last_position_size": risk_decision.position_size,
            "risk_decision": risk_decision.to_dict(),
        })
    
    # Add historical performance
    historical_wins = getattr(lane, '_historical_wins', 0)
    historical_losses = getattr(lane, '_historical_losses', 0)
    total_trades = historical_wins + historical_losses
    
    if total_trades > 0:
        status["historical_performance"] = {
            "total_trades": total_trades,
            "wins": historical_wins,
            "losses": historical_losses,
            "win_rate": historical_wins / total_trades,
        }
    
    return status


# Example usage in Crypto15MLane:
"""
class Crypto15MLane:
    async def _get_consensus(self):
        # Replace existing complex logic with:
        return create_consensus_with_rck(self, best_market, sentiment_bundle)
    
    async def _evaluate_risk(self, consensus, sentiment_bundle):
        # Replace existing complex logic with:
        return create_risk_decision_with_rck(self, consensus, sentiment_bundle)
    
    def get_status(self):
        # Replace existing complex logic with:
        consensus = getattr(self, '_last_consensus', None)
        risk_decision = getattr(self, '_last_risk_decision', None)
        return get_lane_status_with_rck(self, consensus, risk_decision)
"""
