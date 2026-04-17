"""
Enhanced ConsensusBlock Integration with Crypto15MLane

This example demonstrates how to use the enhanced ConsensusBlock with
KalshiContext and RiskDecisionContext for complete audit replay of
RCK decisions in 15m crypto lanes.

Key features:
- Complete Kalshi market context capture
- Full RCK decision state recording
- Immutable, hashable decision chain
- Complete replay capability
"""

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Any, Optional

from schemas.consensus import (
    ConsensusBlock, ConsensusVote, ConsensusOutcome, VoteType,
    KalshiContext, RiskDecisionContext
)
from merid.lanes.crypto15m_lane import (
    kelly_fraction_binary, solve_rck_fraction, 
    estimate_p_true_advanced, devig_yes_no
)


def create_kalshi_context_from_lane(market_data: Dict[str, Any], 
                                  consensus_result: Dict[str, Any]) -> KalshiContext:
    """
    Create KalshiContext from lane market data and consensus result.
    
    Args:
        market_data: Raw market data from Kalshi catalog
        consensus_result: Consensus calculation result
        
    Returns:
        Populated KalshiContext
    """
    return KalshiContext(
        market_id=market_data.get("ticker", ""),
        market_ticker=market_data.get("market_ticker", ""),
        series_ticker=market_data.get("series_ticker", ""),
        symbol=market_data.get("asset", ""),
        timeframe="15m",
        yes_bid_cents=market_data.get("yes_bid"),
        yes_ask_cents=market_data.get("yes_ask"),
        no_bid_cents=market_data.get("no_bid"),
        no_ask_cents=market_data.get("no_ask"),
        p_yes_implied=consensus_result.get("yes_price_cents", 50) / 100.0,
        p_yes_devig=consensus_result.get("p_implied", 0.5),
        settlement_time=market_data.get("expected_expiration_time_ts"),
        category=market_data.get("category", "CRYPTO"),
    )


def create_risk_context_from_decision(risk_decision: Dict[str, Any],
                                    consensus_result: Dict[str, Any],
                                    bankroll_before: float,
                                    bankroll_after: float) -> RiskDecisionContext:
    """
    Create RiskDecisionContext from lane risk evaluation.
    
    Args:
        risk_decision: Risk evaluation result from lane
        consensus_result: Consensus calculation result
        bankroll_before: Bankroll before trade
        bankroll_after: Bankroll after trade
        
    Returns:
        Populated RiskDecisionContext
    """
    rck_info = risk_decision.get("risk_constrained_kelly", {})
    
    return RiskDecisionContext(
        p_true=consensus_result.get("p_true", 0.5),
        p_implied=consensus_result.get("p_implied", 0.5),
        edge_bps=consensus_result.get("edge_bps", 0.0),
        kelly_fraction_full=risk_decision.get("kelly_fraction_full", 0.0),
        kelly_fraction_rck=rck_info.get("f_rck", 0.0),
        kelly_fraction_used=risk_decision.get("kelly_fraction_used", 0.0),
        target_drawdown=rck_info.get("target_drawdown", 0.1),
        drawdown_probability=rck_info.get("drawdown_probability", 0.1),
        safety_factor=rck_info.get("safety_factor", 0.8),
        fraction_of_full=rck_info.get("fraction_of_full", 0.0),
        bankroll_before=bankroll_before,
        bankroll_after=bankroll_after,
        direction="YES" if consensus_result.get("direction") == "yes" else "NO",
        size_contracts=int(risk_decision.get("position_size", 0) * 100),  # Convert to contracts
    )


def create_consensus_block_from_lane(
    market_data: Dict[str, Any],
    consensus_result: Dict[str, Any],
    risk_decision: Dict[str, Any],
    votes: list,
    previous_block: Optional[ConsensusBlock] = None,
    bankroll_before: float = 1000.0,
    bankroll_after: float = 1025.0,
    block_number: int = 0
) -> ConsensusBlock:
    """
    Create a complete ConsensusBlock from lane decision data.
    
    Args:
        market_data: Kalshi market data
        consensus_result: Consensus calculation result
        risk_decision: Risk evaluation result
        votes: Agent votes (if any)
        previous_block: Previous block in chain
        bankroll_before: Bankroll before this decision
        bankroll_after: Bankroll after this decision
        block_number: Block number in chain
        
    Returns:
        Complete ConsensusBlock with full context
    """
    # Create intent hash
    intent_id = market_data.get("ticker", "")
    intent_hash = hashlib.sha256(intent_id.encode()).hexdigest()[:16]
    intent_summary = f"{market_data.get('asset', '')} {market_data.get('ticker', '')} " \
                    f"{'YES' if consensus_result.get('direction') == 'yes' else 'NO'} " \
                    f"@ {consensus_result.get('yes_price_cents', 50)}c"
    
    # Create block
    block = ConsensusBlock(
        block_number=block_number,
        previous_hash=previous_block.block_hash if previous_block else "genesis",
        intent_id=intent_id,
        intent_hash=intent_hash,
        intent_summary=intent_summary,
        votes=votes,
        outcome=ConsensusOutcome.APPROVED if risk_decision.get("approved", False) else ConsensusOutcome.REJECTED,
        consensus_score=0.8 if risk_decision.get("approved", False) else 0.2,  # Simplified
        participating_agents=len(votes),
        required_agents=3,
        kalshi=create_kalshi_context_from_lane(market_data, consensus_result),
        risk_decision=create_risk_context_from_decision(
            risk_decision, consensus_result, bankroll_before, bankroll_after
        ),
    )
    
    return block


def example_lane_to_block():
    """
    Example: Convert a Crypto15MLane decision to a ConsensusBlock.
    
    This shows the complete integration pattern for production use.
    """
    # Simulate market data (would come from Kalshi catalog)
    market_data = {
        "ticker": "KXBTC15M-20260306-0115",
        "market_ticker": "KXBTC15M-20260306-0115",
        "series_ticker": "KXBTC15M",
        "asset": "BTC",
        "yes_bid": 48,
        "yes_ask": 52,
        "no_bid": 48,
        "no_ask": 52,
        "expected_expiration_time_ts": time.time() + 900,
        "category": "CRYPTO",
    }
    
    # Simulate consensus result (would come from lane's _get_consensus)
    consensus_result = {
        "market_id": "KXBTC15M-20260306-0115",
        "direction": "yes",
        "p_true": 0.58,
        "p_implied": 0.52,
        "edge_bps": 600,
        "yes_price_cents": 52,
        "no_price_cents": 48,
        "features": {
            "rti_signal": 0.08,
            "fg_contrarian": 0.05,
            "flow_imbalance": 0.6,
            "asset_sentiment": 0.55,
        }
    }
    
    # Simulate risk decision (would come from lane's _evaluate_risk)
    risk_decision = {
        "approved": True,
        "position_size": 25.0,
        "kelly_fraction_full": 0.42,
        "kelly_fraction_used": 0.28,
        "risk_constrained_kelly": {
            "method": "rck_solver",
            "f_rck": 0.35,
            "target_drawdown": 0.1,
            "drawdown_probability": 0.1,
            "safety_factor": 0.8,
            "fraction_of_full": 0.67,
        }
    }
    
    # Simulate agent votes (would come from consensus process)
    votes = [
        ConsensusVote(
            agent_id="sentiment_agent",
            vote=VoteType.APPROVE,
            confidence=0.75,
            trust_weight=0.8,
            reasoning="Strong positive sentiment and edge",
            signal="bullish"
        ),
        ConsensusVote(
            agent_id="risk_agent",
            vote=VoteType.APPROVE,
            confidence=0.65,
            trust_weight=0.9,
            reasoning="RCK fraction acceptable",
            risk_score=0.3
        ),
        ConsensusVote(
            agent_id="skeptic_agent",
            vote=VoteType.ABSTAIN,
            confidence=0.5,
            trust_weight=0.7,
            reasoning="Insufficient edge confidence"
        ),
    ]
    
    # Create consensus block
    block = create_consensus_block_from_lane(
        market_data=market_data,
        consensus_result=consensus_result,
        risk_decision=risk_decision,
        votes=votes,
        previous_block=None,  # Genesis block
        bankroll_before=1000.0,
        bankroll_after=1025.0,
        block_number=1
    )
    
    print("=== Created ConsensusBlock ===")
    print(f"Block ID: {block.block_id}")
    print(f"Block Hash: {block.block_hash}")
    print(f"Intent: {block.intent_summary}")
    print(f"Outcome: {block.outcome.value}")
    print(f"Kalshi Market: {block.kalshi.market_ticker}")
    print(f"Symbol: {block.kalshi.symbol}")
    print(f"Direction: {block.risk_decision.direction}")
    print(f"Edge: {block.risk_decision.edge_bps} bps")
    print(f"Kelly Used: {block.risk_decision.kelly_fraction_used:.3f}")
    print(f"Contracts: {block.risk_decision.size_contracts}")
    
    return block


def example_block_chain():
    """
    Example: Create a chain of consensus blocks.
    
    Demonstrates how blocks link together for audit trail.
    """
    print("\n=== Creating Block Chain ===")
    
    blocks = []
    previous_block = None
    
    for i in range(3):
        # Simulate sequential decisions
        market_data = {
            "ticker": f"KXBTC15M-20260306-{i:02d}15",
            "market_ticker": f"KXBTC15M-20260306-{i:02d}15",
            "series_ticker": "KXBTC15M",
            "asset": "BTC",
            "yes_bid": 48 + i,
            "yes_ask": 52 + i,
            "category": "CRYPTO",
        }
        
        consensus_result = {
            "market_id": f"KXBTC15M-20260306-{i:02d}15",
            "direction": "yes" if i % 2 == 0 else "no",
            "p_true": 0.55 + (i * 0.02),
            "p_implied": 0.50 + (i * 0.01),
            "edge_bps": 500 + (i * 100),
            "yes_price_cents": 52 + i,
        }
        
        risk_decision = {
            "approved": True,
            "kelly_fraction_used": 0.25 + (i * 0.05),
            "risk_constrained_kelly": {
                "f_rck": 0.30 + (i * 0.05),
                "target_drawdown": 0.1,
                "safety_factor": 0.8,
                "fraction_of_full": 0.6 + (i * 0.1),
            }
        }
        
        votes = [
            ConsensusVote(
                agent_id="agent_1",
                vote=VoteType.APPROVE,
                confidence=0.7,
                trust_weight=0.8,
                reasoning=f"Decision {i+1}"
            )
        ]
        
        block = create_consensus_block_from_lane(
            market_data=market_data,
            consensus_result=consensus_result,
            risk_decision=risk_decision,
            votes=votes,
            previous_block=previous_block,
            block_number=i + 1
        )
        
        blocks.append(block)
        previous_block = block
        
        print(f"Block {i+1}: {block.block_hash[:8]}... -> "
              f"Prev: {block.previous_hash[:8] if block.previous_hash != 'genesis' else 'genesis'}")
    
    # Verify chain integrity
    print(f"\nChain Integrity Check:")
    for i, block in enumerate(blocks):
        is_valid = block.verify_chain(blocks[i-1] if i > 0 else None)
        print(f"  Block {i+1}: {'✓' if is_valid else '✗'} {block.block_hash[:8]}...")
    
    return blocks


def example_block_replay(blocks: list):
    """
    Example: Replay decisions from stored blocks.
    
    Shows how to reconstruct exactly what the lane decided.
    """
    print("\n=== Block Replay Example ===")
    
    for i, block in enumerate(blocks):
        print(f"\nReplaying Block {i+1}:")
        print(f"  Market: {block.kalshi.market_ticker}")
        print(f"  Symbol: {block.kalshi.symbol}")
        print(f"  Settlement: {time.ctime(block.kalshi.settlement_time) if block.kalshi.settlement_time else 'Unknown'}")
        print(f"  Market Prices: YES {block.kalshi.yes_bid_cents}-{block.kalshi.yes_ask_cents}c")
        print(f"  De-vigged Probability: {block.kalshi.p_yes_devig:.3f}")
        print(f"  True Probability: {block.risk_decision.p_true:.3f}")
        print(f"  Edge: {block.risk_decision.edge_bps} bps")
        print(f"  Decision: {block.risk_decision.direction}")
        print(f"  Full Kelly: {block.risk_decision.kelly_fraction_full:.3f}")
        print(f"  RCK Kelly: {block.risk_decision.kelly_fraction_rck:.3f}")
        print(f"  Used Kelly: {block.risk_decision.kelly_fraction_used:.3f}")
        print(f"  Target DD: {block.risk_decision.target_drawdown:.1%}")
        print(f"  Safety Factor: {block.risk_decision.safety_factor:.1f}")
        print(f"  Contracts: {block.risk_decision.size_contracts}")
        print(f"  Bankroll: ${block.risk_decision.bankroll_before:.2f} -> ${block.risk_decision.bankroll_after:.2f}")
        print(f"  Outcome: {block.outcome.value}")
        print(f"  Votes: {len(block.votes)} agents")
        
        # Show agent reasoning
        for vote in block.votes:
            print(f"    {vote.agent_id}: {vote.vote.value} (conf: {vote.confidence:.2f}) - {vote.reasoning}")


def example_block_serialization():
    """
    Example: Serialize and deserialize blocks for storage.
    
    Shows how to persist blocks and reconstruct them later.
    """
    print("\n=== Block Serialization Example ===")
    
    # Create a sample block
    block = example_lane_to_block()
    
    # Serialize to JSON
    json_str = block.to_json()
    print(f"Serialized block size: {len(json_str)} characters")
    print(f"JSON preview: {json_str[:200]}...")
    
    # Deserialize from JSON
    reconstructed_block = ConsensusBlock.from_json(json_str)
    
    # Verify integrity
    hash_match = block.block_hash == reconstructed_block.block_hash
    print(f"Hash integrity: {'✓' if hash_match else '✗'}")
    print(f"Original hash: {block.block_hash}")
    print(f"Reconstructed hash: {reconstructed_block.block_hash}")
    
    # Compare key fields
    fields_match = (
        block.kalshi.market_id == reconstructed_block.kalshi.market_id and
        block.risk_decision.p_true == reconstructed_block.risk_decision.p_true and
        block.risk_decision.kelly_fraction_used == reconstructed_block.risk_decision.kelly_fraction_used
    )
    print(f"Key fields match: {'✓' if fields_match else '✗'}")
    
    return reconstructed_block


def main():
    """Run all examples."""
    print("Enhanced ConsensusBlock Integration Examples")
    print("=" * 60)
    
    # Run examples
    block = example_lane_to_block()
    blocks = example_block_chain()
    example_block_replay(blocks)
    example_block_serialization()
    
    print("\n" + "=" * 60)
    print("All examples completed successfully!")
    print("\nKey Benefits:")
    print("• Complete Kalshi market context capture")
    print("• Full RCK decision state recording")
    print("• Immutable, hashable decision chain")
    print("• Complete replay capability")
    print("• Audit trail for regulatory compliance")
    print("• Backtest validation against live decisions")


if __name__ == "__main__":
    main()
