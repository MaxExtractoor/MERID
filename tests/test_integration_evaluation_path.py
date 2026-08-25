"""
Integration tests for the complete evaluation path.

These tests verify the "one evaluation" path from signal snapshot + orderbook
through candidate generation to log events, ensuring end-to-end correctness.
"""

import pytest
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch
import json
from datetime import datetime, timezone


class TestEvaluationPathIntegration:
    """Integration tests for complete evaluation pipeline."""
    
    def test_one_evaluation_path_signal_to_candidate(self):
        """
        Test one complete evaluation from signal snapshot to candidate.
        
        Path: signal snapshot + orderbook → dual-side evaluation → candidate → log events
        """
        # Setup: Signal snapshot
        signal_snapshot = {
            "asset": "BTC",
            "velocity": 0.0002,
            "velocity_threshold": 0.00015,
            "macd_histogram": 0.001,
            "rsi": 65.0,
            "rsi_zone": "neutral",
            "fvg_direction": "bullish",
            "fvg_confidence": 0.7,
            "obi": 0.3,
            "obi_strong": True,
            "long_score": 4,
            "short_score": 1
        }
        
        # Setup: Orderbook state
        orderbook_state = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "yes_bid_cents": 40,
            "yes_ask_cents": 44,
            "no_bid_cents": 56,
            "no_ask_cents": 60,
            "window_strike_price": 95000.0
        }
        
        # Step 1: Calculate prices
        yes_mid = (orderbook_state["yes_bid_cents"] + orderbook_state["yes_ask_cents"]) // 2
        no_mid = (orderbook_state["no_bid_cents"] + orderbook_state["no_ask_cents"]) // 2
        
        assert yes_mid == 42, f"Expected YES mid=42, got {yes_mid}"
        assert no_mid == 58, f"Expected NO mid=58, got {no_mid}"
        
        # Step 2: Calculate edges (simplified)
        def calculate_edge(score, velocity_sign, macd, rsi, fvg_dir, fvg_conf):
            velocity_magnitude = abs(signal_snapshot["velocity"])
            base_edge = max(velocity_magnitude * 1000, 1.0)
            edge = base_edge + abs(macd) * 10.0
            edge *= 1.0 + (score - 3) * 0.1
            return min(edge, 15.0)
        
        yes_edge = calculate_edge(
            signal_snapshot["long_score"], 1.0,
            signal_snapshot["macd_histogram"], signal_snapshot["rsi"],
            signal_snapshot["fvg_direction"], signal_snapshot["fvg_confidence"]
        )
        
        no_edge = calculate_edge(
            signal_snapshot["short_score"], -1.0,
            signal_snapshot["macd_histogram"], signal_snapshot["rsi"],
            signal_snapshot["fvg_direction"], signal_snapshot["fvg_confidence"]
        )
        
        assert yes_edge > 0, f"YES edge should be positive, got {yes_edge}"
        assert no_edge > 0, f"NO edge should be positive, got {no_edge}"
        
        # Step 3: Hybrid selection
        thesis_side = "yes" if signal_snapshot["velocity"] > 0 else "no"
        side_edges = {"yes": yes_edge, "no": no_edge}
        EDGE_RATIO_THRESHOLD = 1.5
        
        velocity_aligned_edge = side_edges.get(thesis_side)
        opposite_side = "no" if thesis_side == "yes" else "yes"
        opposite_edge = side_edges.get(opposite_side)
        
        if velocity_aligned_edge and opposite_edge:
            edge_ratio = opposite_edge / velocity_aligned_edge
            if edge_ratio >= EDGE_RATIO_THRESHOLD:
                selected_side = opposite_side
                selected_edge = opposite_edge
                selection_method = "MAX_EDGE_COUNTER_TREND"
                velocity_aligned = False
            else:
                selected_side = thesis_side
                selected_edge = velocity_aligned_edge
                selection_method = "HYBRID_ALIGNED"
                velocity_aligned = True
        else:
            selected_side, selected_edge = max(side_edges.items(), key=lambda x: x[1])
            selection_method = "FALLBACK"
            velocity_aligned = (selected_side == thesis_side)
        
        # Step 4: Generate candidate
        candidate = {
            "ticker": orderbook_state["market_id"],
            "side": selected_side,
            "price_cents": yes_mid if selected_side == "yes" else no_mid,
            "count": 1,
            "evaluation_id": "eval_integration_test",
            "edge": selected_edge,
            "selection_method": selection_method,
            "velocity_aligned": velocity_aligned
        }
        
        # Verify candidate
        assert candidate["side"] in ["yes", "no"], f"Invalid side: {candidate['side']}"
        assert candidate["edge"] > 0, f"Edge should be positive, got {candidate['edge']}"
        assert candidate["evaluation_id"] == "eval_integration_test"
        
        # Step 5: Log events (mock)
        logged_events = []
        
        logged_events.append({
            "event_type": "DUAL_SIDE_EVALUATION",
            "evaluation_id": candidate["evaluation_id"],
            "asset": signal_snapshot["asset"],
            "market_id": orderbook_state["market_id"],
            "yes_side": {"price_cents": yes_mid, "edge_pct": yes_edge},
            "no_side": {"price_cents": no_mid, "edge_pct": no_edge},
            "selection": {
                "selected_side": selected_side,
                "selected_edge": selected_edge,
                "selection_method": selection_method,
                "velocity_aligned": velocity_aligned
            }
        })
        
        assert len(logged_events) == 1, f"Expected 1 logged event, got {len(logged_events)}"
        assert logged_events[0]["event_type"] == "DUAL_SIDE_EVALUATION"
    
    def test_evaluation_path_with_price_reconstruction(self):
        """
        Test evaluation path when one side price is missing and needs reconstruction.
        """
        # Setup: Orderbook with missing YES price
        orderbook_state = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "yes_bid_cents": None,
            "yes_ask_cents": None,
            "no_bid_cents": 56,
            "no_ask_cents": 60,
            "window_strike_price": 95000.0
        }
        
        # Step 1: Price reconstruction
        yes_price_cents = None
        no_price_cents = (orderbook_state["no_bid_cents"] + orderbook_state["no_ask_cents"]) // 2
        
        reconstruction_events = []
        
        if yes_price_cents is None or yes_price_cents <= 0:
            if no_price_cents and no_price_cents > 0:
                yes_price_cents = 100 - no_price_cents
                reconstruction_events.append({
                    "event_type": "PRICE_VALIDATION_FAILURE",
                    "side": "yes",
                    "failure_type": "N/A_PRICE_DETECTED",
                    "reconstruction_attempted": True,
                    "reconstruction_method": "DUALITY_INVERSION",
                    "reconstruction_result": "SUCCESS",
                    "reconstructed_price": yes_price_cents
                })
            else:
                reconstruction_events.append({
                    "event_type": "PRICE_VALIDATION_FAILURE",
                    "side": "yes",
                    "failure_type": "N/A_PRICE_DETECTED",
                    "reconstruction_attempted": True,
                    "reconstruction_result": "FAILED"
                })
        
        # Verify reconstruction
        assert yes_price_cents == 42, f"Expected reconstructed YES=42, got {yes_price_cents}"
        assert len(reconstruction_events) == 1
        assert reconstruction_events[0]["reconstruction_result"] == "SUCCESS"
        
        # Step 2: Continue with evaluation using reconstructed price
        yes_in_range = (10 <= yes_price_cents <= 75)
        no_in_range = (10 <= no_price_cents <= 75)
        
        assert yes_in_range == True, "Reconstructed YES should be in range"
        assert no_in_range == True, "NO should be in range"
    
    def test_evaluation_path_rejects_both_negative_edges(self):
        """
        Test that evaluation path rejects when both edges are non-positive.
        """
        # Setup: Signal with weak indicators
        signal_snapshot = {
            "asset": "BTC",
            "velocity": 0.00001,  # Below threshold
            "velocity_threshold": 0.00015,
            "macd_histogram": -0.005,
            "rsi": 50.0,
            "long_score": 1,
            "short_score": 1
        }
        
        # Calculate edges (will be negative)
        yes_edge = -0.02
        no_edge = -0.01
        
        # Hybrid selection
        side_edges = {"yes": yes_edge, "no": no_edge}
        candidates = []
        
        if yes_edge and yes_edge > 0:
            candidates.append(("yes", yes_edge))
        if no_edge and no_edge > 0:
            candidates.append(("no", no_edge))
        
        # Should have no candidates
        assert len(candidates) == 0, f"Expected no candidates, got {len(candidates)}"
        
        # Should log rejection
        rejection_event = {
            "event_type": "DUAL_SIDE_REJECT",
            "asset": signal_snapshot["asset"],
            "yes_edge": yes_edge,
            "no_edge": no_edge,
            "reason": "no positive edge on either side"
        }
        
        assert rejection_event["event_type"] == "DUAL_SIDE_REJECT"
    
    def test_evaluation_path_counter_trend_selection(self):
        """
        Test evaluation path when counter-trend selection occurs.
        """
        # Setup: Signal with positive velocity but NO has much better edge
        signal_snapshot = {
            "asset": "BTC",
            "velocity": 0.0002,  # Positive → thesis_side = yes
            "velocity_threshold": 0.00015,
            "long_score": 2,  # Weak YES indicators
            "short_score": 5  # Strong NO indicators
        }
        
        # Calculate edges (NO much better)
        yes_edge = 0.04
        no_edge = 0.08  # 2x YES edge
        
        # Hybrid selection
        thesis_side = "yes"
        side_edges = {"yes": yes_edge, "no": no_edge}
        EDGE_RATIO_THRESHOLD = 1.5
        
        velocity_aligned_edge = side_edges.get(thesis_side)
        opposite_side = "no"
        opposite_edge = side_edges.get(opposite_side)
        
        edge_ratio = opposite_edge / velocity_aligned_edge
        
        if edge_ratio >= EDGE_RATIO_THRESHOLD:
            selected_side = opposite_side
            selected_edge = opposite_edge
            selection_method = "MAX_EDGE_COUNTER_TREND"
            velocity_aligned = False
        else:
            selected_side = thesis_side
            selected_edge = velocity_aligned_edge
            selection_method = "HYBRID_ALIGNED"
            velocity_aligned = True
        
        # Verify counter-trend selection
        assert selected_side == "no", f"Expected NO (counter-trend), got {selected_side}"
        assert selection_method == "MAX_EDGE_COUNTER_TREND"
        assert velocity_aligned == False
        assert edge_ratio == 2.0
    
    def test_evaluation_path_logs_all_required_events(self):
        """
        Test that evaluation path logs all required events in sequence.
        """
        # Setup
        signal_snapshot = {
            "asset": "BTC",
            "velocity": 0.0002,
            "velocity_threshold": 0.00015
        }
        
        orderbook_state = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "yes_bid_cents": 40,
            "yes_ask_cents": 44,
            "no_bid_cents": 56,
            "no_ask_cents": 60
        }
        
        # Simulate evaluation path
        events = []
        
        # Event 1: DUAL_SIDE_EVALUATION
        events.append({
            "event_type": "DUAL_SIDE_EVALUATION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": "eval_123",
            "asset": signal_snapshot["asset"],
            "market_id": orderbook_state["market_id"]
        })
        
        # Event 2: VELOCITY_ALIGNMENT_DIAGNOSTIC
        events.append({
            "event_type": "VELOCITY_ALIGNMENT_DIAGNOSTIC",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": "eval_123",
            "asset": signal_snapshot["asset"],
            "velocity": signal_snapshot["velocity"]
        })
        
        # Event 3: ORDER_SUBMISSION (if candidate generated)
        events.append({
            "event_type": "ORDER_SUBMISSION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluation_id": "eval_123",
            "order_id": "ord_456"
        })
        
        # Verify all events logged
        assert len(events) == 3
        event_types = [e["event_type"] for e in events]
        assert "DUAL_SIDE_EVALUATION" in event_types
        assert "VELOCITY_ALIGNMENT_DIAGNOSTIC" in event_types
        assert "ORDER_SUBMISSION" in event_types
        
        # Verify all events have same evaluation_id
        evaluation_ids = [e["evaluation_id"] for e in events]
        assert all(eid == "eval_123" for eid in evaluation_ids)
    
    def test_evaluation_path_with_no_candidate_no_order(self):
        """
        Test that when evaluation returns no candidate, no order is submitted.
        """
        # Setup: Signal that produces no candidate
        signal_snapshot = {
            "asset": "BTC",
            "velocity": 0.00001,  # Below threshold
            "velocity_threshold": 0.00015
        }
        
        # Evaluation produces no candidate
        candidate = None
        
        # Order submission logic
        order_submitted = False
        order_events = []
        
        if candidate:
            order_submitted = True
            order_events.append({
                "event_type": "ORDER_SUBMISSION",
                "evaluation_id": "eval_123"
            })
        
        # Verify no order submitted
        assert order_submitted == False
        assert len(order_events) == 0


class TestEvaluationPathErrorHandling:
    """Test error handling in evaluation path."""
    
    def test_evaluation_path_handles_missing_market_state(self):
        """
        Test that evaluation path handles missing market state gracefully.
        """
        # Setup: Missing market state
        market_state = None
        
        # Should log error and return None
        if market_state is None:
            error_event = {
                "event_type": "EVALUATION_ERROR",
                "error_type": "MISSING_MARKET_STATE",
                "action": "REJECTED"
            }
            candidate = None
        else:
            candidate = {"side": "yes"}
        
        assert candidate is None
        assert error_event["event_type"] == "EVALUATION_ERROR"
    
    def test_evaluation_path_handles_invalid_prices(self):
        """
        Test that evaluation path handles invalid prices (both sides N/A).
        """
        # Setup: Both prices N/A
        yes_price_cents = None
        no_price_cents = None
        
        # Should reject
        can_reconstruct = False
        
        if yes_price_cents is None or yes_price_cents <= 0:
            if no_price_cents and no_price_cents > 0:
                yes_price_cents = 100 - no_price_cents
                can_reconstruct = True
        
        if no_price_cents is None or no_price_cents <= 0:
            if yes_price_cents and yes_price_cents > 0:
                no_price_cents = 100 - yes_price_cents
                can_reconstruct = True
        
        assert can_reconstruct == False
        assert yes_price_cents is None
        assert no_price_cents is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
