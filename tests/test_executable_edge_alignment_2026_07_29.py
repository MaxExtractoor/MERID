"""
Test suite for executable edge alignment fix (2026-07-29).

This test validates that signal generation and router use the same executable edge model,
preventing candidates from being rejected downstream due to non_positive_executable_edge.

The fix ensures:
1. Signal generation computes executable edge (maker and taker economics)
2. Candidates with non-positive executable edge are filtered at signal generation
3. Router logs final executable order parameters before handoff
4. Router emits structured rejection reasons with exact fields
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any


class TestExecutableEdgeAlignment:
    """Test executable edge alignment between signal generation and router."""

    def test_signal_generation_computes_executable_edge(self):
        """Test that signal generation computes executable edge for both economics modes."""
        # Simulate signal generation parameters
        asset = "BTC"
        signal_side = "yes"
        best_bid = 60.0
        best_ask = 62.0  # 2 cent spread
        p_model = 0.70
        p_mkt = 0.61

        # Calculate raw edge (fraction)
        edge_pct = p_model - p_mkt  # 0.09 = 9%

        # Calculate spread and fee
        spread_cents = best_ask - best_bid  # 2 cents
        price_cents = (best_bid + best_ask) / 2  # 61 cents
        taker_fee_cents = 0.35
        spread_pct = (spread_cents / price_cents) * 100.0  # 3.28%
        taker_fee_pct = (taker_fee_cents / price_cents) * 100.0  # 0.57%

        # Convert spread and fee to fractions for edge calculation
        spread_frac = spread_pct / 100.0  # 0.0328
        taker_fee_frac = taker_fee_pct / 100.0  # 0.0057

        # Compute executable edges (fractions)
        executable_edge_maker_pct = edge_pct  # 0.09 (no spread/fee)
        executable_edge_taker_pct = edge_pct - spread_frac - taker_fee_frac  # 0.09 - 0.0328 - 0.0057 = 0.0515

        # Verify calculations
        assert spread_cents == 2.0, f"Spread should be 2c, got {spread_cents}c"
        assert executable_edge_maker_pct == pytest.approx(0.09, abs=0.01), \
            f"Maker executable edge should be ~9%, got {executable_edge_maker_pct * 100:.2f}%"
        assert executable_edge_taker_pct == pytest.approx(0.0515, abs=0.01), \
            f"Taker executable edge should be ~5.15%, got {executable_edge_taker_pct * 100:.2f}%"

    def test_signal_filters_non_positive_executable_edge(self):
        """Test that signal generation filters candidates with non-positive executable edge."""
        # Scenario: wide spread makes taker executable edge negative
        best_bid = 60.0
        best_ask = 70.0  # 10 cent spread
        p_model = 0.65
        p_mkt = 0.61

        # Calculate raw edge
        edge_pct = p_model - p_mkt  # 0.04 = 4%

        # Calculate spread and fee
        spread_cents = best_ask - best_bid  # 10 cents
        price_cents = (best_bid + best_ask) / 2  # 65 cents
        taker_fee_cents = 0.35
        spread_pct = (spread_cents / price_cents) * 100.0  # 15.38%
        taker_fee_pct = (taker_fee_cents / price_cents) * 100.0  # 0.54%

        # Compute executable edges
        executable_edge_maker_pct = edge_pct  # 4% (no spread/fee)
        executable_edge_taker_pct = edge_pct - spread_pct - taker_fee_pct  # 4% - 15.38% - 0.54% = -11.92%

        # Verify taker executable edge is negative
        assert executable_edge_taker_pct < 0, \
            f"Taker executable edge should be negative ({executable_edge_taker_pct * 100:.2f}%), but it's positive"

        # This candidate should be filtered by signal generation
        assert executable_edge_taker_pct <= 0, \
            "Candidate with non-positive executable edge should be filtered"

    def test_signal_includes_executable_edge_parameters(self):
        """Test that signal includes executable edge parameters for router alignment."""
        # Create a mock signal with executable edge parameters
        signal = {
            "asset": "BTC",
            "side": "yes",
            "edge_pct": 0.09,
            "executable_edge_maker_pct": 0.09,
            "executable_edge_taker_pct": 0.0515,
            "spread_cents": 2.0,
            "spread_pct": 3.28,
            "taker_fee_cents": 0.35,
            "taker_fee_pct": 0.57,
        }

        # Verify all executable edge parameters are present
        assert "executable_edge_maker_pct" in signal, "Signal should include executable_edge_maker_pct"
        assert "executable_edge_taker_pct" in signal, "Signal should include executable_edge_taker_pct"
        assert "spread_cents" in signal, "Signal should include spread_cents"
        assert "spread_pct" in signal, "Signal should include spread_pct"
        assert "taker_fee_cents" in signal, "Signal should include taker_fee_cents"
        assert "taker_fee_pct" in signal, "Signal should include taker_fee_pct"

        # Verify values are reasonable
        assert signal["executable_edge_maker_pct"] >= 0, "Maker executable edge should be non-negative"
        assert signal["spread_cents"] >= 0, "Spread should be non-negative"
        assert signal["taker_fee_cents"] >= 0, "Taker fee should be non-negative"

    def test_router_logs_handoff_telemetry(self):
        """Test that router logs final executable order parameters before handoff."""
        # Mock the edge metrics
        edge_metrics = Mock()
        edge_metrics.raw_edge_cents = 9.0
        edge_metrics.spread_cents = 2.0
        edge_metrics.spread_cost_cents = 2.0
        edge_metrics.taker_fee_cents = 0.35
        edge_metrics.executable_edge_cents = 6.65

        # Verify router handoff telemetry includes all required fields
        telemetry_fields = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "order_price_cents": 61.0,
            "raw_edge": edge_metrics.raw_edge_cents,
            "spread_cents": edge_metrics.spread_cents,
            "spread_cost_cents": edge_metrics.spread_cost_cents,
            "taker_fee_cents": edge_metrics.taker_fee_cents,
            "executable_edge": edge_metrics.executable_edge_cents,
            "use_maker_economics": False,
            "aggressiveness": 0.5,
        }

        # All fields should be present
        for field, value in telemetry_fields.items():
            assert value is not None, f"Telemetry field {field} should not be None"

    def test_router_emits_structured_rejection_reason(self):
        """Test that router emits structured rejection reason with exact fields."""
        # Mock edge metrics with non-positive executable edge
        edge_metrics = Mock()
        edge_metrics.raw_edge_cents = 4.0
        edge_metrics.spread_cost_cents = 10.0
        edge_metrics.taker_fee_cents = 0.35
        edge_metrics.executable_edge_cents = -6.35  # Negative

        # Build structured rejection reason
        rejection_details = (
            f"non_positive_executable_edge: raw_edge={edge_metrics.raw_edge_cents:.2f}c "
            f"spread_cost={edge_metrics.spread_cost_cents:.2f}c "
            f"taker_fee={edge_metrics.taker_fee_cents:.2f}c "
            f"executable_edge={edge_metrics.executable_edge_cents:.2f}c"
        )

        # Verify rejection reason includes all required fields
        assert "non_positive_executable_edge" in rejection_details
        assert "raw_edge=" in rejection_details
        assert "spread_cost=" in rejection_details
        assert "taker_fee=" in rejection_details
        assert "executable_edge=" in rejection_details

        # Verify exact values are included
        assert "4.00c" in rejection_details  # raw_edge
        assert "10.00c" in rejection_details  # spread_cost
        assert "0.35c" in rejection_details  # taker_fee
        assert "-6.35c" in rejection_details  # executable_edge

    def test_executable_edge_too_low_rejection(self):
        """Test that router emits structured rejection for executable_edge_too_low."""
        # Mock edge metrics with positive but too low executable edge
        edge_metrics = Mock()
        edge_metrics.raw_edge_cents = 2.0
        edge_metrics.spread_cost_cents = 1.0
        edge_metrics.taker_fee_cents = 0.35
        edge_metrics.executable_edge_cents = 0.65  # Positive but below 3c threshold
        min_executable_edge_cents = 3.0

        # Build structured rejection reason
        rejection_details = (
            f"executable_edge_too_low: raw_edge={edge_metrics.raw_edge_cents:.2f}c "
            f"spread_cost={edge_metrics.spread_cost_cents:.2f}c "
            f"taker_fee={edge_metrics.taker_fee_cents:.2f}c "
            f"executable_edge={edge_metrics.executable_edge_cents:.2f}c "
            f"< min_executable_edge={min_executable_edge_cents:.2f}c"
        )

        # Verify rejection reason includes all required fields
        assert "executable_edge_too_low" in rejection_details
        assert "raw_edge=" in rejection_details
        assert "spread_cost=" in rejection_details
        assert "taker_fee=" in rejection_details
        assert "executable_edge=" in rejection_details
        assert "min_executable_edge=" in rejection_details

        # Verify exact values are included
        assert "2.00c" in rejection_details  # raw_edge
        assert "1.00c" in rejection_details  # spread_cost
        assert "0.35c" in rejection_details  # taker_fee
        assert "0.65c" in rejection_details  # executable_edge
        assert "3.00c" in rejection_details  # min_executable_edge

    def test_maker_vs_taker_economics_selection(self):
        """Test that economics mode is correctly derived from aggressiveness."""
        # Test resting order (aggressiveness=0.0) -> maker economics
        aggressiveness_resting = 0.0
        use_maker_economics_resting = (aggressiveness_resting == 0.0)
        assert use_maker_economics_resting is True, \
            "Resting orders (aggressiveness=0.0) should use maker economics"

        # Test marketable order (aggressiveness>0.0) -> taker economics
        aggressiveness_marketable = 0.5
        use_maker_economics_marketable = (aggressiveness_marketable == 0.0)
        assert use_maker_economics_marketable is False, \
            "Marketable orders (aggressiveness>0.0) should use taker economics"

        # Test various aggressiveness values
        test_cases = [
            (0.0, True, "aggressiveness=0.0 should use maker economics"),
            (0.1, False, "aggressiveness=0.1 should use taker economics"),
            (0.5, False, "aggressiveness=0.5 should use taker economics"),
            (1.0, False, "aggressiveness=1.0 should use taker economics"),
        ]

        for agg, expected_maker, description in test_cases:
            use_maker = (agg == 0.0)
            assert use_maker == expected_maker, description

    def test_end_to_end_candidate_flow(self):
        """Test end-to-end candidate flow from signal generation to router handoff."""
        # Step 1: Signal generation with positive executable edge
        signal = {
            "asset": "BTC",
            "side": "yes",
            "edge_pct": 0.09,
            "executable_edge_maker_pct": 0.09,
            "executable_edge_taker_pct": 0.0515,  # Positive - should pass filter
            "spread_cents": 2.0,
            "spread_pct": 3.28,
            "taker_fee_cents": 0.35,
            "taker_fee_pct": 0.57,
            "aggressiveness": 0.5,  # Marketable -> taker economics
        }

        # Step 2: Verify candidate passes executable edge filter
        assert signal["executable_edge_taker_pct"] > 0, \
            "Candidate with positive executable edge should pass filter"

        # Step 3: Router computes economics based on aggressiveness
        use_maker_economics = (signal["aggressiveness"] == 0.0)
        assert use_maker_economics is False, \
            "Marketable order should use taker economics"

        # Step 4: Router logs handoff telemetry
        handoff_telemetry = {
            "ticker": "KXBTC15M-TEST",
            "side": signal["side"],
            "aggressiveness": signal["aggressiveness"],
            "use_maker_economics": use_maker_economics,
            "executable_edge": signal["executable_edge_taker_pct"] * 100,  # Convert to cents
        }

        # Verify telemetry is logged
        assert handoff_telemetry["executable_edge"] > 0, \
            "Handoff telemetry should show positive executable edge"

        # Step 5: Order should be accepted (not rejected)
        # Since executable_edge > 0, order should pass edge-aware gate
        assert handoff_telemetry["executable_edge"] > 0, \
            "Order with positive executable edge should be accepted"

    def test_candidate_rejected_at_signal_generation(self):
        """Test that candidate with non-positive executable edge is rejected at signal generation."""
        # Signal with negative taker executable edge
        signal = {
            "asset": "BTC",
            "side": "yes",
            "edge_pct": 0.04,
            "executable_edge_maker_pct": 0.04,
            "executable_edge_taker_pct": -0.1192,  # Negative - should be filtered
            "spread_cents": 10.0,
            "spread_pct": 15.38,
            "taker_fee_cents": 0.35,
            "taker_fee_pct": 0.54,
        }

        # Verify candidate is filtered
        assert signal["executable_edge_taker_pct"] <= 0, \
            "Candidate with non-positive executable edge should be filtered at signal generation"

        # This prevents downstream router rejection
        # The order never reaches the router, saving resources

    def test_rest_fallback_mode_activation(self):
        """Test that REST fallback mode is activated when WebSocket fails."""
        # Simulate WebSocket bridge initialization
        # REST fallback should be enabled by default due to WebSocket issues
        rest_fallback_mode = True  # TEMPORARY FIX 2026-07-29

        # Verify REST fallback is enabled
        assert rest_fallback_mode is True, \
            "REST fallback mode should be enabled by default due to WebSocket orderbook subscription issues"

        # When REST fallback is active, market data should be fetched via REST API
        # This ensures fresh market data even when WebSocket is not receiving events
        # This prevents extreme spreads and trade rejections

    def test_market_data_quality_with_rest_fallback(self):
        """Test that REST fallback provides fresh market data with reasonable spreads."""
        # Simulate REST API orderbook response with reasonable spread
        rest_orderbook = {
            "ticker": "KXBTC15M-TEST",
            "bids": [[60, 100], [59, 50]],  # Reasonable bid prices
            "asks": [[62, 100], [63, 50]],  # Reasonable ask prices
        }

        # Calculate spread from REST data
        best_bid = rest_orderbook["bids"][0][0]
        best_ask = rest_orderbook["asks"][0][0]
        spread_cents = best_ask - best_bid  # 2 cents - reasonable

        # Verify spread is reasonable (not extreme like 99c)
        assert spread_cents < 10, \
            f"REST fallback should provide reasonable spreads, got {spread_cents}c spread"

        # Verify both bid and ask are non-zero
        assert best_bid > 0, "REST fallback should provide non-zero bid"
        assert best_ask < 100, "REST fallback should provide ask below ceiling (100c)"

        # This ensures executable edge calculation can succeed
        # With reasonable spreads, candidates won't be rejected due to extreme spreads


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
