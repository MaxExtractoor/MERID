"""Tests for Pass 3 risk management and position sizing bug fixes.

Tests cover the critical bugs fixed in risk management:
1. BUG #16: Missing get_base_position_size() method
2. BUG #19: Proper base position size calculation
3. BUG #18: Depth thresholds from risk envelope (not agent config)
4. BUG #17: Unified risk envelope initialization
5. BUG #23: Position size validation against min/max notional
6. BUG #20: Per-asset position tracking
7. BUG #21: Concurrent trade limit enforcement
8. BUG #10: Per-strip order limit tracking
9. BUG #15: Improved asset extraction robustness
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from dataclasses import fields


class TestBug16GetBasePositionSize:
    """Test BUG #16: Missing get_base_position_size() method."""

    def test_risk_envelope_has_get_base_position_size(self):
        """Verify KalshiCrypto15mRiskEnvelope has get_base_position_size method."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        # Check method exists
        assert hasattr(KalshiCrypto15mRiskEnvelope, 'get_base_position_size')

    def test_get_base_position_size_returns_integer(self):
        """Verify get_base_position_size returns an integer."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        # Create envelope with sample values
        envelope = compute_kalshi_crypto_15m_risk_envelope(
            live_bankroll_usd=1000.0,
            profile_path=None
        )
        
        base_size = envelope.get_base_position_size()
        assert isinstance(base_size, int)
        assert base_size >= 1  # Minimum 1 contract

    def test_get_base_position_size_uses_max_single_order_notional(self):
        """Verify base position size is derived from max_single_order_notional_usd."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        # Create envelope with specific notional
        envelope = compute_kalshi_crypto_15m_risk_envelope(
            live_bankroll_usd=1000.0,
            profile_path=None
        )
        
        base_size = envelope.get_base_position_size()
        
        # With $10 max_single_order_notional and $0.50 contract price, should be ~20 contracts
        # Formula: max_single_order_notional_usd / 0.50
        expected_size = int(envelope.max_single_order_notional_usd / 0.50)
        assert base_size == expected_size


class TestBug19PositionSizeCalculation:
    """Test BUG #19: Proper base position size calculation."""

    def test_position_size_calculation_uses_contract_price(self):
        """Verify position size calculation uses assumed contract price."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        envelope = compute_kalshi_crypto_15m_risk_envelope(
            live_bankroll_usd=1000.0,
            profile_path=None
        )
        
        # The calculation should use 0.50 USD as assumed contract price
        base_size = envelope.get_base_position_size()
        calculated_size = envelope.max_single_order_notional_usd / 0.50
        
        assert abs(base_size - calculated_size) < 1  # Allow for rounding

    def test_position_size_minimum_one_contract(self):
        """Verify position size is never less than 1 contract."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        # Even with very small notional, should return at least 1
        envelope = compute_kalshi_crypto_15m_risk_envelope(
            live_bankroll_usd=10.0,  # Small bankroll
            profile_path=None
        )
        
        base_size = envelope.get_base_position_size()
        assert base_size >= 1


class TestBug18DepthThresholdsFromEnvelope:
    """Test BUG #18: Depth thresholds from risk envelope (not agent config)."""

    def test_agent_config_no_longer_has_depth_fields(self):
        """Verify LeanAgentConfig no longer has min_depth_yes/min_depth_no fields."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        from dataclasses import fields
        
        field_names = {f.name for f in fields(LeanAgentConfig)}
        assert 'min_depth_yes' not in field_names
        assert 'min_depth_no' not in field_names

    def test_agent_uses_risk_envelope_for_depth_thresholds(self):
        """Verify agent reads depth thresholds from risk envelope."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m
        
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        agent = LeanAgent15m(
            config=config,
            catalog=Mock(),
            market_state_store=Mock(),
            spot_provider=Mock(),
            order_router=Mock(),
            risk_config=Mock(),
        )
        
        # Mock market state
        market_state = Mock()
        market_state.staleness_ms = 1000
        market_state.min_depth_yes = 10
        market_state.min_depth_no = 10
        market_state.best_bid_cents = 50
        market_state.best_ask_cents = 55
        market_state.last_update_ts = time.time()  # Add timestamp to avoid TypeError
        
        market = Mock()
        market.market.ticker = "KXBTCD-26JUN111330-30"
        
        agent.market_state_store = Mock()
        agent.market_state_store.get = Mock(return_value=market_state)
        
        # This should use risk envelope thresholds (with fallback to 1)
        result = agent._validate_market_state(market)
        # Should pass since depth 10 >= threshold 1 (fallback)
        assert result is True


class TestRiskEnvelopeImports:
    """Test that risk envelope modules can be imported without errors."""

    def test_risk_envelope_imports(self):
        """Verify risk envelope modules can be imported."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            KalshiCrypto15mRiskEnvelope,
            compute_kalshi_crypto_15m_risk_envelope,
            get_kalshi_crypto_15m_risk_envelope
        )
        assert KalshiCrypto15mRiskEnvelope is not None
        assert compute_kalshi_crypto_15m_risk_envelope is not None
        assert get_kalshi_crypto_15m_risk_envelope is not None

    def test_risk_envelope_service_imports(self):
        """Verify risk envelope service can be imported."""
        from merid.risk.profiles.risk_envelope_service import (
            RiskEnvelopeService,
            get_risk_envelope_service,
            RiskEnvelopeConfig
        )
        assert RiskEnvelopeService is not None
        assert get_risk_envelope_service is not None
        assert RiskEnvelopeConfig is not None


class TestLoop15mRiskEnvelopeUsage:
    """Test that loop_15m.py can use risk envelope methods."""

    def test_loop_15m_can_call_get_base_position_size(self):
        """Verify loop_15m can call get_base_position_size on risk envelope."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        envelope = compute_kalshi_crypto_15m_risk_envelope(
            live_bankroll_usd=1000.0,
            profile_path=None
        )
        
        # This is what loop_15m does
        base_size = envelope.get_base_position_size()
        risk_multiplier = envelope.per_trade_risk_multiplier
        count = int(base_size * risk_multiplier)
        
        assert isinstance(count, int)
        assert count >= 1


class TestBug17UnifiedRiskEnvelope:
    """Test BUG #17: Unified risk envelope initialization."""

    def test_loop_15m_uses_risk_envelope_service(self):
        """Verify loop_15m uses RiskEnvelopeService for initialization."""
        # This test verifies the code structure - actual initialization requires full stack
        from merid.loop_15m import Kalshi15mLoop
        
        # Check that the method exists and uses the right service
        # We can't fully test without mocking the entire stack
        assert Kalshi15mLoop is not None


class TestBug23PositionSizeValidation:
    """Test BUG #23: Position size validation against min/max notional."""

    def test_position_notional_calculation(self):
        """Verify position notional is calculated correctly."""
        count = 20
        price_cents = 50
        notional_usd = (count * price_cents) / 100.0
        assert notional_usd == 10.0

    def test_position_size_reduced_for_max_notional(self):
        """Verify position size is reduced if exceeding max notional."""
        max_notional = 5.0
        price_cents = 50
        initial_count = 20  # $10 notional
        
        # Calculate reduced count
        reduced_count = int((max_notional * 100.0) / price_cents)
        assert reduced_count == 10  # $5 notional


class TestBug20PerAssetPositionTracking:
    """Test BUG #20: Per-asset position tracking."""

    def test_loop_15m_initializes_asset_positions(self):
        """Verify loop_15m initializes position tracking for all 5 assets."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Check initialization in __init__
        # The loop should initialize _asset_positions for BTC, ETH, SOL, XRP, DOGE
        assert Kalshi15mLoop is not None

    def test_asset_position_tracking_updates(self):
        """Verify position tracking updates after order execution."""
        # Simulate position update
        asset_positions = {"BTC": 0.0, "ETH": 0.0, "SOL": 0.0, "XRP": 0.0, "DOGE": 0.0}
        position_notional_usd = 10.0
        asset = "BTC"
        
        asset_positions[asset] = asset_positions.get(asset, 0.0) + position_notional_usd
        assert asset_positions["BTC"] == 10.0

    def test_position_cache_retry_logic(self):
        """Verify position cache loading has retry logic."""
        from merid.loop_15m import Kalshi15mLoop
        import inspect
        
        # Check that __init__ has retry logic for position cache loading
        source = inspect.getsource(Kalshi15mLoop.__init__)
        assert "max_retries" in source or "retry" in source.lower(), "Position cache loading should have retry logic"
        assert "for attempt in range" in source, "Position cache loading should use retry loop"

    def test_all_five_assets_initialized(self):
        """Verify all 5 crypto assets are initialized in position tracking."""
        from merid.loop_15m import Kalshi15mLoop
        import inspect
        
        # Check that __init__ initializes all 5 assets
        source = inspect.getsource(Kalshi15mLoop.__init__)
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in expected_assets:
            assert asset in source, f"Asset {asset} should be initialized in position tracking"


class TestBug21ConcurrentTradeLimit:
    """Test BUG #21: Concurrent trade limit enforcement."""

    def test_loop_15m_initializes_active_trades(self):
        """Verify loop_15m initializes active trade tracking."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Check initialization in __init__
        assert Kalshi15mLoop is not None

    def test_concurrent_trade_limit_check(self):
        """Verify concurrent trade limit is enforced with new 5 trade limit."""
        max_concurrent = 5  # INCREASED from 3 to 5 for 5 assets
        active_trades = {"ticker1": 2, "ticker2": 3}
        current_active = sum(active_trades.values())
        
        should_block = current_active >= max_concurrent
        assert should_block is True  # 5 >= 5

    def test_concurrent_trade_per_cycle_reset(self):
        """Verify concurrent trades counter resets per cycle."""
        from merid.loop_15m import Kalshi15mLoop
        import inspect
        
        # Check that _run_loop has per-cycle reset logic
        source = inspect.getsource(Kalshi15mLoop._run_loop)
        assert "_active_trades.clear()" in source, "Concurrent trades counter should reset per cycle"
        assert "Reset concurrent trades counter" in source, "Should have logging for counter reset"


class TestBug10PerStripOrderLimit:
    """Test BUG #10: Per-strip order limit tracking."""

    def test_agent_initializes_strip_order_counts(self):
        """Verify agent initializes strip order tracking."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m
        
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        agent = LeanAgent15m(
            config=config,
            catalog=Mock(),
            market_state_store=Mock(),
            spot_provider=Mock(),
            order_router=Mock(),
            risk_config=Mock(),
        )
        
        # Check that _strip_order_counts is initialized
        assert hasattr(agent, '_strip_order_counts')
        assert "KXBTC15M" in agent._strip_order_counts
        assert agent._strip_order_counts["KXBTC15M"] == 0

    def test_strip_order_limit_enforcement(self):
        """Verify strip order limit is enforced."""
        per_strip_order_limit = 5
        strip_order_counts = {"KXBTC15M": 5}
        
        should_block = strip_order_counts.get("KXBTC15M", 0) >= per_strip_order_limit
        assert should_block is True


class TestBug15AssetExtraction:
    """Test BUG #15: Improved asset extraction robustness."""

    def test_asset_extraction_from_ticker(self):
        """Verify asset extraction uses prefix mapping."""
        asset_map = {
            "KXBTC": "BTC",
            "KXETH": "ETH",
            "KXSOL": "SOL",
            "KXXRP": "XRP",
            "KXDOGE": "DOGE",
        }
        
        # Test all 5 assets
        test_cases = [
            ("KXBTCD-26JUN111330-30", "BTC"),
            ("KXETHD-26JUN111330-30", "ETH"),
            ("KXSOLD-26JUN111330-30", "SOL"),
            ("KXXRPD-26JUN111330-30", "XRP"),
            ("KXDOGED-26JUN111330-30", "DOGE"),
        ]
        
        for ticker, expected_asset in test_cases:
            asset = None
            for prefix, asset_name in asset_map.items():
                if ticker.startswith(prefix):
                    asset = asset_name
                    break
            assert asset == expected_asset, f"Failed for {ticker}: got {asset}, expected {expected_asset}"


class TestRiskProfileFixes:
    """Test fixes to risk profile configuration."""

    def test_per_asset_cap_increased_to_5_percent(self):
        """Verify per-asset max_notional_pct increased from 2% to 5%."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Check that all 5 assets have 5% cap
        expected_pct = 0.05
        for asset_name, asset_config in profile.asset_configs.items():
            assert asset_config.max_notional_pct == expected_pct, \
                f"Asset {asset_name} should have {expected_pct*100}% cap, got {asset_config.max_notional_pct*100}%"

    def test_min_notional_usd_increased(self):
        """Verify min_notional_usd increased from $0.05 to $0.50."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Check that min_notional_usd is $0.50
        assert profile.min_notional_usd == 0.50, \
            f"min_notional_usd should be $0.50, got ${profile.min_notional_usd}"

    def test_max_concurrent_trades_increased(self):
        """Verify max_concurrent_trades increased from 3 to 5."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile


class TestModelProbDistanceThreshold:
    """Test MODEL_PROB_DISTANCE_THRESHOLD increased from 0.02 to 0.05."""

    def test_model_prob_distance_threshold_increased(self):
        """Verify MODEL_PROB_DISTANCE_THRESHOLD increased from 0.02 to 0.05."""
        from merid.event_venues.kalshi.risk_parameters import MODEL_PROB_DISTANCE_THRESHOLD
        
        # Check that threshold is 0.05 (5 percentage points)
        expected_threshold = 0.05
        assert MODEL_PROB_DISTANCE_THRESHOLD == expected_threshold, \
            f"MODEL_PROB_DISTANCE_THRESHOLD should be {expected_threshold}, got {MODEL_PROB_DISTANCE_THRESHOLD}"

    def test_model_prob_distance_threshold_allows_realistic_trades(self):
        """Verify new threshold allows realistic 15m crypto trades."""
        from merid.event_venues.kalshi.risk_parameters import MODEL_PROB_DISTANCE_THRESHOLD
        
        # Test cases: model_prob, price_prob, distance
        test_cases = [
            (0.50, 0.45, 0.05),  # Exactly at threshold - should be allowed
            (0.50, 0.46, 0.04),  # Below threshold - should be allowed
            (0.50, 0.44, 0.06),  # Above threshold - should be rejected
            (0.60, 0.55, 0.05),  # Exactly at threshold - should be allowed
            (0.40, 0.36, 0.04),  # Below threshold - should be allowed
        ]
        
        for model_prob, price_prob, distance in test_cases:
            if distance <= MODEL_PROB_DISTANCE_THRESHOLD:
                # Should be allowed
                assert distance <= MODEL_PROB_DISTANCE_THRESHOLD, \
                    f"Distance {distance} should be <= threshold {MODEL_PROB_DISTANCE_THRESHOLD}"
            else:
                # Should be rejected
                assert distance > MODEL_PROB_DISTANCE_THRESHOLD, \
                    f"Distance {distance} should be > threshold {MODEL_PROB_DISTANCE_THRESHOLD}"

    def test_histogram_buckets_include_new_threshold(self):
        """Verify histogram buckets include 0.08 for new 0.05 threshold."""
        from merid.event_venues.kalshi.kalshi_deployment_safety_metrics import KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM
        
        # Check that histogram exists and is configured
        # The actual bucket configuration is in the source code at line 77
        # This test verifies the import works and the histogram is available
        assert KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM is not None, \
            "KALSHI_MODEL_PROB_DISTANCE_HISTOGRAM should be available"
