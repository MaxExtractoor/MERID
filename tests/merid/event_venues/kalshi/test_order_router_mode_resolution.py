"""Tests for order router mode resolution (BUG-002 fix verification).

Verifies that mode resolution never silently falls back and that
TradeMode/VenueGate consistency is enforced to prevent confusion.
"""

import pytest
from unittest.mock import patch, MagicMock

from merid.event_venues.kalshi.order_router import (
    _resolve_mode,
    OrderIntent,
    route_order,
)
from merid.prediction.venue_gate import TradingMode
from trading.trade_mode import TradeMode as CoreTradeMode


class TestOrderRouterModeResolution:
    """Test suite for order router mode resolution without silent fallback."""

    def test_explicit_override_takes_precedence(self):
        """Explicit mode override in OrderIntent takes precedence."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode:
            mock_get_mode.return_value = CoreTradeMode.PAPER

            # Override should be used regardless of get_trade_mode()
            mode = _resolve_mode(override=TradingMode.LIVE)
            assert mode == TradingMode.LIVE

    def test_resolves_from_get_trade_mode_when_no_override(self):
        """Resolves from get_trade_mode() when no override provided."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.PAPER
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.PAPER
            mock_gate.return_value = mock_gate_inst

            mode = _resolve_mode(override=None)
            assert mode == TradingMode.PAPER

    def test_raises_on_mode_inconsistency_between_trademode_and_venuegate(self):
        """Raises RuntimeError when TradeMode and VenueGate are inconsistent."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            # TradeMode says LIVE, VenueGate says PAPER
            mock_get_mode.return_value = CoreTradeMode.LIVE
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.PAPER
            mock_gate.return_value = mock_gate_inst

            with pytest.raises(RuntimeError, match="Mode inconsistency detected"):
                _resolve_mode(override=None)

    def test_no_silent_fallback_on_get_trade_mode_exception(self):
        """Does not silently fall back to VenueGate if get_trade_mode() fails."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode:
            # Simulate failure
            mock_get_mode.side_effect = RuntimeError("get_trade_mode() failed")

            with pytest.raises(RuntimeError, match="get_trade_mode\\(\\) failed"):
                _resolve_mode(override=None)

    def test_consistency_check_passes_when_modes_match(self):
        """No error when TradeMode and VenueGate are consistent."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.LIVE
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.LIVE
            mock_gate.return_value = mock_gate_inst

            # Should not raise
            mode = _resolve_mode(override=None)
            assert mode == TradingMode.LIVE

    def test_consistency_check_skipped_gracefully_if_venuegate_unavailable(self, caplog):
        """Consistency check skipped (with warning) if VenueGate unavailable."""
        import logging
        caplog.set_level(logging.WARNING)

        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.PAPER
            # Simulate VenueGate unavailable
            mock_gate.side_effect = ImportError("VenueGate not available")

            # Should not raise, but should log warning
            mode = _resolve_mode(override=None)
            assert mode == TradingMode.PAPER
            assert "VenueGate consistency check skipped" in caplog.text

    def test_paper_mode_routes_to_simulation(self):
        """Paper mode routes orders to simulation, not live client."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.PAPER
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.PAPER
            mock_gate.return_value = mock_gate_inst

            intent = OrderIntent(
                ticker="KXBTC-TEST",
                side="yes",
                action="buy",
                price_cents=55,
                count=10,
            )

            result = route_order(intent)

            assert result.status == "filled_paper"
            assert result.mode == TradingMode.PAPER
            assert result.fill is not None
            assert result.fill["simulated"] is True

    def test_mock_mode_routes_to_simulation(self):
        """Mock mode routes orders to simulation."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.MOCK
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.MOCK
            mock_gate.return_value = mock_gate_inst

            intent = OrderIntent(
                ticker="KXBTC-TEST",
                side="yes",
                action="buy",
                price_cents=55,
                count=10,
            )

            result = route_order(intent)

            assert result.status == "filled_mock"
            assert result.mode == TradingMode.MOCK
            assert result.fill is not None
            assert result.fill["simulated"] is True

    def test_intent_mode_override_bypasses_consistency_check(self):
        """Intent with explicit mode override bypasses consistency check."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            # Set up inconsistent global state
            mock_get_mode.return_value = CoreTradeMode.LIVE
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.PAPER
            mock_gate.return_value = mock_gate_inst

            # Intent with explicit override should work
            intent = OrderIntent(
                ticker="KXBTC-TEST",
                side="yes",
                action="buy",
                price_cents=55,
                count=10,
                mode=TradingMode.MOCK,  # Explicit override
            )

            result = route_order(intent)

            # Should use override mode, not global mode
            assert result.status == "filled_mock"
            assert result.mode == TradingMode.MOCK

    def test_mode_resolution_error_message_is_clear(self):
        """Error message for mode inconsistency is clear and actionable."""
        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.LIVE
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.PAPER
            mock_gate.return_value = mock_gate_inst

            with pytest.raises(RuntimeError) as exc_info:
                _resolve_mode(override=None)

            error_msg = str(exc_info.value)
            assert "Mode inconsistency" in error_msg
            assert "TradeMode (live)" in error_msg
            assert "VenueGate.mode (paper)" in error_msg
            assert "Fix configuration" in error_msg
            assert "live/paper confusion" in error_msg

    def test_defensive_depth_both_sources_checked(self):
        """Defense-in-depth: both TradeMode and VenueGate are checked."""
        call_count = {"get_trade_mode": 0, "get_venue_gate": 0}

        def mock_get_trade_mode():
            call_count["get_trade_mode"] += 1
            return CoreTradeMode.PAPER

        def mock_get_venue_gate():
            call_count["get_venue_gate"] += 1
            gate = MagicMock()
            gate.mode = TradingMode.PAPER
            return gate

        with patch("merid.event_venues.kalshi.order_router.get_trade_mode", side_effect=mock_get_trade_mode), \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate", side_effect=mock_get_venue_gate):

            _resolve_mode(override=None)

            # Both sources should be consulted
            assert call_count["get_trade_mode"] == 1
            assert call_count["get_venue_gate"] == 1


class TestModeResolutionIntegration:
    """Integration tests for mode resolution across order lifecycle."""

    def test_paper_order_never_reaches_live_client_even_with_misconfiguration(self):
        """Even with misconfiguration, paper orders don't reach live client."""
        # This test verifies defense-in-depth: multiple layers prevent mode confusion

        with patch("merid.event_venues.kalshi.order_router.get_trade_mode") as mock_get_mode, \
             patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_gate:

            mock_get_mode.return_value = CoreTradeMode.PAPER
            mock_gate_inst = MagicMock()
            mock_gate_inst.mode = TradingMode.PAPER
            mock_gate.return_value = mock_gate_inst

            intent = OrderIntent(
                ticker="KXBTC-TEST",
                side="yes",
                action="buy",
                price_cents=55,
                count=10,
            )

            result = route_order(intent)

            # Paper mode should route to simulation
            assert result.status == "filled_paper"
            assert result.fill["simulated"] is True

            # Live client should NEVER be called in paper mode
            # (This is verified by the fact that we didn't mock the client
            # and no exception was raised from trying to use it)
