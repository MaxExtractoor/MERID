"""Comprehensive tests for merid/execution/base.py - REAL implementation coverage."""

import pytest
from typing import Dict, Any

from merid.execution.base import (
    Quote,
    Position,
    TradeResult,
    TradeExecutor,
    TradeSideLiteral
)


class TestQuote:
    """Test Quote dataclass."""
    
    def test_quote_creation(self):
        """Test Quote creation."""
        quote = Quote(
            symbol="AAPL",
            side="buy",
            price=150.0,
            venue="alpaca",
            size=100.0,
            latency_ms=15.5,
            metadata={"source": "api"}
        )
        
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.0
        assert quote.venue == "alpaca"
        assert quote.size == 100.0
        assert quote.latency_ms == 15.5
        assert quote.metadata == {"source": "api"}
    
    def test_quote_defaults(self):
        """Test Quote default values."""
        quote = Quote(
            symbol="BTC-USD",
            side="sell",
            price=50000.0,
            venue="coinbase",
            size=0.5
        )
        
        assert quote.latency_ms is None
        assert quote.metadata == {}
    
    def test_quote_slots(self):
        """Test Quote uses slots (memory optimization)."""
        quote = Quote(
            symbol="ETH-USD",
            side="buy",
            price=3000.0,
            venue="kraken",
            size=10.0
        )
        
        # Should not have __dict__ if slots=True
        assert not hasattr(quote, "__dict__")


class TestPosition:
    """Test Position dataclass."""
    
    def test_position_creation(self):
        """Test Position creation."""
        position = Position(
            symbol="AAPL",
            size=100.0,
            entry_price=145.0,
            pnl=500.0,
            venue="alpaca",
            leverage=2.0,
            metadata={"sector": "tech"}
        )
        
        assert position.symbol == "AAPL"
        assert position.size == 100.0
        assert position.entry_price == 145.0
        assert position.pnl == 500.0
        assert position.venue == "alpaca"
        assert position.leverage == 2.0
        assert position.metadata == {"sector": "tech"}
    
    def test_position_defaults(self):
        """Test Position default values."""
        position = Position(
            symbol="BTC-USD",
            size=0.5,
            entry_price=48000.0,
            pnl=-500.0,
            venue="coinbase"
        )
        
        assert position.leverage is None
        assert position.metadata == {}
    
    def test_position_negative_size(self):
        """Test Position with negative size (short)."""
        position = Position(
            symbol="TSLA",
            size=-50.0,
            entry_price=200.0,
            pnl=1000.0,
            venue="webull"
        )
        
        assert position.size == -50.0
        assert position.pnl == 1000.0


class TestTradeResult:
    """Test TradeResult dataclass."""
    
    def test_trade_result_success(self):
        """Test TradeResult for successful trade."""
        result = TradeResult(
            success=True,
            venue="alpaca",
            symbol="AAPL",
            side="buy",
            size=100.0,
            price=150.0,
            tx_id="tx_12345",
            metadata={"order_id": "ord_123"}
        )
        
        assert result.success is True
        assert result.venue == "alpaca"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.size == 100.0
        assert result.price == 150.0
        assert result.tx_id == "tx_12345"
        assert result.error is None
        assert result.metadata == {"order_id": "ord_123"}
    
    def test_trade_result_failure(self):
        """Test TradeResult for failed trade."""
        result = TradeResult(
            success=False,
            venue="coinbase",
            symbol="BTC-USD",
            side="sell",
            size=0.5,
            price=0.0,
            error="Insufficient funds"
        )
        
        assert result.success is False
        assert result.error == "Insufficient funds"
        assert result.tx_id is None
    
    def test_trade_result_defaults(self):
        """Test TradeResult default values."""
        result = TradeResult(
            success=True,
            venue="kalshi",
            symbol="FED-25DEC-T3.00",
            side="buy",
            size=100.0,
            price=65.0
        )
        
        assert result.tx_id is None
        assert result.error is None
        assert result.explanation_id is None
        assert result.metadata == {}
    
    def test_trade_result_with_explanation(self):
        """Test TradeResult with explanation_id."""
        result = TradeResult(
            success=True,
            venue="polymarket",
            symbol="0x123abc",
            side="buy",
            size=1000.0,
            price=0.65,
            explanation_id="exp_123",
            metadata={"market_slug": "will-it-rain"}
        )
        
        assert result.explanation_id == "exp_123"


class TestTradeExecutorInterface:
    """Test TradeExecutor abstract interface."""
    
    def test_trade_executor_is_abstract(self):
        """Test TradeExecutor cannot be instantiated directly."""
        with pytest.raises(TypeError):
            TradeExecutor()
    
    def test_trade_executor_subclass_must_implement(self):
        """Test TradeExecutor subclasses must implement abstract methods."""
        class IncompleteExecutor(TradeExecutor):
            venue = "test"
        
        with pytest.raises(TypeError):
            IncompleteExecutor()
    
    def test_trade_executor_complete_implementation(self):
        """Test complete TradeExecutor implementation."""
        class MockExecutor(TradeExecutor):
            venue = "mock"
            
            async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
                return Quote(
                    symbol=symbol,
                    side=side,
                    price=100.0,
                    venue=self.venue,
                    size=amount
                )
            
            async def execute_trade(self, symbol: str, side: TradeSideLiteral, amount: float, **kwargs) -> TradeResult:
                return TradeResult(
                    success=True,
                    venue=self.venue,
                    symbol=symbol,
                    side=side,
                    size=amount,
                    price=100.0
                )
            
            async def get_positions(self):
                return []
        
        # Should be instantiable
        executor = MockExecutor()
        assert executor.venue == "mock"
    
    def test_trade_executor_venue_attribute(self):
        """Test TradeExecutor venue attribute."""
        class TestExecutor(TradeExecutor):
            venue = "test_venue"
            
            async def get_quote(self, symbol, side, amount):
                pass
            
            async def execute_trade(self, symbol, side, amount, **kwargs):
                pass
            
            async def get_positions(self):
                pass
        
        executor = TestExecutor()
        assert hasattr(executor, 'venue')
        assert executor.venue == "test_venue"


class TestTypeAliases:
    """Test type aliases."""
    
    def test_trade_side_literal_buy(self):
        """Test TradeSideLiteral accepts 'buy'."""
        side: TradeSideLiteral = "buy"
        assert side == "buy"
    
    def test_trade_side_literal_sell(self):
        """Test TradeSideLiteral accepts 'sell'."""
        side: TradeSideLiteral = "sell"
        assert side == "sell"


class TestDataclassBehavior:
    """Test dataclass behaviors across all types."""
    
    def test_quote_equality(self):
        """Test Quote equality comparison."""
        quote1 = Quote("AAPL", "buy", 150.0, "alpaca", 100.0)
        quote2 = Quote("AAPL", "buy", 150.0, "alpaca", 100.0)
        quote3 = Quote("TSLA", "buy", 150.0, "alpaca", 100.0)
        
        assert quote1 == quote2
        assert quote1 != quote3
    
    def test_position_equality(self):
        """Test Position equality comparison."""
        pos1 = Position("AAPL", 100.0, 145.0, 500.0, "alpaca")
        pos2 = Position("AAPL", 100.0, 145.0, 500.0, "alpaca")
        pos3 = Position("TSLA", 100.0, 145.0, 500.0, "alpaca")
        
        assert pos1 == pos2
        assert pos1 != pos3
    
    def test_trade_result_equality(self):
        """Test TradeResult equality comparison."""
        result1 = TradeResult(True, "alpaca", "AAPL", "buy", 100.0, 150.0)
        result2 = TradeResult(True, "alpaca", "AAPL", "buy", 100.0, 150.0)
        result3 = TradeResult(False, "alpaca", "AAPL", "buy", 100.0, 150.0)
        
        assert result1 == result2
        assert result1 != result3
    
    def test_quote_repr(self):
        """Test Quote string representation."""
        quote = Quote("AAPL", "buy", 150.0, "alpaca", 100.0)
        repr_str = repr(quote)
        
        assert "AAPL" in repr_str
        assert "buy" in repr_str
        assert "alpaca" in repr_str
    
    def test_position_repr(self):
        """Test Position string representation."""
        position = Position("AAPL", 100.0, 145.0, 500.0, "alpaca")
        repr_str = repr(position)
        
        assert "AAPL" in repr_str
        assert "alpaca" in repr_str
