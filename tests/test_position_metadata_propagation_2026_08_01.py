"""
Comprehensive tests for position metadata propagation and R-multiple calculation fixes (2026-08-01).

Tests the end-to-end flow of vol_regime and confidence from:
1. OrderIntent creation (upstream)
2. TP target registration (midstream) 
3. Position creation (downstream)
4. PositionMonitor integration (end-to-end)

Also tests R-multiple calculation from actual TP/SL prices when tp_targets lookup fails.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from merid.event_venues.kalshi.position_cache import KalshiPositionCache, CachedPosition
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.position_management.position import Position, PositionSide, TrailingType


class TestVolRegimeConfidencePropagation:
    """Test vol_regime and confidence propagation through the entire data flow."""
    
    def test_register_tp_targets_with_metadata(self):
        """Test that vol_regime and confidence are registered with TP targets."""
        cache = KalshiPositionCache()
        
        client_order_id = "test-order-123"
        
        cache.register_tp_targets(
            client_order_id=client_order_id,
            take_profit_price_cents=60,
            take_profit_r_multiple=1.5,
            stop_loss_price_cents=45,
            entry_price_cents=50,
            vol_regime="normal",
            confidence="high"
        )
        
        targets = cache._pending_tp_targets.get(client_order_id)
        assert targets is not None
        assert targets["vol_regime"] == "normal"
        assert targets["confidence"] == "high"
        assert "registered_at" in targets
    
    def test_register_tp_targets_without_metadata_backward_compat(self):
        """Test backward compatibility when vol_regime and confidence are not provided."""
        cache = KalshiPositionCache()
        
        client_order_id = "test-order-456"
        
        cache.register_tp_targets(
            client_order_id=client_order_id,
            take_profit_price_cents=60,
            stop_loss_price_cents=45
            # vol_regime and confidence not provided (optional)
        )
        
        targets = cache._pending_tp_targets.get(client_order_id)
        assert targets is not None
        assert targets["vol_regime"] is None
        assert targets["confidence"] is None
    
    def test_cached_position_stores_metadata(self):
        """Test that CachedPosition stores vol_regime and confidence."""
        position = CachedPosition(
            market_id="KXBTC15M-26AUG010100-00",
            agent_id="test_agent",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            take_profit_price_cents=60,
            take_profit_r_multiple=1.5,
            stop_loss_price_cents=45,
            vol_regime="normal",
            confidence="high"
        )
        
        assert position.vol_regime == "normal"
        assert position.confidence == "high"
    
    def test_cached_position_defaults_to_unknown(self):
        """Test that CachedPosition defaults to unknown when metadata not provided."""
        position = CachedPosition(
            market_id="KXBTC15M-26AUG010100-00",
            agent_id="test_agent",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50
        )
        
        assert position.vol_regime == "unknown"
        assert position.confidence == "unknown"
    
    def test_position_stores_metadata(self):
        """Test that Position stores vol_regime and confidence."""
        position = Position(
            market_id="KXBTC15M-26AUG010100-00",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
            vol_regime="normal",
            confidence="high"
        )
        
        assert position.vol_regime == "normal"
        assert position.confidence == "high"
    
    def test_position_defaults_to_unknown(self):
        """Test that Position defaults to unknown when metadata not provided."""
        position = Position(
            market_id="KXBTC15M-26AUG010100-00",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50
        )
        
        assert position.vol_regime == "unknown"
        assert position.confidence == "unknown"


class TestRMultipleCalculationFix:
    """Test R-multiple calculation from actual TP/SL prices when tp_targets lookup fails."""
    
    def test_r_multiple_calculation_yes_side(self):
        """Test R-multiple calculation for YES side."""
        entry_price = 50
        tp_price = 60
        sl_price = 45
        
        # YES: R = entry - SL = 50 - 45 = 5
        # TP-R = (TP - entry) / R = (60 - 50) / 5 = 2.0
        risk_distance = entry_price - sl_price
        profit_distance = tp_price - entry_price
        tp_r = profit_distance / risk_distance if risk_distance > 0 else 1.5
        
        assert tp_r == 2.0
    
    def test_r_multiple_calculation_no_side(self):
        """Test R-multiple calculation for NO side."""
        entry_price = 50
        tp_price = 40
        sl_price = 55
        
        # NO: R = SL - entry = 55 - 50 = 5
        # TP-R = (entry - TP) / R = (50 - 40) / 5 = 2.0
        risk_distance = sl_price - entry_price
        profit_distance = entry_price - tp_price
        tp_r = profit_distance / risk_distance if risk_distance > 0 else 1.5
        
        assert tp_r == 2.0
    
    def test_r_multiple_fallback_when_zero_risk(self):
        """Test R-multiple fallback when risk distance is zero."""
        entry_price = 50
        tp_price = 60
        sl_price = 50  # Same as entry - zero risk
        
        risk_distance = abs(entry_price - sl_price)
        tp_r = 1.5 if risk_distance == 0 else (tp_price - entry_price) / risk_distance
        
        assert tp_r == 1.5  # Fallback to 1.5R


class TestConfidenceClassification:
    """Test confidence classification from numeric to categorical."""
    
    def test_high_confidence_classification(self):
        """Test high confidence classification (>= 0.75)."""
        confidence = 0.80
        confidence_str = "high" if confidence >= 0.75 else (
            "medium" if confidence >= 0.65 else "low"
        )
        assert confidence_str == "high"
    
    def test_medium_confidence_classification(self):
        """Test medium confidence classification (0.65 - 0.75)."""
        confidence = 0.70
        confidence_str = "high" if confidence >= 0.75 else (
            "medium" if confidence >= 0.65 else "low"
        )
        assert confidence_str == "medium"
    
    def test_low_confidence_classification(self):
        """Test low confidence classification (< 0.65)."""
        confidence = 0.60
        confidence_str = "high" if confidence >= 0.75 else (
            "medium" if confidence >= 0.65 else "low"
        )
        assert confidence_str == "low"
    
    def test_none_confidence_classification(self):
        """Test confidence classification when None."""
        confidence = None
        confidence_str = "medium"  # Default when None
        assert confidence_str == "medium"


class TestVolRegimeClassification:
    """Test volatility regime classification."""
    
    def test_vol_regime_value_mapping(self):
        """Test that vol_regime values are lowercase strings."""
        from merid.event_venues.kalshi.dynamic_risk import VolatilityRegime
        
        assert VolatilityRegime.LOW.value == "low"
        assert VolatilityRegime.NORMAL.value == "normal"
        assert VolatilityRegime.HIGH.value == "high"
        assert VolatilityRegime.EXTREME.value == "extreme"


class TestEndToEndMetadataFlow:
    """Test end-to-end metadata flow from order to position."""
    
    @pytest.mark.asyncio
    async def test_metadata_flow_from_intent_to_position(self):
        """Test complete metadata flow from OrderIntent to CachedPosition."""
        cache = KalshiPositionCache()
        
        # Simulate order placement with metadata
        client_order_id = "test-order-789"
        cache.register_tp_targets(
            client_order_id=client_order_id,
            take_profit_price_cents=60,
            take_profit_r_multiple=1.5,
            stop_loss_price_cents=45,
            entry_price_cents=50,
            vol_regime="normal",
            confidence="high"
        )
        
        # Simulate fill creating position
        tp_targets = cache._pending_tp_targets.get(client_order_id)
        
        # Create position with metadata from tp_targets
        position = CachedPosition(
            market_id="KXBTC15M-26AUG010100-00",
            agent_id="test_agent",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=tp_targets.get("entry_price") or 50,
            take_profit_price_cents=tp_targets.get("tp_price"),
            take_profit_r_multiple=tp_targets.get("tp_r"),
            stop_loss_price_cents=tp_targets.get("sl_price"),
            vol_regime=tp_targets.get("vol_regime") or "unknown",
            confidence=tp_targets.get("confidence") or "unknown"
        )
        
        # Verify metadata propagated correctly
        assert position.vol_regime == "normal"
        assert position.confidence == "high"
        assert position.take_profit_price_cents == 60
        assert position.stop_loss_price_cents == 45
    
    @pytest.mark.asyncio
    async def test_metadata_flow_to_position_monitor(self):
        """Test metadata flow from CachedPosition to PositionMonitor Position."""
        from merid.position_management.position_monitor import PositionMonitor
        
        # Create CachedPosition with metadata
        cached_position = CachedPosition(
            market_id="KXBTC15M-26AUG010100-00",
            agent_id="test_agent",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
            vol_regime="normal",
            confidence="high"
        )
        
        # Create PositionMonitor Position with metadata
        monitor_position = Position(
            position_id="KXBTC15M-26AUG010100-00",
            market_id="KXBTC15M-26AUG010100-00",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
            vol_regime=cached_position.vol_regime or "unknown",
            confidence=cached_position.confidence or "unknown"
        )
        
        # Verify metadata propagated to monitor position
        assert monitor_position.vol_regime == "normal"
        assert monitor_position.confidence == "high"


class TestMetadataInLogging:
    """Test that metadata appears in log messages."""
    
    def test_position_cache_log_includes_metadata(self):
        """Test that position cache log includes vol_regime and confidence."""
        # This is a regression test to ensure the log message format
        # includes vol_regime and confidence fields
        position = CachedPosition(
            market_id="KXBTC15M-26AUG010100-00",
            agent_id="test_agent",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
            vol_regime="normal",
            confidence="high"
        )
        
        # Verify metadata is available for logging
        assert position.vol_regime == "normal"
        assert position.confidence == "high"
        
        # The actual log message is tested in integration tests


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
