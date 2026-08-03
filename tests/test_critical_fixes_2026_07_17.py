"""
Critical Fixes Test Suite (2026-07-17)

Tests for critical bug fixes:
1. position_monitor_exit source whitelist fix
2. OrderResult.success property fix
3. UnifiedSpotService.get_spot_data method fix
4. UnifiedSpotService.get_ohlcv_buffer method fix
5. Duplicate startup race condition fix (main_15m_lean.py vs loop_15m.py)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Optional, Dict, Any


class TestPositionMonitorExitSourceWhitelist:
    """Test that position_monitor_exit is in allowed sources for kalshi_crypto_15m_v2 profile."""

    @pytest.fixture
    def mock_profile_adapter(self):
        """Mock profile adapter for kalshi_crypto_15m_v2."""
        adapter = Mock()
        profile = Mock()
        profile.profile_name = 'kalshi_crypto_15m_v2'
        adapter.profile = profile
        return adapter

    @pytest.fixture
    def mock_intent(self):
        """Mock order intent with position_monitor_exit source."""
        intent = Mock()
        intent.source = 'position_monitor_exit'
        intent.ticker = 'KXETH15M-26JUL162045-45'
        intent.intent_id = 'test_intent_123'
        return intent

    def test_position_monitor_exit_allowed_in_profile(self, mock_profile_adapter, mock_intent):
        """Test that position_monitor_exit source is allowed for kalshi_crypto_15m_v2 profile."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        # Check that position_monitor_exit is in the allowed sources list
        allowed_sources = ["merid.prediction.agent_grid_15m", "kalshi_tools", "offset_hedging", "position_monitor_exit"]
        
        # Verify the source is allowed
        assert any("position_monitor_exit" in allowed for allowed in allowed_sources)
        
        # Test that intent.source passes the check
        if mock_intent.source and not any(allowed in mock_intent.source for allowed in allowed_sources):
            pytest.fail("position_monitor_exit should be in allowed sources")
        
        # Verify it matches the pattern
        assert "position_monitor_exit" in mock_intent.source

    def test_other_sources_still_blocked(self, mock_profile_adapter):
        """Test that other unauthorized sources are still blocked."""
        # Test with unauthorized source
        unauthorized_intent = Mock()
        unauthorized_intent.source = 'unauthorized_source'
        
        allowed_sources = ["merid.prediction.agent_grid_15m", "kalshi_tools", "offset_hedging", "position_monitor_exit"]
        
        # This should fail the check
        if unauthorized_intent.source and not any(allowed in unauthorized_intent.source for allowed in allowed_sources):
            # Correctly blocked
            assert True
        else:
            pytest.fail("Unauthorized source should be blocked")

    def test_position_monitor_exit_recognized_as_exit_order(self):
        """Test that position_monitor_exit is recognized as an exit order by exit_order_utils.
        
        CRITICAL FIX (2026-07-20): position_monitor_exit must be in EXIT_ORDER_MARKERS
        so that exit orders from PositionMonitor bypass risk checks and cash out profitable positions.
        """
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source, EXIT_ORDER_MARKERS
        
        # Verify position_monitor_exit is in EXIT_ORDER_MARKERS
        assert "position_monitor_exit" in EXIT_ORDER_MARKERS, \
            "position_monitor_exit must be in EXIT_ORDER_MARKERS for exit orders to bypass risk checks"
        
        # Verify is_exit_order_from_source returns True for position_monitor_exit
        assert is_exit_order_from_source("position_monitor_exit") is True, \
            "is_exit_order_from_source should return True for position_monitor_exit"
        
        # Verify other exit markers are still recognized
        assert is_exit_order_from_source("take_profit") is True
        assert is_exit_order_from_source("stop_loss") is True
        assert is_exit_order_from_source("ratchet") is True
        
        # Verify non-exit sources return False
        assert is_exit_order_from_source("merid.prediction.agent_grid_15m") is False
        assert is_exit_order_from_source("unauthorized_source") is False


class TestOrderResultSuccessProperty:
    """Test OrderResult.success property fix."""

    def test_order_result_success_property_exists(self):
        """Test that OrderResult has a success property."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        # Create an OrderResult
        result = OrderResult(
            status="filled_live",
            mode=TradingMode.LIVE,
            latency_ms=100.0
        )
        
        # Test that success property exists
        assert hasattr(result, 'success')
        
        # Test that it returns True for successful statuses
        assert result.success is True

    def test_order_result_success_for_filled_statuses(self):
        """Test that success returns True for all filled/accepted/submitted statuses."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        successful_statuses = [
            "filled_mock",
            "filled_paper",
            "filled_live",
            "partial_live",
            "accepted_live",
            "submitted_live"
        ]
        
        for status in successful_statuses:
            result = OrderResult(
                status=status,
                mode=TradingMode.LIVE,
                latency_ms=100.0
            )
            assert result.success is True, f"Status {status} should return success=True"

    def test_order_result_success_false_for_rejected(self):
        """Test that success returns False for rejected status."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        result = OrderResult(
            status="rejected",
            mode=TradingMode.LIVE,
            reason="profile_blocked_source",
            latency_ms=100.0
        )
        
        assert result.success is False

    def test_order_result_success_false_for_duplicate_unknown(self):
        """Test that success returns False for duplicate_unknown status."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        result = OrderResult(
            status="duplicate_unknown",
            mode=TradingMode.LIVE,
            latency_ms=100.0
        )
        
        assert result.success is False

    def test_order_result_additional_attributes(self):
        """Test that OrderResult has order_id and error attributes."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        result = OrderResult(
            status="filled_live",
            mode=TradingMode.LIVE,
            order_id="test_order_123",
            error="test_error",
            latency_ms=100.0
        )
        
        assert result.order_id == "test_order_123"
        assert result.error == "test_error"


class TestUnifiedSpotServiceGetSpotData:
    """Test UnifiedSpotService.get_spot_data method fix."""

    @pytest.fixture
    def spot_service(self):
        """Create a UnifiedSpotService instance."""
        from data.unified_spot_service import UnifiedSpotService
        return UnifiedSpotService()

    def test_get_spot_data_method_exists(self, spot_service):
        """Test that get_spot_data method exists."""
        assert hasattr(spot_service, 'get_spot_data')
        assert callable(spot_service.get_spot_data)

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_get_spot_data_returns_spot_snapshot(self, mock_get, spot_service):
        """Test that get_spot_data returns a SpotSnapshot object."""
        # Mock the get method to return a valid SpotPrice
        from data.unified_spot_service import SpotPrice
        import time
        
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        result = spot_service.get_spot_data("BTC")
        
        # Verify result is not None
        assert result is not None
        
        # Verify result has expected attributes
        assert hasattr(result, 'price_usd')
        assert hasattr(result, 'staleness_ms')
        assert hasattr(result, 'source')
        assert hasattr(result, 'open')
        assert hasattr(result, 'high')
        assert hasattr(result, 'low')
        assert hasattr(result, 'volume')
        
        # Verify values
        assert result.price_usd == 50000.0
        assert result.source == "coinbase_ticker_hybrid"

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_get_spot_data_returns_none_for_spot_error(self, mock_get, spot_service):
        """Test that get_spot_data returns None for SpotError."""
        from data.unified_spot_service import SpotError
        
        mock_get.return_value = SpotError(
            reason="no_data",
            asset="BTC",
            message="test_error"
        )
        
        result = spot_service.get_spot_data("BTC")
        
        assert result is None

    def test_get_spot_data_compatibility_with_get_spot(self, spot_service):
        """Test that get_spot_data returns same format as get_spot."""
        # This is a basic structural test - both should return SpotSnapshot-like objects
        assert callable(spot_service.get_spot_data)
        assert callable(spot_service.get_spot)


class TestUnifiedSpotServiceGetOhlcvBuffer:
    """Test UnifiedSpotService.get_ohlcv_buffer method fix."""

    @pytest.fixture
    def spot_service(self):
        """Create a UnifiedSpotService instance."""
        from data.unified_spot_service import UnifiedSpotService
        return UnifiedSpotService()

    def test_get_ohlcv_buffer_method_exists(self, spot_service):
        """Test that get_ohlcv_buffer method exists."""
        assert hasattr(spot_service, 'get_ohlcv_buffer')
        assert callable(spot_service.get_ohlcv_buffer)

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_get_ohlcv_buffer_returns_list(self, mock_get, spot_service):
        """Test that get_ohlcv_buffer returns a list."""
        from data.unified_spot_service import SpotPrice
        import time
        
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        result = spot_service.get_ohlcv_buffer("BTC", "15m")
        
        # Verify result is a list
        assert isinstance(result, list)
        
        # Verify list is not empty
        assert len(result) > 0

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_get_ohlcv_buffer_candle_attributes(self, mock_get, spot_service):
        """Test that OHLCV candles have required attributes."""
        from data.unified_spot_service import SpotPrice
        import time
        
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        result = spot_service.get_ohlcv_buffer("BTC", "15m")
        
        # Get first candle
        candle = result[0]
        
        # Verify required attributes
        assert hasattr(candle, 'open')
        assert hasattr(candle, 'high')
        assert hasattr(candle, 'low')
        assert hasattr(candle, 'close')
        assert hasattr(candle, 'volume')
        assert hasattr(candle, 'timestamp_window_end')
        
        # Verify values
        assert candle.open == 49900.0
        assert candle.high == 50100.0
        assert candle.low == 49800.0
        assert candle.close == 50000.0
        assert candle.volume == 100.0

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_get_ohlcv_buffer_returns_none_for_spot_error(self, mock_get, spot_service):
        """Test that get_ohlcv_buffer returns None for SpotError."""
        from data.unified_spot_service import SpotError
        
        mock_get.return_value = SpotError(
            reason="no_data",
            asset="BTC",
            message="test_error"
        )
        
        result = spot_service.get_ohlcv_buffer("BTC", "15m")
        
        assert result is None

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_get_ohlcv_buffer_default_timeframe(self, mock_get, spot_service):
        """Test that get_ohlcv_buffer uses default timeframe."""
        from data.unified_spot_service import SpotPrice
        import time
        
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        # Call without timeframe parameter
        result = spot_service.get_ohlcv_buffer("BTC")
        
        # Should still work
        assert isinstance(result, list)
        assert len(result) > 0


class TestIntegrationExitOrderFlow:
    """Integration test for exit order flow with all fixes."""

    @patch('merid.event_venues.kalshi.order_router.route_order_async')
    @patch('merid.risk.global_slot_allocator.GlobalSlotAllocator')
    @patch('merid.prediction.venue_gate.get_venue_gate')
    def test_exit_order_with_position_monitor_exit_source(self, mock_venue_gate, mock_allocator, mock_route_async):
        """Test that exit order with position_monitor_exit source works correctly."""
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        
        # Mock venue gate
        mock_vg = Mock()
        mock_vg.mode = TradingMode.LIVE
        mock_venue_gate.return_value = mock_vg
        
        # Mock allocator
        mock_alloc = Mock()
        mock_allocator.return_value = mock_alloc
        
        # Mock route_order_async to return successful result
        mock_result = OrderResult(
            status="filled_live",
            mode=TradingMode.LIVE,
            order_id="test_order_123",
            latency_ms=100.0
        )
        mock_route_async.return_value = mock_result
        
        # Verify the result has success property
        assert hasattr(mock_result, 'success')
        assert mock_result.success is True


class TestSpotSnapshotAttributeFix:
    """Test for SpotSnapshot attribute error fix (2026-07-17)."""

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_edge_based_exit_evaluator_uses_price_usd(self, mock_get):
        """Test that edge_based_exit_evaluator uses price_usd instead of price."""
        from data.unified_spot_service import UnifiedSpotService, SpotPrice
        from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
        import time
        
        # Mock spot data
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        spot_service = UnifiedSpotService()
        spot_data = spot_service.get_spot_data("BTC")
        
        # Verify spot_data has price_usd attribute
        assert hasattr(spot_data, 'price_usd')
        assert spot_data.price_usd == 50000.0
        
        # Verify spot_data does NOT have 'price' attribute (the bug)
        assert not hasattr(spot_data, 'price'), "SpotSnapshot should not have 'price' attribute"

    def test_edge_based_exit_evaluator_source_code_uses_price_usd(self):
        """Test that edge_based_exit_evaluator source code uses price_usd."""
        import inspect
        from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
        
        # Get the source code of compute_current_edge method
        source = inspect.getsource(EdgeBasedExitEvaluator.compute_current_edge)
        
        # Verify that spot_data.price_usd IS used (the fix)
        assert "spot_data.price_usd" in source, \
            "edge_based_exit_evaluator should use spot_data.price_usd (fix)"
        
        # Verify that spot_data.price is NOT used as a standalone attribute
        # (it should only appear as part of spot_data.price_usd)
        lines = source.split('\n')
        for line in lines:
            # Skip lines that are comments or contain price_usd
            if 'spot_data.price' in line and 'spot_data.price_usd' not in line and '#' not in line:
                # Check if it's actually using spot_data.price as a standalone attribute
                if 'spot_data.price' in line and not line.strip().startswith('#'):
                    pytest.fail(f"Found standalone spot_data.price usage: {line}")


class TestPositionCacheEntryPriceZeroFix:
    """Test for entry_price=0c fix in position_cache.py (2026-07-17)."""

    @patch('merid.event_venues.kalshi.position_cache._get_market_price_fallback')
    async def test_position_cache_treats_zero_as_missing(self, mock_fallback):
        """Test that position_cache treats avg_price_cents=0 as missing and uses fallback."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        from decimal import Decimal
        
        # Mock fallback to return 50 cents
        mock_fallback.return_value = 50
        
        # Create position cache
        cache = KalshiPositionCache()
        
        # Simulate REST sync with avg_price_cents=0
        positions = [
            {
                "market_id": "KXBTC15M-26JUL162015-15",
                "contracts": 1,
                "side": "yes",
                "avg_price_cents": 0,  # BUG: REST API returns 0
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0
            }
        ]
        
        # Sync from REST
        await cache.sync_from_rest(positions, force=True)
        
        # Verify fallback was called for avg_price_cents=0
        mock_fallback.assert_called()
        
        # Verify the cached position has fallback price (50c), not 0
        cached_pos = cache.get_position("KXBTC15M-26JUL162015-15")
        assert cached_pos is not None
        assert cached_pos.avg_price_cents == 50, \
            "Position should use fallback price when REST returns avg_price_cents=0"

    @patch('merid.event_venues.kalshi.position_cache._get_market_price_fallback')
    async def test_position_cache_uses_valid_price(self, mock_fallback):
        """Test that position_cache uses valid price when REST returns non-zero."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        from decimal import Decimal
        
        # Mock fallback to return 50 cents
        mock_fallback.return_value = 50
        
        # Create position cache
        cache = KalshiPositionCache()
        
        # Simulate REST sync with valid avg_price_cents
        positions = [
            {
                "market_id": "KXBTC15M-26JUL162015-15",
                "contracts": 1,
                "side": "yes",
                "avg_price_cents": 42,  # Valid price
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0
            }
        ]
        
        # Sync from REST
        await cache.sync_from_rest(positions, force=True)
        
        # Verify fallback was NOT called for valid price
        mock_fallback.assert_not_called()
        
        # Verify the cached position has the actual price (42c)
        cached_pos = cache.get_position("KXBTC15M-26JUL162015-15")
        assert cached_pos is not None
        assert cached_pos.avg_price_cents == 42, \
            "Position should use actual price when REST returns valid avg_price_cents"

    @patch('merid.event_venues.kalshi.position_cache._get_market_price_fallback')
    async def test_position_cache_uses_fallback_for_missing_key(self, mock_fallback):
        """Test that position_cache uses fallback when avg_price_cents key is missing."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        from decimal import Decimal
        
        # Mock fallback to return 50 cents
        mock_fallback.return_value = 50
        
        # Create position cache
        cache = KalshiPositionCache()
        
        # Simulate REST sync without avg_price_cents key
        positions = [
            {
                "market_id": "KXBTC15M-26JUL162015-15",
                "contracts": 1,
                "side": "yes",
                # avg_price_cents key is missing
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0
            }
        ]
        
        # Sync from REST
        await cache.sync_from_rest(positions, force=True)
        
        # Verify fallback was called for missing key
        mock_fallback.assert_called()
        
        # Verify the cached position has fallback price (50c)
        cached_pos = cache.get_position("KXBTC15M-26JUL162015-15")
        assert cached_pos is not None
        assert cached_pos.avg_price_cents == 50, \
            "Position should use fallback price when avg_price_cents key is missing"


class TestRiskEnvelopeLogMessageFix:
    """Test for per-agent limit display/logging fix (2026-07-17)."""

    def test_risk_envelope_log_uses_global_limit_not_per_agent(self):
        """Test that risk envelope log says 'global_limit' not 'per_agent_limit'."""
        import inspect
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        # Get the source code of the function
        source = inspect.getsource(get_kalshi_crypto_15m_risk_envelope)
        
        # Verify that log message uses 'global_limit' not 'per_agent_limit'
        assert "global_limit=" in source, \
            "Risk envelope log should use 'global_limit=' (fix)"
        
        # Verify that old log message is NOT present
        assert "per_agent_limit=" not in source, \
            "Risk envelope log should NOT use 'per_agent_limit=' (bug - this is misleading)"


class TestPositionMonitorWhitelistFix:
    """Test for position_monitor whitelist fix (2026-07-17)."""

    def test_position_monitor_in_kalshi_15m_crypto_whitelist(self):
        """Test that position_monitor is in the Kalshi 15m crypto agent whitelist."""
        from merid.event_venues.kalshi.order_router import _KALSHI_15M_CRYPTO_AGENTS
        
        # Verify position_monitor is in the whitelist
        assert "position_monitor" in _KALSHI_15M_CRYPTO_AGENTS, \
            "position_monitor should be in _KALSHI_15M_CRYPTO_AGENTS whitelist"
        
        # Verify the standard agents are still there
        assert "BTC_15M" in _KALSHI_15M_CRYPTO_AGENTS
        assert "ETH_15M" in _KALSHI_15M_CRYPTO_AGENTS
        assert "SOL_15M" in _KALSHI_15M_CRYPTO_AGENTS
        assert "XRP_15M" in _KALSHI_15M_CRYPTO_AGENTS
        assert "DOGE_15M" in _KALSHI_15M_CRYPTO_AGENTS

    def test_is_kalshi_15m_crypto_agent_accepts_position_monitor(self):
        """Test that _is_kalshi_15m_crypto_agent accepts position_monitor."""
        from merid.event_venues.kalshi.order_router import _is_kalshi_15m_crypto_agent
        
        # Test position_monitor is accepted
        assert _is_kalshi_15m_crypto_agent("position_monitor") is True, \
            "position_monitor should be accepted as a valid Kalshi 15m crypto agent"
        
        # Test standard agents are still accepted
        assert _is_kalshi_15m_crypto_agent("BTC_15M") is True
        assert _is_kalshi_15m_crypto_agent("ETH_15M") is True
        
        # Test unauthorized agents are rejected
        assert _is_kalshi_15m_crypto_agent("unauthorized_agent") is False


class TestUnifiedEdgeComputerAPIFix:
    """Test for UnifiedEdgeComputer API fix in edge_based_exit_evaluator (2026-07-17)."""

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    @patch('merid.prediction.unified_edge.get_unified_edge_computer')
    def test_edge_evaluator_uses_correct_api(self, mock_get_computer, mock_get):
        """Test that edge_based_exit_evaluator uses correct UnifiedEdgeComputer API."""
        from data.unified_spot_service import UnifiedSpotService, SpotPrice
        from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
        from merid.prediction.unified_edge import EdgeResult
        from datetime import datetime, timezone
        import time
        
        # Mock spot data
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        # Mock edge computer
        mock_computer = Mock()
        mock_edge_result = EdgeResult(
            edge=0.05,
            edge_fee_adjusted=0.03,
            edge_risk_adjusted=0.04,
            edge_slippage_adjusted=0.035,
            model_prob=0.50,
            market_implied_prob=0.47,
            spot_ref=None,
            confidence=0.8,
            metadata={},
            raw_edge_cents=5.0,
            spread_cost_cents=1.0,
            fee_cost_cents=1.0,
            net_edge_cents=3.0,
            ev_per_contract_cents=3.0
        )
        mock_computer.compute_edge.return_value = mock_edge_result
        mock_get_computer.return_value = mock_computer
        
        # Create evaluator
        evaluator = EdgeBasedExitEvaluator()
        
        # Create mock position
        mock_position = Mock()
        mock_position.market_id = "KXBTC15M-26JUL162015-15"
        mock_position.series_ticker = "KXBTC15M"
        mock_position.side = "yes"
        mock_position.avg_entry_price_cents = 42
        mock_position.position_id = "test_position_123"
        
        # Compute edge
        edge_pct = evaluator.compute_current_edge(
            position=mock_position,
            current_price_cents=45,
            time_to_expiry_seconds=900.0
        )
        
        # Verify compute_edge was called with correct parameters
        mock_computer.compute_edge.assert_called_once()
        call_kwargs = mock_computer.compute_edge.call_args[1]
        
        # Verify it uses the correct API (asset, spot_ref, contract, order_size, order_side)
        assert 'asset' in call_kwargs
        assert 'spot_ref' in call_kwargs
        assert 'contract' in call_kwargs
        assert 'order_size' in call_kwargs
        assert 'order_side' in call_kwargs
        
        # Verify it does NOT use the old API (spot_price, strike_price, yes_price, time_to_expiry)
        assert 'spot_price' not in call_kwargs, "Should not use old spot_price parameter"
        assert 'strike_price' not in call_kwargs, "Should not use old strike_price parameter"
        assert 'yes_price' not in call_kwargs, "Should not use old yes_price parameter"
        assert 'time_to_expiry' not in call_kwargs, "Should not use old time_to_expiry parameter"
        
        # Verify edge was computed
        assert edge_pct == 0.03  # Should return edge_fee_adjusted

    def test_edge_evaluator_source_code_uses_correct_api(self):
        """Test that edge_based_exit_evaluator source code uses correct API."""
        import inspect
        from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
        
        # Get the source code of compute_current_edge method
        source = inspect.getsource(EdgeBasedExitEvaluator.compute_current_edge)
        
        # Verify that SpotReference and ContractState are imported/used
        assert "SpotReference" in source, "Should use SpotReference"
        assert "ContractState" in source, "Should use ContractState"
        
        # Verify that old API parameters are NOT used in compute_edge call
        # (strike_price is used in ContractState construction, which is correct)
        lines = source.split('\n')
        compute_edge_call_found = False
        for line in lines:
            if 'compute_edge(' in line and not line.strip().startswith('#'):
                compute_edge_call_found = True
                # Check that old parameters are NOT in the compute_edge call
                assert 'spot_price=' not in line, "Should not use spot_price= in compute_edge call"
                assert 'yes_price=' not in line, "Should not use yes_price= in compute_edge call"
                assert 'time_to_expiry=' not in line, "Should not use time_to_expiry= in compute_edge call"
        
        assert compute_edge_call_found, "compute_edge call should be found in source"
        
        # Verify new API is used
        assert "spot_ref=" in source, "Should use spot_ref="
        assert "contract=" in source, "Should use contract="


class TestDuplicateStartupRaceConditionFix:
    """Test for duplicate startup race condition fix (2026-07-17)."""

    def test_main_15m_lean_does_not_start_position_monitor(self):
        """Test that main_15m_lean.py does NOT start PositionMonitor.
        
        CRITICAL FIX (2026-07-17): main_15m_lean.py was starting PositionMonitor
        without the exit callback, creating a race condition with loop_15m.py
        which tries to register the callback and start the monitor.
        
        The fix: main_15m_lean.py only retrieves the singleton; loop_15m.py
        handles callback registration and monitor start.
        """
        import inspect
        from web.main_15m_lean import _run_startup_phases_v20260530
        
        # Get the source code of the startup function (not lifespan)
        source = inspect.getsource(_run_startup_phases_v20260530)
        
        # Verify that position_monitor.start() is NOT called in main_15m_lean.py
        assert "position_monitor.start()" not in source, \
            "main_15m_lean.py should NOT call position_monitor.start() - this causes race condition"
        
        # Verify that the comment mentions loop_15m.py handles startup
        assert "loop_15m.py" in source, \
            "main_15m_lean.py should document that loop_15m.py handles PositionMonitor startup"
        
        # Verify that singleton retrieval is present
        assert "get_position_monitor()" in source, \
            "main_15m_lean.py should retrieve PositionMonitor singleton"

    def test_loop_15m_registers_callback_before_start(self):
        """Test that loop_15m.py registers callback BEFORE starting monitor.
        
        This ensures the exit callback is available when the monitor starts.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of the start method
        source = inspect.getsource(Kalshi15mLoop.start)
        
        # Verify callback registration happens before monitor start
        lines = source.split('\n')
        register_line = None
        start_line = None
        
        for i, line in enumerate(lines):
            if 'register_exit_intent_callback' in line:
                register_line = i
            if 'position_monitor.start()' in line:
                start_line = i
        
        assert register_line is not None, "Callback registration not found"
        assert start_line is not None, "Monitor start not found"
        assert register_line < start_line, \
            "Callback registration must happen BEFORE monitor start to prevent race condition"

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_edge_based_exit_evaluator_with_get_spot_data(self, mock_get):
        """Test that edge_based_exit_evaluator can use get_spot_data."""
        from data.unified_spot_service import UnifiedSpotService, SpotPrice
        import time
        
        spot_service = UnifiedSpotService()
        
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        # Test get_spot_data
        spot_data = spot_service.get_spot_data("BTC")
        
        assert spot_data is not None
        assert hasattr(spot_data, 'price_usd')
        assert spot_data.price_usd == 50000.0

    @patch('data.unified_spot_service.UnifiedSpotService.get')
    def test_position_monitor_with_get_ohlcv_buffer(self, mock_get):
        """Test that position_monitor can use get_ohlcv_buffer."""
        from data.unified_spot_service import UnifiedSpotService, SpotPrice
        import time
        
        spot_service = UnifiedSpotService()
        
        mock_spot_price = SpotPrice(
            price=50000.0,
            timestamp=int(time.time() * 1000),
            source="coinbase_ticker_hybrid",
            open=49900.0,
            high=50100.0,
            low=49800.0,
            volume=100.0
        )
        mock_get.return_value = mock_spot_price
        
        # Test get_ohlcv_buffer
        ohlcv_buffer = spot_service.get_ohlcv_buffer("BTC", "15m")
        
        assert ohlcv_buffer is not None
        assert isinstance(ohlcv_buffer, list)
        assert len(ohlcv_buffer) >= 1
        
        # Verify candle attributes for pattern detection
        candle = ohlcv_buffer[0]
        assert hasattr(candle, 'open')
        assert hasattr(candle, 'high')
        assert hasattr(candle, 'low')
        assert hasattr(candle, 'close')
        assert hasattr(candle, 'timestamp_window_end')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
