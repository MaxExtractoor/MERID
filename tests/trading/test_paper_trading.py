"""Tests for trading/paper_trading.py."""
import pytest
import time
from unittest.mock import Mock, patch
from trading.paper_trading import (
    PaperOrderStatus, PaperOrderType, PaperOrder, PaperPosition, PaperPortfolio,
    PaperTradingEngine, get_paper_engine, paper_trading_handler, _paper_engine
)


class TestPaperOrderStatus:
    """Test PaperOrderStatus enum."""

    def test_status_values(self):
        """Test order status enum values."""
        assert PaperOrderStatus.PENDING.value == "pending"
        assert PaperOrderStatus.FILLED.value == "filled"
        assert PaperOrderStatus.CANCELLED.value == "cancelled"
        assert PaperOrderStatus.REJECTED.value == "rejected"


class TestPaperOrderType:
    """Test PaperOrderType enum."""

    def test_type_values(self):
        """Test order type enum values."""
        assert PaperOrderType.MARKET.value == "market"
        assert PaperOrderType.LIMIT.value == "limit"
        assert PaperOrderType.STOP_LOSS.value == "stop_loss"


class TestPaperOrder:
    """Test PaperOrder dataclass."""

    def test_creation(self):
        """Test PaperOrder creation."""
        order = PaperOrder(
            order_id="ord_123",
            user_id="user_456",
            asset="BTC",
            side="long",
            order_type=PaperOrderType.MARKET,
            size_usd=1000.0,
            price=50000.0,
            leverage=2
        )
        assert order.order_id == "ord_123"
        assert order.user_id == "user_456"
        assert order.asset == "BTC"
        assert order.side == "long"
        assert order.order_type == PaperOrderType.MARKET
        assert order.size_usd == 1000.0
        assert order.price == 50000.0
        assert order.leverage == 2
        assert order.status == PaperOrderStatus.PENDING


class TestPaperPosition:
    """Test PaperPosition dataclass."""

    def test_creation(self):
        """Test PaperPosition creation."""
        position = PaperPosition(
            position_id="pos_123",
            user_id="user_456",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            entry_price=50000.0,
            current_price=51000.0,
            leverage=2
        )
        assert position.position_id == "pos_123"
        assert position.asset == "BTC"
        assert position.side == "long"
        assert position.size_usd == 1000.0
        assert position.entry_price == 50000.0
        assert position.leverage == 2


class TestPaperPortfolio:
    """Test PaperPortfolio dataclass."""

    def test_default_values(self):
        """Test PaperPortfolio default values."""
        portfolio = PaperPortfolio(user_id="user_123")
        assert portfolio.user_id == "user_123"
        assert portfolio.starting_balance == 10000.0
        assert portfolio.current_balance == 10000.0
        assert portfolio.total_pnl == 0.0
        assert portfolio.total_trades == 0


class TestPaperTradingEngine:
    """Test PaperTradingEngine class."""

    def setup_method(self):
        """Reset engine before each test."""
        global _paper_engine
        _paper_engine = None

    def test_initialization(self):
        """Test engine initialization."""
        with patch('trading.paper_trading.get_live_price_feed') as mock_feed:
            mock_feed.return_value = Mock()
            engine = PaperTradingEngine(starting_balance=5000.0)
            assert engine.starting_balance == 5000.0
            assert len(engine.portfolios) == 0

    def test_get_portfolio_creates_new(self):
        """Test get_portfolio creates new portfolio."""
        with patch('trading.paper_trading.get_live_price_feed') as mock_feed:
            mock_feed.return_value = Mock()
            engine = PaperTradingEngine()
            portfolio = engine.get_portfolio("user_123")
            assert portfolio.user_id == "user_123"
            assert portfolio.starting_balance == 10000.0

    def test_get_portfolio_returns_existing(self):
        """Test get_portfolio returns existing portfolio."""
        with patch('trading.paper_trading.get_live_price_feed') as mock_feed:
            mock_feed.return_value = Mock()
            engine = PaperTradingEngine()
            portfolio1 = engine.get_portfolio("user_123")
            portfolio1.current_balance = 5000.0
            portfolio2 = engine.get_portfolio("user_123")
            assert portfolio2.current_balance == 5000.0

    def test_symbols_match_exact(self):
        """Test _symbols_match with exact match."""
        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        assert engine._symbols_match("BTC/USD", "BTC/USD") is True

    def test_symbols_match_base(self):
        """Test _symbols_match with base asset only."""
        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        assert engine._symbols_match("BTC", "BTC/USD") is True

    def test_symbols_match_no_match(self):
        """Test _symbols_match with no match."""
        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        assert engine._symbols_match("ETH", "BTC/USD") is False

    @patch('trading.paper_trading.get_live_price_feed')
    def test_place_order_insufficient_balance(self, mock_feed):
        """Test order rejected with insufficient balance."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine(starting_balance=100.0)
        order = engine.place_order(
            user_id="user_123",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        assert order.status == PaperOrderStatus.REJECTED

    @patch('trading.paper_trading.get_live_price_feed')
    def test_place_order_success(self, mock_feed):
        """Test successful order placement."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        engine.current_prices["BTC/USD"] = 50000.0
        engine.current_prices["BTC"] = 50000.0
        order = engine.place_order(
            user_id="user_123",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market",
            leverage=1
        )
        assert order.status == PaperOrderStatus.FILLED
        assert order.fill_price is not None

    @patch('trading.paper_trading.get_live_price_feed')
    def test_close_position_success(self, mock_feed):
        """Test successful position close."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        engine.current_prices["BTC/USD"] = 50000.0
        engine.current_prices["BTC"] = 50000.0

        # Open position
        engine.place_order("user_123", "BTC", "long", 1000.0, "market")

        # Get the actual position key from the portfolio
        portfolio = engine.get_portfolio("user_123")
        position_keys = list(portfolio.positions.keys())
        assert len(position_keys) > 0, "No positions created"

        # Close position using the actual key
        pnl = engine.close_position("user_123", position_keys[0])
        assert pnl is not None

    @patch('trading.paper_trading.get_live_price_feed')
    def test_close_position_not_found(self, mock_feed):
        """Test close position not found."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        pnl = engine.close_position("user_123", "NONEXISTENT")
        assert pnl is None

    @patch('trading.paper_trading.get_live_price_feed')
    def test_calculate_position_pnl_long(self, mock_feed):
        """Test P&L calculation for long position."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        engine.current_prices["BTC"] = 55000.0
        
        position = PaperPosition(
            position_id="pos_1",
            user_id="user_123",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            entry_price=50000.0,
            current_price=50000.0,
            leverage=1
        )
        
        pnl = engine._calculate_position_pnl(position)
        assert pnl > 0  # Price went up, should be profit

    @patch('trading.paper_trading.get_live_price_feed')
    def test_calculate_position_pnl_short(self, mock_feed):
        """Test P&L calculation for short position."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        engine.current_prices["BTC"] = 45000.0
        
        position = PaperPosition(
            position_id="pos_1",
            user_id="user_123",
            asset="BTC",
            side="short",
            size_usd=1000.0,
            entry_price=50000.0,
            current_price=50000.0,
            leverage=1
        )
        
        pnl = engine._calculate_position_pnl(position)
        assert pnl > 0  # Price went down, short should profit

    @patch('trading.paper_trading.get_live_price_feed')
    def test_get_portfolio_stats(self, mock_feed):
        """Test portfolio stats calculation."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        engine.current_prices["BTC"] = 50000.0
        
        # Open a position
        engine.place_order("user_123", "BTC", "long", 1000.0, "market")
        
        stats = engine.get_portfolio_stats("user_123")
        assert stats["user_id"] == "user_123"
        assert stats["starting_balance"] == 10000.0
        assert stats["open_positions"] == 1

    @patch('trading.paper_trading.get_live_price_feed')
    def test_get_global_stats(self, mock_feed):
        """Test global stats calculation."""
        mock_feed.return_value = Mock()
        engine = PaperTradingEngine()
        engine.current_prices["BTC"] = 50000.0
        engine.current_prices["ETH"] = 3000.0  # Set ETH price for order to succeed
        
        engine.place_order("user_1", "BTC", "long", 1000.0, "market")
        engine.place_order("user_2", "ETH", "long", 500.0, "market")
        
        stats = engine.get_global_stats()
        assert stats["accounts"] == 2
        assert stats["active_positions"] == 2


class TestGetPaperEngine:
    """Test get_paper_engine function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _paper_engine
        import trading.paper_trading as pt
        pt._paper_engine = None

    @patch('trading.paper_trading.get_live_price_feed')
    def test_singleton(self, mock_feed):
        """Test get_paper_engine returns singleton."""
        mock_feed.return_value = Mock()
        engine1 = get_paper_engine()
        engine2 = get_paper_engine()
        assert engine1 is engine2


class TestPaperTradingHandler:
    """Test paper_trading_handler function."""

    @patch('trading.paper_trading.get_paper_engine')
    def test_propose_order(self, mock_get_engine):
        """Test propose_order action."""
        mock_engine = Mock()
        mock_order = Mock()
        mock_order.order_id = "ord_123"
        mock_order.status.value = "filled"
        mock_order.fill_price = 50000.0
        mock_engine.place_order.return_value = mock_order
        mock_get_engine.return_value = mock_engine

        result = paper_trading_handler("propose_order", {
            "agent_id": "agent_1",
            "asset": "BTC",
            "side": "long",
            "size": 1000.0
        })

        assert result["paper_executed"] is True
        assert result["paper_order_id"] == "ord_123"

    @patch('trading.paper_trading.get_paper_engine')
    def test_close_position(self, mock_get_engine):
        """Test close_position action."""
        mock_engine = Mock()
        mock_engine.close_position.return_value = 100.0
        mock_get_engine.return_value = mock_engine

        result = paper_trading_handler("close_position", {
            "agent_id": "agent_1",
            "position_key": "BTC_long_perp"
        })

        assert result["paper_executed"] is True
        assert result["closed"] is True
        assert result["pnl"] == 100.0

    @patch('trading.paper_trading.get_paper_engine')
    def test_get_portfolio(self, mock_get_engine):
        """Test get_portfolio action."""
        mock_engine = Mock()
        mock_engine.get_portfolio_stats.return_value = {"equity": 11000.0}
        mock_get_engine.return_value = mock_engine

        result = paper_trading_handler("get_portfolio", {
            "agent_id": "agent_1"
        })

        assert result["paper_executed"] is True
        assert result["portfolio"]["equity"] == 11000.0

    def test_unknown_action(self):
        """Test unknown action type."""
        result = paper_trading_handler("unknown_action", {})
        assert result["paper_executed"] is False
        assert "error" in result
