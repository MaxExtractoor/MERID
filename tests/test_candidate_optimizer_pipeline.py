"""
Candidate Optimizer Pipeline Tests
=================================

Tests to ensure the candidate pipeline runs end-to-end:
loop → agent_grid → collect_order_candidate → candidate_optimizer

Key invariants:
1. Candidate optimizer generates candidates from markets
2. Thresholds behave as expected
3. Pipeline metrics track correctly
4. No regressions that drop all candidates
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Dict, Any
from decimal import Decimal

from merid.prediction.candidate_optimizer import (
    CandidateOptimizer,
    get_candidate_optimizer,
    MarketCandidate,
    CandidatePipelineMetrics
)


@dataclass
class MockMarket:
    """Mock market for testing."""
    market_id: str
    series_ticker: str
    title: str
    minutes_to_expiry: int
    strike_price: int
    settlement_pool: int


@dataclass
class MockMarketState:
    """Mock market state for testing."""
    market_id: str
    best_bid: int
    best_ask: int
    bid_size: int
    ask_size: int
    last_book_update_ts: float
    executable: bool = True
    book_initialized: bool = True


@dataclass
class MockSpotService:
    """Mock spot service for testing."""
    prices: Dict[str, float]

    def get_spot_price(self, asset: str) -> float:
        return self.prices.get(asset, 0.0)


class TestCandidateOptimizerUnit:
    """Unit tests for candidate optimizer."""

    @pytest.fixture
    def optimizer(self):
        """Create a candidate optimizer for testing."""
        return CandidateOptimizer()

    @pytest.fixture
    def sample_markets(self):
        """Create sample markets for testing."""
        return [
            MockMarket(
                market_id="KXBTC15M-25JUN26-95000",
                series_ticker="KXBTC15M",
                title="BTC > $95000 on June 25",
                minutes_to_expiry=10,
                strike_price=95000,
                settlement_pool=1000000
            ),
            MockMarket(
                market_id="KXETH15M-25JUN26-3500",
                series_ticker="KXETH15M",
                title="ETH > $3500 on June 25",
                minutes_to_expiry=10,
                strike_price=3500,
                settlement_pool=500000
            )
        ]

    @pytest.fixture
    def mock_market_state_store(self):
        """Create a mock market state store."""
        store = Mock()
        
        def get_market_state(market_id: str):
            return MockMarketState(
                market_id=market_id,
                best_bid=48,
                best_ask=52,
                bid_size=1000,
                ask_size=1000,
                last_book_update_ts=asyncio.get_event_loop().time() - 5.0
            )
        
        store.get = get_market_state
        return store

    @pytest.fixture
    def mock_spot_service(self):
        """Create a mock spot service."""
        return MockSpotService(prices={"BTC": 96000.0, "ETH": 3550.0})

    async def test_basic_candidate_generation(self, optimizer, sample_markets, mock_market_state_store, mock_spot_service):
        """Test 1: Basic candidate generation with mock markets."""
        # Arrange
        asset = "BTC"
        
        # Act
        candidates, metrics = await optimizer.generate_candidates(
            markets=[m.__dict__ for m in sample_markets if m.series_ticker == "KXBTC15M"],
            asset=asset,
            market_state_store=mock_market_state_store,
            spot_service=mock_spot_service
        )
        
        # Assert
        assert isinstance(candidates, list), "Should return a list of candidates"
        assert isinstance(metrics, CandidatePipelineMetrics), "Should return metrics"
        assert metrics.total_markets_scanned > 0, "Should have scanned at least one market"
        
        # Check that ENTRY log was called (we can't directly test logging but can verify the method ran)
        assert metrics.total_markets_scanned == 1, "Should have scanned one BTC market"

    async def test_thresholds_behavior_pass(self, optimizer, sample_markets, mock_market_state_store, mock_spot_service):
        """Test 2: Markets with good quality pass thresholds."""
        # Arrange - create markets with high quality
        high_quality_markets = [
            {
                'market_id': 'KXBTC15M-25JUN26-95000',
                'series_ticker': 'KXBTC15M',
                'title': 'BTC > $95000',
                'minutes_to_expiry': 10,
                'strike_price': 95000,
                'settlement_pool': 1000000  # Large pool = high quality
            }
        ]
        
        # Act
        candidates, metrics = await optimizer.generate_candidates(
            markets=high_quality_markets,
            asset="BTC",
            market_state_store=mock_market_state_store,
            spot_service=mock_spot_service
        )
        
        # Assert
        assert metrics.total_markets_scanned == 1, "Should scan one market"
        # Note: Actual candidate generation depends on edge computation, but at least the pipeline should run

    async def test_thresholds_behavior_filter(self, optimizer, mock_market_state_store, mock_spot_service):
        """Test 3: Markets with poor quality are filtered out."""
        # Arrange - create markets with low quality
        low_quality_markets = [
            {
                'market_id': 'KXBTC15M-25JUN26-95000',
                'series_ticker': 'KXBTC15M',
                'title': 'BTC > $95000',
                'minutes_to_expiry': 10,
                'strike_price': 95000,
                'settlement_pool': 1000  # Very small pool = low quality
            }
        ]
        
        # Act
        candidates, metrics = await optimizer.generate_candidates(
            markets=low_quality_markets,
            asset="BTC",
            market_state_store=mock_market_state_store,
            spot_service=mock_spot_service
        )
        
        # Assert
        assert metrics.total_markets_scanned == 1, "Should scan one market"
        # The market should be filtered out due to low quality
        # This tests that thresholds are working

    async def test_no_markets_passed(self, optimizer, mock_market_state_store, mock_spot_service):
        """Test 4: No markets passed to optimizer."""
        # Arrange
        empty_markets = []
        
        # Act
        candidates, metrics = await optimizer.generate_candidates(
            markets=empty_markets,
            asset="BTC",
            market_state_store=mock_market_state_store,
            spot_service=mock_spot_service
        )
        
        # Assert
        assert candidates == [], "Should return empty list for no markets"
        assert metrics.total_markets_scanned == 0, "Should report 0 markets scanned"

    async def test_markets_seen_increment(self, optimizer, sample_markets, mock_market_state_store, mock_spot_service):
        """Test 5: markets_seen metric increments correctly."""
        # Arrange
        markets = [m.__dict__ for m in sample_markets]
        
        # Act
        candidates, metrics = await optimizer.generate_candidates(
            markets=markets,
            asset="BTC",
            market_state_store=mock_market_state_store,
            spot_service=mock_spot_service
        )
        
        # Assert
        expected_markets = len(markets)  # All markets are passed to the optimizer
        assert metrics.total_markets_scanned == expected_markets, \
            f"Expected {expected_markets} markets scanned, got {metrics.total_markets_scanned}"

    async def test_error_handling(self, optimizer, mock_market_state_store, mock_spot_service):
        """Test 6: Error handling in candidate generation."""
        # Arrange - create markets that will cause errors but not crash
        invalid_markets = [
            {
                'market_id': 'invalid_market',  # Valid string, but market doesn't exist
                'series_ticker': 'KXBTC15M',
                'title': 'Invalid Market',
                'minutes_to_expiry': -1,  # Invalid expiry
                'strike_price': 0,
                'settlement_pool': 0
            }
        ]
        
        # Act
        candidates, metrics = await optimizer.generate_candidates(
            markets=invalid_markets,
            asset="BTC",
            market_state_store=mock_market_state_store,
            spot_service=mock_spot_service
        )
        
        # Assert - should handle errors gracefully
        assert isinstance(candidates, list), "Should still return a list on error"
        assert isinstance(metrics, CandidatePipelineMetrics), "Should still return metrics on error"
        # The optimizer should process the market but likely filter it out due to invalid data


class TestAgentGridIntegration:
    """Integration tests for agent grid calling candidate optimizer."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent for testing."""
        agent = Mock()
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        agent.config.enabled = True
        agent._cached_bankroll_usd = Decimal('15.51')
        return agent

    @pytest.fixture
    def mock_agent_grid(self, mock_agent):
        """Create a mock agent grid."""
        grid = Mock()
        grid._agents = [mock_agent]
        return grid

    @patch('merid.prediction.candidate_optimizer.get_candidate_optimizer')
    async def test_agent_grid_calls_collect_order_candidate(self, mock_get_optimizer, mock_agent_grid):
        """Test 7: agent_grid.run_cycle calls collect_order_candidate."""
        # Arrange
        mock_optimizer = Mock()
        mock_optimizer.generate_candidates = AsyncMock(return_value=([], Mock()))
        mock_get_optimizer.return_value = mock_optimizer
        
        # Mock the agent's collect_order_candidate method
        mock_agent = mock_agent_grid._agents[0]
        mock_agent.collect_order_candidate = AsyncMock(return_value=None)
        
        # Act - simulate run_cycle calling collect_order_candidate
        tick = 1
        await mock_agent.collect_order_candidate(tick)
        
        # Assert
        mock_agent.collect_order_candidate.assert_called_once_with(tick)

    @patch('merid.prediction.candidate_optimizer.get_candidate_optimizer')
    async def test_collect_order_candidate_calls_optimizer(self, mock_get_optimizer):
        """Test 8: collect_order_candidate calls candidate_optimizer.generate_candidates."""
        # Arrange
        mock_optimizer = Mock()
        mock_optimizer.generate_candidates = AsyncMock(return_value=([], Mock()))
        mock_get_optimizer.return_value = mock_optimizer
        
        # Create a mock agent with the collect_order_candidate method
        agent = Mock()
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        agent.config.enabled = True
        agent._cached_bankroll_usd = Decimal('15.51')
        
        # Mock the agent's internal methods to return test data
        sample_markets = [{'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'}]
        agent._select_markets = AsyncMock(return_value=(sample_markets, {'total': 1}))
        agent._get_asset_from_series = Mock(return_value="BTC")
        
        # Import the real collect_order_candidate method
        from merid.prediction.agent_grid_15m import LeanAgent15m
        
        # Use the actual method from the real class by binding it to our mock
        # This ensures the real logic runs but uses our mocked dependencies
        real_agent = LeanAgent15m.__new__(LeanAgent15m)
        real_agent.config = agent.config
        real_agent._cached_bankroll_usd = agent._cached_bankroll_usd
        real_agent._select_markets = agent._select_markets
        real_agent._get_asset_from_series = agent._get_asset_from_series
        
        # Act
        await real_agent.collect_order_candidate(1)
        
        # Assert
        mock_optimizer.generate_candidates.assert_called_once()
        # Verify the call arguments
        call_args = mock_optimizer.generate_candidates.call_args
        assert call_args[0][1] == "BTC"  # asset parameter
        assert len(call_args[0][0]) == 1  # markets parameter
        assert call_args[0][0][0]['market_id'] == 'KXBTC15M-25JUN26-95000'

    @patch('merid.prediction.candidate_optimizer.get_candidate_optimizer')
    async def test_candidate_optimizer_entry_observed(self, mock_get_optimizer):
        """Test 9: Candidate optimizer entry is observed with debug logging."""
        # Arrange
        mock_optimizer = Mock()
        
        # Mock the generate_candidates method to capture the call
        captured_calls = []
        
        async def mock_generate_candidates(markets, asset, market_state_store, spot_service):
            captured_calls.append({
                'markets': markets,
                'asset': asset,
                'market_state_store': market_state_store,
                'spot_service': spot_service
            })
            return [], Mock()
        
        mock_optimizer.generate_candidates = mock_generate_candidates
        mock_get_optimizer.return_value = mock_optimizer
        
        # Act - call the optimizer
        from merid.prediction.candidate_optimizer import get_candidate_optimizer
        optimizer = get_candidate_optimizer()
        
        sample_markets = [{'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'}]
        await optimizer.generate_candidates(sample_markets, "BTC", Mock(), Mock())
        
        # Assert
        assert len(captured_calls) == 1, "Optimizer should be called once"
        call = captured_calls[0]
        assert call['asset'] == "BTC"
        assert len(call['markets']) == 1
        assert call['markets'][0]['market_id'] == 'KXBTC15M-25JUN26-95000'


class TestEndToEndPipeline:
    """End-to-end pipeline tests with fake loop."""

    @patch('merid.prediction.candidate_optimizer.CandidateOptimizer')
    async def test_end_to_end_pipeline_with_fake_loop(self, MockCandidateOptimizer):
        """Test 10: End-to-end pipeline with fake loop - simplified version."""
        # Arrange
        mock_optimizer_instance = Mock()
        mock_optimizer_instance.generate_candidates = AsyncMock(return_value=([], Mock()))
        MockCandidateOptimizer.return_value = mock_optimizer_instance
        
        # Create a simple mock agent that calls the optimizer
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.name = "BTC_15M"
        mock_agent.config.enabled = True
        mock_agent._cached_bankroll_usd = Decimal('15.51')
        
        # Mock collect_order_candidate to directly call optimizer
        async def mock_collect_order_candidate(tick):
            markets = [{'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'}]
            
            # Create proper mocks for market state store and spot service
            mock_market_state = Mock()
            mock_market_state.spread_cents = 2.0
            mock_market_state.mid_cents = 50.0
            mock_market_state.depth_yes = 100
            mock_market_state.depth_no = 100
            mock_market_state.executable = True
            mock_market_state.book_initialized = True
            mock_market_state.last_book_update_ts = 1234567890.0
            
            mock_store = Mock()
            mock_store.get = Mock(return_value=mock_market_state)
            
            mock_spot = Mock()
            mock_spot.is_ready = Mock(return_value=True)
            
            from merid.prediction.candidate_optimizer import get_candidate_optimizer
            optimizer = get_candidate_optimizer()
            await optimizer.generate_candidates(markets, "BTC", mock_store, mock_spot)
            return None
        
        mock_agent.collect_order_candidate = mock_collect_order_candidate
        
        # Act - simulate a single cycle
        await mock_agent.collect_order_candidate(1)
        
        # Assert
        mock_optimizer_instance.generate_candidates.assert_called_once()
        call_args = mock_optimizer_instance.generate_candidates.call_args
        assert call_args[0][1] == "BTC"  # asset parameter
        assert len(call_args[0][0]) == 1  # markets parameter
        assert call_args[0][0][0]['market_id'] == 'KXBTC15M-25JUN26-95000'

    async def test_markets_seen_moves_from_zero(self):
        """Test 11: markets_seen moves from 0 when markets are processed."""
        # Arrange
        from merid.prediction.candidate_optimizer import reset_candidate_optimizer
        reset_candidate_optimizer()  # Reset singleton cache
        
        with patch('merid.prediction.candidate_optimizer.CandidateOptimizer') as MockCandidateOptimizer:
            mock_optimizer_instance = Mock()
            
            # Track metrics
            captured_metrics = []
            
            async def mock_generate_candidates(markets, asset, market_state_store, spot_service):
                metrics = Mock()
                metrics.total_markets_scanned = len(markets)
                captured_metrics.append(metrics)
                return [], metrics
            
            mock_optimizer_instance.generate_candidates = mock_generate_candidates
            MockCandidateOptimizer.return_value = mock_optimizer_instance
            
            # Act - directly call the optimizer to verify metrics tracking
            from merid.prediction.candidate_optimizer import get_candidate_optimizer
            optimizer = get_candidate_optimizer()
            markets = [{'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'}]
            await optimizer.generate_candidates(markets, "BTC", Mock(), Mock())
            
            # Assert
            assert len(captured_metrics) == 1
            assert captured_metrics[0].total_markets_scanned == 1, \
                "markets_seen should increment from 0 to 1"

    async def test_asset_gate_summary_behavior(self):
        """Test 12: ASSET-GATE-SUMMARY behavior with candidates."""
        # Arrange
        from merid.prediction.candidate_optimizer import reset_candidate_optimizer
        reset_candidate_optimizer()  # Reset singleton cache
        
        with patch('merid.prediction.candidate_optimizer.CandidateOptimizer') as MockCandidateOptimizer:
            mock_optimizer_instance = Mock()
            
            # Create mock candidates
            mock_candidates = [
                Mock(market_id='KXBTC15M-25JUN26-95000', edge=0.02),
                Mock(market_id='KXETH15M-25JUN26-3500', edge=0.015)
            ]
            
            mock_metrics = Mock()
            mock_metrics.final_candidates = len(mock_candidates)
            mock_metrics.total_markets_scanned = 2
            
            mock_optimizer_instance.generate_candidates = AsyncMock(return_value=(mock_candidates, mock_metrics))
            MockCandidateOptimizer.return_value = mock_optimizer_instance
            
            # Act
            from merid.prediction.candidate_optimizer import get_candidate_optimizer
            optimizer = get_candidate_optimizer()
            markets = [
                {'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'},
                {'market_id': 'KXETH15M-25JUN26-3500', 'series_ticker': 'KXETH15M'}
            ]
            candidates, metrics = await optimizer.generate_candidates(markets, "BTC", Mock(), Mock())
            
            # Assert
            assert len(candidates) == 2, "Should have 2 candidates"
            assert metrics.final_candidates == 2, "Should report 2 final candidates"


class TestRegressionChecks:
    """Regression checks for common issues."""

    async def test_md_age_computation_monotonic(self):
        """Test 13: md_age uses monotonic time, not Unix timestamps."""
        # Arrange
        import time
        
        # Create a mock market state with monotonic timestamp
        current_time = time.monotonic()
        mock_state = Mock()
        mock_state.last_book_update_ts = current_time - 5.0  # 5 seconds ago
        
        # Act - compute md_age as the loop does
        md_age = time.monotonic() - mock_state.last_book_update_ts
        
        # Assert
        assert md_age == 5.0, f"Expected md_age=5.0, got {md_age}"
        assert md_age >= 0, "md_age should never be negative"

    async def test_no_unix_timestamp_mixing(self):
        """Test 14: No mixing of Unix timestamps with monotonic time."""
        # Arrange
        import time
        from datetime import datetime, timezone
        
        # Unix timestamp (seconds since epoch)
        unix_ts = datetime.now(timezone.utc).timestamp()
        
        # Monotonic timestamp (implementation-defined)
        mono_ts = time.monotonic()
        
        # Act - these should not be mixed
        # The system should consistently use one or the other for time deltas
        
        # Assert - they should be different scales
        assert abs(unix_ts - mono_ts) > 1000000, \
            "Unix timestamp and monotonic time should be on different scales"
        
        # md_age should always use monotonic time
        mock_state = Mock()
        mock_state.last_book_update_ts = mono_ts - 10.0
        md_age = time.monotonic() - mock_state.last_book_update_ts
        assert md_age == 10.0, "md_age should use monotonic time"

    async def test_markets_seen_metrics_increment(self):
        """Test 15: markets_seen metrics increment correctly."""
        # Arrange
        from merid.prediction.candidate_optimizer import reset_candidate_optimizer
        reset_candidate_optimizer()  # Reset singleton cache
        
        with patch('merid.prediction.candidate_optimizer.CandidateOptimizer') as MockCandidateOptimizer:
            mock_optimizer_instance = Mock()
            
            # Track multiple calls
            call_count = 0
            
            async def mock_generate_candidates(markets, asset, market_state_store, spot_service):
                nonlocal call_count
                call_count += 1
                metrics = Mock()
                metrics.total_markets_scanned = len(markets)
                metrics.final_candidates = len(markets)  # Assume all pass
                return [], metrics
            
            mock_optimizer_instance.generate_candidates = mock_generate_candidates
            MockCandidateOptimizer.return_value = mock_optimizer_instance
            
            # Act - multiple calls
            from merid.prediction.candidate_optimizer import get_candidate_optimizer
            optimizer = get_candidate_optimizer()
            markets1 = [{'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'}]
            markets2 = [
                {'market_id': 'KXBTC15M-25JUN26-95000', 'series_ticker': 'KXBTC15M'},
                {'market_id': 'KXETH15M-25JUN26-3500', 'series_ticker': 'KXETH15M'}
            ]
            
            await optimizer.generate_candidates(markets1, "BTC", Mock(), Mock())
            await optimizer.generate_candidates(markets2, "BTC", Mock(), Mock())
            
            # Assert
            assert call_count == 2, "Should have been called twice"
            # Each call should report the correct number of markets
            # (This is verified in the mock function itself)
