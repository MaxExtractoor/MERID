"""
Consensus Engine Integration for Crypto15MLane

This module provides integration helpers for Crypto15MLane to
update the consensus engine with Kalshi + RCK context.

Key features:
- Update lane intents with KalshiContext and RiskDecisionContext
- Convert consensus results to votes with full context
- Bridge between lane data and consensus engine data structures
"""

from typing import Dict, Any, Optional
import time

from core.consensus_engine import get_consensus_engine, Vote, ConsensusResult
from schemas.consensus import KalshiContext, RiskDecisionContext


def update_consensus_engine_with_lane_data(
    lane_id: str,
    kalshi_context: KalshiContext,
    risk_decision: RiskDecisionContext
) -> None:
    """
    Update the consensus engine with current lane data.
    
    This should be called by Crypto15MLane after each consensus/risk evaluation
    to provide the API endpoints with current Kalshi + RCK context.
    
    Args:
        lane_id: Lane identifier (e.g., "BTC_15M")
        kalshi_context: Kalshi market context
        risk_decision: RCK decision context
    """
    engine = get_consensus_engine()
    
    # Convert dataclasses to dictionaries for storage
    intent_data = {
        "kalshi_context": kalshi_context.to_dict(),
        "risk_decision": risk_decision.to_dict(),
        "updated_at": time.time(),
    }
    
    # Update engine's current intents
    engine.update_lane_intent(lane_id, intent_data)


def create_vote_from_lane_decision(
    agent_id: str,
    lane_id: str,
    kalshi_context: KalshiContext,
    risk_decision: RiskDecisionContext,
    confidence: float = 0.8,
    trust: float = 1.0
) -> Vote:
    """
    Create a Vote object from lane decision data.
    
    This converts Crypto15MLane's consensus/risk evaluation into
    a Vote that can be submitted to the consensus engine.
    
    Args:
        agent_id: Agent identifier (e.g., "sentiment_agent")
        lane_id: Lane identifier
        kalshi_context: Kalshi market context
        risk_decision: RCK decision context
        confidence: Vote confidence (0-1)
        trust: Agent trust score
        
    Returns:
        Vote object with full Kalshi + RCK context
    """
    # Determine signal from direction
    signal_map = {
        "YES": "bullish",
        "NO": "bearish", 
        "FLAT": "neutral"
    }
    signal = signal_map.get(risk_decision.direction, "neutral")
    
    return Vote(
        agent_id=agent_id,
        proposal=f"trade_{kalshi_context.market_id}",
        signal=signal,
        confidence=confidence,
        trust=trust,
        timestamp=time.time(),
        
        # Kalshi + RCK context
        lane_id=lane_id,
        market_id=kalshi_context.market_id,
        symbol=kalshi_context.symbol,
        side=risk_decision.direction,
        p_true=risk_decision.p_true,
        p_implied=risk_decision.p_implied,
        edge_bps=risk_decision.edge_bps,
        kelly_fraction_used=risk_decision.kelly_fraction_used,
        size_contracts=risk_decision.size_contracts,
    )


def create_consensus_result_from_lane_decision(
    lane_id: str,
    kalshi_context: KalshiContext,
    risk_decision: RiskDecisionContext,
    votes: list,
    decision: str,
    confidence: float,
    quorum_met: bool = True,
    vetoed: bool = False,
    veto_reason: str = ""
) -> ConsensusResult:
    """
    Create a ConsensusResult from lane decision data.
    
    This converts Crypto15MLane's final decision into a ConsensusResult
    that can be logged and published by the consensus engine.
    
    Args:
        lane_id: Lane identifier
        kalshi_context: Kalshi market context
        risk_decision: RCK decision context
        votes: List of votes that contributed to this decision
        decision: Final decision string
        confidence: Decision confidence
        quorum_met: Whether quorum was met
        vetoed: Whether decision was vetoed
        veto_reason: Reason for veto
        
    Returns:
        ConsensusResult with full Kalshi + RCK context
    """
    # Determine signal from direction
    signal_map = {
        "YES": "bullish",
        "NO": "bearish",
        "FLAT": "neutral"
    }
    signal = signal_map.get(risk_decision.direction, "neutral")
    
    return ConsensusResult(
        decision=decision,
        signal=signal,
        confidence=confidence,
        votes=votes,
        quorum_met=quorum_met,
        vetoed=vetoed,
        veto_reason=veto_reason,
        timestamp=time.time(),
        
        # Kalshi + RCK context
        lane_id=lane_id,
        market_id=kalshi_context.market_id,
        symbol=kalshi_context.symbol,
        series_ticker=kalshi_context.series_ticker,
        timeframe=kalshi_context.timeframe,
        yes_bid_cents=kalshi_context.yes_bid_cents,
        yes_ask_cents=kalshi_context.yes_ask_cents,
        no_bid_cents=kalshi_context.no_bid_cents,
        no_ask_cents=kalshi_context.no_ask_cents,
        p_yes_implied=kalshi_context.p_yes_implied,
        p_yes_devig=kalshi_context.p_yes_devig,
        p_true=risk_decision.p_true,
        edge_bps=risk_decision.edge_bps,
        kelly_fraction_full=risk_decision.kelly_fraction_full,
        kelly_fraction_rck=risk_decision.kelly_fraction_rck,
        kelly_fraction_used=risk_decision.kelly_fraction_used,
        target_drawdown=risk_decision.target_drawdown,
        drawdown_probability=risk_decision.drawdown_probability,
        safety_factor=risk_decision.safety_factor,
        direction=risk_decision.direction,
        size_contracts=risk_decision.size_contracts,
        bankroll_before=risk_decision.bankroll_before,
        bankroll_after=risk_decision.bankroll_after,
    )


def submit_lane_votes_to_consensus(
    lane_id: str,
    kalshi_context: KalshiContext,
    risk_decision: RiskDecisionContext,
    agent_votes: Dict[str, float] = None
) -> None:
    """
    Submit votes from lane agents to the consensus engine.
    
    This is a convenience function that creates and submits votes
    from all relevant lane agents.
    
    Args:
        lane_id: Lane identifier
        kalshi_context: Kalshi market context
        risk_decision: RCK decision context
        agent_votes: Dict of agent_id -> confidence (optional)
    """
    engine = get_consensus_engine()
    
    if agent_votes is None:
        # Default agents and their confidence levels
        agent_votes = {
            "sentiment_agent": 0.8,
            "risk_agent": 0.9,
            "skeptic_agent": 0.7,
        }
    
    for agent_id, confidence in agent_votes.items():
        vote = create_vote_from_lane_decision(
            agent_id=agent_id,
            lane_id=lane_id,
            kalshi_context=kalshi_context,
            risk_decision=risk_decision,
            confidence=confidence,
            trust=engine.trust_scores.get(agent_id, 1.0)
        )
        
        # Add to pending votes
        engine.pending_votes[agent_id] = vote


# Integration example for Crypto15MLane
"""
Example usage in Crypto15MLane:

async def _run_cycle(self):
    # ... existing cycle logic ...
    
    # After consensus and risk evaluation:
    consensus_result = self._get_consensus(best_market, sentiment_bundle)
    risk_decision = self._evaluate_risk(consensus_result, sentiment_bundle)
    
    if consensus_result and risk_decision:
        # Create Kalshi and RCK contexts
        kalshi_context = KalshiContext(
            market_id=best_market["market_id"],
            market_ticker=best_market["market_ticker"],
            series_ticker=best_market["series_ticker"],
            symbol=self.cfg.symbol,
            timeframe="15m",
            yes_bid_cents=best_market.get("yes_bid"),
            yes_ask_cents=best_market.get("yes_ask"),
            no_bid_cents=best_market.get("no_bid"),
            no_ask_cents=best_market.get("no_ask"),
            p_yes_implied=consensus_result["yes_price_cents"] / 100.0,
            p_yes_devig=consensus_result["p_implied"],
        )
        
        risk_context = RiskDecisionContext(
            p_true=consensus_result["p_true"],
            p_implied=consensus_result["p_implied"],
            edge_bps=consensus_result["edge_bps"],
            kelly_fraction_full=risk_decision["kelly_fraction_full"],
            kelly_fraction_rck=risk_decision["risk_constrained_kelly"]["f_rck"],
            kelly_fraction_used=risk_decision["kelly_fraction_used"],
            target_drawdown=risk_decision["risk_constrained_kelly"]["target_drawdown"],
            drawdown_probability=risk_decision["risk_constrained_kelly"]["drawdown_probability"],
            safety_factor=risk_decision["risk_constrained_kelly"]["safety_factor"],
            direction=risk_decision["risk_constrained_kelly"]["direction"],
            size_contracts=int(risk_decision["position_size"] * 100),
        )
        
        # Update consensus engine with current lane data
        update_consensus_engine_with_lane_data(
            self.lane_id, kalshi_context, risk_context
        )
        
        # Submit votes to consensus engine
        submit_lane_votes_to_consensus(
            self.lane_id, kalshi_context, risk_context
        )
"""
