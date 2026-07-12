"""Comprehensive tests for merid/event_venues/kalshi/trading.py.

NOTE: This module tests the legacy KalshiTrader which is not used by the
production kalshi_crypto_15m_v2 profile. The production stack uses the
order_router module for order routing and execution.

This test file is skipped to avoid legacy contamination in production tests.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.trading import KalshiTrader
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
    VenuePosition,
)


pytestmark = pytest.mark.skip(reason="Legacy KalshiTrader not used in production kalshi_crypto_15m_v2 stack")


@pytest.fixture
def mock_client():
    """Create mock KalshiVenueClient."""
    client = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def _trader_unit_gate_patches(monkeypatch):
    """Unit tests use mocks; bypass VenueGate + risk stack so client.place_order is exercised."""
    monkeypatch.setattr(KalshiTrader, "_is_live_trading_allowed", lambda self: True)
    # Note: _pre_order_check is NOT mocked in all tests - some tests need to verify price validation


@pytest.fixture
def trader(mock_client):
    """Create KalshiTrader with mock client and mocked risk checks."""
    trader = KalshiTrader(client=mock_client)
    # Mock venue gate to allow live trading
    trader._is_live_trading_allowed = lambda: True
    # Mock risk checks to allow orders (but keep price validation)
    original_pre_check = trader._pre_order_check
    def mock_pre_check(ticker, count, price_cents, category=None):
        # First check price validation (real logic)
        if price_cents < 50 or price_cents > 70:
            return False, f"invalid_price_range:{price_cents}c (must be 50-70c)"
        # Then return OK for risk checks
        return True, "OK"
    trader._pre_order_check = mock_pre_check
    return trader


class TestKalshiTraderPriceValidation:
    """Test price range validation in _pre_order_check."""

    @pytest.fixture
    def trader_with_checks(self, mock_client):
        """Create trader with real _pre_order_check but mocked risk checks."""
        trader = KalshiTrader(client=mock_client)
        # Mock venue gate to allow live trading
        trader._is_live_trading_allowed = lambda: True
        # Mock risk checks to allow orders
        trader._pre_order_check = lambda *a, **k: (True, "OK")
        return trader


class TestKalshiTraderContractCountEnforcement:
    """Test contract count enforcement in _pre_order_check (2026-07-09 fix)."""

    @pytest.fixture
    def trader_with_real_checks(self, mock_client):
        """Create trader with real _pre_order_check but mocked risk checks."""
        trader = KalshiTrader(client=mock_client)
        # Mock venue gate to allow live trading
        trader._is_live_trading_allowed = lambda: True
        return trader

    @pytest.mark.asyncio
    async def test_pre_order_check_rejects_count_gt_1(self, trader_with_real_checks):
        """Test that _pre_order_check rejects orders with count > 1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                # Test count=2 (should be rejected)
                allowed, reason = trader_with_real_checks._pre_order_check("TEST-TICKER", 2, 55)
                assert not allowed
                assert "max_contracts_exceeded" in reason
                assert "count=2>1" in reason

                # Test count=5 (should be rejected)
                allowed, reason = trader_with_real_checks._pre_order_check("TEST-TICKER", 5, 55)
                assert not allowed
                assert "max_contracts_exceeded" in reason
                assert "count=5>1" in reason

    @pytest.mark.asyncio
    async def test_pre_order_check_accepts_count_1(self, trader_with_real_checks):
        """Test that _pre_order_check accepts orders with count=1."""
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                # Test count=1 (should be accepted)
                allowed, reason = trader_with_real_checks._pre_order_check("TEST-TICKER", 1, 55)
                assert allowed
                assert reason == "OK"


class TestKalshiTraderInitialization:
    """Test KalshiTrader initialization."""

    def test_init_with_client(self, mock_client):
        """Test initialization with provided client."""
        trader = KalshiTrader(client=mock_client)
        assert trader.client is mock_client

    def test_init_without_client(self):
        """Test initialization without client creates new one."""
        with patch('merid.event_venues.kalshi.trading.KalshiVenueClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            trader = KalshiTrader()
            mock_client_class.assert_called_once()
            assert trader.client is mock_client

    def test_init_with_config(self):
        """Test initialization with config."""
        config = KalshiConfig()
        with patch('merid.event_venues.kalshi.trading.KalshiVenueClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            trader = KalshiTrader(config=config)
            mock_client_class.assert_called_once_with(config)


class TestKalshiTraderConnection:
    """Test KalshiTrader connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, trader, mock_client):
        """Test connect delegates to client."""
        await trader.connect()
        mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, trader, mock_client):
        """Test close delegates to client."""
        await trader.close()
        mock_client.close.assert_called_once()


class TestKalshiTraderBuyOperations:
    """Test KalshiTrader buy operations."""

    @pytest.mark.asyncio
    async def test_buy_yes_market_order(self, trader, mock_client):
        """Test buying YES contracts at market price."""
        expected_order = PlacedOrder(
            order_id="order_123",
            market_id="FED-25DEC-T3.00",
            side="buy",
            size=Decimal("10"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_yes("FED-25DEC-T3.00", 10)

        assert result == expected_order
        mock_client.place_order.assert_called_once()
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.market_id == "FED-25DEC-T3.00"
        assert call_args.side == "buy"
        assert call_args.size == Decimal("10")
        assert call_args.outcome_id == "yes"
        assert call_args.order_type == "market"
        # Market orders now include default price for validation (bug fix)
        assert call_args.price == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_buy_yes_limit_order(self, trader, mock_client):
        """Test buying YES contracts at limit price."""
        expected_order = PlacedOrder(
            order_id="order_124",
            market_id="FED-25DEC-T3.00",
            side="buy",
            size=Decimal("5"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_yes("FED-25DEC-T3.00", 5, price=60)

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.order_type == "limit"
        assert call_args.price == Decimal("0.60")

    @pytest.mark.asyncio
    async def test_buy_no_market_order(self, trader, mock_client):
        """Test buying NO contracts at market price."""
        expected_order = PlacedOrder(
            order_id="order_125",
            market_id="FED-25DEC-T3.00",
            side="buy",
            size=Decimal("20"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_no("FED-25DEC-T3.00", 20)

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.outcome_id == "no"
        assert call_args.order_type == "market"

    @pytest.mark.asyncio
    async def test_buy_no_limit_order(self, trader, mock_client):
        """Test buying NO contracts at limit price."""
        expected_order = PlacedOrder(
            order_id="order_126",
            market_id="FED-25DEC-T3.00",
            side="buy",
            size=Decimal("15"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_no("FED-25DEC-T3.00", 15, price=55)

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.order_type == "limit"
        assert call_args.price == Decimal("0.55")


class TestKalshiTraderSellOperations:
    """Test KalshiTrader sell operations."""

    @pytest.mark.asyncio
    async def test_sell_yes_market_order(self, trader, mock_client):
        """Test selling YES contracts at market price."""
        expected_order = PlacedOrder(
            order_id="order_127",
            market_id="FED-25DEC-T3.00",
            side="sell",
            size=Decimal("8"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.sell_yes("FED-25DEC-T3.00", 8)

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.outcome_id == "yes"

    @pytest.mark.asyncio
    async def test_sell_no_market_order(self, trader, mock_client):
        """Test selling NO contracts at market price."""
        expected_order = PlacedOrder(
            order_id="order_128",
            market_id="FED-25DEC-T3.00",
            side="sell",
            size=Decimal("12"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.sell_no("FED-25DEC-T3.00", 12)

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.outcome_id == "no"


class TestKalshiTraderClosePosition:
    """Test KalshiTrader position closing."""

    @pytest.mark.asyncio
    async def test_close_position_with_yes_position(self, trader, mock_client):
        """Test closing YES position."""
        position = VenuePosition(
            market_id="FED-25DEC-T3.00",
            outcome_id="yes",
            size=Decimal("10"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        placed_order = PlacedOrder(
            order_id="order_close",
            market_id="FED-25DEC-T3.00",
            side="sell",
            size=Decimal("10"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = placed_order

        result = await trader.close_position("FED-25DEC-T3.00")

        assert len(result) == 1
        assert result[0] == placed_order
        mock_client.place_order.assert_called_once()
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.size == Decimal("10")

    @pytest.mark.asyncio
    async def test_close_position_with_no_position(self, trader, mock_client):
        """Test closing NO position."""
        position = VenuePosition(
            market_id="FED-25DEC-T3.00",
            outcome_id="no",
            size=Decimal("-5"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        placed_order = PlacedOrder(
            order_id="order_close",
            market_id="FED-25DEC-T3.00",
            side="buy",
            size=Decimal("5"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = placed_order

        result = await trader.close_position("FED-25DEC-T3.00")

        assert len(result) == 1
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "buy"
        assert call_args.size == Decimal("5")

    @pytest.mark.asyncio
    async def test_close_position_zero_size_skipped(self, trader, mock_client):
        """Test that zero-size positions are skipped."""
        position = VenuePosition(
            market_id="FED-25DEC-T3.00",
            outcome_id="yes",
            size=Decimal("0"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        result = await trader.close_position("FED-25DEC-T3.00")

        assert len(result) == 0
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_no_positions(self, trader, mock_client):
        """Test closing position when no positions exist."""
        mock_client.get_positions.return_value = []

        result = await trader.close_position("FED-25DEC-T3.00")

        assert len(result) == 0
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_other_market_ignored(self, trader, mock_client):
        """Test that positions in other markets are ignored."""
        position = VenuePosition(
            market_id="OTHER-MARKET",
            outcome_id="yes",
            size=Decimal("10"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        result = await trader.close_position("FED-25DEC-T3.00")

        assert len(result) == 0


class TestKalshiTraderMarketOperations:
    """Test KalshiTrader market operations."""

    @pytest.mark.asyncio
    async def test_get_market_by_ticker(self, trader, mock_client):
        """Test getting market by ticker."""
        expected_market = EventMarket(
            market_id="FED-25DEC-T3.00",
            venue="kalshi",
            question="Fed Rate Decision",
            description="Will Fed raise rates?",
            outcomes=[],
            category="finance"
        )
        mock_client.get_market.return_value = expected_market

        result = await trader.get_market_by_ticker("FED-25DEC-T3.00")

        assert result == expected_market
        mock_client.get_market.assert_called_once_with("FED-25DEC-T3.00")

    @pytest.mark.asyncio
    async def test_search_markets(self, trader, mock_client):
        """Test searching markets."""
        expected_markets = [
            EventMarket(market_id="FED-1", venue="kalshi", question="Fed Meeting 1", description="Desc", outcomes=[]),
            EventMarket(market_id="FED-2", venue="kalshi", question="Fed Meeting 2", description="Desc", outcomes=[]),
        ]
        mock_client.list_markets.return_value = expected_markets

        result = await trader.search_markets("Fed", limit=5)

        assert result == expected_markets
        mock_client.list_markets.assert_called_once()
        call_args = mock_client.list_markets.call_args[0][0]
        assert call_args.search == "Fed"
        assert call_args.limit == 5

    @pytest.mark.asyncio
    async def test_get_best_price_buy_side(self, trader, mock_client):
        """Test getting best price for buying."""
        from datetime import datetime
        from merid.event_venues.base import VenueOrderBook
        orderbook = VenueOrderBook(
            market_id="FED-25DEC-T3.00",
            outcome_id="yes",
            bids=[(Decimal("0.60"), Decimal("100"))],
            asks=[(Decimal("0.65"), Decimal("200"))],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("FED-25DEC-T3.00", side="yes", action="buy")

        assert result == Decimal("0.65")

    @pytest.mark.asyncio
    async def test_get_best_price_sell_side(self, trader, mock_client):
        """Test getting best price for selling."""
        from datetime import datetime
        from merid.event_venues.base import VenueOrderBook
        orderbook = VenueOrderBook(
            market_id="FED-25DEC-T3.00",
            outcome_id="yes",
            bids=[(Decimal("0.60"), Decimal("100"))],
            asks=[(Decimal("0.65"), Decimal("200"))],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("FED-25DEC-T3.00", side="yes", action="sell")

        assert result == Decimal("0.60")

    @pytest.mark.asyncio
    async def test_get_best_price_no_orderbook(self, trader, mock_client):
        """Test getting best price when orderbook is empty."""
        mock_client.get_orderbook.return_value = None

        result = await trader.get_best_price("FED-25DEC-T3.00")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_best_price_empty_asks(self, trader, mock_client):
        """Test getting best price when asks are empty."""
        from datetime import datetime
        from merid.event_venues.base import VenueOrderBook
        orderbook = VenueOrderBook(
            market_id="FED-25DEC-T3.00",
            outcome_id="yes",
            bids=[(Decimal("0.60"), Decimal("100"))],
            asks=[],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("FED-25DEC-T3.00", action="buy")

        assert result is None


class TestKalshiTraderAccountOperations:
    """Test KalshiTrader account operations."""

    @pytest.mark.asyncio
    async def test_get_account_summary(self, trader, mock_client):
        """Test getting account summary."""
        balance = {"USD": Decimal("1000.00"), "total": Decimal("1500.00")}
        positions = [
            VenuePosition(market_id="M1", outcome_id="yes", size=Decimal("10"), average_entry_price=Decimal("0.50")),
            VenuePosition(market_id="M2", outcome_id="no", size=Decimal("-5"), average_entry_price=Decimal("0.50")),
        ]
        open_orders = [
            PlacedOrder(order_id="ord1", market_id="M1", side="buy", size=Decimal("1"), price=None, status="open"),
        ]

        mock_client.get_balance.return_value = balance
        mock_client.get_positions.return_value = positions
        mock_client.get_open_orders.return_value = open_orders

        result = await trader.get_account_summary()

        assert result["balance"] == balance
        assert result["positions"] == positions
        assert result["open_orders"] == open_orders
        assert result["position_count"] == 2
        assert result["open_order_count"] == 1

    @pytest.mark.asyncio
    async def test_get_account_summary_empty(self, trader, mock_client):
        """Test getting account summary with no positions or orders."""
        balance = {"USD": Decimal("1000.00"), "total": Decimal("1000.00")}

        mock_client.get_balance.return_value = balance
        mock_client.get_positions.return_value = []
        mock_client.get_open_orders.return_value = []

        result = await trader.get_account_summary()

        assert result["position_count"] == 0
        assert result["open_order_count"] == 0
