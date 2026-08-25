"""Unit tests for LiquidityFallbackExecutor.

Tests the tiered fallback logic for liquidity crisis management,
based on Markaicode research (2024) on flash crash prevention.
"""

import pytest
from decimal import Decimal

from merid.risk.liquidity_fallback import (
    LiquidityFallbackExecutor,
    ExecutionTier,
    FallbackConfig,
    LiquidityScore,
    get_liquidity_fallback_executor,
    init_liquidity_fallback_executor,
)


class TestExecutionTier:
    """Test ExecutionTier enum."""
    
    def test_tier_values(self):
        """Test that all tier values are defined."""
        assert ExecutionTier.NORMAL.value == "normal"
        assert ExecutionTier.CAUTIOUS.value == "cautious"
        assert ExecutionTier.DEFENSIVE.value == "defensive"
        assert ExecutionTier.EMERGENCY.value == "emergency"
        assert ExecutionTier.HALT.value == "halt"


class TestFallbackConfig:
    """Test FallbackConfig dataclass."""
    
    def test_config_creation(self):
        """Test creating a fallback config."""
        config = FallbackConfig(
            tier=ExecutionTier.NORMAL,
            max_order_size_usd=50000,
            max_spread_pct=0.5,
            order_type='limit',
            limit_offset_bps=10,
            max_clip_size_pct=0.25,
            timeout_seconds=30,
            min_confidence=0.55,
        )
        
        assert config.tier == ExecutionTier.NORMAL
        assert config.max_order_size_usd == 50000
        assert config.max_spread_pct == 0.5
        assert config.order_type == 'limit'
        assert config.limit_offset_bps == 10
        assert config.max_clip_size_pct == 0.25
        assert config.timeout_seconds == 30
        assert config.min_confidence == 0.55


class TestLiquidityScore:
    """Test LiquidityScore dataclass."""
    
    def test_score_creation(self):
        """Test creating a liquidity score."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={"spread_score": 32.0, "depth_score": 30.0, "stability_score": 20.0},
        )
        
        assert score.score == 85.0
        assert score.tier == ExecutionTier.NORMAL
        assert score.spread_pct == 0.02
        assert score.depth_total == 150
        assert score.depth_ratio == 0.75
        assert score.spread_ratio == 0.8
        assert score.details["spread_score"] == 32.0


class TestLiquidityFallbackExecutor:
    """Test LiquidityFallbackExecutor functionality."""
    
    @pytest.fixture
    def executor(self):
        """Create a LiquidityFallbackExecutor instance for testing."""
        return LiquidityFallbackExecutor(
            score_window=5,
        )
    
    @pytest.fixture
    def mock_orderbook(self):
        """Create a mock OrderbookSnapshot for testing.
        
        Respects Kalshi's YES/NO duality: yes_ask = 100 - no_bid
        """
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        return OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(
                OrderbookLevel(price_cents=50, size=100),
                OrderbookLevel(price_cents=49, size=50),
            ),
            no_bids=(
                OrderbookLevel(price_cents=45, size=50),  # yes_ask = 100 - 45 = 55
            ),
            seq=0,
            ts=1000.0,
        )
    
    def test_executor_initialization(self, executor):
        """Test executor initialization."""
        assert executor.score_window == 5
        assert len(executor.configs) == 5  # All tiers
        assert ExecutionTier.NORMAL in executor.configs
        assert ExecutionTier.HALT in executor.configs
        assert executor._score_history == {}
        assert executor._max_depth_ref == {}
        assert executor._max_spread_ref == {}
    
    def test_custom_configs(self):
        """Test executor with custom configurations."""
        custom_configs = {
            ExecutionTier.NORMAL: FallbackConfig(
                tier=ExecutionTier.NORMAL,
                max_order_size_usd=100000,
                max_spread_pct=0.3,
                order_type='limit',
                limit_offset_bps=5,
                max_clip_size_pct=0.30,
                timeout_seconds=30,
                min_confidence=0.50,
            ),
        }
        
        executor = LiquidityFallbackExecutor(configs=custom_configs)
        
        assert executor.configs[ExecutionTier.NORMAL].max_order_size_usd == 100000
        assert executor.configs[ExecutionTier.NORMAL].max_spread_pct == 0.3
    
    def test_compute_liquidity_score_normal(self, executor, mock_orderbook):
        """Test liquidity score computation for NORMAL tier."""
        score = executor.compute_liquidity_score(mock_orderbook, side="yes")
        
        assert score.score >= 70.0  # Should be in NORMAL tier
        assert score.tier == ExecutionTier.NORMAL
        assert score.spread_pct >= 0.0
        assert score.depth_total > 0
        assert 0.0 <= score.depth_ratio <= 1.0
        assert 0.0 <= score.spread_ratio <= 1.0
    
    def test_compute_liquidity_score_caution(self, executor, mock_orderbook):
        """Test liquidity score computation for CAUTIOUS tier."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        # Reduce depth to trigger CAUTIOUS tier
        mock_orderbook_caution = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=10),),
            no_bids=mock_orderbook.no_bids,
            seq=mock_orderbook.seq,
            ts=mock_orderbook.ts,
        )
        
        score = executor.compute_liquidity_score(mock_orderbook_caution, side="yes")
        
        # After multiple updates, should move to lower tier
        for _ in range(6):
            score = executor.compute_liquidity_score(mock_orderbook_caution, side="yes")
        
        assert 40.0 <= score.score < 70.0 or score.tier == ExecutionTier.CAUTIOUS
    
    def test_compute_liquidity_score_halt(self, executor, mock_orderbook):
        """Test liquidity score computation for HALT tier."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        # Zero depth to trigger HALT
        mock_orderbook_halt = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(),
            no_bids=(),
            seq=mock_orderbook.seq,
            ts=mock_orderbook.ts,
        )
        
        score = executor.compute_liquidity_score(mock_orderbook_halt, side="yes")
        
        # After multiple updates, should move to HALT
        for _ in range(6):
            score = executor.compute_liquidity_score(mock_orderbook_halt, side="yes")
        
        assert score.tier == ExecutionTier.HALT or score.score == 0.0
    
    def test_score_smoothing(self, executor, mock_orderbook):
        """Test that scores are smoothed over the window."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        scores = []
        for i in range(10):
            # Vary depth to create score variation
            mock_orderbook_varied = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(OrderbookLevel(price_cents=50, size=100 if i % 2 == 0 else 10),),
                no_bids=mock_orderbook.no_bids,
                seq=mock_orderbook.seq,
                ts=mock_orderbook.ts,
            )
            score = executor.compute_liquidity_score(mock_orderbook_varied, side="yes")
            scores.append(score.score)
        
        # Check that history is maintained
        assert len(executor._score_history[mock_orderbook.ticker]) == executor.score_window
    
    def test_get_execution_config(self, executor):
        """Test getting execution config for a tier."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        config = executor.get_execution_config(score)
        
        assert config.tier == ExecutionTier.NORMAL
        assert config.max_order_size_usd == 50000
        assert config.max_spread_pct == 0.5
    
    def test_should_execute_normal(self, executor):
        """Test execution decision in NORMAL tier."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        should_execute, reason = executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=1000.0,
        )
        
        assert should_execute is True
        assert "approved" in reason.lower()
    
    def test_should_execute_halt(self, executor):
        """Test execution decision in HALT tier."""
        score = LiquidityScore(
            score=0.0,
            tier=ExecutionTier.HALT,
            spread_pct=0.0,
            depth_total=0,
            depth_ratio=0.0,
            spread_ratio=0.0,
            details={},
        )
        
        should_execute, reason = executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=1000.0,
        )
        
        assert should_execute is False
        assert "halt" in reason.lower()
    
    def test_should_execute_low_confidence(self, executor):
        """Test execution decision with low model confidence."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        should_execute, reason = executor.should_execute(
            score,
            model_confidence=0.4,  # Below min_confidence of 0.55
            order_size_usd=1000.0,
        )
        
        assert should_execute is False
        assert "confidence" in reason.lower()
    
    def test_should_execute_oversized_order(self, executor):
        """Test execution decision with oversized order."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        should_execute, reason = executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=100000.0,  # Above max_order_size_usd of 50000
        )
        
        assert should_execute is False
        assert "size" in reason.lower()
    
    def test_should_execute_wide_spread(self, executor):
        """Test execution decision with wide spread."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.60,  # Above max_spread_pct of 0.5
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        should_execute, reason = executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=1000.0,
        )
        
        assert should_execute is False
        assert "spread" in reason.lower()
    
    def test_adjust_order_size_normal(self, executor):
        """Test order size adjustment in NORMAL tier."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        adjusted = executor.adjust_order_size(score, 1000.0)
        
        # Should not reduce (within tier limit)
        assert adjusted <= 1000.0
        assert adjusted <= 50000.0  # Tier max
    
    def test_adjust_order_size_oversized(self, executor):
        """Test order size adjustment for oversized order."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        adjusted = executor.adjust_order_size(score, 100000.0)
        
        # Should cap at tier max
        assert adjusted == 50000.0
    
    def test_adjust_order_size_defensive(self, executor):
        """Test order size adjustment in DEFENSIVE tier."""
        score = LiquidityScore(
            score=30.0,
            tier=ExecutionTier.DEFENSIVE,
            spread_pct=0.05,
            depth_total=50,
            depth_ratio=0.25,
            spread_ratio=0.5,
            details={},
        )
        
        adjusted = executor.adjust_order_size(score, 10000.0)
        
        # Should cap at DEFENSIVE tier max (2000)
        assert adjusted <= 2000.0
    
    def test_get_limit_offset(self, executor):
        """Test getting limit order offset."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        offset = executor.get_limit_offset(score)
        
        assert offset == 10  # NORMAL tier offset
    
    def test_get_timeout(self, executor):
        """Test getting order timeout."""
        score = LiquidityScore(
            score=85.0,
            tier=ExecutionTier.NORMAL,
            spread_pct=0.02,
            depth_total=150,
            depth_ratio=0.75,
            spread_ratio=0.8,
            details={},
        )
        
        timeout = executor.get_timeout(score)
        
        assert timeout == 30  # NORMAL tier timeout


class TestSingletonPattern:
    """Test singleton pattern for liquidity fallback executor."""
    
    def test_init_singleton(self):
        """Test initializing the singleton."""
        executor = init_liquidity_fallback_executor()
        
        assert executor is not None
        assert isinstance(executor, LiquidityFallbackExecutor)
    
    def test_get_singleton(self):
        """Test getting the singleton instance."""
        # Initialize
        init_liquidity_fallback_executor()
        
        # Get
        executor = get_liquidity_fallback_executor()
        
        assert executor is not None
        assert isinstance(executor, LiquidityFallbackExecutor)
    
    def test_singleton_same_instance(self):
        """Test that singleton returns the same instance."""
        executor1 = init_liquidity_fallback_executor()
        executor2 = get_liquidity_fallback_executor()
        
        assert executor1 is executor2
    
    def test_singleton_custom_config(self):
        """Test singleton with custom configuration."""
        custom_configs = {
            ExecutionTier.NORMAL: FallbackConfig(
                tier=ExecutionTier.NORMAL,
                max_order_size_usd=100000,
                max_spread_pct=0.3,
                order_type='limit',
                limit_offset_bps=5,
                max_clip_size_pct=0.30,
                timeout_seconds=30,
                min_confidence=0.50,
            ),
        }
        
        executor = init_liquidity_fallback_executor(configs=custom_configs, force_reinit=True)
        
        assert executor.configs[ExecutionTier.NORMAL].max_order_size_usd == 100000


class TestLiquidityFallbackEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_multiple_tickers(self):
        """Test executor with multiple tickers."""
        executor = LiquidityFallbackExecutor()
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        ob1 = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=50, size=50),),
            seq=0,
            ts=1000.0,
        )
        
        ob2 = OrderbookSnapshot(
            ticker="KXETH15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=50, size=50),),
            seq=0,
            ts=1000.0,
        )
        
        # Process both
        executor.compute_liquidity_score(ob1, side="yes")
        executor.compute_liquidity_score(ob2, side="yes")
        
        # Verify separate score history
        assert "KXBTC15M-26AUG012215-15" in executor._score_history
        assert "KXETH15M-26AUG012215-15" in executor._score_history
    
    def test_zero_depth_orderbook(self):
        """Test liquidity score with zero depth."""
        executor = LiquidityFallbackExecutor()
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        
        ob = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(),
            no_bids=(),
            seq=0,
            ts=1000.0,
        )
        
        score = executor.compute_liquidity_score(ob, side="yes")
        
        assert score.depth_total == 0
        assert score.depth_ratio == 0.0
    
    def test_wide_spread_orderbook(self):
        """Test liquidity score with wide spread."""
        executor = LiquidityFallbackExecutor()
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        # Create orderbook with wide spread (respecting YES/NO duality)
        # yes_bid=10, no_bid=20 → yes_ask=100-20=80, spread=70
        ob = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=10, size=100),),
            no_bids=(OrderbookLevel(price_cents=20, size=50),),
            seq=0,
            ts=1000.0,
        )
        
        score = executor.compute_liquidity_score(ob, side="yes")
        
        assert score.spread_pct > 0.5  # Should be high


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
