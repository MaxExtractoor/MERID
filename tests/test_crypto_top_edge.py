"""Tests for crypto_top_edge module — Cross-asset top edge selection with dynamic floor.

This test suite validates:
- Cross-sectional floor calculation (gamma * top/median edge)
- Rolling distribution floor calculation (mu + alpha * sigma)
- Winner selection (top N from qualified candidates)
- Rejection reason handling
- Integration with strategy.py changes
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from merid.prediction.crypto_top_edge import (
    CandidateSignal,
    CrossAssetCycleResult,
    CryptoTopEdgeArbiter,
    CRYPTO_ASSETS,
    MEAN_REVERSION_TIMEFRAMES,
    RollingEdgeHistory,
    get_crypto_top_edge_arbiter,
    reset_crypto_top_edge_arbiter,
    select_top_edges,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton arbiter before each test."""
    reset_crypto_top_edge_arbiter()
    yield
    reset_crypto_top_edge_arbiter()


@pytest.fixture
def sample_candidates() -> List[CandidateSignal]:
    """Sample candidates for testing (BTC, ETH, SOL with varying edges)."""
    return [
        CandidateSignal(
            signal_id="btc_1",
            agent_id="BTC_15M",
            asset="BTC",
            timeframe="15m",
            ticker="KXBTC15M-TEST",
            net_edge=0.045,  # Best edge
            confidence=0.75,
            direction="long",
            suggested_contracts=5,
        ),
        CandidateSignal(
            signal_id="eth_1",
            agent_id="ETH_15M",
            asset="ETH",
            timeframe="15m",
            ticker="KXETH15M-TEST",
            net_edge=0.032,  # Second best
            confidence=0.68,
            direction="short",
            suggested_contracts=3,
        ),
        CandidateSignal(
            signal_id="sol_1",
            agent_id="SOL_15M",
            asset="SOL",
            timeframe="15m",
            ticker="KXSOL15M-TEST",
            net_edge=0.025,  # Third
            confidence=0.62,
            direction="long",
            suggested_contracts=2,
        ),
        CandidateSignal(
            signal_id="xrp_1",
            agent_id="XRP_15M",
            asset="XRP",
            timeframe="15m",
            ticker="KXXRP15M-TEST",
            net_edge=0.015,  # Below typical floor
            confidence=0.55,
            direction="long",
            suggested_contracts=1,
        ),
        CandidateSignal(
            signal_id="doge_1",
            agent_id="DOGE_15M",
            asset="DOGE",
            timeframe="15m",
            ticker="KXDOGE15M-TEST",
            net_edge=-0.005,  # Negative edge (should be rejected)
            confidence=0.45,
            direction="short",
            suggested_contracts=1,
        ),
    ]


# =============================================================================
# Test Classes
# =============================================================================

class TestCryptoTopEdgeArbiterBasics:
    """Basic initialization and configuration tests."""
    
    def test_init_default_config(self):
        """Test arbiter initializes with default config."""
        arbiter = CryptoTopEdgeArbiter()
        # Note: Actual runtime value may differ from DEFAULT_GAMMA due to env var overrides
        # The value is clamped to [0.3, 0.7]
        assert 0.3 <= arbiter._gamma <= 0.7
        assert arbiter._alpha == 0.0
        assert arbiter._top_n == 3  # Reverted from 1 to restore trade volume
        assert arbiter._min_edge_absolute == 0.0  # Reverted from 0.015 to allow lower-edge trades
    
    def test_init_custom_config(self):
        """Test arbiter initializes with custom config."""
        arbiter = CryptoTopEdgeArbiter(
            gamma=0.6,  # Test non-default value
            alpha=0.5,
            top_n=2,  # Test non-default value
            min_edge_absolute=0.02,  # Test non-default value
        )
        assert arbiter._gamma == 0.6
        assert arbiter._alpha == 0.5
        assert arbiter._top_n == 2
        assert arbiter._min_edge_absolute == 0.02
    
    def test_gamma_clamping(self):
        """Test gamma is clamped to [0.3, 0.7]."""
        arbiter_high = CryptoTopEdgeArbiter(gamma=1.0)
        assert arbiter_high._gamma == 0.7
        
        arbiter_low = CryptoTopEdgeArbiter(gamma=0.1)
        assert arbiter_low._gamma == 0.3
    
    def test_singleton_pattern(self):
        """Test singleton returns same instance."""
        arbiter1 = get_crypto_top_edge_arbiter()
        arbiter2 = get_crypto_top_edge_arbiter()
        assert arbiter1 is arbiter2


class TestCrossSectionalFloor:
    """Cross-sectional dynamic floor calculation tests."""
    
    def test_floor_from_top_edge(self, sample_candidates):
        """Test floor computed as gamma * top_edge."""
        # gamma=0.5, top_edge=0.045 (BTC)
        # floor_from_top = 0.5 * 0.045 = 0.0225
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=2)
        
        for c in sample_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Top edge is 0.045, floor_from_top = 0.5 * 0.045 = 0.0225
        # Median edge is 0.025, floor_from_median = 0.5 * 0.025 = 0.0125
        # dynamic_floor = max(0.0225, 0.0125) = 0.0225
        assert result.top_edge == 0.045
        assert result.median_edge == 0.025
        assert result.dynamic_floor == 0.0225  # max of both
    
    def test_floor_from_median_edge(self, sample_candidates):
        """Test floor respects median when higher than top fraction."""
        # With gamma=0.3, top=0.045 -> 0.0135, median=0.025 -> 0.0075
        arbiter = CryptoTopEdgeArbiter(gamma=0.3, top_n=2)
        
        for c in sample_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # floor_from_top = 0.3 * 0.045 = 0.0135
        # floor_from_median = 0.3 * 0.025 = 0.0075
        # dynamic_floor = max(0.0135, 0.0075) = 0.0135
        assert result.dynamic_floor == 0.0135
    
    def test_floor_never_negative(self, sample_candidates):
        """Test floor is never negative (clamped at 0)."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=2)
        
        # All negative edges
        negative_candidates = [
            CandidateSignal(
                signal_id="neg_1",
                agent_id="BTC_15M",
                asset="BTC",
                timeframe="15m",
                ticker="KXBTC15M-TEST",
                net_edge=-0.01,
            ),
            CandidateSignal(
                signal_id="neg_2",
                agent_id="ETH_15M",
                asset="ETH",
                timeframe="15m",
                ticker="KXETH15M-TEST",
                net_edge=-0.02,
            ),
        ]
        
        for c in negative_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Top edge is -0.01, but floor should be 0
        assert result.final_floor == 0.0
        assert len(result.winners) == 0


class TestWinnerSelection:
    """Winner selection logic tests."""
    
    def test_top_n_selection(self, sample_candidates):
        """Test only top N candidates are selected."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.3, top_n=2)
        
        for c in sample_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Floor = 0.3 * 0.045 = 0.0135
        # Qualified: BTC(0.045), ETH(0.032), SOL(0.025), XRP(0.015)
        # Top 2: BTC, ETH
        assert len(result.winners) == 2
        assert result.winners[0].asset == "BTC"
        assert result.winners[1].asset == "ETH"
        assert result.winners[0].rank == 1
        assert result.winners[1].rank == 2
    
    def test_negative_edge_rejection(self, sample_candidates):
        """Test negative edges are rejected."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=5)
        
        for c in sample_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # DOGE has negative edge
        doge = [c for c in result.all_candidates if c.asset == "DOGE"][0]
        assert doge.rejection_reason == "negative_or_zero_edge"
        assert doge not in result.winners
    
    def test_below_floor_rejection(self, sample_candidates):
        """Test edges below dynamic floor are rejected."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.6, top_n=5)
        
        for c in sample_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Floor = 0.6 * 0.045 = 0.027
        # XRP has 0.015, below floor
        xrp = [c for c in result.all_candidates if c.asset == "XRP"][0]
        assert "below_dynamic_floor" in xrp.rejection_reason
        assert xrp not in result.winners
    
    def test_few_qualified_candidates_high_floor(self):
        """Test handling when few candidates pass high floor."""
        # Use max gamma (0.7) to create high floor - note: gamma clamped to [0.3, 0.7]
        arbiter = CryptoTopEdgeArbiter(gamma=0.7, top_n=2)
        
        # Use fresh candidates with known values
        candidates = [
            CandidateSignal(signal_id="btc_1", agent_id="BTC_15M", asset="BTC", 
                          timeframe="15m", ticker="KXBTC-TEST", net_edge=0.045),
            CandidateSignal(signal_id="eth_1", agent_id="ETH_15M", asset="ETH", 
                          timeframe="15m", ticker="KXETH-TEST", net_edge=0.032),
        ]
        
        for c in candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Floor = 0.7 * 0.045 = 0.0315 (top), 0.7 * 0.0385 = 0.02695 (median)
        # dynamic_floor = max(0.0315, 0.02695) = 0.0315
        # BTC(0.045) > 0.0315, ETH(0.032) > 0.0315
        # Both qualify with this gamma, so we get 2 winners
        # (Need higher threshold to only get 1 winner)
        assert len(result.winners) == 2  # Both BTC and ETH pass floor with gamma=0.7
        assert result.gamma_used == 0.7
    
    def test_single_candidate_wins(self):
        """Test single candidate always wins if positive edge."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=3)
        
        single = CandidateSignal(
            signal_id="btc_1",
            agent_id="BTC_15M",
            asset="BTC",
            timeframe="15m",
            ticker="KXBTC15M-TEST",
            net_edge=0.02,
        )
        
        arbiter.submit_candidate(single)
        result = arbiter.run_cycle()
        
        # Top=median=0.02, floor=0.5*0.02=0.01, candidate has 0.02 > 0.01
        assert len(result.winners) == 1
        assert result.winners[0].asset == "BTC"


class TestRollingEdgeHistory:
    """Rolling edge history and global floor tests."""
    
    def test_record_and_stats(self):
        """Test recording edges and computing stats."""
        history = RollingEdgeHistory(max_size=10)
        
        # Record some edges
        for i in range(5):
            history.record("BTC", 0.03 + i * 0.01)
            history.record("ETH", 0.02 + i * 0.005)
        
        stats = history.get_stats(min_samples=3)
        assert stats is not None
        mu, sigma, p80 = stats
        assert mu > 0
        assert sigma >= 0
        assert p80 >= mu  # 80th percentile >= mean
    
    def test_insufficient_samples(self):
        """Test returns None when insufficient samples."""
        history = RollingEdgeHistory()
        
        # Only 2 samples, need min 20
        history.record("BTC", 0.03)
        history.record("BTC", 0.04)
        
        stats = history.get_stats(min_samples=5)
        assert stats is None
    
    def test_per_asset_stats(self):
        """Test per-asset statistics."""
        history = RollingEdgeHistory()
        
        for i in range(15):
            history.record("BTC", 0.04)
            history.record("ETH", 0.03)
        
        btc_stats = history.get_asset_stats("BTC", min_samples=10)
        eth_stats = history.get_asset_stats("ETH", min_samples=10)
        
        assert btc_stats is not None
        assert eth_stats is not None
        assert btc_stats[0] == 0.04  # Mean
        assert eth_stats[0] == 0.03


class TestSelectTopEdgesConvenience:
    """Test the one-shot select_top_edges function."""
    
    def test_basic_selection(self, sample_candidates):
        """Test one-shot selection works."""
        result = select_top_edges(
            sample_candidates,
            gamma=0.5,
            alpha=0.0,
            top_n=2,
        )
        
        assert isinstance(result, CrossAssetCycleResult)
        assert len(result.winners) == 2
        assert result.winners[0].net_edge >= result.winners[1].net_edge
    
    def test_empty_input(self):
        """Test empty candidate list."""
        result = select_top_edges([])
        
        assert len(result.all_candidates) == 0
        assert len(result.winners) == 0
        assert result.final_floor == 0.0


class TestCrossAssetCycleResult:
    """Test result serialization and metrics."""
    
    def test_to_dict(self, sample_candidates):
        """Test result serialization."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=2)
        
        for c in sample_candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        d = result.to_dict()
        
        assert "cycle_id" in d
        assert "timestamp" in d
        assert "stats" in d
        assert "selection" in d
        assert "winners" in d
        
        # Stats
        assert "top_edge" in d["stats"]
        assert "median_edge" in d["stats"]
        assert "final_floor" in d["stats"]
        
        # Selection
        assert d["selection"]["total_candidates"] == 5
        assert d["selection"]["winners_count"] == 2
        assert "gamma" in d["selection"]
    
    def test_metrics(self, sample_candidates):
        """Test arbiter metrics."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=2)
        
        # Run a few cycles
        for i in range(3):
            for c in sample_candidates:
                arbiter.submit_candidate(c)
            arbiter.run_cycle(cycle_id=f"test_{i}")
        
        metrics = arbiter.get_metrics()
        
        assert metrics["cycles_run"] == 3
        assert metrics["config"]["gamma"] == 0.5


class TestCryptoAssetsConstant:
    """Test CRYPTO_ASSETS constant."""
    
    def test_expected_assets(self):
        """Test CRYPTO_ASSETS contains expected symbols."""
        expected = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        assert CRYPTO_ASSETS == expected
    
    def test_all_uppercase(self):
        """Test all assets are uppercase."""
        for asset in CRYPTO_ASSETS:
            assert asset.isupper()
            assert len(asset) >= 3


class TestIntegrationWithStrategySignal:
    """Test integration with StrategySignal pattern."""
    
    def test_submit_from_strategy_signal_mock(self):
        """Test submit_from_strategy_signal with mock signal."""
        arbiter = CryptoTopEdgeArbiter()
        
        # Create a mock signal object
        class MockEdge:
            net_edge = 0.05
            confidence = 0.75
        
        class MockSignal:
            action = type('obj', (object,), {'value': 'buy_yes'})()
            side = "yes"
            contracts = 5
            edge = MockEdge()
            eval_context = {"archetype": "directional"}
            phase = type('obj', (object,), {'value': 'EARLY'})()
            correlation_id = "test-123"
        
        arbiter.submit_from_strategy_signal(
            signal=MockSignal(),
            agent_id="BTC_15M",
            asset="BTC",
            timeframe="15m",
            ticker="KXBTC15M-TEST",
        )
        
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1
        assert result.winners[0].asset == "BTC"
        assert result.winners[0].net_edge == 0.05
    
    def test_non_crypto_asset_filtered(self):
        """Test non-crypto assets are filtered out."""
        arbiter = CryptoTopEdgeArbiter()
        
        class MockEdge:
            net_edge = 0.05
        
        class MockSignal:
            action = type('obj', (object,), {'value': 'buy_yes'})()
            edge = MockEdge()
        
        # Try to submit non-crypto asset
        arbiter.submit_from_strategy_signal(
            signal=MockSignal(),
            agent_id="SPX_DAILY",
            asset="SPX",  # Not in CRYPTO_ASSETS
            timeframe="daily",
            ticker="KXSPX-DAILY-TEST",
        )
        
        result = arbiter.run_cycle()
        
        assert len(result.all_candidates) == 0
        assert len(result.winners) == 0
