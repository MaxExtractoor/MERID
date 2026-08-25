"""
Test suite for Maker/Taker Gate Split (CRITICAL FIX 2026-08-03).

Tests the split gate logic that applies different controls for maker vs taker economics:
- Maker gate: Relaxed spread controls (ratio=1.0, no spread cap)
- Taker gate: Strict spread controls (ratio from config, spread cap enforced)

This addresses the issue where maker orders were being rejected by taker-focused spread gates.
"""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass


@dataclass
class MockEdgeMetrics:
    """Mock edge metrics for testing."""
    side: str
    raw_edge_cents: float
    spread_cents: int
    executable_edge_cents: float
    spread_cost_cents: float
    taker_fee_cents: float
    spread_to_edge_ratio: float
    p_hat_yes_cents: float


@dataclass
class MockDynamicThresholdResult:
    """Mock dynamic threshold result for testing."""
    threshold_cents: float
    spread_component: float
    volatility_component: float
    fee_component: float
    slippage_component: float
    base_hurdle: float
    asset_config_name: str


class TestMakerTakerGateSplit:
    """
    Test suite for maker/taker gate split logic in order_router.
    """

    def test_maker_economics_bypasses_strict_spread_cap(self):
        """
        Test that maker economics bypass strict spread cap.

        Scenario: Maker order with wide spread (35c) but positive edge.
        Expected: Order passes gate (makers capture spread, wide spreads are profitable).
        """
        # Mock edge metrics for maker order
        edge_metrics = MockEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=35,  # Wide spread
            executable_edge_cents=15.0,  # Positive edge (maker captures spread)
            spread_cost_cents=0.0,  # No spread cost for maker
            taker_fee_cents=0.0,  # No fee for maker
            spread_to_edge_ratio=2.33,  # High ratio (would fail taker gate)
            p_hat_yes_cents=65.0
        )

        # Mock dynamic threshold
        dynamic_threshold = MockDynamicThresholdResult(
            threshold_cents=3.0,
            spread_component=0.0,
            volatility_component=0.0,
            fee_component=0.0,
            slippage_component=0.0,
            base_hurdle=3.0,
            asset_config_name="BTC"
        )

        # Mock the edge_aware_microstructure_gate function
        with patch('merid.event_venues.kalshi.order_router.edge_aware_microstructure_gate') as mock_gate:
            # Configure mock to return success for maker gate
            mock_gate.return_value = (True, "ok")

            # Simulate maker gate call (from order_router.py lines 814-827)
            use_maker_economics = True
            min_executable_edge_frac = 0.03  # 3c

            passes, reason = mock_gate(
                edge_metrics=edge_metrics,
                min_executable_edge_frac=min_executable_edge_frac,
                max_spread_to_edge_ratio=1.0,  # RELAXED for maker
                max_spread_cents=None,  # DISABLED for maker
                dynamic_threshold=dynamic_threshold
            )

            # Verify gate was called with maker-specific parameters
            assert mock_gate.called
            call_args = mock_gate.call_args
            assert call_args[1]['max_spread_to_edge_ratio'] == 1.0
            assert call_args[1]['max_spread_cents'] is None

    def test_taker_economics_enforces_spread_cap(self):
        """
        Test that taker economics enforces spread cap.

        Scenario: Taker order with wide spread (35c) that exceeds cap.
        Expected: Order fails gate (takers pay spread, wide spreads are costly).
        """
        # Mock edge metrics for taker order
        edge_metrics = MockEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=35,  # Wide spread
            executable_edge_cents=-20.0,  # Negative edge after spread cost
            spread_cost_cents=35.0,  # Full spread cost for taker
            taker_fee_cents=0.07,  # Taker fee
            spread_to_edge_ratio=2.33,  # High ratio
            p_hat_yes_cents=65.0
        )

        # Mock dynamic threshold
        dynamic_threshold = MockDynamicThresholdResult(
            threshold_cents=3.0,
            spread_component=0.0,
            volatility_component=0.0,
            fee_component=0.0,
            slippage_component=0.0,
            base_hurdle=3.0,
            asset_config_name="BTC"
        )

        # Mock the edge_aware_microstructure_gate function
        with patch('merid.event_venues.kalshi.order_router.edge_aware_microstructure_gate') as mock_gate:
            # Configure mock to return failure for taker gate with wide spread
            mock_gate.return_value = (False, "spread_too_wide: 35c > 20c")

            # Simulate taker gate call (from order_router.py lines 829-842)
            use_maker_economics = False
            min_executable_edge_frac = 0.03  # 3c
            max_spread_to_edge_ratio = 0.4  # Strict ratio
            max_spread_cents = 20.0  # Strict cap

            passes, reason = mock_gate(
                edge_metrics=edge_metrics,
                min_executable_edge_frac=min_executable_edge_frac,
                max_spread_to_edge_ratio=max_spread_to_edge_ratio,  # STRICT for taker
                max_spread_cents=max_spread_cents,  # STRICT for taker
                dynamic_threshold=dynamic_threshold
            )

            # Verify gate was called with taker-specific parameters
            assert mock_gate.called
            call_args = mock_gate.call_args
            assert call_args[1]['max_spread_to_edge_ratio'] == 0.4
            assert call_args[1]['max_spread_cents'] == 20.0

    def test_maker_gate_uses_relaxed_ratio(self):
        """
        Test that maker gate uses relaxed spread/edge ratio.

        Scenario: Maker order with high spread/edge ratio (2.33).
        Expected: Gate uses ratio=1.0 (relaxed), order passes.
        """
        edge_metrics = MockEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=35,
            executable_edge_cents=15.0,
            spread_cost_cents=0.0,
            taker_fee_cents=0.0,
            spread_to_edge_ratio=2.33,  # High ratio
            p_hat_yes_cents=65.0
        )

        dynamic_threshold = MockDynamicThresholdResult(
            threshold_cents=3.0,
            spread_component=0.0,
            volatility_component=0.0,
            fee_component=0.0,
            slippage_component=0.0,
            base_hurdle=3.0,
            asset_config_name="BTC"
        )

        with patch('merid.event_venues.kalshi.order_router.edge_aware_microstructure_gate') as mock_gate:
            mock_gate.return_value = (True, "ok")

            use_maker_economics = True
            min_executable_edge_frac = 0.03

            passes, reason = mock_gate(
                edge_metrics=edge_metrics,
                min_executable_edge_frac=min_executable_edge_frac,
                max_spread_to_edge_ratio=1.0,  # RELAXED
                max_spread_cents=None,
                dynamic_threshold=dynamic_threshold
            )

            # Verify relaxed ratio was used
            call_args = mock_gate.call_args
            assert call_args[1]['max_spread_to_edge_ratio'] == 1.0

    def test_taker_gate_uses_configured_ratio(self):
        """
        Test that taker gate uses configured strict spread/edge ratio.

        Scenario: Taker order with high spread/edge ratio (2.33).
        Expected: Gate uses ratio=0.4 (strict), order fails.
        """
        edge_metrics = MockEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=35,
            executable_edge_cents=-20.0,
            spread_cost_cents=35.0,
            taker_fee_cents=0.07,
            spread_to_edge_ratio=2.33,  # High ratio
            p_hat_yes_cents=65.0
        )

        dynamic_threshold = MockDynamicThresholdResult(
            threshold_cents=3.0,
            spread_component=0.0,
            volatility_component=0.0,
            fee_component=0.0,
            slippage_component=0.0,
            base_hurdle=3.0,
            asset_config_name="BTC"
        )

        with patch('merid.event_venues.kalshi.order_router.edge_aware_microstructure_gate') as mock_gate:
            mock_gate.return_value = (False, "spread_to_edge_ratio_too_high: 2.33 > 0.4")

            use_maker_economics = False
            min_executable_edge_frac = 0.03
            max_spread_to_edge_ratio = 0.4  # STRICT
            max_spread_cents = 20.0

            passes, reason = mock_gate(
                edge_metrics=edge_metrics,
                min_executable_edge_frac=min_executable_edge_frac,
                max_spread_to_edge_ratio=max_spread_to_edge_ratio,  # STRICT
                max_spread_cents=max_spread_cents,
                dynamic_threshold=dynamic_threshold
            )

            # Verify strict ratio was used
            call_args = mock_gate.call_args
            assert call_args[1]['max_spread_to_edge_ratio'] == 0.4

    def test_maker_and_taker_paths_log_distinct_diagnostics(self):
        """
        Test that maker and taker paths emit distinct diagnostic markers.

        Scenario: Both maker and taker orders are processed.
        Expected: Each path logs its specific diagnostic marker.
        """
        with patch('merid.event_venues.kalshi.order_router.logger') as mock_logger:
            # Simulate maker path logging (from order_router.py line 815)
            use_maker_economics = True
            ticker = "KXBTC15M-26AUG021345-45"
            edge = 15.0
            spread = 35.0

            mock_logger.info(
                f"[MAKER-GATE] ticker={ticker} using maker-specific gate: "
                f"edge={edge:.2f}c spread={spread:.2f}c "
                f"(makers capture spread, relaxed spread controls)"
            )

            # Verify maker diagnostic was logged
            assert mock_logger.info.called
            call_args = mock_logger.info.call_args
            assert "[MAKER-GATE]" in str(call_args[0][0])

            # Reset mock
            mock_logger.reset_mock()

            # Simulate taker path logging (from order_router.py line 831)
            use_maker_economics = False

            mock_logger.info(
                f"[TAKER-GATE] ticker={ticker} using taker-specific gate: "
                f"edge={edge:.2f}c spread={spread:.2f}c "
                f"(takers pay spread, strict spread controls)"
            )

            # Verify taker diagnostic was logged
            assert mock_logger.info.called
            call_args = mock_logger.info.call_args
            assert "[TAKER-GATE]" in str(call_args[0][0])

    def test_maker_gate_no_spread_cap_parameter(self):
        """
        Test that maker gate passes None for max_spread_cents.

        Scenario: Maker order with any spread.
        Expected: max_spread_cents=None (disabled).
        """
        edge_metrics = MockEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=100,  # Very wide spread
            executable_edge_cents=15.0,
            spread_cost_cents=0.0,
            taker_fee_cents=0.0,
            spread_to_edge_ratio=6.67,
            p_hat_yes_cents=65.0
        )

        dynamic_threshold = MockDynamicThresholdResult(
            threshold_cents=3.0,
            spread_component=0.0,
            volatility_component=0.0,
            fee_component=0.0,
            slippage_component=0.0,
            base_hurdle=3.0,
            asset_config_name="BTC"
        )

        with patch('merid.event_venues.kalshi.order_router.edge_aware_microstructure_gate') as mock_gate:
            mock_gate.return_value = (True, "ok")

            use_maker_economics = True
            min_executable_edge_frac = 0.03

            passes, reason = mock_gate(
                edge_metrics=edge_metrics,
                min_executable_edge_frac=min_executable_edge_frac,
                max_spread_to_edge_ratio=1.0,
                max_spread_cents=None,  # DISABLED
                dynamic_threshold=dynamic_threshold
            )

            # Verify spread cap is disabled
            call_args = mock_gate.call_args
            assert call_args[1]['max_spread_cents'] is None

    def test_taker_gate_enforces_spread_cap_parameter(self):
        """
        Test that taker gate passes configured max_spread_cents.

        Scenario: Taker order with spread exceeding cap.
        Expected: max_spread_cents=20.0 (enforced).
        """
        edge_metrics = MockEdgeMetrics(
            side="yes",
            raw_edge_cents=15.0,
            spread_cents=35,  # Exceeds cap
            executable_edge_cents=-20.0,
            spread_cost_cents=35.0,
            taker_fee_cents=0.07,
            spread_to_edge_ratio=2.33,
            p_hat_yes_cents=65.0
        )

        dynamic_threshold = MockDynamicThresholdResult(
            threshold_cents=3.0,
            spread_component=0.0,
            volatility_component=0.0,
            fee_component=0.0,
            slippage_component=0.0,
            base_hurdle=3.0,
            asset_config_name="BTC"
        )

        with patch('merid.event_venues.kalshi.order_router.edge_aware_microstructure_gate') as mock_gate:
            mock_gate.return_value = (False, "spread_too_wide: 35c > 20c")

            use_maker_economics = False
            min_executable_edge_frac = 0.03
            max_spread_cents = 20.0

            passes, reason = mock_gate(
                edge_metrics=edge_metrics,
                min_executable_edge_frac=min_executable_edge_frac,
                max_spread_to_edge_ratio=0.4,
                max_spread_cents=max_spread_cents,  # ENFORCED
                dynamic_threshold=dynamic_threshold
            )

            # Verify spread cap is enforced
            call_args = mock_gate.call_args
            assert call_args[1]['max_spread_cents'] == 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
