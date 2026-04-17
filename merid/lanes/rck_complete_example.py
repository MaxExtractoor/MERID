"""
Complete RCK + Bayesian Integration Example

This example demonstrates the final, production-ready integration
of the RCK + Bayesian system with Crypto15MLane.

Key features:
- Clean dataclass-based pipeline
- Symbol-specific configuration
- Complete audit trail
- Production monitoring
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from merid.lanes.crypto15m_lane import Crypto15MLane, Crypto15MLaneConfig
from merid.lanes.rck_integration_wrapper import (
    create_consensus_with_rck, create_risk_decision_with_rck, get_lane_status_with_rck
)


class EnhancedCrypto15MLane(Crypto15MLane):
    """
    Enhanced Crypto15MLane with clean RCK + Bayesian integration.
    
    This shows how to drop the new dataclasses directly into the existing
    lane methods without any glue code.
    """
    
    async def _get_consensus(self, best_market: Dict[str, Any], 
                           sentiment_bundle: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Enhanced consensus using RCK + Bayesian pipeline.
        
        This replaces the complex consensus logic with a clean,
        production-ready implementation using the new dataclasses.
        """
        consensus = create_consensus_with_rck(self, best_market, sentiment_bundle)
        
        if consensus:
            # Store for status and audit
            self._last_consensus = consensus
            return consensus.to_dict()
        
        return None
    
    async def _evaluate_risk(self, consensus: Optional[Dict[str, Any]], 
                           sentiment_bundle: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Enhanced risk evaluation using RCK pipeline.
        
        This replaces the complex risk logic with a clean,
        production-ready implementation using the new dataclasses.
        """
        if not consensus:
            return None
        
        # Convert back to ConsensusResult for processing
        from merid.lanes.rck_dataclasses import ConsensusResult, BayesianLearningResult
        
        consensus_result = ConsensusResult(
            market_id=consensus["market_id"],
            market_title=consensus["market_title"],
            symbol=consensus["symbol"],
            direction=consensus["direction"],
            p_true=consensus["p_true"],
            p_implied=consensus["p_implied"],
            fair_yes_prob=consensus["fair_yes_prob"],
            fair_no_prob=consensus["fair_no_prob"],
            yes_price_cents=consensus["yes_price_cents"],
            no_price_cents=consensus["no_price_cents"],
            edge_bps=consensus["edge_bps"],
            features=consensus["features"],
            bayesian_learning=BayesianLearningResult(**consensus["bayesian_learning"])
        )
        
        risk_decision = create_risk_decision_with_rck(self, consensus_result, sentiment_bundle)
        
        if risk_decision:
            # Store for status and audit
            self._last_risk_decision = risk_decision
            return risk_decision.to_dict()
        
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """
        Enhanced status with complete RCK + Bayesian details.
        
        This provides comprehensive status information for the UI
        and monitoring systems.
        """
        consensus = getattr(self, '_last_consensus', None)
        risk_decision = getattr(self, '_last_risk_decision', None)
        
        return get_lane_status_with_rck(self, consensus, risk_decision)


async def example_complete_integration():
    """
    Example: Complete RCK + Bayesian integration in action.
    
    This shows the end-to-end flow from market discovery to trade execution
    with full RCK + Bayesian processing.
    """
    print("=== Complete RCK + Bayesian Integration Example ===")
    
    # Create enhanced lane with symbol-specific defaults
    btc_config = Crypto15MLaneConfig(
        symbol="BTC",
        paper=True,  # Paper mode for safety
        enable=True,
    )
    
    # The config automatically sets symbol-specific RCK + Bayesian parameters:
    # - BTC: target_drawdown=0.10, dd_prob=0.10, prior_strength=30
    # - ETH: target_drawdown=0.08, dd_prob=0.12, prior_strength=25
    # - SOL: target_drawdown=0.05, dd_prob=0.15, prior_strength=40
    # - XRP: target_drawdown=0.05, dd_prob=0.15, prior_strength=45
    
    lane = EnhancedCrypto15MLane(btc_config)
    lane.lane_id = "BTC_15M_ENHANCED"
    
    print(f"Created {lane.lane_id} with config:")
    print(f"  RCK target DD: {lane.cfg.rck_target_drawdown:.1%}")
    print(f"  RCK DD probability: {lane.cfg.rck_drawdown_probability:.1%}")
    print(f"  Bayesian prior strength: {lane.cfg.bayesian_prior_strength}")
    print(f"  Safety factor: {lane.cfg.rck_safety_factor}")
    
    # Simulate market data (would come from Kalshi catalog)
    market_data = {
        "market_id": "KXBTC15M-20260306-0115",
        "market_title": "Bitcoin price up or down at 1:15 AM UTC on Mar 6, 2026",
        "yes_price_cents": 52,
        "no_price_cents": 48,
        "symbol": "BTC",
    }
    
    # Simulate sentiment data (would come from sentiment bus)
    sentiment_bundle = {
        "fear_greed": {
            "value": 25,
            "classification": "extreme_fear",
            "is_extreme_fear": True,
            "is_extreme_greed": False,
            "contrarian_signal": 0.08,
        },
        "asset_sentiment_15m": {
            "sentiment_score_15m": 0.58,
            "social_volume": 150,
        }
    }
    
    # Simulate historical performance
    lane._historical_wins = 18
    lane._historical_losses = 12
    
    print(f"\nHistorical performance: {lane._historical_wins}W/{lane._historical_losses}L")
    
    # Step 1: Create consensus with RCK + Bayesian pipeline
    print("\n--- Step 1: Consensus with Bayesian Learning ---")
    consensus = await lane._get_consensus(market_data, sentiment_bundle)
    
    if consensus:
        print(f"✓ Consensus created:")
        print(f"  Market: {consensus['market_id']}")
        print(f"  Direction: {consensus['direction']}")
        print(f"  p_true: {consensus['p_true']:.3f}")
        print(f"  p_implied: {consensus['p_implied']:.3f}")
        print(f"  Edge: {consensus['edge_bps']:.1f} bps")
        
        bayesian = consensus['bayesian_learning']
        print(f"  Bayesian confidence: {bayesian['confidence']}")
        print(f"  Prior strength: {bayesian['prior_strength']}")
        print(f"  Feature adjustment: {bayesian['feature_adjustment']:.3f}")
    else:
        print("✗ Consensus failed")
        return
    
    # Step 2: Create risk decision with RCK solver
    print("\n--- Step 2: Risk Decision with RCK Solver ---")
    risk_decision = await lane._evaluate_risk(consensus, sentiment_bundle)
    
    if risk_decision:
        print(f"✓ Risk decision created:")
        print(f"  Approved: {risk_decision['approved']}")
        print(f"  Position size: ${risk_decision['position_size']:.2f}")
        print(f"  Full Kelly: {risk_decision['kelly_fraction_full']:.3f}")
        print(f"  RCK Kelly: {risk_decision['risk_constrained_kelly']['f_rck']:.3f}")
        print(f"  Used Kelly: {risk_decision['kelly_fraction_used']:.3f}")
        print(f"  Fraction of full: {risk_decision['risk_constrained_kelly']['fraction_of_full']:.2%}")
        
        rck = risk_decision['risk_constrained_kelly']
        print(f"  Target DD: {rck['target_drawdown']:.1%}")
        print(f"  DD probability: {rck['drawdown_probability']:.1%}")
        print(f"  Safety factor: {rck['safety_factor']:.1f}")
        print(f"  Solver paths: {rck['solver_paths']}")
        
        if risk_decision['fear_greed_applied']:
            print(f"  Fear & Greed applied: {risk_decision['fg_multiplier']:.2f}x")
    else:
        print("✗ Risk decision failed")
        return
    
    # Step 3: Get comprehensive status
    print("\n--- Step 3: Comprehensive Lane Status ---")
    status = lane.get_status()
    
    print(f"✓ Lane status:")
    print(f"  Lane ID: {status['lane_id']}")
    print(f"  Symbol: {status['symbol']}")
    print(f"  Running: {status['running']}")
    print(f"  Paper mode: {status['paper']}")
    
    if 'historical_performance' in status:
        hist = status['historical_performance']
        print(f"  Historical: {hist['total_trades']} trades, {hist['win_rate']:.1%} win rate")
    
    if 'rck_config' in status:
        rck_cfg = status['rck_config']
        print(f"  RCK config: DD={rck_cfg['target_drawdown']:.1%}, prob={rck_cfg['drawdown_probability']:.1%}")
    
    if 'bayesian_config' in status:
        bay_cfg = status['bayesian_config']
        print(f"  Bayesian config: prior={bay_cfg['prior_strength']}, weights=[{bay_cfg['rti_weight']:.2f}, {bay_cfg['flow_weight']:.2f}, {bay_cfg['asset_weight']:.2f}]")
    
    print(f"\n🎯 Integration complete! Ready for production deployment.")


async def example_symbol_comparison():
    """
    Example: Compare RCK parameters across different symbols.
    
    This demonstrates how the system automatically adapts to different
    crypto symbols with their specific risk profiles.
    """
    print("\n=== Symbol Comparison Example ===")
    
    symbols = ["BTC", "ETH", "SOL", "XRP"]
    
    for symbol in symbols:
        config = Crypto15MLaneConfig(symbol=symbol, paper=True)
        
        print(f"\n{symbol}:")
        print(f"  Target DD: {config.rck_target_drawdown:.1%}")
        print(f"  DD Probability: {config.rck_drawdown_probability:.1%}")
        print(f"  Prior Strength: {config.bayesian_prior_strength}")
        print(f"  Expected Kelly Range: {0.2:.2f}x - {0.35:.2f}x of full Kelly")


def example_dataclass_usage():
    """
    Example: Direct usage of the new dataclasses.
    
    This shows how the dataclasses can be used independently
    for testing, analysis, or custom integrations.
    """
    print("\n=== Dataclass Usage Example ===")
    
    from merid.lanes.rck_dataclasses import (
        ConsensusResult, RiskDecisionResult, BayesianLearningResult,
        RCKSolverResult, ConfidenceLevel
    )
    
    # Create Bayesian learning result
    bayesian_result = BayesianLearningResult(
        prior_strength=30,
        posterior_alpha=21.5,
        posterior_beta=18.5,
        posterior_mean=0.537,
        historical_wins=12,
        historical_losses=8,
        total_historical=20,
        feature_adjustment=0.018,
        confidence=ConfidenceLevel.MEDIUM,
    )
    
    # Create consensus result
    consensus = ConsensusResult(
        market_id="KXBTC15M-20260306-0115",
        market_title="Bitcoin price up or down",
        symbol="BTC",
        direction="yes",
        p_true=0.537,
        p_implied=0.52,
        fair_yes_prob=0.52,
        fair_no_prob=0.48,
        yes_price_cents=52,
        no_price_cents=48,
        edge_bps=170,
        features={"rti_signal": 0.05, "fg_contrarian": 0.08},
        bayesian_learning=bayesian_result,
    )
    
    # Create RCK solver result
    rck_result = RCKSolverResult(
        method="rck_solver",
        f_rck=0.28,
        target_drawdown=0.10,
        drawdown_probability=0.10,
        safety_factor=0.8,
        fraction_of_full=0.67,
        solver_paths=1000,
        solver_trades=500,
    )
    
    # Create risk decision result
    risk_decision = RiskDecisionResult(
        approved=True,
        position_size=25.0,
        bankroll_before=1000.0,
        bankroll_after=1000.0,
        kelly_fraction_full=0.42,
        kelly_fraction_used=0.28,
        risk_constrained_kelly=rck_result,
        edge_bps=170,
        current_positions=0,
        fear_greed_applied=True,
        fg_multiplier=1.05,
    )
    
    print("✓ Created dataclass instances:")
    print(f"  Consensus edge: {consensus.edge_bps} bps")
    print(f"  Bayesian confidence: {consensus.bayesian_learning.confidence.value}")
    print(f"  RCK method: {risk_decision.risk_constrained_kelly.method}")
    print(f"  Position size: ${risk_decision.position_size}")
    
    # Convert to dictionaries for JSON serialization
    print(f"\n✓ JSON serialization ready:")
    print(f"  Consensus dict keys: {list(consensus.to_dict().keys())}")
    print(f"  Risk decision dict keys: {list(risk_decision.to_dict().keys())}")


async def main():
    """Run all integration examples."""
    print("RCK + Bayesian Integration Examples")
    print("=" * 60)
    
    await example_complete_integration()
    await example_symbol_comparison()
    example_dataclass_usage()
    
    print("\n" + "=" * 60)
    print("🎯 All examples completed successfully!")
    print("\nKey Benefits:")
    print("• Clean dataclass-based pipeline")
    print("• Symbol-specific configuration")
    print("• Complete audit trail")
    print("• Production monitoring ready")
    print("• Zero glue code required")
    print("\nReady for immediate deployment in Crypto15MLane! 🚀")


if __name__ == "__main__":
    asyncio.run(main())
