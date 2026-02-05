"""Tests for paper trading module - Batch 14 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time

from trading.paper_trading import (
    PaperOrderStatus,
    PaperOrderType,
    PaperOrder,
    PaperPosition,
    PaperPortfolio,
    PaperTradingEngine,
    get_paper_engine
)


class TestPaperOrderStatus:
    """Tests for PaperOrderStatus enum."""

    def test_all_statuses_exist(self):
        """Test all order statuses defined."""
        assert PaperOrderStatus.PENDING.value == "pending"
        assert PaperOrderStatus.FILLED.value == "filled"
        assert PaperOrderStatus.CANCELLED.value == "cancelled"
        assert PaperOrderStatus.REJECTED.value == "rejected"


class TestPaperOrderType:
    """Tests for PaperOrderType enum."""

    def test_all_types_exist(self):
        """Test all order types defined."""
        assert PaperOrderType.MARKET.value == "market"
        assert PaperOrderType.LIMIT.value == "limit"
        assert PaperOrderType.STOP_LOSS.value == "stop_loss"


class TestPaperOrder:
    """Tests for PaperOrder dataclass."""

    def test_order_creation(self):
        """Test creating paper order."""
        order = PaperOrder(
            order_id="order_123",
            user_id="user_456",
            asset="BTCUSDT",
            side="long",
            order_type=PaperOrderType.MARKET,
            size_usd=1000.0,
            leverage=2
        )
        assert order.order_id == "order_123"
        assert order.user_id == "user_456"
        assert order.asset == "BTCUSDT"
        assert order.side == "long"
        assert order.status == PaperOrderStatus.PENDING
        assert order.leverage == 2

    def test_order_defaults(self):
        """Test order default values."""
        order = PaperOrder(
            order_id="order_123",
            user_id="user_456",
            asset="ETHUSDT",
            side="short",
            order_type=PaperOrderType.LIMIT,
            size_usd=500.0
        )
        assert order.leverage == 1
        assert order.price is None
        assert order.filled_size == 0.0


class TestPaperPosition:
    """Tests for PaperPosition dataclass."""

    def test_position_creation(self):
        """Test creating paper position."""
        position = PaperPosition(
            position_id="pos_123",
            user_id="user_456",
            asset="BTCUSDT",
            side="long",
            size_usd=1000.0,
            entry_price=45000.0,
            current_price=45000.0,
            leverage=2
        )
        assert position.position_id == "pos_123"
        assert position.asset == "BTCUSDT"
        assert position.size_usd == 1000.0


class TestPaperPortfolio:
    """Tests for PaperPortfolio dataclass."""

    def test_portfolio_creation(self):
        """Test creating paper portfolio."""
        portfolio = PaperPortfolio(
            user_id="user_123",
            starting_balance=10000.0,
            current_balance=10000.0
        )
        assert portfolio.user_id == "user_123"
        assert portfolio.starting_balance == 10000.0

    def test_portfolio_defaults(self):
        """Test portfolio default values."""
        portfolio = PaperPortfolio(user_id="user_123")
        assert portfolio.starting_balance == 10000.0
        assert len(portfolio.positions) == 0


class TestPaperTradingEngine:
    """Tests for PaperTradingEngine."""

    @pytest.fixture
    def engine(self):
        """Create paper trading engine."""
        with patch('trading.paper_trading.get_live_price_feed') as mock_feed:
            mock_feed.return_value = MagicMock()
            return PaperTradingEngine(starting_balance=10000.0)

    def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine.starting_balance == 10000.0
        assert len(engine.portfolios) == 0

    def test_get_portfolio_new_user(self, engine):
        """Test getting portfolio for new user."""
        portfolio = engine.get_portfolio("user_123")
        assert portfolio.user_id == "user_123"
        assert portfolio.current_balance == 10000.0

    def test_symbols_match_exact(self, engine):
        """Test symbol matching - exact match."""
        assert engine._symbols_match("BTC/USDT", "BTC/USDT") is True

    def test_symbols_match_base(self, engine):
        """Test symbol matching - base asset match."""
        assert engine._symbols_match("BTC", "BTC/USDT") is True

    def test_get_global_stats_empty(self, engine):
        """Test global stats with no portfolios."""
        stats = engine.get_global_stats()
        assert stats["accounts"] == 0
        assert stats["cash"] == 0.0

    def test_place_order_market(self, engine):
        """Test placing market order."""
        engine.current_prices = {"BTCUSDT": 45000.0}
        
        order = engine.place_order(
            user_id="user_123",
            asset="BTCUSDT",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        assert order.status == PaperOrderStatus.FILLED
        assert order.fill_price is not None

    def test_place_order_insufficient_balance(self, engine):
        """Test placing order with insufficient balance."""
        portfolio = engine.get_portfolio("user_123")
        portfolio.current_balance = 100.0
        
        order = engine.place_order(
            user_id="user_123",
            asset="BTCUSDT",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        assert order.status == PaperOrderStatus.REJECTED

    def test_position_created_after_order(self, engine):
        """Test position created after market order."""
        engine.current_prices = {"BTCUSDT": 45000.0}
        
        order = engine.place_order(
            user_id="user_123",
            asset="BTCUSDT",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        portfolio = engine.get_portfolio("user_123")
        assert "BTCUSDT_long_perp" in portfolio.positions

    def test_close_position(self, engine):
        """Test closing position."""
        engine.current_prices = {"BTCUSDT": 45000.0}
        
        engine.place_order(
            user_id="user_123",
            asset="BTCUSDT",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        pnl = engine.close_position("user_123", "BTCUSDT_long_perp")
        assert pnl is not None

    def test_close_nonexistent_position(self, engine):
        """Test closing non-existent position."""
        pnl = engine.close_position("user_123", "NONEXISTENT")
        assert pnl is None


class TestGetPaperEngine:
    """Tests for get_paper_engine singleton."""

    def test_singleton_creation(self):
        """Test singleton is created."""
        with patch('trading.paper_trading.get_live_price_feed') as mock_feed:
            mock_feed.return_value = MagicMock()
            
            engine1 = get_paper_engine()
            engine2 = get_paper_engine()
            
            assert engine1 is engine2
