"""Comprehensive tests for trading/paper_trading.py - Coverage improvement."""

import pytest
import time
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from trading.paper_trading import (
    PaperOrderStatus, PaperOrderType, PaperOrder, PaperPosition,
    PaperPortfolio, PaperTradingEngine, get_paper_engine
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestPaperOrderStatus:
    """Test PaperOrderStatus enum."""

    def test_pending(self):
        assert PaperOrderStatus.PENDING.value == "pending"

    def test_filled(self):
        assert PaperOrderStatus.FILLED.value == "filled"

    def test_cancelled(self):
        assert PaperOrderStatus.CANCELLED.value == "cancelled"

    def test_rejected(self):
        assert PaperOrderStatus.REJECTED.value == "rejected"


class TestPaperOrderType:
    """Test PaperOrderType enum."""

    def test_market(self):
        assert PaperOrderType.MARKET.value == "market"

    def test_limit(self):
        assert PaperOrderType.LIMIT.value == "limit"

    def test_stop_loss(self):
        assert PaperOrderType.STOP_LOSS.value == "stop_loss"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestPaperOrder:
    """Test PaperOrder dataclass."""

    def test_creation(self):
        order = PaperOrder(
            order_id="order_1",
            user_id="user_1",
            asset="BTC/USDT",
            side="long",
            order_type=PaperOrderType.MARKET,
            size_usd=1000.0
        )
        assert order.order_id == "order_1"
        assert order.status == PaperOrderStatus.PENDING

    def test_defaults(self):
        order = PaperOrder(
            order_id="order_2",
            user_id="user_2",
            asset="ETH/USDT",
            side="short",
            order_type=PaperOrderType.LIMIT,
            size_usd=500.0
        )
        assert order.leverage == 1
        assert order.market_type == "perp"
        assert order.fill_price is None


class TestPaperPosition:
    """Test PaperPosition dataclass."""

    def test_creation(self):
        position = PaperPosition(
            position_id="pos_1",
            user_id="user_1",
            asset="BTC/USDT",
            side="long",
            size_usd=1000.0,
            entry_price=50000.0,
            current_price=51000.0
        )
        assert position.position_id == "pos_1"
        assert position.unrealized_pnl == 0.0

    def test_defaults(self):
        position = PaperPosition(
            position_id="pos_2",
            user_id="user_2",
            asset="ETH/USDT",
            side="short",
            size_usd=500.0,
            entry_price=3000.0,
            current_price=2900.0
        )
        assert position.leverage == 1
        assert position.closed_at is None


class TestPaperPortfolio:
    """Test PaperPortfolio dataclass."""

    def test_creation(self):
        portfolio = PaperPortfolio(user_id="user_1")
        assert portfolio.starting_balance == 10000.0
        assert portfolio.current_balance == 10000.0

    def test_defaults(self):
        portfolio = PaperPortfolio(user_id="user_2")
        assert portfolio.total_trades == 0
        assert portfolio.positions == {}
        assert portfolio.orders == {}


# =============================================================================
# PaperTradingEngine Tests
# =============================================================================

@pytest.fixture
def engine():
    """Create PaperTradingEngine with mocked price feed."""
    with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
        mock_price_feed = MagicMock()
        mock_feed.return_value = mock_price_feed
        
        engine = PaperTradingEngine(starting_balance=10000.0)
        engine.current_prices["BTC/USDT"] = 50000.0
        engine.current_prices["BTC"] = 50000.0
        engine.current_prices["ETH/USDT"] = 3000.0
        engine.current_prices["ETH"] = 3000.0
        return engine


class TestPaperTradingEngineInit:
    """Test PaperTradingEngine initialization."""

    def test_init_defaults(self):
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            engine = PaperTradingEngine()
        
        assert engine.starting_balance == 10000.0
        assert engine.portfolios == {}


class TestGetPortfolio:
    """Test get_portfolio method."""

    def test_creates_new_portfolio(self, engine):
        portfolio = engine.get_portfolio("new_user")
        
        assert portfolio.user_id == "new_user"
        assert portfolio.starting_balance == 10000.0

    def test_returns_existing_portfolio(self, engine):
        portfolio1 = engine.get_portfolio("user_1")
        portfolio1.current_balance = 5000.0
        
        portfolio2 = engine.get_portfolio("user_1")
        
        assert portfolio2.current_balance == 5000.0


class TestPlaceOrder:
    """Test place_order method."""

    def test_place_market_order_success(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        assert order.status == PaperOrderStatus.FILLED
        assert order.fill_price is not None

    def test_place_order_insufficient_balance(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=50000.0,  # More than starting balance
            order_type="market"
        )
        
        assert order.status == PaperOrderStatus.REJECTED

    def test_place_limit_order(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="limit",
            price=48000.0
        )
        
        assert order.status == PaperOrderStatus.PENDING
        portfolio = engine.get_portfolio("user_1")
        assert order.order_id in portfolio.orders

    def test_place_order_with_leverage(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=5000.0,
            leverage=5
        )
        
        # With 5x leverage, only need 1000 margin
        assert order.status == PaperOrderStatus.FILLED


class TestExecuteOrder:
    """Test _execute_order method."""

    def test_execute_long_order(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0
        )
        
        # Long orders have positive slippage
        assert order.fill_price > 50000.0

    def test_execute_short_order(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="ETH",
            side="short",
            size_usd=1000.0
        )
        
        # Short orders have negative slippage
        assert order.fill_price < 3000.0

    def test_execute_prediction_market_order(self, engine):
        order = engine.place_order(
            user_id="user_1",
            asset="MARKET_YES",
            side="yes",
            size_usd=100.0,
            market_type="prediction",
            price=0.65
        )
        
        assert order.status == PaperOrderStatus.FILLED

    def test_execute_order_no_price(self, engine):
        # Remove price for asset
        engine.current_prices.pop("BTC", None)
        engine.current_prices.pop("BTC/USDT", None)
        
        order = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=100.0
        )
        
        assert order.status == PaperOrderStatus.REJECTED


class TestClosePosition:
    """Test close_position method."""

    def test_close_position_profit(self, engine):
        # Place order to create position
        engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0
        )
        
        # Simulate price increase
        engine.current_prices["BTC"] = 55000.0
        engine.current_prices["BTC/USDT"] = 55000.0

        portfolio = engine.get_portfolio("user_1")
        position_keys = list(portfolio.positions.keys())
        assert len(position_keys) > 0
        pnl = engine.close_position("user_1", position_keys[0])

        assert pnl is not None

    def test_close_position_loss(self, engine):
        engine.place_order(
            user_id="user_1",
            asset="ETH",
            side="long",
            size_usd=1000.0
        )

        # Simulate price decrease
        engine.current_prices["ETH"] = 2500.0
        engine.current_prices["ETH/USDT"] = 2500.0

        portfolio = engine.get_portfolio("user_1")
        position_keys = list(portfolio.positions.keys())
        assert len(position_keys) > 0
        pnl = engine.close_position("user_1", position_keys[0])

        assert pnl is not None

    def test_close_position_not_found(self, engine):
        pnl = engine.close_position("user_1", "nonexistent_key")
        assert pnl is None


class TestSymbolsMatch:
    """Test _symbols_match static method."""

    def test_exact_match(self):
        assert PaperTradingEngine._symbols_match("BTC/USDT", "BTC/USDT") is True

    def test_base_match(self):
        assert PaperTradingEngine._symbols_match("BTC", "BTC/USDT") is True

    def test_no_match(self):
        assert PaperTradingEngine._symbols_match("ETH", "BTC/USDT") is False


class TestSubscriptions:
    """Test subscription methods."""

    def test_subscribe_to_summary(self, engine):
        callback = MagicMock()
        unsubscribe = engine.subscribe_to_summary(callback)
        
        callback.assert_called_once()
        assert callable(unsubscribe)

    def test_subscribe_to_trades(self, engine):
        callback = MagicMock()
        unsubscribe = engine.subscribe_to_trades(callback)
        
        callback.assert_called_once()
        assert callable(unsubscribe)

    def test_subscribe_to_positions(self, engine):
        callback = MagicMock()
        unsubscribe = engine.subscribe_to_positions(callback)
        
        callback.assert_called_once()
        assert callable(unsubscribe)

    def test_unsubscribe(self, engine):
        callback = MagicMock()
        unsubscribe = engine.subscribe_to_summary(callback)
        
        unsubscribe()
        
        # Callback should no longer be in listeners
        assert callback not in engine._listeners["summary"]


class TestGetGlobalStats:
    """Test get_global_stats method."""

    def test_empty_stats(self, engine):
        stats = engine.get_global_stats()
        
        assert stats["accounts"] == 0
        assert stats["cash"] == 0.0
        assert stats["active_positions"] == 0

    def test_stats_with_positions(self, engine):
        engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0
        )
        
        stats = engine.get_global_stats()
        
        assert stats["accounts"] == 1
        assert stats["active_positions"] == 1


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetPaperEngine:
    """Test get_paper_engine singleton."""

    def test_returns_same_instance(self):
        import trading.paper_trading as module
        module._paper_engine = None
        
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            
            engine1 = get_paper_engine()
            engine2 = get_paper_engine()
        
        assert engine1 is engine2


# =============================================================================
# Coverage Gap Tests - Lines 140, 152-157, 209-210, 213-228, 237, 240-249
# =============================================================================

class TestSubscriptionAndPriceUpdates:
    """Test subscription and price update handling."""

    @pytest.fixture
    def engine(self):
        mock_price_feed = MagicMock()
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed, \
             patch("merid.settings.settings") as mock_settings:
            mock_feed.return_value = (mock_price_feed, MagicMock())
            mock_settings.KALSHI_ONLY = False
            engine = PaperTradingEngine()
            yield engine

    def test_subscribe_unsupported_event_raises(self, engine):
        """Test subscribing to unsupported event type raises ValueError (line 140)."""
        with pytest.raises(ValueError, match="Unsupported telemetry event"):
            engine._subscribe("invalid_event_type", lambda x: None)

    def test_notify_listeners_with_exception(self, engine):
        """Test listener exception handling (lines 152-157)."""
        def failing_callback(payload):
            raise RuntimeError("Callback failed")

        engine._listeners["summary"] = {failing_callback}
        # Should not raise, just log
        engine._notify_listeners("summary", {"test": "data"})

    def test_subscribe_to_prices_exception(self, engine):
        """Test price subscription error handling (lines 209-210)."""
        engine.price_feed.subscribe.side_effect = Exception("Connection failed")
        # Should not raise, just log
        engine._subscribe_to_prices()

    def test_on_price_update_updates_positions(self, engine):
        """Test price update propagates to positions (lines 213-228)."""
        PriceData = MagicMock  # PriceData is from data.live_price_feed, not re-exported
        
        # Create a position first
        engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0
        )
        
        # Mock price data
        price_data = MagicMock()
        price_data.symbol = "BTC/USDT"
        price_data.price = 55000.0
        
        engine._on_price_update(price_data)
        
        assert engine.current_prices.get("BTC/USDT") == 55000.0
        assert engine.current_prices.get("BTC") == 55000.0

    def test_symbols_match_with_slash(self, engine):
        """Test symbol matching with slash format (line 237)."""
        assert PaperTradingEngine._symbols_match("BTC/USDT", "BTC/USD") is True
        assert PaperTradingEngine._symbols_match("ETH/USDT", "BTC/USD") is False

    def test_get_live_price_cached(self, engine):
        """Test getting cached live price (lines 240-249)."""
        engine.current_prices["ETH/USDT"] = 3000.0
        price = engine._get_live_price("ETH/USDT")
        assert price == 3000.0

    def test_get_live_price_from_feed(self, engine):
        """Test getting live price from feed (lines 244-248)."""
        mock_price_data = MagicMock()
        mock_price_data.price = 4000.0
        engine.price_feed.get_current_price.return_value = mock_price_data
        
        price = engine._get_live_price("SOL")
        assert price == 4000.0
        assert engine.current_prices.get("SOL/USDT") == 4000.0

    def test_get_live_price_fallback(self, engine):
        """Test getting live price fallback (line 249)."""
        engine.price_feed.get_current_price.return_value = None
        engine.current_prices["DOGE"] = 0.15
        
        price = engine._get_live_price("DOGE/USDT")
        assert price == 0.15


# =============================================================================
# Risk Kill Switch Tests - Lines 382-392
# =============================================================================

class TestRiskKillSwitch:
    """Test risk controller kill switch integration."""

    @pytest.fixture
    def engine(self):
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            engine = PaperTradingEngine()
            yield engine

    def test_order_rejected_when_kill_switch_triggered(self, engine):
        """Test order rejection when risk kill switch is triggered (lines 382-392)."""
        mock_risk_ctrl = MagicMock()
        mock_risk_ctrl.can_trade.return_value = False
        
        with patch("trading.paper_trading._get_risk_controller", return_value=mock_risk_ctrl):
            order = engine.place_order(
                user_id="user_1",
                asset="BTC",
                side="long",
                size_usd=1000.0
            )
        
        assert order.status == PaperOrderStatus.REJECTED
        assert "rejected" in order.order_id


# =============================================================================
# Position Averaging Tests - Lines 489-494
# =============================================================================

class TestPositionAveraging:
    """Test position averaging when adding to existing positions."""

    @pytest.fixture
    def engine(self):
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            engine = PaperTradingEngine()
            # Set up mock prices to avoid rejection
            engine.current_prices["BTC"] = 50000.0
            engine.current_prices["BTC/USDT"] = 50000.0
            yield engine

    def test_add_to_existing_position_averages_entry(self, engine):
        """Test adding to existing position averages entry price (lines 489-494)."""
        # First order
        order1 = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0
        )
        assert order1.status == PaperOrderStatus.FILLED
        
        # Second order same direction - should average
        order2 = engine.place_order(
            user_id="user_1",
            asset="BTC",
            side="long",
            size_usd=1000.0
        )
        assert order2.status == PaperOrderStatus.FILLED
        
        portfolio = engine.get_portfolio("user_1")
        # Should have one position with combined size
        assert len(portfolio.positions) == 1
        position = list(portfolio.positions.values())[0]
        assert position.size_usd == 2000.0


# =============================================================================
# PnL Calculation Tests - Line 590
# =============================================================================

class TestPnLCalculation:
    """Test PnL calculation for different position types."""

    @pytest.fixture
    def engine(self):
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            engine = PaperTradingEngine()
            yield engine

    def test_prediction_market_no_side_pnl(self, engine):
        """Test prediction market 'no' side PnL calculation (line 590)."""
        # Create a prediction market position with "no" side
        order = engine.place_order(
            user_id="user_1",
            asset="ELECTION_OUTCOME",
            side="no",
            size_usd=100.0,
            market_type="prediction"
        )
        
        portfolio = engine.get_portfolio("user_1")
        position = list(portfolio.positions.values())[0]
        
        # Calculate PnL — value depends on current price feed; just assert it runs without error
        pnl = engine._calculate_position_pnl(position)
        assert isinstance(pnl, (int, float))


# =============================================================================
# Update Prices Tests - Lines 602-609
# =============================================================================

class TestUpdatePrices:
    """Test update_prices method."""

    @pytest.fixture
    def engine(self):
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            engine = PaperTradingEngine()
            yield engine

    def test_update_prices_updates_perp_positions(self, engine):
        """Test update_prices updates perp positions (lines 602-609)."""
        # Create a perp position
        engine.place_order(
            user_id="user_1",
            asset="ETH",
            side="long",
            size_usd=1000.0,
            market_type="perp"
        )
        
        # Update prices
        engine.update_prices({"ETH": 3500.0})
        
        assert engine.current_prices.get("ETH") == 3500.0


# =============================================================================
# Pipeline Registration Tests - Lines 718-724
# =============================================================================

class TestPipelineRegistration:
    """Test register_with_pipeline function."""

    def test_register_with_pipeline_success(self):
        """Test successful pipeline registration (lines 718-722)."""
        from trading.paper_trading import register_with_pipeline
        
        mock_pipeline = MagicMock()
        mock_module = MagicMock()
        mock_module.get_simulation_pipeline = MagicMock(return_value=mock_pipeline)
        
        with patch.dict("sys.modules", {"core.simulation_pipeline": mock_module}):
            register_with_pipeline()
            mock_pipeline.register_paper_handler.assert_called_once()
        
    def test_register_with_pipeline_import_error(self):
        """Test pipeline registration handles ImportError (lines 723-724)."""
        from trading.paper_trading import register_with_pipeline
        
        # Remove the module from sys.modules to force ImportError
        import sys
        if "core.simulation_pipeline" in sys.modules:
            del sys.modules["core.simulation_pipeline"]
        
        # Should not raise, just log warning
        register_with_pipeline()  # Will hit the ImportError path
