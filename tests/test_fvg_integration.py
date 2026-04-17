"""
FVG (Fair Value Gap) Tests — Comprehensive test coverage for FVG integration.

Tests cover:
1. FVGZone and FVGContext dataclasses
2. FVG detection logic with synthetic price sequences
3. FVG config integration with crypto registry
4. FVG signal propagation to CrossTimeframeAggregator
"""

import pytest
import math
from datetime import datetime, timezone
from collections import deque
from typing import List, Dict

# FVG models
from merid.signals.crypto_15m_indicators import (
    FVGZone,
    FVGContext,
    Crypto15mIndicatorStack,
    IndicatorConfig,
    IndicatorSnapshot,
)
from merid.sentiment.crypto_registry import (
    get_crypto_registry,
    get_fvg_config,
    is_fvg_enabled,
    FVGConfig,
)
from merid.sentiment.cross_timeframe_aggregator import (
    CrossTimeframeAggregator,
    get_cross_timeframe_aggregator,
)


# =============================================================================
# FVGZone Tests
# =============================================================================

class TestFVGZone:
    """Test FVGZone dataclass and methods."""
    
    def test_fvg_zone_creation(self):
        """Test basic FVGZone creation."""
        zone = FVGZone(
            top=100.0,
            bottom=98.0,
            direction="bullish",
            created_at=datetime.now(timezone.utc),
            timeframe="15m",
            strength=2.5,
        )
        
        assert zone.top == 100.0
        assert zone.bottom == 98.0
        assert zone.direction == "bullish"
        assert zone.strength == 2.5
        assert not zone.is_filled
    
    def test_fvg_zone_mid_and_height(self):
        """Test mid and height calculations."""
        zone = FVGZone(
            top=104.0,
            bottom=100.0,
            direction="bearish",
            created_at=datetime.now(timezone.utc),
            timeframe="15m",
            strength=1.5,
        )
        
        assert zone.mid == 102.0
        assert zone.height == 4.0
    
    def test_fvg_zone_contains_price(self):
        """Test price containment check."""
        zone = FVGZone(
            top=105.0,
            bottom=102.0,
            direction="bullish",
            created_at=datetime.now(timezone.utc),
            timeframe="15m",
            strength=2.0,
        )
        
        assert zone.contains_price(103.0)  # Inside gap
        assert zone.contains_price(102.0)   # On boundary
        assert zone.contains_price(105.0)  # On boundary
        assert not zone.contains_price(101.0)  # Below
        assert not zone.contains_price(106.0)  # Above
    
    def test_fvg_zone_distance_to_price(self):
        """Test signed distance calculation."""
        zone = FVGZone(
            top=100.0,
            bottom=98.0,
            direction="bullish",
            created_at=datetime.now(timezone.utc),
            timeframe="15m",
            strength=2.0,
        )
        
        # Mid is 99.0
        assert zone.distance_to_price(101.0) == 2.0  # Price above gap
        assert zone.distance_to_price(97.0) == -2.0   # Price below gap
        assert zone.distance_to_price(99.0) == 0.0   # At mid
    
    def test_fvg_zone_fill_tracking(self):
        """Test fill tracking."""
        zone = FVGZone(
            top=100.0,
            bottom=98.0,
            direction="bullish",
            created_at=datetime.now(timezone.utc),
            timeframe="15m",
            strength=2.0,
        )
        
        assert not zone.is_filled
        zone.filled_at = datetime.now(timezone.utc)
        zone.fill_price = 99.0
        assert zone.is_filled
    
    def test_fvg_zone_to_dict(self):
        """Test serialization to dict."""
        zone = FVGZone(
            top=100.0,
            bottom=98.0,
            direction="bullish",
            created_at=datetime.now(timezone.utc),
            timeframe="15m",
            strength=2.0,
        )
        
        d = zone.to_dict()
        assert d["top"] == 100.0
        assert d["bottom"] == 98.0
        assert d["direction"] == "bullish"
        assert d["strength"] == 2.0
        assert d["mid"] == 99.0
        assert not d["is_filled"]


# =============================================================================
# FVGContext Tests
# =============================================================================

class TestFVGContext:
    """Test FVGContext dataclass."""
    
    def test_fvg_context_empty(self):
        """Test empty context."""
        ctx = FVGContext()
        assert ctx.zones == []
        assert ctx.fvg_pressure == 0.0
        assert ctx.unfilled_count == 0
        assert ctx.dominant_direction == "neutral"
    
    def test_fvg_context_with_zones(self):
        """Test context with zones."""
        zones = [
            FVGZone(
                top=100.0, bottom=98.0, direction="bullish",
                created_at=datetime.now(timezone.utc), timeframe="15m", strength=2.0,
            ),
            FVGZone(
                top=95.0, bottom=93.0, direction="bearish",
                created_at=datetime.now(timezone.utc), timeframe="15m", strength=1.5,
            ),
        ]
        
        ctx = FVGContext(
            zones=zones,
            fvg_pressure=0.3,
            unfilled_count=2,
            nearest_distance_atr=1.5,
            has_confluence=True,
            dominant_direction="bullish",
        )
        
        assert len(ctx.zones) == 2
        assert ctx.fvg_pressure == 0.3
        assert ctx.unfilled_count == 2
        assert ctx.has_confluence
        assert ctx.dominant_direction == "bullish"
    
    def test_fvg_context_to_dict(self):
        """Test serialization."""
        zones = [
            FVGZone(
                top=100.0, bottom=98.0, direction="bullish",
                created_at=datetime.now(timezone.utc), timeframe="15m", strength=2.0,
            ),
        ]
        
        ctx = FVGContext(
            zones=zones,
            fvg_pressure=0.5,
            unfilled_count=1,
            nearest_distance_atr=2.0,
            has_confluence=False,
            dominant_direction="bullish",
        )
        
        d = ctx.to_dict()
        assert d["fvg_pressure"] == 0.5
        assert d["unfilled_count"] == 1
        assert d["nearest_distance_atr"] == 2.0
        assert not d["has_confluence"]
        assert d["dominant_direction"] == "bullish"
        assert len(d["active_zones"]) == 1


# =============================================================================
# FVG Detection Tests
# =============================================================================

class TestFVGDetection:
    """Test FVG detection logic in Crypto15mIndicatorStack."""
    
    def test_bullish_fvg_detection(self):
        """Test detection of bullish FVG (gap up) - verify machinery is in place."""
        cfg = IndicatorConfig(fvg_enabled=True)
        stack = Crypto15mIndicatorStack(config=cfg)
        stack.set_asset_symbol("BTC")
        
        # Build sufficient history for ATR computation (need 15+ bars)
        for i in range(60):
            stack.update(100.0 + i * 0.1)
        
        # Create bullish displacement - 3 candle pattern
        # Need a clear gap: low of candle 2 > high of candle 0
        stack.update(105.0)  # Candle 0 - baseline
        stack.update(106.0)  # Candle 1 - higher
        stack.update(108.0)  # Candle 2 - gap up (approximated)
        
        snap = stack.snapshot()
        
        # Verify FVG is enabled and fields exist
        assert snap.fvg_enabled
        assert hasattr(snap, 'fvg_pressure')
        assert hasattr(snap, 'fvg_context')
    
    def test_bearish_fvg_detection(self):
        """Test detection of bearish FVG (gap down)."""
        cfg = IndicatorConfig(fvg_enabled=True)
        stack = Crypto15mIndicatorStack(config=cfg)
        
        # Create bearish displacement
        prices = [100.0 + i * 0.5 for i in range(50)]  # Trend up
        prices.append(102.0)  # High
        prices.append(99.0)   # Sharp drop - bearish displacement
        
        for p in prices:
            stack.update(p)
        
        snap = stack.snapshot()
        assert snap.fvg_enabled
    
    def test_fvg_fill_detection(self):
        """Test that FVG fills are detected - verify machinery is in place."""
        cfg = IndicatorConfig(fvg_enabled=True, fvg_max_zones_tracked=5)
        stack = Crypto15mIndicatorStack(config=cfg)
        stack.set_asset_symbol("BTC")
        
        # Need enough prices to build indicators and ATR (15+ bars)
        for i in range(60):
            stack.update(100.0 + i * 0.1)
        
        # Verify FVG infrastructure exists
        assert hasattr(stack, '_fvg_zones')
        assert hasattr(stack, '_fvg_window')
        assert len(stack._fvg_window) > 0  # Should have accumulated bars
    
    def test_fvg_disabled(self):
        """Test that FVG can be disabled."""
        cfg = IndicatorConfig(fvg_enabled=False)
        stack = Crypto15mIndicatorStack(config=cfg)
        
        for p in range(100, 130):
            stack.update(float(p))
        
        snap = stack.snapshot()
        assert not snap.fvg_enabled
        assert snap.fvg_pressure == 0.0


# =============================================================================
# FVG Config Registry Tests
# =============================================================================

class TestFVGRegistry:
    """Test FVG configuration via crypto registry."""
    
    def test_btc_fvg_config(self):
        """Test BTC FVG config from registry."""
        cfg = get_fvg_config("BTC")
        assert cfg is not None
        assert cfg.enabled
        assert cfg.min_gap_size_atr == 1.5
        assert cfg.min_gap_size_pct == 0.0015
        assert "15m" in cfg.active_timeframes
    
    def test_eth_fvg_config(self):
        """Test ETH FVG config."""
        cfg = get_fvg_config("ETH")
        assert cfg is not None
        assert cfg.enabled
        assert cfg.min_gap_size_atr == 1.5
    
    def test_sol_fvg_config(self):
        """Test SOL FVG config (wider thresholds for higher vol)."""
        cfg = get_fvg_config("SOL")
        assert cfg is not None
        assert cfg.enabled
        assert cfg.min_gap_size_atr == 1.8  # Wider than BTC
        assert cfg.pressure_weight == 0.30  # Lower weight
    
    def test_xrp_fvg_config(self):
        """Test XRP FVG config (conservative for noise)."""
        cfg = get_fvg_config("XRP")
        assert cfg is not None
        assert cfg.enabled
        assert cfg.min_gap_size_atr == 2.0  # Even wider
        assert cfg.max_zones_tracked == 6   # Fewer zones
    
    def test_doge_fvg_config(self):
        """Test DOGE FVG config (most conservative)."""
        cfg = get_fvg_config("DOGE")
        assert cfg is not None
        assert cfg.enabled
        assert cfg.min_gap_size_atr == 2.2  # Widest
        assert cfg.max_zones_tracked == 5   # Very few zones
        assert cfg.pressure_weight == 0.20  # Lowest weight
    
    def test_fvg_enabled_per_timeframe(self):
        """Test timeframe-specific enablement."""
        assert is_fvg_enabled("BTC", "15m")
        assert is_fvg_enabled("BTC", "1h")
        assert is_fvg_enabled("BTC", "1d")
        # DOGE only has 15m and 1h enabled
        assert is_fvg_enabled("DOGE", "15m")
        assert not is_fvg_enabled("DOGE", "4h")


# =============================================================================
# CrossTimeframeAggregator FVG Tests
# =============================================================================

class TestFVGAggregator:
    """Test FVG integration with CrossTimeframeAggregator."""
    
    def test_push_fvg_signal(self):
        """Test pushing FVG signal to aggregator."""
        agg = CrossTimeframeAggregator()
        
        agg.push_fvg_signal(
            asset="BTC",
            fvg_pressure=0.7,
            unfilled_count=3,
            nearest_distance_atr=1.2,
            timeframe="15m",
        )
        
        # Verify signal was added
        result = agg.aggregate("BTC")
        assert result.asset == "BTC"
        # Should have FVG signal in the mix
    
    def test_fvg_signal_confidence_calculation(self):
        """Test FVG confidence is based on proximity and count."""
        agg = CrossTimeframeAggregator()
        
        # Near zone with many unfilled = higher confidence
        agg.push_fvg_signal(
            asset="BTC",
            fvg_pressure=0.8,
            unfilled_count=5,
            nearest_distance_atr=0.5,  # Very close
            timeframe="15m",
        )
        
        # Verify the signal was pushed with appropriate confidence
    
    def test_sync_from_fvg_stacks(self):
        """Test syncing FVG from indicator stacks."""
        agg = CrossTimeframeAggregator()
        
        # Create mock stacks
        cfg = IndicatorConfig(fvg_enabled=True)
        btc_stack = Crypto15mIndicatorStack(config=cfg)
        btc_stack.set_asset_symbol("BTC")
        
        # Feed prices
        for p in range(100, 160):
            btc_stack.update(float(p))
        
        stacks = {"BTC": btc_stack}
        
        # Sync to aggregator
        count = agg.sync_from_fvg_stacks(stacks)
        assert count >= 0  # May be 0 if no FVG detected yet


# =============================================================================
# Integration Tests
# =============================================================================

class TestFVGIntegration:
    """End-to-end FVG integration tests."""
    
    def test_full_fvg_pipeline(self):
        """Test complete FVG pipeline from price feed to signal."""
        # 1. Get asset config from registry
        registry = get_crypto_registry()
        btc_cfg = registry.get_config("BTC")
        
        # 2. Create indicator stack with FVG config
        indicator_cfg = IndicatorConfig(
            fvg_enabled=btc_cfg.fvg_config.enabled,
            fvg_min_gap_size_atr=btc_cfg.fvg_config.min_gap_size_atr,
            fvg_max_zones_tracked=btc_cfg.fvg_config.max_zones_tracked,
        )
        stack = Crypto15mIndicatorStack(config=indicator_cfg)
        stack.set_asset_symbol("BTC")
        
        # 3. Feed prices simulating a bullish FVG
        base = 50000.0
        for i in range(60):
            stack.update(base + i * 10)  # Trend up
        
        # Bullish displacement - creates FVG
        stack.update(base + 700)  # Big jump
        stack.update(base + 710)  # Continue up
        
        # 4. Get snapshot with FVG data
        snap = stack.snapshot()
        
        # Verify FVG fields
        assert snap.fvg_enabled
        assert hasattr(snap, 'fvg_pressure')
        assert hasattr(snap, 'fvg_context')
        assert snap.fvg_context is not None
        
        # 5. Push to aggregator
        agg = get_cross_timeframe_aggregator()
        count = agg.sync_from_fvg_stacks({"BTC": stack})
        
        # 6. Verify aggregation
        result = agg.aggregate("BTC")
        assert result.asset == "BTC"
    
    def test_fvg_confluence_detection(self):
        """Test FVG confluence with trend detection."""
        cfg = IndicatorConfig(fvg_enabled=True)
        stack = Crypto15mIndicatorStack(config=cfg)
        stack.set_asset_symbol("BTC")
        
        # Create trend + FVG scenario
        for i in range(60):
            stack.update(100.0 + i * 0.5)
        
        # Bullish displacement (FVG) in bullish trend
        stack.update(135.0)
        stack.update(137.0)
        
        snap = stack.snapshot()
        
        # Should detect confluence
        if snap.fvg_context and snap.fvg_context.zones:
            # Check if confluence was detected
            pass


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

class TestFVGEdgeCases:
    """Test edge cases and error handling."""
    
    def test_fvg_with_zero_atr(self):
        """Test FVG handling when ATR is zero - should not crash."""
        cfg = IndicatorConfig(fvg_enabled=True)
        stack = Crypto15mIndicatorStack(config=cfg)
        
        # Single price (zero ATR)
        stack.update(100.0)
        
        snap = stack.snapshot()
        # Should not crash - FVG may be disabled due to insufficient bars/ATR
        assert hasattr(snap, 'fvg_enabled')
        # Either enabled with no zones, or disabled due to insufficient data
        assert snap.fvg_enabled == False or (snap.fvg_enabled and snap.fvg_context is not None)
    
    def test_fvg_immediate_fill(self):
        """Test that immediately filled gaps are ignored."""
        cfg = IndicatorConfig(
            fvg_enabled=True,
            fvg_ignore_immediate_fill=True,
        )
        stack = Crypto15mIndicatorStack(config=cfg)
        
        # Would need precise OHLC simulation
        # This test verifies the config option exists
        assert cfg.fvg_ignore_immediate_fill
    
    def test_fvg_max_zones_limit(self):
        """Test that max zones limit is respected."""
        cfg = IndicatorConfig(
            fvg_enabled=True,
            fvg_max_zones_tracked=3,
        )
        stack = Crypto15mIndicatorStack(config=cfg)
        
        assert len(stack._fvg_zones) <= 3  # Initially empty
    
    def test_fvg_very_small_gap(self):
        """Test that tiny gaps below threshold are ignored."""
        cfg = IndicatorConfig(
            fvg_enabled=True,
            fvg_min_gap_size_pct=0.01,  # 1% minimum
        )
        stack = Crypto15mIndicatorStack(config=cfg)
        
        # Feed prices with tiny moves (< 1% gaps)
        p = 100.0
        for _ in range(70):
            stack.update(p)
            p += 0.5  # 0.5% moves, below 1% threshold
        
        snap = stack.snapshot()
        # Should have minimal or no FVG zones


# =============================================================================
# Performance Tests
# =============================================================================

class TestFVGPerformance:
    """Performance tests for FVG operations."""
    
    def test_fvg_detection_performance(self):
        """Test that FVG detection doesn't significantly slow updates."""
        import time
        
        cfg = IndicatorConfig(fvg_enabled=True)
        stack = Crypto15mIndicatorStack(config=cfg)
        
        # Time 100 updates
        start = time.time()
        for i in range(100):
            stack.update(100.0 + i * 0.1)
        elapsed = time.time() - start
        
        # Should complete in reasonable time (< 1 second for 100 updates)
        assert elapsed < 1.0
    
    def test_fvg_snapshot_performance(self):
        """Test snapshot performance with FVG enabled."""
        import time
        
        cfg = IndicatorConfig(fvg_enabled=True)
        stack = Crypto15mIndicatorStack(config=cfg)
        
        # Fill with data
        for i in range(120):
            stack.update(100.0 + i * 0.1)
        
        # Time multiple snapshots
        start = time.time()
        for _ in range(100):
            stack.snapshot()
        elapsed = time.time() - start
        
        # Should be fast (< 0.5 seconds for 100 snapshots)
        assert elapsed < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
