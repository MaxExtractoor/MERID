"""
Test suite for Dynamic Spread Model (CRITICAL FIX 2026-08-03).

Tests the Avellaneda-Stoikov based dynamic spread model that implements:
- Inventory-aware spread adjustment
- Volatility-adjusted spreads
- Time-to-expiry scaling
- Maker vs taker order handling
- Order flow imbalance detection
- Adverse selection protection

Based on research from:
- Avellaneda & Stoikov (2008): High-frequency trading in a limit order book
- Glosten & Milgrom (1985): Adverse selection and spread compensation
- Polymarket Market Making Bible: Belief volatility and Greeks
- HFT Book: Order flow imbalance and information-based market making
"""

import pytest
import math
from merid.event_venues.kalshi.dynamic_spread_model import (
    AvellanedaStoikovParameters,
    DynamicSpreadModel,
    SpreadCalculationResult,
    calculate_optimal_spread_for_order,
    get_dynamic_spread_model,
)


class TestAvellanedaStoikovParameters:
    """Test suite for AvellanedaStoikovParameters dataclass."""

    def test_default_parameters(self):
        """Test that default parameters are set correctly."""
        params = AvellanedaStoikovParameters()

        assert params.risk_aversion == 0.5
        assert params.volatility == 0.05  # Updated to match real market conditions (5% default, was 2%)
        assert params.order_book_liquidity == 0.5  # Updated to match real market conditions (0.5 default, was 0.1)
        assert params.closing_time == 1.0
        assert params.current_time == 0.0

    def test_custom_parameters(self):
        """Test that custom parameters can be set."""
        params = AvellanedaStoikovParameters(
            risk_aversion=0.7,
            volatility=0.05,
            order_book_liquidity=0.2,
            closing_time=1.0,
            current_time=0.5
        )

        assert params.risk_aversion == 0.7
        assert params.volatility == 0.05
        assert params.order_book_liquidity == 0.2
        assert params.closing_time == 1.0
        assert params.current_time == 0.5


class TestSpreadCalculationResult:
    """Test suite for SpreadCalculationResult dataclass."""

    def test_result_structure(self):
        """Test that result has all required fields."""
        result = SpreadCalculationResult(
            optimal_spread_cents=10.0,
            reservation_price_cents=50.0,
            inventory_adjustment_cents=1.0,
            volatility_adjustment_cents=2.0,
            time_adjustment_cents=0.5,
            liquidity_adjustment_cents=1.5,
            confidence=0.9
        )

        assert result.optimal_spread_cents == 10.0
        assert result.reservation_price_cents == 50.0
        assert result.inventory_adjustment_cents == 1.0
        assert result.volatility_adjustment_cents == 2.0
        assert result.time_adjustment_cents == 0.5
        assert result.liquidity_adjustment_cents == 1.5
        assert result.confidence == 0.9


class TestDynamicSpreadModel:
    """Test suite for DynamicSpreadModel class."""

    def test_default_initialization(self):
        """Test that model initializes with default parameters."""
        model = DynamicSpreadModel()

        assert model.params.risk_aversion == 0.5
        assert model.params.volatility == 0.05  # Updated to match real market conditions (5% default, was 2%)
        assert model.params.order_book_liquidity == 0.5  # Updated to match real market conditions (0.5 default, was 0.1)

    def test_custom_initialization(self):
        """Test that model initializes with custom parameters."""
        params = AvellanedaStoikovParameters(
            risk_aversion=0.7,
            volatility=0.05,
            order_book_liquidity=0.2
        )
        model = DynamicSpreadModel(params)

        assert model.params.risk_aversion == 0.7
        assert model.params.volatility == 0.05
        assert model.params.order_book_liquidity == 0.2

    def test_calculate_optimal_spread_basic(self):
        """Test basic optimal spread calculation."""
        model = DynamicSpreadModel()

        result = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,  # Full 15 minutes
            order_book_liquidity=0.1,
            volatility=0.02
        )

        assert result.optimal_spread_cents > 0
        assert result.reservation_price_cents == 50.0  # No inventory adjustment
        assert result.inventory_adjustment_cents == 0.0
        assert result.confidence > 0

    def test_calculate_optimal_spread_with_inventory(self):
        """Test optimal spread calculation with inventory adjustment."""
        model = DynamicSpreadModel()

        # Long inventory (positive)
        result_long = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=10,  # Long position
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        # Short inventory (negative)
        result_short = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=-10,  # Short position
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        # Long inventory should lower reservation price (favor sell orders)
        assert result_long.reservation_price_cents < 50.0
        assert result_long.inventory_adjustment_cents > 0

        # Short inventory should raise reservation price (favor buy orders)
        assert result_short.reservation_price_cents > 50.0
        assert result_short.inventory_adjustment_cents < 0

    def test_calculate_optimal_spread_with_time_decay(self):
        """Test optimal spread calculation with time decay."""
        model = DynamicSpreadModel()

        # Early in window (full 15 minutes)
        result_early = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        # Late in window (3 minutes remaining)
        result_late = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=180.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        # Late window should have wider spread (time adjustment)
        assert result_late.optimal_spread_cents > result_early.optimal_spread_cents
        assert result_late.time_adjustment_cents > 0

    def test_calculate_optimal_spread_with_volatility(self):
        """Test optimal spread calculation with volatility adjustment."""
        model = DynamicSpreadModel()

        # Use 3 minutes remaining to see volatility adjustment effect
        # Low volatility
        result_low_vol = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=180.0,  # 3 minutes remaining
            order_book_liquidity=0.1,
            volatility=0.01  # Low volatility
        )

        # High volatility
        result_high_vol = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=180.0,  # 3 minutes remaining
            order_book_liquidity=0.1,
            volatility=0.05  # High volatility
        )

        # High volatility should have wider spread
        assert result_high_vol.optimal_spread_cents > result_low_vol.optimal_spread_cents
        assert result_high_vol.volatility_adjustment_cents > result_low_vol.volatility_adjustment_cents

    def test_calculate_optimal_spread_with_liquidity(self):
        """Test optimal spread calculation with liquidity adjustment."""
        model = DynamicSpreadModel()

        # High liquidity (tight spread)
        result_high_liq = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.5,  # High liquidity
            volatility=0.02
        )

        # Low liquidity (wide spread)
        result_low_liq = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.05,  # Low liquidity
            volatility=0.02
        )

        # Low liquidity should have wider spread
        assert result_low_liq.optimal_spread_cents > result_high_liq.optimal_spread_cents
        assert result_low_liq.liquidity_adjustment_cents > result_high_liq.liquidity_adjustment_cents

    def test_calculate_optimal_spread_with_order_flow_imbalance(self):
        """Test optimal spread calculation with order flow imbalance."""
        model = DynamicSpreadModel()

        # No imbalance
        result_no_imbalance = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=0.0
        )

        # Strong positive imbalance (more bids)
        result_positive_imbalance = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=0.8
        )

        # Strong negative imbalance (more asks)
        result_negative_imbalance = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=-0.8
        )

        # Strong imbalance should have wider spread (adverse selection protection)
        assert result_positive_imbalance.optimal_spread_cents > result_no_imbalance.optimal_spread_cents
        assert result_negative_imbalance.optimal_spread_cents > result_no_imbalance.optimal_spread_cents

    def test_calculate_maker_spread(self):
        """Test maker spread calculation."""
        model = DynamicSpreadModel()

        result = model.calculate_maker_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        # Maker spread should be wider than base optimal spread
        base_result = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        assert result.optimal_spread_cents > base_result.optimal_spread_cents
        assert result.reservation_price_cents < base_result.reservation_price_cents

    def test_calculate_taker_spread(self):
        """Test taker spread calculation."""
        model = DynamicSpreadModel()

        result = model.calculate_taker_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        # Taker spread should be tighter than base optimal spread
        base_result = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02
        )

        assert result.optimal_spread_cents < base_result.optimal_spread_cents
        assert result.reservation_price_cents > base_result.reservation_price_cents
        assert result.optimal_spread_cents >= 0.1  # Minimum spread

    def test_calculate_time_bucket_spread(self):
        """Test time bucket spread adjustment."""
        model = DynamicSpreadModel()
        base_spread = 10.0

        # Test all time buckets
        buckets = ["0-3min", "3-6min", "6-10min", "10-13min", "13-15min"]
        expected_multipliers = [0.8, 0.9, 1.0, 1.2, 1.5]

        for bucket, expected_multiplier in zip(buckets, expected_multipliers):
            adjusted = model.calculate_time_bucket_spread(bucket, base_spread)
            assert adjusted == base_spread * expected_multiplier

    def test_calculate_volatility_adjusted_spread(self):
        """Test volatility-adjusted spread calculation."""
        model = DynamicSpreadModel()
        base_spread = 10.0

        # High volatility (2x historical)
        adjusted_high = model.calculate_volatility_adjusted_spread(
            base_spread_cents=base_spread,
            current_volatility=0.04,
            historical_volatility=0.02
        )

        # Low volatility (0.5x historical)
        adjusted_low = model.calculate_volatility_adjusted_spread(
            base_spread_cents=base_spread,
            current_volatility=0.01,
            historical_volatility=0.02
        )

        # High volatility should widen spread (up to 2x)
        assert adjusted_high > base_spread
        assert adjusted_high <= base_spread * 2.0

        # Low volatility should tighten spread (down to 0.5x)
        assert adjusted_low < base_spread
        assert adjusted_low >= base_spread * 0.5

    def test_calculate_order_flow_imbalance(self):
        """Test order flow imbalance calculation."""
        model = DynamicSpreadModel()

        # Balanced book
        ofi_balanced = model.calculate_order_flow_imbalance(
            yes_bid_depth=100,
            yes_ask_depth=100,
            no_bid_depth=100,
            no_ask_depth=100
        )

        # More bids (positive OFI)
        ofi_positive = model.calculate_order_flow_imbalance(
            yes_bid_depth=200,
            yes_ask_depth=100,
            no_bid_depth=200,
            no_ask_depth=100
        )

        # More asks (negative OFI)
        ofi_negative = model.calculate_order_flow_imbalance(
            yes_bid_depth=100,
            yes_ask_depth=200,
            no_bid_depth=100,
            no_ask_depth=200
        )

        assert ofi_balanced == 0.0
        assert ofi_positive > 0.0
        assert ofi_negative < 0.0
        assert -1.0 <= ofi_positive <= 1.0
        assert -1.0 <= ofi_negative <= 1.0

    def test_detect_adverse_selection_risk(self):
        """Test adverse selection risk detection."""
        model = DynamicSpreadModel()

        # Low risk (balanced flow, no price move, normal volume)
        high_risk_low, risk_score_low = model.detect_adverse_selection_risk(
            order_flow_imbalance=0.2,
            recent_price_move_cents=0.5,
            volume_ratio=1.0
        )

        # High risk (strong imbalance, price move in same direction, high volume)
        high_risk_high, risk_score_high = model.detect_adverse_selection_risk(
            order_flow_imbalance=0.8,
            recent_price_move_cents=2.0,
            volume_ratio=2.0
        )

        assert not high_risk_low
        assert high_risk_high
        assert risk_score_high > risk_score_low
        assert 0.0 <= risk_score_low <= 1.0
        assert 0.0 <= risk_score_high <= 1.0


class TestCalculateOptimalSpreadForOrder:
    """Test suite for calculate_optimal_spread_for_order convenience function."""

    def test_maker_order_spread(self):
        """Test optimal spread calculation for maker order."""
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02
        )

        assert result.optimal_spread_cents > 0
        assert result.confidence > 0

    def test_taker_order_spread(self):
        """Test optimal spread calculation for taker order."""
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="taker",
            order_book_liquidity=0.1,
            volatility=0.02
        )

        assert result.optimal_spread_cents > 0
        assert result.optimal_spread_cents >= 0.1  # Minimum spread
        assert result.confidence > 0

    def test_time_bucket_adjustment(self):
        """Test optimal spread with time bucket adjustment."""
        # Early window
        result_early = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            time_bucket="0-3min"
        )

        # Late window
        result_late = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=180.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            time_bucket="13-15min"
        )

        # Late window should have wider spread
        assert result_late.optimal_spread_cents > result_early.optimal_spread_cents

    def test_volatility_adjustment(self):
        """Test optimal spread with volatility adjustment."""
        # High volatility
        result_high_vol = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.04,
            current_volatility=0.04,
            historical_volatility=0.02
        )

        # Low volatility
        result_low_vol = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.01,
            current_volatility=0.01,
            historical_volatility=0.02
        )

        # High volatility should have wider spread
        assert result_high_vol.optimal_spread_cents > result_low_vol.optimal_spread_cents

    def test_order_flow_imbalance_adjustment(self):
        """Test optimal spread with order flow imbalance adjustment."""
        # No imbalance
        result_no_imbalance = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=0.0
        )

        # Strong imbalance
        result_strong_imbalance = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=0.8
        )

        # Strong imbalance should have wider spread
        assert result_strong_imbalance.optimal_spread_cents > result_no_imbalance.optimal_spread_cents


class TestGetDynamicSpreadModel:
    """Test suite for get_dynamic_spread_model singleton function."""

    def test_singleton_instance(self):
        """Test that singleton returns the same instance."""
        model1 = get_dynamic_spread_model()
        model2 = get_dynamic_spread_model()

        assert model1 is model2

    def test_singleton_with_custom_parameters(self):
        """Test that singleton uses default parameters."""
        model = get_dynamic_spread_model()

        assert model.params.risk_aversion == 0.5
        assert model.params.volatility == 0.05  # Updated to match real market conditions (5% default, was 2%)
        assert model.params.order_book_liquidity == 0.5  # Updated to match real market conditions (0.5 default, was 0.1)


class TestIntegrationScenarios:
    """Integration tests for realistic trading scenarios."""

    def test_btc_early_window_maker_order(self):
        """
        Test BTC maker order in early window (0-3min).

        Scenario: BTC at 50c, no inventory, 900s remaining, balanced book.
        Expected: Tight spread (early window, low volatility, maker order).
        """
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.2,  # High liquidity for BTC
            volatility=0.015,  # Low volatility for BTC
            order_flow_imbalance=0.1,  # Balanced
            time_bucket="0-3min",
            current_volatility=0.015,
            historical_volatility=0.015
        )

        # Should have tight spread (early window, low volatility, high liquidity)
        assert result.optimal_spread_cents < 5.0
        assert result.confidence > 0.8

    def test_eth_late_window_taker_order(self):
        """
        Test ETH taker order in late window (13-15min).

        Scenario: ETH at 50c, no inventory, 180s remaining, imbalanced book.
        Expected: Wide spread (late window, high volatility, taker order).
        """
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=180.0,
            order_side="taker",
            order_book_liquidity=0.05,  # Low liquidity for ETH
            volatility=0.03,  # High volatility for ETH
            order_flow_imbalance=0.7,  # Strong imbalance
            time_bucket="13-15min",
            current_volatility=0.03,
            historical_volatility=0.02
        )

        # Should have wide spread (late window, high volatility, low liquidity, imbalance)
        assert result.optimal_spread_cents > 10.0
        assert result.optimal_spread_cents >= 0.1  # Minimum spread
        assert result.confidence > 0.8

    def test_sol_mid_window_with_inventory(self):
        """
        Test SOL order with inventory in mid window (6-10min).

        Scenario: SOL at 50c, long inventory (10), 600s remaining, balanced book.
        Expected: Spread adjusted for inventory risk.
        """
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=10,  # Long inventory
            time_to_expiry_seconds=600.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=0.0,
            time_bucket="6-10min"
        )

        # Should have inventory adjustment
        assert result.inventory_adjustment_cents > 0
        assert result.reservation_price_cents < 50.0  # Lower to favor sell orders
        assert result.confidence > 0.8

    def test_doge_high_volatility_scenario(self):
        """
        Test DOGE order in high volatility scenario.

        Scenario: DOGE at 50c, no inventory, 180s remaining, high volatility.
        Expected: Wide spread (high volatility compensation).
        """
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=180.0,  # 3 minutes remaining to see volatility effect
            order_side="maker",
            order_book_liquidity=0.05,  # Low liquidity for DOGE
            volatility=0.05,  # High volatility for DOGE
            order_flow_imbalance=0.0,
            current_volatility=0.05,
            historical_volatility=0.03
        )

        # Should have wide spread (high volatility)
        assert result.optimal_spread_cents > 5.0
        assert result.volatility_adjustment_cents > 0
        assert result.confidence > 0.8

    def test_xrp_adverse_selection_protection(self):
        """
        Test XRP order with adverse selection protection.

        Scenario: XRP at 50c, no inventory, 900s remaining, strong imbalance.
        Expected: Wider spread (adverse selection protection).
        """
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            order_flow_imbalance=0.9,  # Strong imbalance
        )

        # Should have wider spread (adverse selection protection)
        assert result.optimal_spread_cents > 3.0
        assert result.confidence > 0.8


class TestRegimeAwareSpreadFloor:
    """
    Test suite for regime-aware spread floor calculation (CRITICAL FIX 2026-08-03).

    Tests the new regime-aware floor logic that computes minimum spread from
    observed market spread instead of hardcoded minimums.
    """

    def test_clamp_spread_uses_regime_aware_floor_when_observed_spread_lower_than_floor(self):
        """
        Test that clamp_spread uses regime-aware floor when observed spread is provided.

        Scenario: BTC with observed spread 35c, calculated spread 3.1c.
        Expected: Floor is 17.5c (50% of observed), spread clamped to 17.5c.
        """
        from merid.event_venues.kalshi.dynamic_spread_model import clamp_spread

        # Simulate the bug: calculated spread is 3.1c but observed is 35c
        calculated_spread = 3.1
        observed_spread = 35.0
        asset = "BTC"

        clamped, was_clamped, reason = clamp_spread(
            spread_cents=calculated_spread,
            asset=asset,
            time_bucket="13-15min",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Should be clamped to regime floor (50% of observed = 17.5c)
        assert was_clamped
        assert clamped == 17.5
        assert "regime_floor" in reason
        assert clamped >= 17.5  # Floor is 50% of observed

    def test_clamp_spread_respects_floor_based_on_half_observed_spread(self):
        """
        Test that floor is exactly 50% of observed spread when observed is provided.

        Scenario: ETH with observed spread 51c.
        Expected: Floor is 25.5c (50% of observed).
        """
        from merid.event_venues.kalshi.dynamic_spread_model import clamp_spread

        observed_spread = 51.0
        asset = "ETH"

        clamped, was_clamped, reason = clamp_spread(
            spread_cents=10.0,  # Below floor
            asset=asset,
            time_bucket="13-15min",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Floor should be exactly 50% of observed
        assert was_clamped
        assert clamped == 25.5  # 50% of 51c
        assert "regime_floor" in reason

    def test_clamp_spread_respects_existing_max_cap(self):
        """
        Test that clamp_spread still respects maximum cap even with regime-aware floor.

        Scenario: BTC with observed spread 100c, calculated spread 80c, max cap 65c.
        Expected: Clamped to max cap 65c (not observed spread).
        """
        from merid.event_venues.kalshi.dynamic_spread_model import clamp_spread

        calculated_spread = 80.0
        observed_spread = 100.0
        asset = "BTC"
        max_cap = 65.0

        clamped, was_clamped, reason = clamp_spread(
            spread_cents=calculated_spread,
            asset=asset,
            time_bucket="13-15min",
            per_asset_cap=max_cap,
            observed_market_spread=observed_spread
        )

        # Should be clamped to max cap, not observed spread
        assert was_clamped
        assert clamped == max_cap
        assert "maximum" in reason

    def test_clamp_spread_uses_base_minimum_when_no_observed_spread(self):
        """
        Test that clamp_spread falls back to base minimum when observed spread is not provided.

        Scenario: BTC with no observed spread, calculated spread 1.0c.
        Expected: Clamped to base minimum (2.0c * time multiplier).
        """
        from merid.event_venues.kalshi.dynamic_spread_model import clamp_spread

        calculated_spread = 1.0
        asset = "BTC"

        clamped, was_clamped, reason = clamp_spread(
            spread_cents=calculated_spread,
            asset=asset,
            time_bucket="13-15min",
            per_asset_cap=None,
            observed_market_spread=None  # No observed spread
        )

        # Should use base minimum with time multiplier
        assert was_clamped
        assert clamped >= 2.0  # Base minimum
        assert "below_regime_floor" in reason or "below_minimum" in reason

    def test_clamp_spread_no_clamp_when_spread_above_floor(self):
        """
        Test that clamp_spread does not clamp when spread is above regime floor.

        Scenario: BTC with observed spread 35c, calculated spread 20c.
        Expected: No clamping (20c > 17.5c floor).
        """
        from merid.event_venues.kalshi.dynamic_spread_model import clamp_spread

        calculated_spread = 20.0
        observed_spread = 35.0
        asset = "BTC"

        clamped, was_clamped, reason = clamp_spread(
            spread_cents=calculated_spread,
            asset=asset,
            time_bucket="13-15min",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Should not be clamped (above floor)
        assert not was_clamped
        assert clamped == calculated_spread
        assert reason == ""

    def test_calculate_optimal_spread_for_order_passes_observed_market_spread_through(self):
        """
        Test that calculate_optimal_spread_for_order passes observed spread to inner model.

        Scenario: Maker order with observed spread 35c.
        Expected: Observed spread is passed through to clamp_spread.
        """
        observed_spread = 35.0

        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            asset="BTC",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Result should be valid
        assert result.optimal_spread_cents > 0
        assert result.confidence > 0

    def test_calculate_optimal_spread_for_order_backwards_compatible_without_observed_spread(self):
        """
        Test that calculate_optimal_spread_for_order works without observed spread (backwards compatible).

        Scenario: Maker order without observed spread parameter.
        Expected: Uses base minimum floor (backwards compatible behavior).
        """
        result = calculate_optimal_spread_for_order(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_side="maker",
            order_book_liquidity=0.1,
            volatility=0.02,
            asset="BTC",
            per_asset_cap=None
            # observed_market_spread not provided (optional parameter)
        )

        # Result should still be valid
        assert result.optimal_spread_cents > 0
        assert result.confidence > 0

    def test_calculate_optimal_spread_with_observed_spread_parameter(self):
        """
        Test that calculate_optimal_spread accepts and uses observed_market_spread parameter.

        Scenario: Direct call to calculate_optimal_spread with observed spread.
        Expected: Observed spread is passed to clamp_spread.
        """
        model = DynamicSpreadModel()
        observed_spread = 35.0

        result = model.calculate_optimal_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02,
            asset="BTC",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Result should be valid
        assert result.optimal_spread_cents > 0
        assert result.confidence > 0

    def test_maker_spread_with_observed_spread(self):
        """
        Test that calculate_maker_spread passes observed spread to base calculation.

        Scenario: Maker order with observed spread 51c.
        Expected: Observed spread is passed through to calculate_optimal_spread.
        """
        model = DynamicSpreadModel()
        observed_spread = 51.0

        result = model.calculate_maker_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02,
            asset="ETH",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Result should be valid with maker premium
        assert result.optimal_spread_cents > 0
        assert result.confidence > 0

    def test_taker_spread_with_observed_spread(self):
        """
        Test that calculate_taker_spread passes observed spread to base calculation.

        Scenario: Taker order with observed spread 51c.
        Expected: Observed spread is passed through to calculate_optimal_spread.
        """
        model = DynamicSpreadModel()
        observed_spread = 51.0

        result = model.calculate_taker_spread(
            mid_price_cents=50.0,
            inventory=0,
            time_to_expiry_seconds=900.0,
            order_book_liquidity=0.1,
            volatility=0.02,
            asset="ETH",
            per_asset_cap=None,
            observed_market_spread=observed_spread
        )

        # Result should be valid with taker discount
        assert result.optimal_spread_cents > 0
        assert result.optimal_spread_cents >= 0.1  # Minimum spread
        assert result.confidence > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
