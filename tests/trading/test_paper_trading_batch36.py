"""Tests for trading paper_trading module - Batch 36 Coverage."""
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
    get_paper_engine,
    paper_trading_handler,
)


class TestEnums:
    """Tests for paper trading enums."""

    def test_paper_order_status_values(self):
        assert PaperOrderStatus.PENDING.value == "pending"
        assert PaperOrderStatus.FILLED.value == "filled"
        assert PaperOrderStatus.CANCELLED.value == "cancelled"
        assert PaperOrderStatus.REJECTED.value == "rejected"

    def test_paper_order_type_values(self):
        assert PaperOrderType.MARKET.value == "market"
        assert PaperOrderType.LIMIT.value == "limit"
        assert PaperOrderType.STOP_LOSS.value == "stop_loss"


class TestPaperOrder:
    """Tests for PaperOrder dataclass."""

    @pytest.fixture
    def sample_order(self):
        return PaperOrder(
            order_id="order_123",
            user_id="user_456",
            asset="BTC",
            side="long",
            order_type=PaperOrderType.MARKET,
            size_usd=1000.0,
        )

    def test_order_creation(self, sample_order):
        assert sample_order.order_id == "order_123"
        assert sample_order.user_id == "user_456"
        assert sample_order.asset == "BTC"
        assert sample_order.side == "long"
        assert sample_order.order_type == PaperOrderType.MARKET
        assert sample_order.size_usd == 1000.0
        assert sample_order.status == PaperOrderStatus.PENDING
        assert sample_order.leverage == 1
        assert sample_order.market_type == "perp"

    def test_order_default_timestamps(self, sample_order):
        assert sample_order.created_at > 0


class TestPaperPosition:
    """Tests for PaperPosition dataclass."""

    @pytest.fixture
    def sample_position(self):
        return PaperPosition(
            position_id="pos_123",
            user_id="user_456",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            entry_price=50000.0,
            current_price=50000.0,
        )

    def test_position_creation(self, sample_position):
        assert sample_position.position_id == "pos_123"
        assert sample_position.user_id == "user_456"
        assert sample_position.asset == "BTC"
        assert sample_position.side == "long"
        assert sample_position.size_usd == 1000.0
        assert sample_position.entry_price == 50000.0
        assert sample_position.unrealized_pnl == 0.0
        assert sample_position.realized_pnl == 0.0

    def test_position_default_timestamps(self, sample_position):
        assert sample_position.opened_at > 0


class TestPaperPortfolio:
    """Tests for PaperPortfolio dataclass."""

    def test_portfolio_creation(self):
        portfolio = PaperPortfolio(user_id="user_123")
        assert portfolio.user_id == "user_123"
        assert portfolio.starting_balance == 10000.0
        assert portfolio.current_balance == 10000.0
        assert portfolio.total_pnl == 0.0
        assert portfolio.total_trades == 0
        assert portfolio.winning_trades == 0
        assert portfolio.losing_trades == 0
        assert portfolio.positions == {}
        assert portfolio.orders == {}
        assert portfolio.trade_history == []


class TestPaperTradingEngine:
    """Tests for PaperTradingEngine class."""

    @pytest.fixture
    def engine(self):
        with patch('trading.paper_trading.get_live_price_feed'):
            return PaperTradingEngine(starting_balance=10000.0)

    def test_initialization(self, engine):
        assert engine.starting_balance == 10000.0
        assert engine.portfolios == {}
        assert engine.order_counter == 0
        assert engine.position_counter == 0
        assert engine.current_prices == {}

    def test_get_portfolio_new(self, engine):
        portfolio = engine.get_portfolio("user_123")
        assert portfolio.user_id == "user_123"
        assert portfolio.starting_balance == 10000.0
        assert "user_123" in engine.portfolios

    def test_get_portfolio_existing(self, engine):
        portfolio1 = engine.get_portfolio("user_123")
        portfolio2 = engine.get_portfolio("user_123")
        assert portfolio1 is portfolio2

    def test_symbols_match_exact(self, engine):
        assert engine._symbols_match("BTC/USDT", "BTC/USDT") is True

    def test_symbols_match_base(self, engine):
        assert engine._symbols_match("BTC", "BTC/USDT") is True

    def test_symbols_match_different(self, engine):
        assert engine._symbols_match("BTC", "ETH/USDT") is False

    def test_place_order_market(self, engine):
        engine.current_prices["BTC"] = 50000.0
        order = engine.place_order("user_123", "BTC", "long", 1000.0)
        
        assert order.status == PaperOrderStatus.FILLED
        assert order.fill_price is not None
        assert order.filled_size == 1000.0

    def test_place_order_insufficient_balance(self, engine):
        order = engine.place_order("user_123", "BTC", "long", 20000.0)
        assert order.status == PaperOrderStatus.REJECTED

    def test_place_order_limit(self, engine):
        order = engine.place_order("user_123", "BTC", "long", 1000.0, order_type="limit", price=48000.0)
        assert order.status == PaperOrderStatus.PENDING
        assert order.order_type == PaperOrderType.LIMIT

    def test_close_position_success(self, engine):
        engine.current_prices["BTC"] = 50000.0
        engine.place_order("user_123", "BTC", "long", 1000.0)

        portfolio = engine.get_portfolio("user_123")
        position_keys = list(portfolio.positions.keys())
        assert len(position_keys) > 0
        pnl = engine.close_position("user_123", position_keys[0])
        assert pnl is not None

    def test_close_position_not_found(self, engine):
        pnl = engine.close_position("user_123", "NONEXISTENT")
        assert pnl is None

    def test_get_portfolio_stats_empty(self, engine):
        stats = engine.get_portfolio_stats("user_123")
        assert stats["user_id"] == "user_123"
        assert stats["starting_balance"] == 10000.0
        assert stats["total_trades"] == 0
        assert stats["win_rate_pct"] == 0.0

    def test_get_portfolio_stats_with_trades(self, engine):
        engine.current_prices["BTC"] = 50000.0
        engine.place_order("user_123", "BTC", "long", 1000.0)
        
        stats = engine.get_portfolio_stats("user_123")
        assert stats["total_trades"] == 1
        assert stats["open_positions"] == 1

    def test_get_global_stats_empty(self, engine):
        stats = engine.get_global_stats()
        assert stats["accounts"] == 0
        assert stats["cash"] == 0.0
        assert stats["active_positions"] == 0

    def test_get_global_stats_with_data(self, engine):
        engine.current_prices["BTC"] = 50000.0
        engine.place_order("user_123", "BTC", "long", 1000.0)
        
        stats = engine.get_global_stats()
        assert stats["accounts"] == 1
        assert stats["active_positions"] == 1

    def test_get_recent_trades_empty(self, engine):
        trades = engine.get_recent_trades()
        assert trades == []

    def test_get_recent_trades_with_orders(self, engine):
        engine.current_prices["BTC"] = 50000.0
        engine.place_order("user_123", "BTC", "long", 1000.0)
        
        trades = engine.get_recent_trades()
        assert len(trades) == 1
        assert trades[0]["asset"] == "BTC"

    def test_update_prices(self, engine):
        engine.update_prices({"BTC": 51000.0})
        assert engine.current_prices["BTC"] == 51000.0


class TestPaperTradingHandler:
    """Tests for paper_trading_handler function."""

    @pytest.fixture
    def engine(self):
        with patch('trading.paper_trading.get_live_price_feed'):
            # Reset singleton
            import trading.paper_trading as pt_module
            pt_module._paper_engine = None
            return get_paper_engine()

    def test_handler_propose_order(self, engine):
        engine.current_prices["BTC"] = 50000.0
        result = paper_trading_handler("propose_order", {
            "agent_id": "test_agent",
            "asset": "BTC",
            "side": "long",
            "size": 1000.0,
        })
        
        assert result["paper_executed"] is True
        assert "paper_order_id" in result
        assert result["status"] == "filled"

    def test_handler_get_portfolio(self, engine):
        result = paper_trading_handler("get_portfolio", {
            "agent_id": "test_agent",
        })
        
        assert result["paper_executed"] is True
        assert "portfolio" in result

    def test_handler_unknown_action(self, engine):
        result = paper_trading_handler("unknown_action", {})
        
        assert result["paper_executed"] is False
        assert "error" in result


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_paper_engine(self):
        # Reset singleton
        import trading.paper_trading as pt_module
        pt_module._paper_engine = None

        with patch('trading.paper_trading.get_live_price_feed'):
            engine1 = get_paper_engine()
            engine2 = get_paper_engine()
            assert engine1 is engine2
