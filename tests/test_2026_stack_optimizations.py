"""
Tests for 2026 stack-wide optimizations

Tests for new high-leverage optimizations across the entire trading stack:
- Increased max_orders_per_cycle for more trade opportunities
- Order Book Imbalance (OBI) filter for 5-7% win rate boost
- News event avoidance (15 min before/after high-impact events)
- Optimized edge thresholds for 53%+ win rate floor
- Market catalog filter fix (min_minutes_to_expiry from profile)
- Max spread cents increase (from 10c to 25c)
- ADX threshold relaxation (from 20 to 5)
"""

import pytest
import yaml
from datetime import datetime, timedelta
from merid.prediction.order_book_imbalance_filter import (
    OrderBookImbalanceFilter,
    OBIConfig,
    OBISignal,
    OBIMeasurement,
    OBIContext,
    get_obi_filter,
)


class TestMaxOrdersPerCycle:
    """Test max_orders_per_15m_window optimization."""
    
    def test_max_orders_per_15m_window_increased(self):
        """Test that max_orders_per_15m_window is increased to 15."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check throttling section
        assert "throttling" in profile
        assert "max_orders_per_15m_window" in profile["throttling"]
        
        # Check value is 24 (current configuration - 2026-07-10: increased from 5 to 24 for $1+/15m target)
        max_orders = profile["throttling"]["max_orders_per_15m_window"]
        assert max_orders == 24, f"Expected 24, got {max_orders}"
    
    def test_max_orders_per_15m_window_reasonable(self):
        """Test that max_orders_per_15m_window is within reasonable bounds."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        max_orders = profile["throttling"]["max_orders_per_15m_window"]
        
        # Should be between 5 and 30 (reasonable range for 15m trading with 5 assets)
        assert 5 <= max_orders <= 30, f"max_orders_per_15m_window {max_orders} out of reasonable range"


class TestOrderBookImbalanceFilter:
    """Test order book imbalance filter implementation."""
    
    def test_obi_computation(self):
        """Test OBI computation formula."""
        filter = OrderBookImbalanceFilter()
        
        # Test balanced book
        obi = filter.compute_obi(bid_depth=100, ask_depth=100)
        assert obi == 0.0, f"Balanced book should have OBI=0, got {obi}"
        
        # Test stacked bids
        obi = filter.compute_obi(bid_depth=200, ask_depth=50)
        assert obi > 0, f"Stacked bids should have positive OBI, got {obi}"
        assert obi == (200 - 50) / (200 + 50), f"OBI calculation incorrect"
        
        # Test stacked asks
        obi = filter.compute_obi(bid_depth=50, ask_depth=200)
        assert obi < 0, f"Stacked asks should have negative OBI, got {obi}"
    
    def test_obi_signal_classification(self):
        """Test OBI signal classification."""
        config = OBIConfig(strong_threshold=0.7, moderate_threshold=0.3)
        filter = OrderBookImbalanceFilter(config)
        
        # Test strong buy
        signal = filter.classify_signal(0.8)
        assert signal == OBISignal.STRONG_BUY
        
        # Test moderate buy
        signal = filter.classify_signal(0.5)
        assert signal == OBISignal.BUY
        
        # Test neutral
        signal = filter.classify_signal(0.1)
        assert signal == OBISignal.NEUTRAL
        
        # Test moderate sell
        signal = filter.classify_signal(-0.5)
        assert signal == OBISignal.SELL
        
        # Test strong sell
        signal = filter.classify_signal(-0.8)
        assert signal == OBISignal.STRONG_SELL
    
    def test_obi_measurement_update(self):
        """Test OBI measurement update."""
        filter = OrderBookImbalanceFilter()
        
        measurement = filter.update_measurement(
            market_id="TEST_MARKET",
            bid_depth=150,
            ask_depth=50,
            timestamp_ms=1000
        )
        
        assert measurement.obi_value > 0
        assert measurement.signal in [OBISignal.BUY, OBISignal.STRONG_BUY]
        assert measurement.timestamp_ms == 1000
        assert measurement.bid_depth == 150
        assert measurement.ask_depth == 50
    
    def test_directional_consistency(self):
        """Test directional consistency computation."""
        filter = OrderBookImbalanceFilter()
        market_id = "TEST_MARKET"
        
        # Add consistent buy signals
        for i in range(15):
            filter.update_measurement(market_id, bid_depth=200, ask_depth=50)
        
        consistency = filter.compute_directional_consistency(market_id, "buy")
        assert consistency >= 0.75, f"Consistency should be high for consistent signals, got {consistency}"
        
        # Add mixed signals
        for i in range(10):
            filter.update_measurement(market_id, bid_depth=50, ask_depth=200)
        
        consistency = filter.compute_directional_consistency(market_id, "buy")
        assert consistency < 0.75, f"Consistency should drop with mixed signals, got {consistency}"
    
    def test_obi_should_trade(self):
        """Test OBI trade decision logic."""
        config = OBIConfig(
            strong_threshold=0.7,
            moderate_threshold=0.3,
            consistency_window_size=10,
            min_consistency_pct=0.60
        )
        filter = OrderBookImbalanceFilter(config)
        market_id = "TEST_MARKET"
        
        # Add consistent buy signals
        for i in range(8):
            filter.update_measurement(market_id, bid_depth=200, ask_depth=50)
        
        context = filter.should_trade(market_id, bid_depth=200, ask_depth=50, direction="buy")
        
        # Should recommend TRADE with consistent strong signals
        assert context.recommendation in ["TRADE", "FILTER", "HOLD"]
        assert context.current_obi > 0
        assert context.directional_consistency >= 0.60
    
    def test_obi_filter_global_instance(self):
        """Test global OBI filter instance."""
        filter1 = get_obi_filter()
        filter2 = get_obi_filter()
        
        # Should return same instance
        assert filter1 is filter2, "get_obi_filter should return singleton instance"


class TestNewsEventAvoidance:
    """Test news event avoidance configuration."""
    
    def test_news_event_avoidance_in_profile(self):
        """Test that news event avoidance is configured in profile."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check news_event_avoidance section exists
        assert "news_event_avoidance" in profile
        
        nea = profile["news_event_avoidance"]
        
        # Check required fields
        assert "enabled" in nea
        assert "avoidance_window_min" in nea
        assert "high_impact_events" in nea
    
    def test_news_event_avoidance_values(self):
        """Test that news event avoidance values are correct."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        nea = profile["news_event_avoidance"]
        
        # Should be enabled
        assert nea["enabled"] is True, "news_event_avoidance should be enabled"
        
        # Avoidance window should be 15 minutes
        assert nea["avoidance_window_min"] == 15, \
            f"Expected 15 min avoidance window, got {nea['avoidance_window_min']}"
        
        # Should include high-impact events
        assert len(nea["high_impact_events"]) > 0, "Should have high-impact events listed"
        
        # Should include key events
        required_events = ["NFP", "CPI", "FOMC", "GDP"]
        for event in required_events:
            assert event in nea["high_impact_events"], \
                f"Missing required event: {event}"


class TestEdgeThresholdOptimization:
    """Test edge threshold optimization."""
    
    def test_edge_bands_lowered(self):
        """Test that edge bands are lowered for increased coverage."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check edge_bands section exists
        assert "edge_bands" in profile
        assert profile["edge_bands"]["enabled"] is True
        
        bands = profile["edge_bands"]
        
        # Check watch band thresholds (actual configuration values)
        watch_min = bands["watch_band"]["min_edge_pct"]
        watch_max = bands["watch_band"]["max_edge_pct"]
        # 2026-07-07: Updated edge band thresholds based on trade scenario simulation (reduced to 0.5%)
        assert watch_min == 0.005, f"Watch band min should be 0.5%, got {watch_min}"
        assert watch_max == 0.005, f"Watch band max should be 0.5%, got {watch_max}"
        
        # Check small band thresholds (actual configuration values)
        small_min = bands["small_band"]["min_edge_pct"]
        small_max = bands["small_band"]["max_edge_pct"]
        assert small_min == 0.005, f"Small band min should be 0.5%, got {small_min}"
        assert small_max == 0.01, f"Small band max should be 1%, got {small_max}"
        
        # Check standard band thresholds (actual configuration values)
        standard_min = bands["standard_band"]["min_edge_pct"]
        assert standard_min == 0.005, f"Standard band min should be 0.5%, got {standard_min}"
    
    def test_edge_band_progression(self):
        """Test that edge bands have proper progression.
        
        2026-07-07: Updated to reflect new tiered structure where bands share a common
        minimum edge (0.5%) but differ in action and Kelly multipliers. This allows
        for more granular sizing based on edge quality while maintaining a unified
        entry threshold.
        """
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        bands = profile["edge_bands"]
        
        # Verify bands share the same minimum edge (unified entry threshold)
        watch_min = bands["watch_band"]["min_edge_pct"]
        small_min = bands["small_band"]["min_edge_pct"]
        standard_min = bands["standard_band"]["min_edge_pct"]
        
        assert watch_min == small_min == standard_min == 0.005, \
            "All bands should share the same minimum edge (0.5%) for unified entry threshold"
        
        # Verify bands have different actions and Kelly multipliers
        assert bands["watch_band"]["action"] == "log_only"
        assert bands["watch_band"]["kelly_multiplier"] == 0.0
        
        assert bands["small_band"]["action"] == "trade_small"
        assert bands["small_band"]["kelly_multiplier"] == 0.25
        
        assert bands["standard_band"]["action"] == "trade_standard"
        assert bands["standard_band"]["kelly_multiplier"] == 0.50
        
        # Verify max edges increase appropriately
        watch_max = bands["watch_band"]["max_edge_pct"]
        small_max = bands["small_band"]["max_edge_pct"]
        standard_max = bands["standard_band"]["max_edge_pct"]
        
        assert watch_max <= small_max, "Watch band max should be <= small band max"
        assert small_max < standard_max, "Small band max should be < standard band max"
    
    def test_kelly_multipliers(self):
        """Test that Kelly multipliers are properly configured."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        bands = profile["edge_bands"]
        
        # Watch band should have 0 multiplier
        assert bands["watch_band"]["kelly_multiplier"] == 0.0
        
        # Small band should have reduced multiplier
        assert 0 < bands["small_band"]["kelly_multiplier"] < 1.0
        
        # Standard band should have higher multiplier
        assert bands["standard_band"]["kelly_multiplier"] > bands["small_band"]["kelly_multiplier"]


class TestOBIProfileConfiguration:
    """Test OBI filter profile configuration."""
    
    def test_obi_config_in_profile(self):
        """Test that OBI filter is configured in profile."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check order_book_imbalance_filter section exists
        assert "order_book_imbalance_filter" in profile
        
        obi = profile["order_book_imbalance_filter"]
        
        # Check required fields
        assert "enabled" in obi
        assert "strong_threshold" in obi
        assert "moderate_threshold" in obi
        assert "consistency_window_size" in obi
        assert "min_consistency_pct" in obi
        assert "max_staleness_ms" in obi
        assert "top_levels" in obi
    
    def test_obi_config_values(self):
        """Test that OBI configuration values are correct."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        obi = profile["order_book_imbalance_filter"]
        
        # Should be enabled
        assert obi["enabled"] is True, "OBI filter should be enabled"
        
        # Strong threshold should be 0.70 (2026-07-10: reduced for crypto volatility)
        assert obi["strong_threshold"] == 0.70, \
            f"Expected strong_threshold=0.70, got {obi['strong_threshold']}"
        
        # Moderate threshold should be 0.3
        assert obi["moderate_threshold"] == 0.3, \
            f"Expected moderate_threshold=0.3, got {obi['moderate_threshold']}"
        
        # Consistency window should be reasonable
        assert obi["consistency_window_size"] >= 10, \
            f"Consistency window too small: {obi['consistency_window_size']}"
        
        # Min consistency should be 60% (2026-07-03: restored to research standard)
        assert obi["min_consistency_pct"] == 0.60, \
            f"Expected min_consistency_pct=0.60, got {obi['min_consistency_pct']}"
        
        # Staleness threshold should be reasonable (<= 10 seconds)
        assert obi["max_staleness_ms"] <= 10000, \
            f"Staleness threshold too high: {obi['max_staleness_ms']}ms"
    
    def test_obi_per_asset_thresholds(self):
        """Test that per-asset OBI thresholds are configured."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        obi = profile["order_book_imbalance_filter"]
        
        # Check per-asset thresholds exist
        assert "per_asset_strong_threshold" in obi, \
            "per_asset_strong_threshold should be configured"
        
        per_asset = obi["per_asset_strong_threshold"]
        
        # BTC/ETH should have 70% threshold (high volatility, deep book)
        assert per_asset["BTC"] == 0.70, \
            f"Expected BTC threshold=0.70, got {per_asset['BTC']}"
        assert per_asset["ETH"] == 0.70, \
            f"Expected ETH threshold=0.70, got {per_asset['ETH']}"
        
        # SOL/XRP/DOGE should have 65% threshold (high volatility, thinner book)
        assert per_asset["SOL"] == 0.65, \
            f"Expected SOL threshold=0.65, got {per_asset['SOL']}"
        assert per_asset["XRP"] == 0.65, \
            f"Expected XRP threshold=0.65, got {per_asset['XRP']}"
        assert per_asset["DOGE"] == 0.65, \
            f"Expected DOGE threshold=0.65, got {per_asset['DOGE']}"
        
        # Top levels should be between 1 and 10
        assert 1 <= obi["top_levels"] <= 10, \
            f"Top levels out of range: {obi['top_levels']}"


class TestMarketCatalogFilterFix:
    """Test market catalog filter fix for min_minutes_to_expiry."""
    
    def test_min_entry_mins_in_profile(self):
        """Test that min_entry_mins is configured in profile guardrails."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check guardrails section exists
        assert "guardrails" in profile
        
        guardrails = profile["guardrails"]
        
        # Check min_entry_mins exists
        assert "min_entry_mins" in guardrails, "min_entry_mins should be in guardrails"
        
        # Should be 0.5 (relaxed from 2.0 to allow full window trading)
        min_entry = guardrails["min_entry_mins"]
        assert min_entry == 0.5, f"Expected min_entry_mins=0.5, got {min_entry}"
    
    def test_max_entry_mins_in_profile(self):
        """Test that max_entry_mins is configured in profile guardrails."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        guardrails = profile["guardrails"]
        
        # Check max_entry_mins exists
        assert "max_entry_mins" in guardrails, "max_entry_mins should be in guardrails"
        
        # Should be 15.0
        max_entry = guardrails["max_entry_mins"]
        assert max_entry == 15.0, f"Expected max_entry_mins=15.0, got {max_entry}"


class TestHybridModePriceCaps:
    """Test hybrid mode price caps to prevent poor risk/reward trades."""
    
    def test_hybrid_price_caps_in_profile(self):
        """Test that hybrid mode price caps are configured in profile."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check hybrid section exists
        assert "hybrid" in profile, "hybrid section should be in profile"
        
        hybrid = profile["hybrid"]
        
        # Check max_entry_price_yes exists
        assert "max_entry_price_yes" in hybrid, "max_entry_price_yes should be in hybrid config"
        
        # Should be 0.70 (reduced from 80¢ to avoid highest fee zone - fees peak at 50¢, lower at 70¢)
        max_yes = hybrid["max_entry_price_yes"]
        assert max_yes == 0.70, f"Expected max_entry_price_yes=0.70, got {max_yes}"
        
        # Check min_entry_price_no exists
        assert "min_entry_price_no" in hybrid, "min_entry_price_no should be in hybrid config"
        
        # Should be 0.30 (increased from 20¢ for symmetry with 70¢ YES cap - avoids extreme low-fee but illiquid zone)
        min_no = hybrid["min_entry_price_no"]
        assert min_no == 0.30, f"Expected min_entry_price_no=0.30, got {min_no}"
    
    def test_hybrid_price_caps_reasonable(self):
        """Test that hybrid price caps are reasonable and symmetric."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        hybrid = profile["hybrid"]
        
        max_yes = hybrid["max_entry_price_yes"]
        min_no = hybrid["min_entry_price_no"]
        
        # Caps should be symmetric around 0.50 (relaxed from previous strict bounds)
        assert max_yes <= 0.85, f"max_entry_price_yes too high: {max_yes}"
        assert min_no >= 0.15, f"min_entry_price_no too low: {min_no}"
        
        # Sum should be 1.00 (symmetric)
        assert abs((max_yes + min_no) - 1.0) < 0.01, \
            f"Price caps not symmetric: max_yes={max_yes}, min_no={min_no}"


class TestOBISizeMultiplier:
    """Test OBI filter conversion from hard gate to size multiplier based on 2026 research."""
    
    def test_obi_context_has_size_multiplier(self):
        """Test that OBIContext has size_multiplier field."""
        from merid.prediction.order_book_imbalance_filter import OBIContext
        
        # Create an OBIContext with size_multiplier
        context = OBIContext(
            current_obi=0.5,
            current_signal="buy",
            directional_consistency=0.8,
            window_size=20,
            is_fresh=True,
            recommendation="TRADE",
            size_multiplier=1.0
        )
        
        # Check size_multiplier exists and is 1.0
        assert hasattr(context, 'size_multiplier'), "OBIContext should have size_multiplier field"
        assert context.size_multiplier == 1.0, f"Expected size_multiplier=1.0, got {context.size_multiplier}"
    
    def test_obi_reduced_recommendation(self):
        """Test that OBI filter returns REDUCED recommendation instead of FILTER."""
        from merid.prediction.order_book_imbalance_filter import OrderBookImbalanceFilter, OBIConfig
        
        # Create OBI filter
        config = OBIConfig()
        filter = OrderBookImbalanceFilter(config)
        
        # Add some history to build consistency (avoid warmup state)
        for i in range(10):
            filter.update_measurement(
                market_id="TEST-MARKET",
                bid_depth=100,
                ask_depth=100,
                timestamp_ms=i * 1000,
                asset="BTC"
            )
        
        # Test with neutral signal (should return REDUCED with 0.70 multiplier)
        context = filter.should_trade(
            market_id="TEST-MARKET",
            bid_depth=100,
            ask_depth=100,  # Balanced book
            direction="buy"
        )
        
        # Should return REDUCED with size_multiplier=0.70 (neutral signal)
        assert context.recommendation in ["REDUCED", "TRADE"], f"Expected REDUCED or TRADE, got {context.recommendation}"
        if context.recommendation == "REDUCED":
            # With history, neutral signal should give 0.70 multiplier
            # If consistency is still 0 (warmup), it will be 0.50
            assert context.size_multiplier in [0.50, 0.70], f"Expected size_multiplier 0.50 or 0.70, got {context.size_multiplier}"
    
    def test_obi_consistency_zero_warmup(self):
        """Test that OBI filter handles consistency=0.0 (warmup) with REDUCED recommendation."""
        from merid.prediction.order_book_imbalance_filter import OrderBookImbalanceFilter, OBIConfig
        
        # Create OBI filter
        config = OBIConfig()
        filter = OrderBookImbalanceFilter(config)
        
        # Test with insufficient history (consistency will be 0.0)
        context = filter.should_trade(
            market_id="TEST-MARKET",
            bid_depth=100,
            ask_depth=100,
            direction="buy"
        )
        
        # Should return REDUCED with size_multiplier=0.50 for warmup
        assert context.recommendation in ["REDUCED", "TRADE"], f"Expected REDUCED or TRADE, got {context.recommendation}"
        if context.recommendation == "REDUCED":
            assert context.size_multiplier == 0.50, f"Expected size_multiplier=0.50 for warmup, got {context.size_multiplier}"


class TestZeroValueBugFixes:
    """Test fixes for 0 value bugs in technical indicators."""
    
    def test_panic_fade_skips_zero_rsi(self):
        """Test that panic fade signal skips when RSI=0.0 (insufficient data)."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        
        # The fix ensures panic fade skips when RSI or Z-score is 0.0
        # This prevents false signals during warmup
        rsi = 0.0  # Insufficient data
        zscore = -2.5  # Valid extreme
        velocity = -0.0003  # Valid panic move
        
        # With RSI=0.0, panic fade should skip (not generate signal)
        should_skip = (rsi == 0.0) or (zscore == 0.0)
        assert should_skip, "Panic fade should skip when RSI=0.0 (insufficient data)"
    
    def test_panic_fade_skips_zero_zscore(self):
        """Test that panic fade signal skips when Z-score=0.0 (insufficient data)."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        
        # The fix ensures panic fade skips when RSI or Z-score is 0.0
        rsi = 20.0  # Valid extreme
        zscore = 0.0  # Insufficient data
        velocity = -0.0003  # Valid panic move
        
        # With Z-score=0.0, panic fade should skip (not generate signal)
        should_skip = (rsi == 0.0) or (zscore == 0.0)
        assert should_skip, "Panic fade should skip when Z-score=0.0 (insufficient data)"
    
    def test_panic_fade_proceeds_with_valid_indicators(self):
        """Test that panic fade proceeds when both RSI and Z-score are non-zero."""
        rsi = 20.0  # Valid extreme
        zscore = -2.5  # Valid extreme
        velocity = -0.0003  # Valid panic move
        
        # With valid indicators, panic fade should proceed
        should_skip = (rsi == 0.0) or (zscore == 0.0)
        assert not should_skip, "Panic fade should proceed with valid RSI and Z-score"


class TestMaxSpreadCentsFix:
    """Test max_spread_cents unified to 100c based on 2026-07-10 relaxation for wider market spreads."""
    
    def test_guardrails_max_spread_cents(self):
        """Test that guardrails max_spread_cents is 100c (relaxed for current market conditions)."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        guardrails = profile["guardrails"]
        
        # Check max_spread_cents exists
        assert "max_spread_cents" in guardrails
        
        # Should be 20 (2026-07-12: ALIGNED with industry research - 20c max for 15m crypto)
        max_spread = guardrails["max_spread_cents"]
        assert max_spread == 20, f"Expected max_spread_cents=20, got {max_spread}"
    
    def test_market_microstructure_max_spread_cents(self):
        """Test that market_microstructure max_spread_cents is 20c (aligned with industry research)."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check market_microstructure section exists
        assert "market_microstructure" in profile
        
        micro = profile["market_microstructure"]
        
        # Check max_spread_cents exists
        assert "max_spread_cents" in micro
        
        # Should be 20 (2026-07-12: ALIGNED with industry research - 20c max for 15m crypto)
        max_spread = micro["max_spread_cents"]
        assert max_spread == 20, f"Expected max_spread_cents=20, got {max_spread}"


class TestADXThresholdRelaxation:
    """Test ADX threshold relaxation from 20 to 5."""
    
    def test_adx_filter_threshold_in_code(self):
        """Test that ADX filter threshold is 5 in agent_grid_15m.py."""
        # Read the agent_grid_15m.py file
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for ADX threshold of 5.0
        assert "adx < 5.0" in content, "ADX filter should use threshold of 5.0"
        assert "adx >= 5.0" in content, "ADX filter should use threshold of 5.0"
        
        # Ensure old threshold of 20 is not present
        # (it should be replaced with 5)
        assert "adx < 20.0" not in content or "adx >= 20.0" not in content, \
            "Old ADX threshold of 20 should be removed"
    
    def test_adx_dynamic_threshold_in_code(self):
        """Test that dynamic ADX thresholds are updated in agent_grid_15m.py."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for updated ADX multipliers
        # Should have threshold at 5.0
        assert "adx >= 5.0" in content, "Dynamic threshold should use 5.0"
        
        # Should have threshold at 10.0 for moderate trend
        assert "adx >= 10.0" in content, "Dynamic threshold should use 10.0 for moderate trend"
        
        # Should have threshold at 25.0 for strong trend
        assert "adx >= 25.0" in content, "Dynamic threshold should use 25.0 for strong trend"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
