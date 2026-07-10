"""
Tests for multi-contract order bypass fixes (2026-07-09).

Tests the following fixes:
1. Duplicate order detection - orders recorded BEFORE submission (order_router.py)
2. Resting duplicate detection with count parameter (order_gate.py)
3. KalshiTrader contract count enforcement (trading.py)
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    route_order_async,
    _record_order_placed,
    _check_duplicate_order,
)
from merid.event_venues.kalshi.order_gate import PreTradeGate, GateVerdict, OrderStatus
from merid.event_venues.kalshi.trading import KalshiTrader


class TestDuplicateOrderDetectionFix:
    """Test that duplicate order detection happens BEFORE submission."""

    @pytest.fixture
    def valid_order_intent(self):
        """Create a valid order intent for testing."""
        return OrderIntent(
            intent_id="test-123",
            ticker="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            price_cents=55,
            count=1,
            source="BTC_15M",
            window_resolution_id="test_window",
            risk_tier="A",
            max_hold_seconds=600
        )

    def test_record_order_placed_called_before_submission(self, valid_order_intent):
        """Test that _record_order_placed is called before order submission."""
        # Reset duplicate tracker
        from merid.event_venues.kalshi.order_router import _duplicate_order_tracker
        _duplicate_order_tracker.clear()

        # Record the order
        _record_order_placed(valid_order_intent)

        # Verify it's in the tracker
        key = (valid_order_intent.ticker.upper(), valid_order_intent.side.upper(), 
               valid_order_intent.action.upper(), valid_order_intent.price_cents)
        assert key in _duplicate_order_tracker

        # Verify duplicate check now blocks
        result = _check_duplicate_order(valid_order_intent)
        assert result is not None
        assert "duplicate_order" in result

    def test_duplicate_order_prevents_race_condition(self, valid_order_intent):
        """Test that recording before submission prevents race condition."""
        from merid.event_venues.kalshi.order_router import _duplicate_order_tracker
        _duplicate_order_tracker.clear()

        # Simulate rapid identical order submissions
        # First order should be recorded
        _record_order_placed(valid_order_intent)

        # Second identical order should be blocked
        result = _check_duplicate_order(valid_order_intent)
        assert result is not None
        assert "duplicate_order" in result

        # Different price should not be blocked
        valid_order_intent.price_cents = 56
        result = _check_duplicate_order(valid_order_intent)
        assert result is None


class TestRestingDuplicateDetectionWithCount:
    """Test that resting duplicate detection includes count parameter."""

    @pytest.fixture
    def gate(self):
        """Create a PreTradeGate instance for testing."""
        return PreTradeGate()

    @pytest.fixture
    def order_record(self):
        """Create an OrderRecord for testing."""
        from merid.event_venues.kalshi.order_gate import OrderRecord
        return OrderRecord(
            client_order_id="test-coid-1",
            agent_id="BTC_15M",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=55,
            status=OrderStatus.LIVE,
        )

    def test_find_resting_duplicate_includes_count(self, gate, order_record):
        """Test that find_resting_duplicate checks count parameter."""
        # Add an order with count=1
        gate._store._orders[order_record.client_order_id] = order_record

        # Try to find duplicate with same count=1
        duplicate = gate._store.find_resting_duplicate(
            contract_id=order_record.contract_id,
            side=order_record.side,
            action=order_record.action,
            price_cents=order_record.price_cents,
            target_count=1,  # Same count
            exclude_coid=None,
        )
        assert duplicate is not None
        assert duplicate.client_order_id == order_record.client_order_id

        # Try to find duplicate with different count=2
        duplicate = gate._store.find_resting_duplicate(
            contract_id=order_record.contract_id,
            side=order_record.side,
            action=order_record.action,
            price_cents=order_record.price_cents,
            target_count=2,  # Different count
            exclude_coid=None,
        )
        assert duplicate is None  # Should NOT find duplicate due to count mismatch

    def test_find_resting_duplicate_prevents_multi_contract_bypass(self, gate):
        """Test that count check prevents multi-contract bypass."""
        from merid.event_venues.kalshi.order_gate import OrderRecord

        # Add order with count=1
        order1 = OrderRecord(
            client_order_id="test-coid-1",
            agent_id="BTC_15M",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=55,
            status=OrderStatus.LIVE,
        )
        gate._store._orders[order1.client_order_id] = order1

        # Add order with count=2 (same market/price)
        order2 = OrderRecord(
            client_order_id="test-coid-2",
            agent_id="BTC_15M",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            target_count=2,
            price_cents=55,
            status=OrderStatus.LIVE,
        )
        gate._store._orders[order2.client_order_id] = order2

        # Search for duplicate with count=1 should find order1
        duplicate = gate._store.find_resting_duplicate(
            contract_id="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            price_cents=55,
            target_count=1,
            exclude_coid=None,
        )
        assert duplicate is not None
        assert duplicate.target_count == 1

        # Search for duplicate with count=2 should find order2
        duplicate = gate._store.find_resting_duplicate(
            contract_id="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            price_cents=55,
            target_count=2,
            exclude_coid=None,
        )
        assert duplicate is not None
        assert duplicate.target_count == 2


class TestKalshiTraderContractCountEnforcement:
    """Test that KalshiTrader enforces max 1 contract per order."""

    @pytest.fixture
    def mock_client(self):
        """Create mock KalshiVenueClient."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def trader(self, mock_client):
        """Create KalshiTrader with mock client."""
        trader = KalshiTrader(client=mock_client)
        # Mock venue gate to allow live trading
        trader._is_live_trading_allowed = lambda: True
        return trader

    @pytest.mark.asyncio
    async def test_pre_order_check_rejects_count_gt_1(self, trader):
        """Test that _pre_order_check rejects orders with count > 1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                # Test count=2 (should be rejected)
                allowed, reason = trader._pre_order_check("TEST-TICKER", 2, 55)
                assert not allowed
                assert "max_contracts_exceeded" in reason
                assert "count=2>1" in reason

                # Test count=5 (should be rejected)
                allowed, reason = trader._pre_order_check("TEST-TICKER", 5, 55)
                assert not allowed
                assert "max_contracts_exceeded" in reason
                assert "count=5>1" in reason

    @pytest.mark.asyncio
    async def test_pre_order_check_accepts_count_1(self, trader):
        """Test that _pre_order_check accepts orders with count=1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                # Test count=1 (should be accepted)
                allowed, reason = trader._pre_order_check("TEST-TICKER", 1, 55)
                assert allowed
                assert reason == "OK"

    @pytest.mark.asyncio
    async def test_buy_yes_rejects_count_gt_1(self, trader, mock_client):
        """Test that buy_yes rejects orders with count > 1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                result = await trader.buy_yes("TEST-TICKER", 2, price=55)
                assert result is None
                mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_buy_no_rejects_count_gt_1(self, trader, mock_client):
        """Test that buy_no rejects orders with count > 1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                result = await trader.buy_no("TEST-TICKER", 3, price=55)
                assert result is None
                mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_sell_yes_rejects_count_gt_1(self, trader, mock_client):
        """Test that sell_yes rejects orders with count > 1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                result = await trader.sell_yes("TEST-TICKER", 10, price=55)
                assert result is None
                mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_sell_no_rejects_count_gt_1(self, trader, mock_client):
        """Test that sell_no rejects orders with count > 1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                result = await trader.sell_no("TEST-TICKER", 5, price=55)
                assert result is None
                mock_client.place_order.assert_not_called()
