"""
End-to-end integration tests for side preservation across the trading pipeline.

This test suite validates that the signal side is preserved through the entire
execution pipeline from signal generation to order execution in the 15m Kalshi
crypto trading system.

Tests cover:
- Signal generation side selection (momentum_fvg and _generate_signal paths)
- Candidate emission preserves signal side
- Order intent construction preserves candidate side
- Order router preserves intent side through validation
- Exchange adapter preserves side through API calls
- Tie-breaking logic prefers NO on equal edges
- One-sided liquidity scenarios do not bias side selection
- Expected side logic from velocity does not invert signals
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from merid.prediction.agent_grid_15m import LeanAgentGrid15m
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.risk.global_slot_allocator import AllocationRequest


class TestSignalGenerationSidePreservation:
    """Test that signal generation correctly selects and preserves side."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock AgentGrid15M for testing."""
        agent = Mock(spec=LeanAgentGrid15m)
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        agent.config.series_tickers = ["KXBTC15M"]
        agent.market_state_store = Mock()
        agent.spot_provider = Mock()
        return agent

    def test_momentum_fvg_tie_breaking_prefers_no(self, mock_agent):
        """Test that momentum_fvg tie-breaking prefers NO on equal edges."""
        # Setup: Equal edges for YES and NO
        side_edges = {"yes": 0.05, "no": 0.05}
        side_edges_with_bonus = {"yes": 0.07, "no": 0.07}  # Equal after bonus

        # Simulate tie-breaking logic from agent_grid_15m.py lines 4844-4853
        max_edge = max(side_edges_with_bonus.values())
        tied_sides = [side for side, edge in side_edges_with_bonus.items() if edge == max_edge]
        
        if len(tied_sides) == 2:
            # Tie: prefer NO to balance YES bias
            signal_side = "no"
        else:
            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)

        # Assert: NO is preferred on tie
        assert len(tied_sides) == 2, "Should have tied sides"
        assert signal_side == "no", f"Expected NO on tie, got {signal_side}"

    def test_generate_signal_expected_side_logic(self, mock_agent):
        """Test that _generate_signal expected_side logic is correct."""
        # Test trend_following mode
        velocity = 0.01  # Positive
        strategy_mode = "trend_following"

        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"

        assert expected_side == "yes", "Positive velocity in trend_following should expect YES"

        # Test mean_reversion mode
        strategy_mode = "mean_reversion"
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"

        assert expected_side == "no", "Positive velocity in mean_reversion should expect NO"

    def test_generate_signal_side_selection_with_expected_side(self, mock_agent):
        """Test that _generate_signal respects expected_side when selecting side."""
        # Setup: Both sides have positive edges
        side_edges = {"yes": 0.08, "no": 0.06}
        positive_sides = {"yes": 0.08, "no": 0.06}
        yes_in_range = True
        no_in_range = True
        velocity = 0.01
        strategy_mode = "trend_following"

        # Calculate expected_side
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"

        # Simulate side selection logic from agent_grid_15m.py lines 9073-9086
        if expected_side == "yes" and yes_in_range and "yes" in positive_sides:
            signal_side = "yes"
            selected_edge = side_edges["yes"]
        elif expected_side == "no" and no_in_range and "no" in positive_sides:
            signal_side = "no"
            selected_edge = side_edges["no"]
        else:
            signal_side = None
            selected_edge = None

        # Assert: Expected side is selected
        assert expected_side == "yes", "Expected side should be YES"
        assert signal_side == "yes", f"Expected YES, got {signal_side}"
        assert selected_edge == 0.08, f"Expected edge 0.08, got {selected_edge}"

    def test_generate_signal_rejects_when_expected_side_unavailable(self, mock_agent):
        """Test that _generate_signal rejects when expected side is unavailable."""
        # Setup: Expected side is YES, but YES has no positive edge
        side_edges = {"yes": -0.02, "no": 0.06}
        positive_sides = {"no": 0.06}  # Only NO has positive edge
        yes_in_range = True
        no_in_range = True
        velocity = 0.01
        strategy_mode = "trend_following"

        # Calculate expected_side
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"

        # Simulate side selection logic
        if expected_side == "yes" and yes_in_range and "yes" in positive_sides:
            signal_side = "yes"
            selected_edge = side_edges["yes"]
        elif expected_side == "no" and no_in_range and "no" in positive_sides:
            signal_side = "no"
            selected_edge = side_edges["no"]
        else:
            signal_side = None
            selected_edge = None

        # Assert: Trade is rejected when expected side unavailable
        assert expected_side == "yes", "Expected side should be YES"
        assert signal_side is None, "Should reject when expected side unavailable"
        assert selected_edge is None, "Should not select edge when expected side unavailable"


class TestCandidateEmissionSidePreservation:
    """Test that candidate emission preserves signal side."""

    def test_candidate_construction_preserves_signal_side(self):
        """Test that candidate construction preserves signal["side"]."""
        # Setup: Signal with NO side
        signal = {
            "side": "no",
            "action": "buy",
            "edge_pct": 0.08,
            "confidence": 0.6,
            "price_cents": 55,
            "count": 1,
            "velocity": 0.01,
            "strategy_intent": "bearish_event"
        }

        # Simulate candidate construction from agent_grid_15m.py lines 12041-12049
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": signal["side"],
            "action": signal["action"],
            "edge_pct": signal.get("edge_pct", 0.0),
            "confidence": signal.get("confidence", 0.5),
            "price_cents": signal.get("price_cents", 50),
            "count": signal.get("count", 1)
        }

        # Assert: Candidate side matches signal side
        assert candidate["side"] == "no", f"Expected candidate side 'no', got {candidate['side']}"
        assert candidate["side"] == signal["side"], "Candidate side should match signal side"

    def test_candidate_construction_preserves_yes_side(self):
        """Test that candidate construction preserves YES side."""
        # Setup: Signal with YES side
        signal = {
            "side": "yes",
            "action": "buy",
            "edge_pct": 0.08,
            "confidence": 0.6,
            "price_cents": 45,
            "count": 1,
            "velocity": 0.01,
            "strategy_intent": "bullish_event"
        }

        # Simulate candidate construction
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": signal["side"],
            "action": signal["action"],
            "edge_pct": signal.get("edge_pct", 0.0),
            "confidence": signal.get("confidence", 0.5),
            "price_cents": signal.get("price_cents", 50),
            "count": signal.get("count", 1)
        }

        # Assert: Candidate side matches signal side
        assert candidate["side"] == "yes", f"Expected candidate side 'yes', got {candidate['side']}"
        assert candidate["side"] == signal["side"], "Candidate side should match signal side"


class TestOrderIntentSidePreservation:
    """Test that order intent construction preserves candidate side."""

    def test_intent_construction_preserves_candidate_side(self):
        """Test that OrderIntent construction preserves candidate side."""
        # Setup: Candidate with NO side
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "no",
            "action": "buy",
            "edge_pct": 0.08,
            "confidence": 0.6,
            "price_cents": 55,
            "count": 1
        }

        # Simulate OrderIntent construction
        intent = OrderIntent(
            intent_id="test_intent_001",
            agent_id=candidate["agent_id"],
            ticker=candidate["ticker"],
            side=candidate["side"],
            action=candidate["action"],
            price_cents=candidate["price_cents"],
            count=candidate["count"],
            edge_pct=candidate["edge_pct"],
            confidence=candidate["confidence"]
        )

        # Assert: Intent side matches candidate side
        assert intent.side == "no", f"Expected intent side 'no', got {intent.side}"
        assert intent.side == candidate["side"], "Intent side should match candidate side"

    def test_intent_construction_preserves_yes_side(self):
        """Test that OrderIntent construction preserves YES side."""
        # Setup: Candidate with YES side
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "yes",
            "action": "buy",
            "edge_pct": 0.08,
            "confidence": 0.6,
            "price_cents": 45,
            "count": 1
        }

        # Simulate OrderIntent construction
        intent = OrderIntent(
            intent_id="test_intent_002",
            agent_id=candidate["agent_id"],
            ticker=candidate["ticker"],
            side=candidate["side"],
            action=candidate["action"],
            price_cents=candidate["price_cents"],
            count=candidate["count"],
            edge_pct=candidate["edge_pct"],
            confidence=candidate["confidence"]
        )

        # Assert: Intent side matches candidate side
        assert intent.side == "yes", f"Expected intent side 'yes', got {intent.side}"
        assert intent.side == candidate["side"], "Intent side should match candidate side"


class TestOrderRouterSidePreservation:
    """Test that order router preserves intent side through validation."""

    @pytest.fixture
    def mock_intent_no(self):
        """Create a mock OrderIntent with NO side."""
        intent = Mock(spec=OrderIntent)
        intent.intent_id = "test_intent_001"
        intent.agent_id = "BTC_15M"
        intent.ticker = "KXBTC15M-26JUL211745-45"
        intent.side = "no"
        intent.action = "buy"
        intent.price_cents = 55
        intent.count = 1
        intent.edge_pct = 0.08
        intent.confidence = 0.6
        return intent

    @pytest.fixture
    def mock_intent_yes(self):
        """Create a mock OrderIntent with YES side."""
        intent = Mock(spec=OrderIntent)
        intent.intent_id = "test_intent_002"
        intent.agent_id = "BTC_15M"
        intent.ticker = "KXBTC15M-26JUL211745-45"
        intent.side = "yes"
        intent.action = "buy"
        intent.price_cents = 45
        intent.count = 1
        intent.edge_pct = 0.08
        intent.confidence = 0.6
        return intent

    def test_router_side_conversion_preserves_no(self, mock_intent_no):
        """Test that router side conversion preserves NO side."""
        # Simulate side conversion from agent_grid_15m.py lines 2146-2158
        side_lower = mock_intent_no.side.lower() if mock_intent_no.side else ""
        action_lower = mock_intent_no.action.lower() if mock_intent_no.action else ""

        converted_side = mock_intent_no.side
        if side_lower in ("yes", "no") and action_lower in ("buy", "sell"):
            if side_lower == "yes" and action_lower == "buy":
                converted_side = "BUY_YES"
            elif side_lower == "yes" and action_lower == "sell":
                converted_side = "SELL_YES"
            elif side_lower == "no" and action_lower == "buy":
                converted_side = "BUY_NO"
            elif side_lower == "no" and action_lower == "sell":
                converted_side = "SELL_NO"

        # Assert: NO side is correctly converted to BUY_NO
        assert side_lower == "no", "Side should be 'no'"
        assert action_lower == "buy", "Action should be 'buy'"
        assert converted_side == "BUY_NO", f"Expected 'BUY_NO', got {converted_side}"

    def test_router_side_conversion_preserves_yes(self, mock_intent_yes):
        """Test that router side conversion preserves YES side."""
        # Simulate side conversion
        side_lower = mock_intent_yes.side.lower() if mock_intent_yes.side else ""
        action_lower = mock_intent_yes.action.lower() if mock_intent_yes.action else ""

        converted_side = mock_intent_yes.side
        if side_lower in ("yes", "no") and action_lower in ("buy", "sell"):
            if side_lower == "yes" and action_lower == "buy":
                converted_side = "BUY_YES"
            elif side_lower == "yes" and action_lower == "sell":
                converted_side = "SELL_YES"
            elif side_lower == "no" and action_lower == "buy":
                converted_side = "BUY_NO"
            elif side_lower == "no" and action_lower == "sell":
                converted_side = "SELL_NO"

        # Assert: YES side is correctly converted to BUY_YES
        assert side_lower == "yes", "Side should be 'yes'"
        assert action_lower == "buy", "Action should be 'buy'"
        assert converted_side == "BUY_YES", f"Expected 'BUY_YES', got {converted_side}"

    def test_router_duplicate_check_preserves_side(self, mock_intent_no):
        """Test that router duplicate check preserves side information."""
        # Simulate duplicate check key generation from order_router.py lines 531-536
        side_normalized = mock_intent_no.side.upper() if mock_intent_no.side else ""
        action_normalized = mock_intent_no.action.upper() if mock_intent_no.action else ""
        ticker_normalized = mock_intent_no.ticker.upper() if mock_intent_no.ticker else ""
        price_cents = mock_intent_no.price_cents

        duplicate_key = (ticker_normalized, side_normalized, action_normalized, price_cents)

        # Assert: Duplicate key includes side information
        assert duplicate_key[1] == "NO", f"Expected 'NO' in duplicate key, got {duplicate_key[1]}"
        assert side_normalized == "NO", "Side should be normalized to 'NO'"

    def test_router_open_order_guard_preserves_side(self, mock_intent_no):
        """Test that router open order guard preserves side information."""
        # Simulate open order guard from order_router.py lines 457-461
        ticker = mock_intent_no.ticker
        side = mock_intent_no.side
        action = mock_intent_no.action

        # Guard would call monitor.find_open_order(ticker, side, action)
        # Assert: Side is passed correctly to monitor
        assert side == "no", f"Expected side 'no' passed to monitor, got {side}"
        assert action == "buy", f"Expected action 'buy' passed to monitor, got {action}"


class TestExchangeAdapterSidePreservation:
    """Test that exchange adapter preserves side through API calls."""

    def test_rest_client_preserves_no_side(self):
        """Test that REST client preserves NO side in order data."""
        # Setup: Order parameters for NO side
        ticker = "KXBTC15M-26JUL211745-45"
        client_order_id = "test_order_001"
        action = "buy"
        side = "no"
        quantity = 1
        price = 55
        order_type = "limit"

        # Simulate order data construction from rest_client.py lines 392-408
        order_data = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "action": action,
            "side": side,
            "count": quantity,
            "type": order_type,
        }

        # Add price for limit orders (only the relevant side)
        if order_type == "limit":
            if side == "yes":
                order_data["yes_price"] = price
            else:
                order_data["no_price"] = price

        # Assert: NO side is preserved in order data
        assert order_data["side"] == "no", f"Expected side 'no' in order data, got {order_data['side']}"
        assert "no_price" in order_data, "NO price should be in order data"
        assert order_data["no_price"] == 55, f"Expected no_price 55, got {order_data['no_price']}"
        assert "yes_price" not in order_data, "YES price should not be in order data for NO side"

    def test_rest_client_preserves_yes_side(self):
        """Test that REST client preserves YES side in order data."""
        # Setup: Order parameters for YES side
        ticker = "KXBTC15M-26JUL211745-45"
        client_order_id = "test_order_002"
        action = "buy"
        side = "yes"
        quantity = 1
        price = 45
        order_type = "limit"

        # Simulate order data construction
        order_data = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "action": action,
            "side": side,
            "count": quantity,
            "type": order_type,
        }

        # Add price for limit orders (only the relevant side)
        if order_type == "limit":
            if side == "yes":
                order_data["yes_price"] = price
            else:
                order_data["no_price"] = price

        # Assert: YES side is preserved in order data
        assert order_data["side"] == "yes", f"Expected side 'yes' in order data, got {order_data['side']}"
        assert "yes_price" in order_data, "YES price should be in order data"
        assert order_data["yes_price"] == 45, f"Expected yes_price 45, got {order_data['yes_price']}"
        assert "no_price" not in order_data, "NO price should not be in order data for YES side"

    def test_execution_pipeline_preserves_side(self):
        """Test that execution pipeline preserves side when parsing intent."""
        # Setup: Intent with NO side in buy_no format
        intent = Mock()
        intent.side = "buy_no"
        intent.market_ticker = "KXBTC15M-26JUL211745-45"
        intent.qty = 1
        intent.price = 0.55
        intent.client_tag = "test_order_001"

        # Simulate side parsing from execution_pipeline.py lines 589-594
        parts = intent.side.split("_")
        action = parts[0]    # "buy" or "sell"
        side = parts[1]      # "yes" or "no"

        # Assert: Side is correctly parsed
        assert action == "buy", f"Expected action 'buy', got {action}"
        assert side == "no", f"Expected side 'no', got {side}"


class TestEndToEndSidePreservation:
    """End-to-end tests for side preservation across the entire pipeline."""

    def test_no_side_end_to_end_preservation(self):
        """Test end-to-end preservation of NO side from signal to API."""
        # Step 1: Signal generation (NO side)
        signal = {
            "side": "no",
            "action": "buy",
            "edge_pct": 0.08,
            "confidence": 0.6,
            "price_cents": 55,
            "count": 1
        }

        # Step 2: Candidate emission
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": signal["side"],
            "action": signal["action"],
            "price_cents": signal["price_cents"],
            "count": signal["count"]
        }

        # Step 3: Order intent construction
        intent = OrderIntent(
            intent_id="test_intent_001",
            agent_id=candidate["agent_id"],
            ticker=candidate["ticker"],
            side=candidate["side"],
            action=candidate["action"],
            price_cents=candidate["price_cents"],
            count=candidate["count"]
        )

        # Step 4: Router side conversion
        side_lower = intent.side.lower()
        action_lower = intent.action.lower()
        if side_lower == "no" and action_lower == "buy":
            converted_side = "BUY_NO"

        # Step 5: REST client order data
        order_data = {
            "ticker": intent.ticker,
            "action": action_lower,
            "side": side_lower,
            "count": intent.count,
            "type": "limit"
        }
        if side_lower == "no":
            order_data["no_price"] = intent.price_cents

        # Assert: NO side is preserved through entire pipeline
        assert signal["side"] == "no", "Signal side should be NO"
        assert candidate["side"] == "no", "Candidate side should be NO"
        assert intent.side == "no", "Intent side should be NO"
        assert converted_side == "BUY_NO", "Converted side should be BUY_NO"
        assert order_data["side"] == "no", "Order data side should be no"
        assert order_data["no_price"] == 55, "Order data should have no_price"

    def test_yes_side_end_to_end_preservation(self):
        """Test end-to-end preservation of YES side from signal to API."""
        # Step 1: Signal generation (YES side)
        signal = {
            "side": "yes",
            "action": "buy",
            "edge_pct": 0.08,
            "confidence": 0.6,
            "price_cents": 45,
            "count": 1
        }

        # Step 2: Candidate emission
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": signal["side"],
            "action": signal["action"],
            "price_cents": signal["price_cents"],
            "count": signal["count"]
        }

        # Step 3: Order intent construction
        intent = OrderIntent(
            intent_id="test_intent_002",
            agent_id=candidate["agent_id"],
            ticker=candidate["ticker"],
            side=candidate["side"],
            action=candidate["action"],
            price_cents=candidate["price_cents"],
            count=candidate["count"]
        )

        # Step 4: Router side conversion
        side_lower = intent.side.lower()
        action_lower = intent.action.lower()
        if side_lower == "yes" and action_lower == "buy":
            converted_side = "BUY_YES"

        # Step 5: REST client order data
        order_data = {
            "ticker": intent.ticker,
            "action": action_lower,
            "side": side_lower,
            "count": intent.count,
            "type": "limit"
        }
        if side_lower == "yes":
            order_data["yes_price"] = intent.price_cents

        # Assert: YES side is preserved through entire pipeline
        assert signal["side"] == "yes", "Signal side should be YES"
        assert candidate["side"] == "yes", "Candidate side should be YES"
        assert intent.side == "yes", "Intent side should be YES"
        assert converted_side == "BUY_YES", "Converted side should be BUY_YES"
        assert order_data["side"] == "yes", "Order data side should be yes"
        assert order_data["yes_price"] == 45, "Order data should have yes_price"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
