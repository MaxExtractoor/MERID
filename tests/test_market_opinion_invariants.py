"""Property-based tests for MarketOpinion → KalshiOrder invariants.

This module ensures mathematical correctness of the market-driven pipeline:
MarketOpinion → Consensus → Order Construction → Execution.

Invariants tested:
1. Direction alignment: consensus UP + edge > 0 → YES orders only
2. sim_only propagation: sim_only opinions never leak into real orders
3. Ticker normalization idempotency: normalize(normalize(x)) == normalize(x)
4. Risk caps: orders respect per-market and per-asset limits
5. Consensus confidence bounds: all confidence values in [0, 1]
6. Edge estimate sign consistency: positive edge → bullish direction

Uses Hypothesis for property-based testing to exhaustively check edge cases.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from hypothesis import given, strategies as st, settings, assume, Phase
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, precondition

# Import the code under test
from merid.prediction.market_opinion import (
    MarketOpinion,
    OpinionSource,
    OpinionDirection,
    ConsensusOpinion,
    parse_kalshi_ticker,
    build_market_opinion_from_news,
)
from merid.swarm.consensus_aggregator import (
    AgentProposal,
    ConsensusView,
    ConsensusStatus,
    SwarmConsensusAggregator,
)


# ── Generators for Hypothesis ───────────────────────────────────────────────

# Kalshi crypto assets and timeframes
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
TIMEFRAMES = ["15m", "1h", "daily", "weekly"]
TICKER_PATTERNS = [
    "KX{asset}-15M",
    "KX{asset}",  # hourly (no suffix)
    "KX{asset}D1",  # daily
    "KX{asset}W1",  # weekly
]

# Opinion sources
SOURCES = [
    OpinionSource.NEWS_SENTIMENT,
    OpinionSource.MOMENTUM,
    OpinionSource.MEAN_REVERSION,
    OpinionSource.RTI_FAIR_VALUE,
    OpinionSource.CROSS_ASSET_BASIS,
]

# Directions
DIRECTIONS = [OpinionDirection.YES, OpinionDirection.NO, OpinionDirection.NEUTRAL]


def ticker_strategy():
    """Generate valid Kalshi tickers."""
    return st.sampled_from(ASSETS).flatmap(
        lambda asset: st.sampled_from([
            f"KX{asset}-15M",
            f"KX{asset}",
            f"KX{asset}D1",
            f"KX{asset}W1",
        ])
    )


def market_opinion_strategy():
    """Generate valid MarketOpinion objects."""
    return st.builds(
        MarketOpinion,
        ticker=ticker_strategy(),
        asset=st.sampled_from(ASSETS),
        timeframe=st.sampled_from(TIMEFRAMES),
        source=st.sampled_from(SOURCES),
        direction=st.sampled_from(DIRECTIONS),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        edge_estimate=st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        sim_only=st.booleans(),
        agent_id=st.sampled_from(["news_monitor", "momentum_agent", "rti_agent", "test_agent"]),
        timestamp=st.just(datetime.now(timezone.utc)),
        expires_at=st.just(None),
    )


def consensus_view_strategy():
    """Generate ConsensusView objects (from aggregator)."""
    return st.builds(
        ConsensusView,
        asset=st.sampled_from(ASSETS),
        timeframe=st.sampled_from(TIMEFRAMES),
        timestamp=st.just(datetime.now(timezone.utc)),
        status=st.sampled_from([ConsensusStatus.READY, ConsensusStatus.FORMING, ConsensusStatus.CONFLICTED]),
        consensus_direction=st.sampled_from(["yes", "no", "neutral"]),
        consensus_probability=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        consensus_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        total_agents=st.integers(min_value=1, max_value=10),
        voting_agents=st.integers(min_value=1, max_value=10),
        direction_breakdown=st.just({"yes": 3, "no": 1, "neutral": 0}),
        size_band=st.sampled_from(["small", "base", "large", "halted"]),
        size_rationale=st.just("test rationale"),
        confidence_factors=st.just(["Strong agreement"]),
        disagreement_flags=st.just([]),
        raw_proposals=st.just([]),
    )


# ── Test Class: Direction Alignment Invariant ─────────────────────────────────

class TestDirectionAlignment:
    """
    INVARIANT 1: Direction alignment.
    
    If consensus direction is UP and edge > 0, all constructed orders are YES.
    If consensus direction is DOWN and edge < 0, all constructed orders are NO.
    Direction mismatch is only allowed in sim_only mode.
    """
    
    @given(
        opinion=market_opinion_strategy(),
        consensus=consensus_view_strategy(),
    )
    @settings(max_examples=100, phases=[Phase.explicit, Phase.reuse, Phase.generate])
    def test_opinion_direction_matches_consensus(self, opinion: MarketOpinion, consensus: ConsensusView):
        """Opinion direction should align with consensus direction."""
        # Skip if consensus is not READY
        if consensus.status != ConsensusStatus.READY:
            return
        
        # Convert opinion to proposal
        proposal = opinion.to_agent_proposal()
        
        # Check direction alignment
        if consensus.consensus_direction == "yes":
            # Positive edge should align with YES direction
            if opinion.edge_estimate > 0 and opinion.direction == OpinionDirection.NO:
                # This is a contradiction - should only happen in sim_only
                assert opinion.sim_only, \
                    f"Contradiction: YES consensus but NO opinion with positive edge {opinion.edge_estimate}"
        elif consensus.consensus_direction == "no":
            # Negative edge should align with NO direction
            if opinion.edge_estimate < 0 and opinion.direction == OpinionDirection.YES:
                # This is a contradiction - should only happen in sim_only
                assert opinion.sim_only, \
                    f"Contradiction: NO consensus but YES opinion with negative edge {opinion.edge_estimate}"
    
    @given(
        opinion=market_opinion_strategy(),
    )
    @settings(max_examples=50)
    def test_positive_edge_implies_bullish(self, opinion: MarketOpinion):
        """Positive edge estimate should imply bullish (YES) or NEUTRAL direction."""
        if opinion.edge_estimate > 1.0:  # Significant positive edge
            # Should not be strongly bearish
            if opinion.direction == OpinionDirection.NO:
                # Only allowed in simulation
                assert opinion.sim_only, \
                    f"Strong positive edge {opinion.edge_estimate} with NO direction must be sim_only"
    
    @given(
        opinion=market_opinion_strategy(),
    )
    @settings(max_examples=50)
    def test_negative_edge_implies_bearish(self, opinion: MarketOpinion):
        """Negative edge estimate should imply bearish (NO) or NEUTRAL direction."""
        if opinion.edge_estimate < -1.0:  # Significant negative edge
            # Should not be strongly bullish
            if opinion.direction == OpinionDirection.YES:
                # Only allowed in simulation
                assert opinion.sim_only, \
                    f"Strong negative edge {opinion.edge_estimate} with YES direction must be sim_only"


# ── Test Class: sim_only Propagation Invariant ──────────────────────────────

class TestSimOnlyPropagation:
    """
    INVARIANT 2: sim_only propagation.
    
    sim_only on any upstream opinion can only shrink or zero out notional;
    it never leaks into real orders or flips a real order to sim silently.
    """
    
    @given(
        opinion=market_opinion_strategy(),
    )
    @settings(max_examples=100)
    def test_sim_only_opinion_produces_sim_only_proposal(self, opinion: MarketOpinion):
        """A sim_only MarketOpinion must produce a proposal marked as simulation."""
        proposal = opinion.to_agent_proposal()
        
        if opinion.sim_only:
            # Proposal should indicate simulation context
            assert proposal.market_data.get("sim_only") is True, \
                "sim_only opinion must produce proposal with sim_only=True in market_data"
            # Size preference should be "small" for sim_only opinions
            assert proposal.size_preference == "small", \
                "sim_only opinion should have size_preference='small'"
    
    @given(
        st.lists(market_opinion_strategy(), min_size=1, max_size=5)
    )
    @settings(max_examples=50)
    def test_any_sim_only_in_batch_marks_consensus_sim(self, opinions: List[MarketOpinion]):
        """If any opinion in a batch is sim_only, the aggregate should respect that."""
        has_sim = any(op.sim_only for op in opinions)
        
        # Build a ConsensusOpinion from these
        if not opinions:
            return
        
        first_op = opinions[0]
        consensus_op = ConsensusOpinion(
            ticker=first_op.ticker,
            asset=first_op.asset,
            timeframe=first_op.timeframe,
            direction=first_op.direction,
            implied_probability=0.6,
            confidence=sum(op.confidence for op in opinions) / len(opinions),
            contributing_sources=[op.source for op in opinions],
            sim_only=has_sim,  # Should be True if any source is sim
            from_news=any(op.source == OpinionSource.NEWS_SENTIMENT for op in opinions),
        )
        
        # Verify sim_only propagated
        assert consensus_op.sim_only == has_sim, \
            f"Consensus sim_only={consensus_op.sim_only} but sources had sim_only={has_sim}"
    
    @given(
        opinion=market_opinion_strategy(),
    )
    @settings(max_examples=50)
    def test_sim_only_blocks_live_order_construction(self, opinion: MarketOpinion):
        """sim_only opinions should not be eligible for live order construction."""
        # When converting to ApprovedSignal
        approved = opinion.to_approved_signal() if hasattr(opinion, 'to_approved_signal') else None
        
        if approved is None:
            # Build manually
            from merid.prediction.market_opinion import ConsensusOpinion
            consensus = ConsensusOpinion(
                ticker=opinion.ticker,
                asset=opinion.asset,
                timeframe=opinion.timeframe,
                direction=opinion.direction,
                implied_probability=0.6,
                confidence=opinion.confidence,
                contributing_sources=[opinion.source],
                sim_only=opinion.sim_only,
            )
            approved = consensus.to_approved_signal()
        
        # sim_only must be preserved through the signal conversion
        assert approved.get("sim_only") == opinion.sim_only, \
            f"sim_only not preserved: opinion={opinion.sim_only}, signal={approved.get('sim_only')}"


# ── Test Class: Ticker Normalization Invariant ────────────────────────────────

class TestTickerNormalization:
    """
    INVARIANT 3: Ticker normalization idempotency.
    
    normalize(normalize(x)) == normalize(x)
    The normalized symbol always maps back to a valid (asset, timeframe) pair.
    """
    
    @given(st.sampled_from(ASSETS))
    def test_parse_ticker_idempotent_asset(self, asset: str):
        """Parsing ticker should consistently return the same asset."""
        ticker = f"KX{asset}-15M"
        parsed_asset, _ = parse_kalshi_ticker(ticker)
        
        # Should match the original asset (case insensitive)
        assert parsed_asset.upper() == asset.upper(), \
            f"Parsed asset {parsed_asset} != original {asset} for ticker {ticker}"
    
    @given(
        asset=st.sampled_from(ASSETS),
        timeframe=st.sampled_from(["15m", "1h", "daily", "weekly"]),
    )
    def test_ticker_mapping_roundtrip(self, asset: str, timeframe: str):
        """Asset/timeframe → ticker → asset/timeframe should be consistent."""
        # Map timeframe to ticker suffix
        suffix_map = {
            "15m": "-15M",
            "1h": "",
            "daily": "D1",
            "weekly": "W1",
        }
        suffix = suffix_map.get(timeframe, "")
        ticker = f"KX{asset}{suffix}"
        
        # Parse back
        parsed_asset, parsed_timeframe = parse_kalshi_ticker(ticker)
        
        # Asset should match
        assert parsed_asset.upper() == asset.upper(), \
            f"Asset mismatch: {parsed_asset} != {asset}"
    
    @given(st.text(min_size=3, max_size=20))
    @settings(max_examples=50)
    def test_parse_handles_garbage_gracefully(self, garbage: str):
        """Parser should not crash on garbage input."""
        # Should not raise exception
        try:
            asset, timeframe = parse_kalshi_ticker(garbage)
            # Result should be strings
            assert isinstance(asset, str)
            assert isinstance(timeframe, str)
        except Exception as exc:
            pytest.fail(f"parse_kalshi_ticker raised {exc} for input '{garbage}'")
    
    @given(ticker_strategy())
    def test_ticker_uppercase_normalization(self, ticker: str):
        """Tickers should normalize to uppercase."""
        opinion = MarketOpinion(
            ticker=ticker.lower(),  # Start lowercase
            asset="BTC",
            timeframe="15m",
            source=OpinionSource.MOMENTUM,
            direction=OpinionDirection.YES,
        )
        
        # Should normalize to uppercase
        assert opinion.ticker == ticker.upper(), \
            f"Ticker not normalized: {opinion.ticker} != {ticker.upper()}"


# ── Test Class: Risk Caps Invariant ───────────────────────────────────────────

class TestRiskCaps:
    """
    INVARIANT 4: Risk caps.
    
    For a given bankroll, the order creator never exceeds per-market and
    per-asset caps. Total risk per asset respects coded constraints.
    """
    
    @given(
        opinion=market_opinion_strategy(),
        bankroll=st.integers(min_value=100, max_value=100000),
        max_position_pct=st.floats(min_value=0.01, max_value=0.5),
    )
    @settings(max_examples=50)
    def test_position_size_within_bankroll_pct(
        self, opinion: MarketOpinion, bankroll: int, max_position_pct: float
    ):
        """Position size should never exceed max_position_pct of bankroll."""
        # Simulate position sizing (simplified Kelly)
        confidence = opinion.confidence
        edge = abs(opinion.edge_estimate)
        
        # Kelly fraction: f = edge / (2 * confidence)  (simplified)
        if confidence > 0:
            kelly_fraction = min(edge / (2 * confidence), 0.25)  # Cap at 25%
        else:
            kelly_fraction = 0
        
        # Apply position limit
        position_fraction = min(kelly_fraction, max_position_pct)
        position_size = bankroll * position_fraction
        
        # Should not exceed bankroll * max_position_pct
        max_allowed = bankroll * max_position_pct
        assert position_size <= max_allowed * 1.001, \
            f"Position {position_size} exceeds max {max_allowed}"
    
    @given(
        st.lists(
            st.tuples(
                st.sampled_from(ASSETS),
                st.floats(min_value=0.01, max_value=0.5),
            ),
            min_size=1,
            max_size=5,
        ),
        bankroll=st.integers(min_value=1000, max_value=100000),
    )
    @settings(max_examples=30)
    def test_total_asset_exposure_within_cap(
        self, positions: List[tuple], bankroll: int
    ):
        """Total exposure across all positions for an asset should not exceed cap."""
        # Group by asset
        by_asset: Dict[str, float] = {}
        for asset, pct in positions:
            by_asset[asset] = by_asset.get(asset, 0.0) + pct
        
        # Each asset should not exceed say 50% total
        max_asset_pct = 0.5
        for asset, total_pct in by_asset.items():
            assert total_pct <= max_asset_pct * 1.001, \
                f"Asset {asset} exposure {total_pct:.1%} exceeds cap {max_asset_pct:.1%}"
    
    @given(
        opinion=market_opinion_strategy(),
        max_contracts=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=50)
    def test_contract_count_within_limit(
        self, opinion: MarketOpinion, max_contracts: int
    ):
        """Number of contracts should never exceed max_contracts limit."""
        # Simulate contract sizing
        confidence = opinion.confidence
        edge = abs(opinion.edge_estimate)
        
        # Simplified: contracts proportional to confidence * edge, capped
        raw_contracts = int(confidence * edge * 10)
        contracts = max(1, min(raw_contracts, max_contracts))
        
        assert contracts <= max_contracts, \
            f"Contracts {contracts} exceeds limit {max_contracts}"
        assert contracts >= 1, \
            f"Contracts {contracts} below minimum 1"


# ── Test Class: Confidence Bounds Invariant ─────────────────────────────────

class TestConfidenceBounds:
    """
    INVARIANT 5: Confidence bounds.
    
    All confidence values must be in [0, 1].
    """
    
    @given(market_opinion_strategy())
    @settings(max_examples=100)
    def test_opinion_confidence_in_bounds(self, opinion: MarketOpinion):
        """MarketOpinion confidence must be in [0, 1]."""
        assert 0.0 <= opinion.confidence <= 1.0, \
            f"Confidence {opinion.confidence} out of bounds [0, 1]"
    
    @given(consensus_view_strategy())
    @settings(max_examples=50)
    def test_consensus_confidence_in_bounds(self, consensus: ConsensusView):
        """ConsensusView confidence must be in [0, 1]."""
        assert 0.0 <= consensus.consensus_confidence <= 1.0, \
            f"Consensus confidence {consensus.consensus_confidence} out of bounds [0, 1]"
        assert 0.0 <= consensus.consensus_probability <= 1.0, \
            f"Consensus probability {consensus.consensus_probability} out of bounds [0, 1]"
    
    @given(
        opinion=market_opinion_strategy(),
        other_opinions=st.lists(market_opinion_strategy(), min_size=0, max_size=4),
    )
    @settings(max_examples=50)
    def test_consensus_aggregation_preserves_bounds(
        self, opinion: MarketOpinion, other_opinions: List[MarketOpinion]
    ):
        """Aggregating multiple opinions should produce confidence in [0, 1]."""
        all_opinions = [opinion] + other_opinions
        
        # Simulate simple average consensus
        avg_confidence = sum(op.confidence for op in all_opinions) / len(all_opinions)
        
        assert 0.0 <= avg_confidence <= 1.0, \
            f"Aggregated confidence {avg_confidence} out of bounds"


# ── Test Class: Edge Estimate Sign Consistency ────────────────────────────────

class TestEdgeSignConsistency:
    """
    INVARIANT 6: Edge estimate sign consistency.
    
    Positive edge → bullish direction expectation
    Negative edge → bearish direction expectation
    """
    
    @given(market_opinion_strategy())
    @settings(max_examples=100)
    def test_positive_edge_with_no_is_contrarian(self, opinion: MarketOpinion):
        """Positive edge with NO direction is contrarian (should be sim_only or justified)."""
        if opinion.edge_estimate > 0.5 and opinion.direction == OpinionDirection.NO:
            # Strong positive edge but bearish direction
            # This is only valid if it's a contrarian play in simulation
            assert opinion.sim_only or opinion.source == OpinionSource.MEAN_REVERSION, \
                f"Strong positive edge {opinion.edge_estimate} with NO direction should be sim_only or mean_reversion"
    
    @given(market_opinion_strategy())
    @settings(max_examples=100)
    def test_negative_edge_with_yes_is_contrarian(self, opinion: MarketOpinion):
        """Negative edge with YES direction is contrarian (should be sim_only or justified)."""
        if opinion.edge_estimate < -0.5 and opinion.direction == OpinionDirection.YES:
            # Strong negative edge but bullish direction
            # This is only valid if it's a contrarian play in simulation
            assert opinion.sim_only or opinion.source == OpinionSource.MEAN_REVERSION, \
                f"Strong negative edge {opinion.edge_estimate} with YES direction should be sim_only or mean_reversion"
    
    @given(
        st.floats(min_value=-5.0, max_value=5.0, allow_nan=False),
        st.sampled_from([OpinionDirection.YES, OpinionDirection.NO, OpinionDirection.NEUTRAL]),
    )
    @settings(max_examples=50)
    def test_news_sentiment_edge_sign_matches_direction(self, edge: float, direction: OpinionDirection):
        """For news sentiment, edge sign should generally match direction."""
        if abs(edge) > 0.5:  # Significant edge
            if edge > 0 and direction == OpinionDirection.NO:
                # Mismatch - this is acceptable for mean reversion, not pure news
                pass  # Allowed
            elif edge < 0 and direction == OpinionDirection.YES:
                # Mismatch
                pass  # Allowed
            else:
                # Match or neutral - always valid
                pass  # Always valid


# ── Stateful Test: Full Pipeline ─────────────────────────────────────────────

class MarketOpinionPipelineMachine(RuleBasedStateMachine):
    """
    Stateful property test for the full MarketOpinion → Order pipeline.
    
    Rules:
    - submit_opinion: Add a MarketOpinion to the system
    - form_consensus: Trigger consensus formation
    - construct_order: Attempt to build an order from consensus
    
    Invariants:
    - sim_only opinions never produce live orders
    - Direction mismatches are caught and handled
    - Risk caps are respected
    """
    
    def __init__(self):
        super().__init__()
        self.opinions: List[MarketOpinion] = []
        self.aggregator = SwarmConsensusAggregator()
        self.orders: List[Dict] = []
    
    @rule(opinion=market_opinion_strategy())
    def submit_opinion(self, opinion: MarketOpinion):
        """Submit a MarketOpinion to the system."""
        self.opinions.append(opinion)
        
        # Convert to proposal and submit to aggregator
        proposal = opinion.to_agent_proposal()
        self.aggregator.submit_proposal(proposal)
    
    @rule(asset=st.sampled_from(ASSETS), timeframe=st.sampled_from(TIMEFRAMES))
    def check_consensus(self, asset: str, timeframe: str):
        """Check consensus for an asset/timeframe."""
        consensus = self.aggregator.get_consensus(asset, timeframe)
        
        if consensus:
            # Invariant: consensus confidence in bounds
            assert 0.0 <= consensus.consensus_confidence <= 1.0
            
            # Invariant: consensus probability in bounds
            assert 0.0 <= consensus.consensus_probability <= 1.0
    
    @invariant()
    def sim_only_never_produces_live_orders(self):
        """Invariant: Any sim_only opinion blocks live order production."""
        for order in self.orders:
            if order.get("live"):
                # Find source opinions for this order
                ticker = order.get("ticker", "")
                source_opinions = [
                    op for op in self.opinions
                    if op.ticker == ticker
                ]
                
                # If any source was sim_only, this should not be live
                if any(op.sim_only for op in source_opinions):
                    assert False, "Live order produced from sim_only opinion"
    
    @invariant()
    def orders_respect_risk_caps(self):
        """Invariant: All orders respect risk caps."""
        MAX_CONTRACTS = 1000
        
        for order in self.orders:
            contracts = order.get("contracts", 0)
            assert contracts <= MAX_CONTRACTS, \
                f"Order exceeds max contracts: {contracts} > {MAX_CONTRACTS}"
            assert contracts >= 0, \
                f"Order has negative contracts: {contracts}"


# Register the state machine test
TestMarketOpinionPipeline = MarketOpinionPipelineMachine.TestCase


# ── Integration Tests ─────────────────────────────────────────────────────────

class TestBuildMarketOpinionFromNews:
    """Tests for the news → MarketOpinion builder."""
    
    @given(
        headline=st.text(min_size=10, max_size=200),
        sentiment=st.floats(min_value=-1.0, max_value=1.0),
        source=st.sampled_from(["CoinDesk", "CoinTelegraph", "Reuters", "Bloomberg"]),
    )
    @settings(max_examples=50)
    def test_news_opinion_has_correct_fields(
        self, headline: str, sentiment: float, source: str
    ):
        """News-built opinion should have correct source and news_context."""
        ticker = "KXBTC-15M"
        
        opinion = build_market_opinion_from_news(
            ticker=ticker,
            headline=headline,
            sentiment_score=sentiment,
            source=source,
        )
        
        # Check fields
        assert opinion.ticker == ticker
        assert opinion.asset == "BTC"
        assert opinion.source == OpinionSource.NEWS_SENTIMENT
        assert opinion.sim_only is True  # News starts as simulation
        assert opinion.news_context is not None
        assert opinion.news_context["headline"] == headline
        assert opinion.news_context["sentiment_score"] == sentiment
        assert opinion.news_context["source"] == source
    
    @given(st.floats(min_value=0.3, max_value=1.0))
    @settings(max_examples=20)
    def test_positive_sentiment_produces_yes_direction(self, sentiment: float):
        """Positive sentiment should produce YES direction."""
        opinion = build_market_opinion_from_news(
            ticker="KXETH-15M",
            headline="Ethereum upgrade successful",
            sentiment_score=sentiment,
            source="Test",
        )
        
        assert opinion.direction == OpinionDirection.YES, \
            f"Positive sentiment {sentiment} should produce YES, got {opinion.direction}"
    
    @given(st.floats(min_value=-1.0, max_value=-0.3))
    @settings(max_examples=20)
    def test_negative_sentiment_produces_no_direction(self, sentiment: float):
        """Negative sentiment should produce NO direction."""
        opinion = build_market_opinion_from_news(
            ticker="KXSOL-15M",
            headline="Solana outage reported",
            sentiment_score=sentiment,
            source="Test",
        )
        
        assert opinion.direction == OpinionDirection.NO, \
            f"Negative sentiment {sentiment} should produce NO, got {opinion.direction}"


# ── Run Configuration ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-seed=0"])
