"""Tests for PositionMonitor cleanup, exit in-flight state machine, and position key identity."""

import pytest
import time
from decimal import Decimal
from unittest.mock import Mock, patch

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor


@pytest.fixture
def monitor():
    return PositionMonitor(poll_interval=0.1)


def make_position(market_id: str = "KXBTC15M-TEST", size: int = 10, price_cents: int = 50):
    return Position(
        position_id=market_id,
        market_id=market_id,
        series_ticker=market_id.split("-")[0] if "-" in market_id else market_id,
        side=PositionSide.YES,
        size=size,
        avg_entry_price_cents=price_cents,
    )


class TestDecimalCleanup:
    """Cleanup must never raise on Decimal/float type mixing."""

    @patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope')
    def test_remove_position_with_decimal_size(self, mock_get_envelope):
        """Position.size as Decimal must not cause TypeError during notional calc."""
        mock_envelope = Mock()
        mock_get_envelope.return_value = mock_envelope

        pos = make_position(size=10, price_cents=50)
        pos.size = Decimal("1.55")  # defensive: even if size somehow is Decimal
        monitor = PositionMonitor()
        monitor.add_position(pos)

        monitor.remove_position(pos.position_id)

        assert monitor.get_position(pos.position_id) is None
        assert len(monitor.get_open_positions()) == 0
        # Notional is 1.55 * 50 / 100 = 0.775
        call_args = mock_envelope.record_position_closure.call_args
        assert call_args is not None
        _, called_notional = call_args[0]
        assert round(called_notional, 3) == 0.775

    @patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope')
    def test_remove_position_with_decimal_avg_price(self, mock_get_envelope):
        """Position.avg_entry_price_cents as Decimal must not cause TypeError."""
        mock_envelope = Mock()
        mock_get_envelope.return_value = mock_envelope

        pos = make_position(size=10, price_cents=50)
        pos.avg_entry_price_cents = Decimal("50")
        monitor = PositionMonitor()
        monitor.add_position(pos)

        monitor.remove_position(pos.position_id)

        assert monitor.get_position(pos.position_id) is None
        assert len(monitor.get_open_positions()) == 0

    @patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope')
    def test_remove_position_queues_cleanup_on_envelope_failure(self, mock_get_envelope):
        """A capacity-release failure must remove the active position and create a cleanup item."""
        mock_envelope = Mock()
        mock_envelope.record_position_closure.side_effect = RuntimeError("bankroll unavailable")
        mock_get_envelope.return_value = mock_envelope

        pos = make_position()
        monitor = PositionMonitor()
        monitor.add_position(pos)

        monitor.remove_position(pos.position_id)

        assert monitor.get_position(pos.position_id) is None
        assert len(monitor.get_open_positions()) == 0
        pending = monitor.get_cleanup_pending()
        assert len(pending) == 1
        assert pending[0]["market_id"] == pos.market_id

    @patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope')
    def test_retry_cleanup_is_idempotent(self, mock_get_envelope):
        """retry_cleanup must release capacity exactly once and remove the work item."""
        mock_envelope = Mock()
        mock_get_envelope.return_value = mock_envelope

        pos = make_position()
        monitor = PositionMonitor()
        monitor.add_position(pos)

        # Fail first removal, queue cleanup
        mock_envelope.record_position_closure.side_effect = RuntimeError("bankroll unavailable")
        monitor.remove_position(pos.position_id)

        # Succeed on retry
        mock_envelope.record_position_closure.side_effect = None
        successes = monitor.retry_cleanup()

        assert successes == 1
        assert len(monitor.get_cleanup_pending()) == 0
        # One queued item + one retry = two calls total
        assert mock_envelope.record_position_closure.call_count == 2


class TestExitInFlightStateMachine:
    """Exit in-flight must transition to SUBMISSION_UNKNOWN on timeout, not silently clear."""

    def test_exit_intent_submitted_blocks_duplicate(self, monitor):
        pos = make_position()
        monitor.add_position(pos)
        monitor._mark_exit_intent_in_flight(pos.position_id, client_order_id="exit-1")

        assert monitor._is_exit_intent_in_flight(pos.position_id) is True

    def test_exit_intent_timeout_transitions_to_submission_unknown(self, monitor):
        pos = make_position()
        monitor.add_position(pos)
        monitor._exit_intent_timeout_seconds = 0.1
        monitor._submission_cache_ttl = 0.05
        monitor._mark_exit_intent_in_flight(pos.position_id, client_order_id="exit-1")

        time.sleep(0.15)

        assert monitor._is_exit_intent_in_flight(pos.position_id) is True
        flight = monitor._exit_intent_in_flight.get(pos.position_id)
        assert flight is not None
        assert flight["state"] == "SUBMISSION_UNKNOWN"

    def test_exit_intent_submission_unknown_still_blocks_re_arm(self, monitor):
        pos = make_position()
        monitor.add_position(pos)
        monitor._exit_intent_in_flight[pos.position_id] = {
            "state": "SUBMISSION_UNKNOWN",
            "timestamp": time.time(),
            "client_order_id": "exit-1",
        }

        assert monitor._is_exit_intent_in_flight(pos.position_id) is True

    def test_exit_intent_reconciled_allows_new_exit(self, monitor):
        pos = make_position()
        monitor.add_position(pos)
        monitor._mark_exit_intent_in_flight(pos.position_id, client_order_id="exit-1")
        monitor._mark_exit_intent_reconciled(pos.position_id, "exchange_reconciled")

        assert monitor._is_exit_intent_in_flight(pos.position_id) is False


class TestPositionKeyIdentity:
    """PositionMonitor must reject strip/series keys and accept full market tickers."""

    def test_add_position_rejects_strip_key(self, monitor):
        pos = make_position(market_id="KXBTC15M")
        monitor.add_position(pos)
        assert len(monitor.get_open_positions()) == 0

    def test_add_position_accepts_full_ticker(self, monitor):
        pos = make_position(market_id="KXBTC15M-TEST")
        monitor.add_position(pos)
        assert len(monitor.get_open_positions()) == 1

    def test_remove_position_resolves_market_id(self, monitor):
        pos = make_position(market_id="KXBTC15M-TEST")
        monitor.add_position(pos)

        # Should resolve via _market_to_position
        monitor.remove_position(pos.market_id)
        assert len(monitor.get_open_positions()) == 0
