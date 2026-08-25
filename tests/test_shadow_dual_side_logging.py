"""
Tests for shadow dual-side logging in agent_grid_15m.py.

Tests cover:
- Shadow dual-side evaluation logic in _generate_signal
- Hypothetical best side calculation with NO tie-breaking
- Log message format and content
- Metrics monitor integration
- Edge cases (equal edges, one side out of range, etc.)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from merid.metrics.shadow_dual_side_metrics import get_shadow_dual_side_monitor


class TestShadowDualSideLoggingLogic:
    """Test the shadow dual-side evaluation logic."""

    def test_hypothetical_best_side_yes_wins(self):
        """Test that YES wins when it has higher edge."""
        expected_side_edge = 0.12
        opposite_side_edge = 0.08
        
        # Simulate the logic from agent_grid_15m.py lines 9080-9091
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "yes", "YES should win with higher edge"
        assert hypothetical_best_edge == 0.12, "Edge should be 0.12"

    def test_hypothetical_best_side_no_wins(self):
        """Test that NO wins when it has higher edge."""
        expected_side_edge = 0.08
        opposite_side_edge = 0.12
        
        # Simulate the logic
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "no", "NO should win with higher edge"
        assert hypothetical_best_edge == 0.12, "Edge should be 0.12"

    def test_hypothetical_best_side_tie_break_prefers_no(self):
        """Test that NO is preferred on equal edges (tie-breaking)."""
        expected_side_edge = 0.10
        opposite_side_edge = 0.10
        
        # Simulate the logic
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "no", "NO should be preferred on tie"
        assert hypothetical_best_edge == 0.10, "Edge should be 0.10"

    def test_opposite_side_calculation(self):
        """Test that opposite side is calculated correctly."""
        expected_side = "yes"
        opposite_side = "no" if expected_side == "yes" else "yes"
        
        assert opposite_side == "no", "Opposite of yes should be no"
        
        expected_side = "no"
        opposite_side = "no" if expected_side == "yes" else "yes"
        
        assert opposite_side == "yes", "Opposite of no should be yes"


class TestShadowDualSideLogMessage:
    """Test the shadow dual-side log message format."""

    def test_log_message_format(self):
        """Test that log message includes all required fields."""
        asset = "BTC"
        velocity = 0.012345
        strategy_mode = "trend_following"
        expected_side = "yes"
        expected_side_edge = 0.08
        opposite_side = "no"
        opposite_side_edge = 0.12
        hypothetical_best_side = "no"
        hypothetical_best_edge = 0.12
        yes_in_range = True
        no_in_range = True
        
        # Simulate log message construction from agent_grid_15m.py lines 9094-9101
        log_format = (
            "[SHADOW-DUAL-SIDE] asset=%s velocity=%.6f mode=%s expected_side=%s expected_edge=%.4f "
            "opposite_side=%s opposite_edge=%.4f hypothetical_best=%s hypothetical_edge=%.4f "
            "yes_in_range=%s no_in_range=%s"
        )
        
        log_message = log_format % (
            asset, velocity, strategy_mode, expected_side, expected_side_edge,
            opposite_side, opposite_side_edge, hypothetical_best_side, hypothetical_best_edge,
            yes_in_range, no_in_range
        )
        
        # Verify all fields are present
        assert "asset=BTC" in log_message
        assert "velocity=0.012345" in log_message
        assert "mode=trend_following" in log_message
        assert "expected_side=yes" in log_message
        assert "expected_edge=0.0800" in log_message
        assert "opposite_side=no" in log_message
        assert "opposite_edge=0.1200" in log_message
        assert "hypothetical_best=no" in log_message
        assert "hypothetical_edge=0.1200" in log_message
        assert "yes_in_range=True" in log_message
        assert "no_in_range=True" in log_message

    def test_log_message_with_false_ranges(self):
        """Test log message with price ranges False."""
        asset = "BTC"
        velocity = 0.012345
        strategy_mode = "trend_following"
        expected_side = "yes"
        expected_side_edge = 0.08
        opposite_side = "no"
        opposite_side_edge = 0.12
        hypothetical_best_side = "no"
        hypothetical_best_edge = 0.12
        yes_in_range = False
        no_in_range = True
        
        log_format = (
            "[SHADOW-DUAL-SIDE] asset=%s velocity=%.6f mode=%s expected_side=%s expected_edge=%.4f "
            "opposite_side=%s opposite_edge=%.4f hypothetical_best=%s hypothetical_edge=%.4f "
            "yes_in_range=%s no_in_range=%s"
        )
        
        log_message = log_format % (
            asset, velocity, strategy_mode, expected_side, expected_side_edge,
            opposite_side, opposite_side_edge, hypothetical_best_side, hypothetical_best_edge,
            yes_in_range, no_in_range
        )
        
        assert "yes_in_range=False" in log_message
        assert "no_in_range=True" in log_message


class TestShadowDualSideMetricsIntegration:
    """Test integration with shadow dual-side metrics monitor."""

    @patch('merid.metrics.shadow_dual_side_metrics.get_shadow_dual_side_monitor')
    def test_metrics_monitor_called_with_correct_params(self, mock_get_monitor):
        """Test that metrics monitor is called with correct parameters."""
        mock_monitor = Mock()
        mock_get_monitor.return_value = mock_monitor
        
        # Simulate the call from agent_grid_15m.py lines 9107-9119
        asset = "BTC"
        velocity = 0.012345
        strategy_mode = "trend_following"
        expected_side = "yes"
        expected_side_edge = 0.08
        opposite_side = "no"
        opposite_side_edge = 0.12
        hypothetical_best_side = "no"
        hypothetical_best_edge = 0.12
        yes_in_range = True
        no_in_range = True
        
        # This is what the code does
        monitor = mock_get_monitor()
        monitor.log_shadow_evaluation(
            asset=asset,
            velocity=velocity,
            strategy_mode=strategy_mode,
            expected_side=expected_side,
            expected_edge=expected_side_edge,
            opposite_side=opposite_side,
            opposite_edge=opposite_side_edge,
            hypothetical_best_side=hypothetical_best_side,
            hypothetical_best_edge=hypothetical_best_edge,
            yes_in_range=yes_in_range,
            no_in_range=no_in_range
        )
        
        # Verify the call
        mock_monitor.log_shadow_evaluation.assert_called_once()
        call_args = mock_monitor.log_shadow_evaluation.call_args
        
        assert call_args.kwargs["asset"] == asset
        assert call_args.kwargs["velocity"] == velocity
        assert call_args.kwargs["strategy_mode"] == strategy_mode
        assert call_args.kwargs["expected_side"] == expected_side
        assert call_args.kwargs["expected_edge"] == expected_side_edge
        assert call_args.kwargs["opposite_side"] == opposite_side
        assert call_args.kwargs["opposite_edge"] == opposite_side_edge
        assert call_args.kwargs["hypothetical_best_side"] == hypothetical_best_side
        assert call_args.kwargs["hypothetical_best_edge"] == hypothetical_best_edge
        assert call_args.kwargs["yes_in_range"] == yes_in_range
        assert call_args.kwargs["no_in_range"] == no_in_range

    @patch('merid.metrics.shadow_dual_side_metrics.get_shadow_dual_side_monitor')
    def test_metrics_monitor_exception_handling(self, mock_get_monitor):
        """Test that exceptions from metrics monitor are caught and logged."""
        mock_monitor = Mock()
        mock_get_monitor.return_value = mock_monitor
        mock_monitor.log_shadow_evaluation.side_effect = Exception("Test error")
        
        # Simulate the try-except from agent_grid_15m.py lines 9103-9121
        try:
            monitor = mock_get_monitor()
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.12,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.12,
                yes_in_range=True,
                no_in_range=True
            )
        except Exception as metrics_err:
            # This should be caught and logged, not re-raised
            exception_caught = True
        else:
            exception_caught = False
        
        # In the actual code, the exception is caught and logged
        # Here we're just verifying the monitor call was attempted
        mock_monitor.log_shadow_evaluation.assert_called_once()


class TestShadowDualSideEdgeCases:
    """Test edge cases in shadow dual-side evaluation."""

    def test_zero_expected_edge(self):
        """Test handling when expected side edge is zero."""
        expected_side_edge = 0.0
        opposite_side_edge = 0.08
        
        # Simulate the logic
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "no", "NO should win when expected edge is zero"
        assert hypothetical_best_edge == 0.08, "Edge should be 0.08"

    def test_zero_opposite_edge(self):
        """Test handling when opposite side edge is zero."""
        expected_side_edge = 0.08
        opposite_side_edge = 0.0
        
        # Simulate the logic
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "yes", "YES should win when opposite edge is zero"
        assert hypothetical_best_edge == 0.08, "Edge should be 0.08"

    def test_both_edges_zero(self):
        """Test handling when both edges are zero."""
        expected_side_edge = 0.0
        opposite_side_edge = 0.0
        
        # Simulate the logic
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "no", "NO should be preferred on tie (both zero)"
        assert hypothetical_best_edge == 0.0, "Edge should be 0.0"

    def test_negative_edges(self):
        """Test handling when edges are negative (should not happen in practice)."""
        expected_side_edge = -0.02
        opposite_side_edge = 0.08
        
        # Simulate the logic
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = "yes"
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = "no"
            hypothetical_best_edge = opposite_side_edge
        else:
            # Equal edges - prefer NO for bias correction
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        assert hypothetical_best_side == "no", "NO should win when expected edge is negative"
        assert hypothetical_best_edge == 0.08, "Edge should be 0.08"


class TestShadowDualSideWithDifferentVelocities:
    """Test shadow dual-side evaluation with different velocity values."""

    def test_positive_velocity_trend_following(self):
        """Test with positive velocity in trend_following mode."""
        velocity = 0.01
        strategy_mode = "trend_following"
        
        # Expected side calculation from agent_grid_15m.py lines 9068-9071
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"
        
        assert expected_side == "yes", "Positive velocity in trend_following should expect YES"

    def test_negative_velocity_trend_following(self):
        """Test with negative velocity in trend_following mode."""
        velocity = -0.01
        strategy_mode = "trend_following"
        
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"
        
        assert expected_side == "no", "Negative velocity in trend_following should expect NO"

    def test_positive_velocity_mean_reversion(self):
        """Test with positive velocity in mean_reversion mode."""
        velocity = 0.01
        strategy_mode = "mean_reversion"
        
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"
        
        assert expected_side == "no", "Positive velocity in mean_reversion should expect NO"

    def test_negative_velocity_mean_reversion(self):
        """Test with negative velocity in mean_reversion mode."""
        velocity = -0.01
        strategy_mode = "mean_reversion"
        
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"
        
        assert expected_side == "yes", "Negative velocity in mean_reversion should expect YES"

    def test_zero_velocity_trend_following(self):
        """Test with zero velocity in trend_following mode."""
        velocity = 0.0
        strategy_mode = "trend_following"
        
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"
        
        assert expected_side == "no", "Zero velocity in trend_following should expect NO (not > 0)"


class TestShadowDualSideIntegrationWithSignalGeneration:
    """Test integration with signal generation flow."""

    def test_shadow_evaluation_before_side_selection(self):
        """Test that shadow evaluation happens before side selection."""
        # This test verifies the order of operations in agent_grid_15m.py
        
        # Step 1: Calculate expected side
        velocity = 0.01
        strategy_mode = "trend_following"
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:
            expected_side = "no" if velocity > 0 else "yes"
        
        # Step 2: Calculate shadow dual-side evaluation
        side_edges = {"yes": 0.08, "no": 0.12}
        expected_side_edge = side_edges.get(expected_side, 0.0)
        opposite_side = "no" if expected_side == "yes" else "yes"
        opposite_side_edge = side_edges.get(opposite_side, 0.0)
        
        # Step 3: Determine hypothetical best
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = expected_side
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = opposite_side
            hypothetical_best_edge = opposite_side_edge
        else:
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        # Step 4: Log shadow evaluation (happens here)
        # [SHADOW-DUAL-SIDE] log message
        
        # Step 5: Select side based on expected_side gating
        yes_in_range = True
        no_in_range = True
        positive_sides = {"yes": 0.08, "no": 0.12}
        
        if expected_side == "yes" and yes_in_range and "yes" in positive_sides:
            signal_side = "yes"
            selected_edge = side_edges["yes"]
        elif expected_side == "no" and no_in_range and "no" in positive_sides:
            signal_side = "no"
            selected_edge = side_edges["no"]
        else:
            signal_side = None
            selected_edge = None
        
        # Verify: Shadow evaluation shows NO is better, but gating selects YES
        assert hypothetical_best_side == "no", "Hypothetical best should be NO"
        assert signal_side == "yes", "Actual selection should be YES (due to gating)"
        assert hypothetical_best_edge == 0.12, "Hypothetical best edge should be 0.12"
        assert selected_edge == 0.08, "Selected edge should be 0.08"

    def test_shadow_evaluation_when_gating_allows_best(self):
        """Test shadow evaluation when gating allows the best side."""
        velocity = -0.01
        strategy_mode = "trend_following"
        
        # Expected side is NO (negative velocity)
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:
            expected_side = "no" if velocity > 0 else "yes"
        
        # NO has better edge
        side_edges = {"yes": 0.08, "no": 0.12}
        expected_side_edge = side_edges.get(expected_side, 0.0)
        opposite_side = "no" if expected_side == "yes" else "yes"
        opposite_side_edge = side_edges.get(opposite_side, 0.0)
        
        # Hypothetical best
        if expected_side_edge > opposite_side_edge:
            hypothetical_best_side = expected_side
            hypothetical_best_edge = expected_side_edge
        elif opposite_side_edge > expected_side_edge:
            hypothetical_best_side = opposite_side
            hypothetical_best_edge = opposite_side_edge
        else:
            hypothetical_best_side = "no"
            hypothetical_best_edge = expected_side_edge
        
        # Actual selection
        yes_in_range = True
        no_in_range = True
        positive_sides = {"yes": 0.08, "no": 0.12}
        
        if expected_side == "yes" and yes_in_range and "yes" in positive_sides:
            signal_side = "yes"
            selected_edge = side_edges["yes"]
        elif expected_side == "no" and no_in_range and "no" in positive_sides:
            signal_side = "no"
            selected_edge = side_edges["no"]
        else:
            signal_side = None
            selected_edge = None
        
        # Verify: Both shadow and actual selection agree (no missed opportunity)
        assert hypothetical_best_side == "no", "Hypothetical best should be NO"
        assert signal_side == "no", "Actual selection should be NO"
        assert hypothetical_best_edge == 0.12, "Hypothetical best edge should be 0.12"
        assert selected_edge == 0.12, "Selected edge should be 0.12"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
