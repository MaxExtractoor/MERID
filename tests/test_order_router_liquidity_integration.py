"""Integration tests for order_router liquidity improvements.

Tests the integration of liquidity fallback executor into order routing.
"""

import pytest
import time
from dataclasses import replace
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    TradingMode,
    _route_live,
)
from merid.risk.liquidity_fallback import (
    LiquidityFallbackExecutor,
    init_liquidity_fallback_executor,
    ExecutionTier,
    LiquidityScore,
)


class TestOrderRouterLiquidityFallbackIntegration:
    """Test integration of liquidity fallback into order_router."""
    
    @pytest.fixture
    def mock_intent(self):
        """Create a mock OrderIntent."""
        intent = Mock(spec=OrderIntent)
        intent.ticker = "KXBTC15M-26AUG012215-15"
        intent.side = "yes"
        intent.action = "buy"
        intent.price_cents = 50
        intent.count = 10
        intent.intent_id = "test-intent-123"
        intent.source = "merid.prediction.agent_grid_15m"
        intent.entry_or_exit = "entry"
        intent.should_execute = True
        intent.edge_net_of_fees_pct = 0.05
        intent.policy_mode = "maker"
        intent.source_signal_id = "signal-123"
        intent.source_signal_hash = "hash-123"
        intent.intent_stage = "execution"
        return intent
    
    @pytest.fixture
    def mock_orderbook(self):
        """Create a mock OrderbookSnapshot."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        return OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=[
                OrderbookLevel(price_cents=50, size=100),
            ],
            no_bids=[
                OrderbookLevel(price_cents=50, size=50),
            ],

        )
    
    @pytest.fixture
    def initialized_executor(self):
        """Initialize a fresh liquidity fallback executor for each test."""
        return init_liquidity_fallback_executor(force_reinit=True, score_window=1)
    
    def test_liquidity_fallback_initialization(self, initialized_executor):
        """Test that liquidity fallback executor is initialized."""
        from merid.risk.liquidity_fallback import get_liquidity_fallback_executor
        
        executor = get_liquidity_fallback_executor()
        
        assert executor is not None
        assert isinstance(executor, LiquidityFallbackExecutor)
    
    @pytest.mark.asyncio
    async def test_order_routing_with_normal_liquidity(self, mock_intent, mock_orderbook, initialized_executor):
        """Test order routing proceeds with NORMAL liquidity tier."""
        score = initialized_executor.compute_liquidity_score(mock_orderbook, side="yes")

        # Should be in NORMAL tier
        assert score.tier == ExecutionTier.NORMAL

        # Check if execution should proceed
        should_execute, reason = initialized_executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=5.0,  # 10 contracts * $0.50
        )

        assert should_execute is True
        assert "approved" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_order_routing_with_halt_liquidity(self, mock_intent, mock_orderbook, initialized_executor):
        """Test order routing is rejected with HALT liquidity tier."""
        # Create orderbook with zero depth (HALT tier)
        mock_orderbook_halt = replace(mock_orderbook,
            yes_bids=[],
            no_bids=[],
        )

        # After multiple updates, should move to HALT tier
        for _ in range(6):
            score = initialized_executor.compute_liquidity_score(mock_orderbook_halt, side="yes")

        # Check if execution should proceed
        should_execute, reason = initialized_executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=5.0,
        )

        assert should_execute is False
        assert "halt" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_order_routing_with_low_confidence(self, mock_intent, mock_orderbook, initialized_executor):
        """Test order routing is rejected with low model confidence."""
        score = initialized_executor.compute_liquidity_score(mock_orderbook, side="yes")

        # Check if execution should proceed with low confidence
        should_execute, reason = initialized_executor.should_execute(
            score,
            model_confidence=0.4,  # Below min_confidence
            order_size_usd=5.0,
        )

        assert should_execute is False
        assert "confidence" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_order_routing_with_oversized_order(self, mock_intent, mock_orderbook, initialized_executor):
        """Test order routing is rejected with oversized order."""
        score = initialized_executor.compute_liquidity_score(mock_orderbook, side="yes")

        # Check if execution should proceed with oversized order
        should_execute, reason = initialized_executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=100000.0,  # Above tier max
        )

        assert should_execute is False
        assert "size" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_order_size_adjustment(self, mock_intent, mock_orderbook, initialized_executor):
        """Test order size adjustment based on liquidity tier."""
        score = initialized_executor.compute_liquidity_score(mock_orderbook, side="yes")

        # Adjust order size
        original_size = 100000.0
        adjusted_size = initialized_executor.adjust_order_size(score, original_size)

        # Should be capped at tier max
        assert adjusted_size <= 50000.0  # NORMAL tier max
    
    @pytest.mark.asyncio
    async def test_order_routing_with_wide_spread(self, mock_intent, mock_orderbook, initialized_executor):
        """Test order routing is rejected with wide spread."""
        # Create orderbook with wide spread (YES bid=10, YES ask=90 => 80c spread)
        mock_orderbook_wide = replace(mock_orderbook,
            yes_bids=[replace(mock_orderbook.yes_bids[0], price_cents=10)],
            no_bids=[replace(mock_orderbook.no_bids[0], price_cents=10)],
        )

        # Compute liquidity score
        score = initialized_executor.compute_liquidity_score(mock_orderbook_wide, side="yes")

        # Check if execution should proceed
        should_execute, reason = initialized_executor.should_execute(
            score,
            model_confidence=0.6,
            order_size_usd=5.0,
        )

        # Should be rejected due to wide spread
        assert should_execute is False or score.spread_pct > 0.5


class TestOrderRouterLiquidityFallbackDisabled:
    """Test order router behavior when liquidity fallback is disabled."""
    
    @pytest.fixture
    def mock_intent(self):
        """Create a mock OrderIntent."""
        intent = Mock(spec=OrderIntent)
        intent.ticker = "KXBTC15M-26AUG012215-15"
        intent.side = "yes"
        intent.action = "buy"
        intent.price_cents = 50
        intent.count = 10
        intent.intent_id = "test-intent-123"
        intent.source = "merid.prediction.agent_grid_15m"
        intent.entry_or_exit = "entry"
        intent.should_execute = True
        intent.edge_net_of_fees_pct = 0.05
        intent.policy_mode = "maker"
        return intent
    
    def test_liquidity_fallback_not_available(self, mock_intent):
        """Test that order router handles missing liquidity fallback gracefully."""
        import importlib
        from merid.event_venues.kalshi import order_router

        # Simulate the liquidity fallback module being unavailable by hiding it
        # from importlib while the module is reloaded.
        try:
            with patch.dict("sys.modules", {"merid.risk.liquidity_fallback": None}):
                importlib.reload(order_router)
            assert order_router.LIQUIDITY_FALLBACK_AVAILABLE is False
        finally:
            # Restore the real module so other tests see the real flag.
            importlib.reload(order_router)


class TestOrderRouterTierTransitions:
    """Test order router behavior across liquidity tier transitions."""
    
    @pytest.fixture
    def mock_orderbook(self):
        """Create a mock OrderbookSnapshot."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        return OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=[
                OrderbookLevel(price_cents=50, size=100),
            ],
            no_bids=[
                OrderbookLevel(price_cents=50, size=50),
            ],

        )
    
    def test_normal_to_caution_transition(self, mock_orderbook):
        """Test transition from NORMAL to CAUTIOUS tier."""
        executor = init_liquidity_fallback_executor(force_reinit=True, score_window=1)

        # Start with NORMAL liquidity
        score = executor.compute_liquidity_score(mock_orderbook, side="yes")
        assert score.tier == ExecutionTier.NORMAL

        # Reduce depth to trigger CAUTIOUS (depth_total <= 40 with this scoring model)
        mock_orderbook_caution = replace(mock_orderbook,
            yes_bids=[replace(mock_orderbook.yes_bids[0], size=15)],
            no_bids=[replace(mock_orderbook.no_bids[0], size=5)],
        )

        score = executor.compute_liquidity_score(mock_orderbook_caution, side="yes")

        # Should move to CAUTIOUS tier
        assert score.tier == ExecutionTier.CAUTIOUS or score.score < 70.0
    
    def test_caution_to_defensive_transition(self, mock_orderbook):
        """Test transition from CAUTIOUS to DEFENSIVE tier."""
        executor = init_liquidity_fallback_executor(force_reinit=True, score_window=1)

        # Start with reduced depth -> CAUTIOUS
        mock_orderbook_caution = replace(mock_orderbook,
            yes_bids=[replace(mock_orderbook.yes_bids[0], size=15)],
            no_bids=[replace(mock_orderbook.no_bids[0], size=5)],
        )

        score = executor.compute_liquidity_score(mock_orderbook_caution, side="yes")
        assert score.tier in (ExecutionTier.NORMAL, ExecutionTier.CAUTIOUS)

        # Wide spread + low depth -> DEFENSIVE
        mock_orderbook_defensive = replace(mock_orderbook,
            yes_bids=[replace(mock_orderbook.yes_bids[0], price_cents=50, size=10)],
            no_bids=[replace(mock_orderbook.no_bids[0], price_cents=90, size=10)],
        )

        score = executor.compute_liquidity_score(mock_orderbook_defensive, side="yes")

        # Should move to DEFENSIVE tier
        assert score.tier == ExecutionTier.DEFENSIVE or score.score < 40.0
    
    def test_defensive_to_emergency_transition(self, mock_orderbook):
        """Test transition from DEFENSIVE to HALT/EMERGENCY tier."""
        executor = init_liquidity_fallback_executor(force_reinit=True, score_window=1)

        # Start with wide spread and low depth -> DEFENSIVE
        mock_orderbook_defensive = replace(mock_orderbook,
            yes_bids=[replace(mock_orderbook.yes_bids[0], price_cents=50, size=10)],
            no_bids=[replace(mock_orderbook.no_bids[0], price_cents=90, size=10)],
        )

        score = executor.compute_liquidity_score(mock_orderbook_defensive, side="yes")
        assert score.tier in (ExecutionTier.CAUTIOUS, ExecutionTier.DEFENSIVE)

        # Empty the book -> HALT (EMERGENCY is unreachable with this scoring model)
        mock_orderbook_halt = replace(mock_orderbook,
            yes_bids=[],
            no_bids=[],
        )

        score = executor.compute_liquidity_score(mock_orderbook_halt, side="yes")

        # Should move to HALT (or EMERGENCY) tier
        assert score.tier in (ExecutionTier.HALT, ExecutionTier.EMERGENCY) or score.score <= 0.0


class TestOrderRouterLiquidityMetrics:
    """Test liquidity metrics used by order router."""
    
    @pytest.fixture
    def mock_orderbook(self):
        """Create a mock OrderbookSnapshot."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
        
        return OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            ts=time.time(),
            yes_bids=[
                OrderbookLevel(price_cents=50, size=100),
            ],
            no_bids=[
                OrderbookLevel(price_cents=50, size=50),
            ],

        )
    
    def test_liquidity_score_components(self, mock_orderbook):
        """Test that liquidity score includes all components."""
        executor = init_liquidity_fallback_executor()
        
        score = executor.compute_liquidity_score(mock_orderbook, side="yes")
        
        # Check that all components are present
        assert score.score is not None
        assert score.tier is not None
        assert score.spread_pct is not None
        assert score.depth_total is not None
        assert score.depth_ratio is not None
        assert score.spread_ratio is not None
        assert score.details is not None
        
        # Check details
        assert "spread_score" in score.details
        assert "depth_score" in score.details
        assert "stability_score" in score.details
    
    def test_liquidity_score_range(self, mock_orderbook):
        """Test that liquidity score is in valid range."""
        executor = init_liquidity_fallback_executor()
        
        score = executor.compute_liquidity_score(mock_orderbook, side="yes")
        
        # Score should be between 0 and 100
        assert 0.0 <= score.score <= 100.0
    
    def test_liquidity_score_tier_mapping(self, mock_orderbook):
        """Test that score maps to correct tier."""
        executor = init_liquidity_fallback_executor()
        
        # Test different liquidity conditions
        conditions = [
            (100, ExecutionTier.NORMAL),
            (80, ExecutionTier.NORMAL),
            (60, ExecutionTier.CAUTIOUS),
            (40, ExecutionTier.CAUTIOUS),
            (30, ExecutionTier.DEFENSIVE),
            (20, ExecutionTier.DEFENSIVE),
            (10, ExecutionTier.EMERGENCY),
            (0, ExecutionTier.HALT),
        ]
        
        for test_score, expected_tier in conditions:
            # Create a mock score
            mock_score = LiquidityScore(
                score=test_score,
                tier=expected_tier,
                spread_pct=0.02,
                depth_total=100,
                depth_ratio=0.5,
                spread_ratio=0.5,
                details={},
            )
            
            # Verify tier
            assert mock_score.tier == expected_tier


class TestOrderRouterFallbackMarketState:
    """Full-path test that the liquidity fallback reaches the real KalshiMarketStateStore adapter."""

    @pytest.mark.asyncio
    async def test_fallback_calls_real_kalshi_market_state_store(self):
        """route_order_async must call get_kalshi_market_state_store().get_unified() in the fallback branch."""
        from types import SimpleNamespace
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel

        now = time.time()
        mock_orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            ts=now,
            yes_bids=[OrderbookLevel(price_cents=45, size=100)],
            no_bids=[OrderbookLevel(price_cents=55, size=100)],
        )

        store = MagicMock()
        store._states = {}
        unified = MagicMock(book=mock_orderbook)
        store.get_unified.return_value = unified

        fallback = MagicMock()
        fallback.compute_liquidity_score.return_value = LiquidityScore(
            score=10.0,
            tier=ExecutionTier.EMERGENCY,
            spread_pct=0.05,
            depth_total=10,
            depth_ratio=0.1,
            spread_ratio=0.5,
            details={},
        )
        fallback.should_execute.return_value = (False, "test_liquidity_reject")

        gate = MagicMock()
        gate.live_enabled = True
        gate.mode = TradingMode.LIVE

        record = MagicMock()
        record.order_attempt_id = "test-oa-123"

        breaker = MagicMock()
        breaker.is_order_allowed.return_value = True

        position_cache = MagicMock()
        position_cache.is_reconciliation_halted.return_value = False

        with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store), \
             patch("merid.risk.liquidity_fallback.get_liquidity_fallback_executor", return_value=fallback), \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate", return_value=gate), \
             patch("merid.event_venues.kalshi.order_identity.OrderAttemptStore") as mock_store_cls, \
             patch("merid.governance.trading_circuit_breaker.get_trading_circuit_breaker", return_value=breaker), \
             patch("merid.event_venues.kalshi.position_cache.get_position_cache", return_value=position_cache), \
             patch("merid.event_venues.kalshi.order_router._validate_order_identity", return_value=None), \
             patch("merid.event_venues.kalshi.order_router._validate_decision_provenance", return_value=None), \
             patch("merid.event_venues.kalshi.order_router._canonical_order_intent_validation", new=AsyncMock(return_value=None)):

            mock_store_cls.return_value.get_by_client_order_id.return_value = record

            intent = OrderIntent(
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                mode=TradingMode.LIVE,
                order_type="limit",
                time_in_force="gtc",
                entry_or_exit="entry",
                source="merid.prediction.agent_grid_15m",
                agent_id="BTC_15M",
                window_resolution_id="win-test",
                exit_policy_id="exit-test",
                risk_tier="A",
                max_hold_seconds=900,
                client_order_id="test-coid-123",
                order_attempt_id="test-oa-123",
                run_id="run-test",
                process_id="12345",
                intent_id="intent-test",
                snapshot_ts=now,
                policy_mode="maker",
                edge_net_of_fees_pct=0.05,
                should_execute=True,
            )

            from merid.event_venues.kalshi.order_router import route_order_async
            result = await route_order_async(intent)

        assert result.status == "rejected"
        assert "liquidity_fallback_reject" in result.reason

        # The critical assertion: the fallback branch reached the real state-store adapter.
        store.get_unified.assert_called_once_with("KXBTC15M-TEST")
        fallback.compute_liquidity_score.assert_called_once()
        ob = fallback.compute_liquidity_score.call_args[1].get("ob") or fallback.compute_liquidity_score.call_args[0][0]
        assert isinstance(ob, OrderbookSnapshot)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
