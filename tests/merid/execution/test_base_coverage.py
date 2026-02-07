"""Comprehensive tests for merid/execution/base.py - Coverage improvement."""

import pytest
from dataclasses import asdict

from merid.execution.base import Quote, Position, TradeResult, TradeExecutor


# =============================================================================
# Quote Dataclass Tests
# =============================================================================

class TestQuote:
    """Test Quote dataclass."""

    def test_creation(self):
        quote = Quote(
            symbol="BTC/USD",
            side="buy",
            price=50000.0,
            venue="test_venue",
            size=1.0
        )
        
        assert quote.symbol == "BTC/USD"
        assert quote.side == "buy"
        assert quote.price == 50000.0
        assert quote.venue == "test_venue"
        assert quote.size == 1.0

    def test_defaults(self):
        quote = Quote(
            symbol="ETH/USD",
            side="sell",
            price=3000.0,
            venue="test",
            size=10.0
        )
        
        assert quote.latency_ms is None
        assert quote.metadata == {}

    def test_with_metadata(self):
        quote = Quote(
            symbol="SOL/USD",
            side="buy",
            price=100.0,
            venue="jupiter",
            size=50.0,
            latency_ms=15.5,
            metadata={"quote_id": "123"}
        )
        
        assert quote.latency_ms == 15.5
        assert quote.metadata["quote_id"] == "123"


# =============================================================================
# Position Dataclass Tests
# =============================================================================

class TestPosition:
    """Test Position dataclass."""

    def test_creation(self):
        position = Position(
            symbol="BTC/USD",
            size=1.5,
            entry_price=48000.0,
            pnl=3000.0,
            venue="alpaca"
        )
        
        assert position.symbol == "BTC/USD"
        assert position.size == 1.5
        assert position.entry_price == 48000.0
        assert position.pnl == 3000.0
        assert position.venue == "alpaca"

    def test_defaults(self):
        position = Position(
            symbol="ETH/USD",
            size=10.0,
            entry_price=2800.0,
            pnl=200.0,
            venue="coinbase"
        )
        
        assert position.leverage is None
        assert position.metadata == {}

    def test_with_leverage(self):
        position = Position(
            symbol="BTC-PERP",
            size=0.1,
            entry_price=50000.0,
            pnl=-50.0,
            venue="hyperliquid",
            leverage=10.0,
            metadata={"position_id": "pos_123"}
        )
        
        assert position.leverage == 10.0
        assert position.metadata["position_id"] == "pos_123"


# =============================================================================
# TradeResult Dataclass Tests
# =============================================================================

class TestTradeResult:
    """Test TradeResult dataclass."""

    def test_successful_trade(self):
        result = TradeResult(
            success=True,
            venue="alpaca",
            symbol="AAPL",
            side="buy",
            size=10.0,
            price=150.0,
            tx_id="order_123"
        )
        
        assert result.success is True
        assert result.venue == "alpaca"
        assert result.tx_id == "order_123"

    def test_failed_trade(self):
        result = TradeResult(
            success=False,
            venue="coinbase",
            symbol="BTC/USD",
            side="sell",
            size=0.5,
            price=0.0,
            error="Insufficient funds"
        )
        
        assert result.success is False
        assert result.error == "Insufficient funds"

    def test_defaults(self):
        result = TradeResult(
            success=True,
            venue="test",
            symbol="ETH",
            side="buy",
            size=1.0,
            price=3000.0
        )
        
        assert result.tx_id is None
        assert result.error is None
        assert result.explanation_id is None
        assert result.metadata == {}

    def test_with_explanation(self):
        result = TradeResult(
            success=True,
            venue="jupiter",
            symbol="SOL/USDC",
            side="buy",
            size=100.0,
            price=150.0,
            explanation_id="exp_456",
            metadata={"strategy": "momentum"}
        )
        
        assert result.explanation_id == "exp_456"
        assert result.metadata["strategy"] == "momentum"


# =============================================================================
# TradeExecutor Abstract Base Class Tests
# =============================================================================

class TestTradeExecutor:
    """Test TradeExecutor abstract base class."""

    def test_is_abstract(self):
        # TradeExecutor should not be instantiable directly
        with pytest.raises(TypeError):
            TradeExecutor()

    def test_concrete_implementation(self):
        class ConcreteExecutor(TradeExecutor):
            venue = "test_venue"
            
            async def get_quote(self, symbol, side, amount):
                return Quote(
                    symbol=symbol,
                    side=side,
                    price=100.0,
                    venue=self.venue,
                    size=amount
                )
            
            async def execute_trade(self, symbol, side, amount, *, order_type="market", price=None, metadata=None):
                return TradeResult(
                    success=True,
                    venue=self.venue,
                    symbol=symbol,
                    side=side,
                    size=amount,
                    price=price or 100.0
                )
            
            async def get_positions(self):
                return []
        
        executor = ConcreteExecutor()
        assert executor.venue == "test_venue"

    @pytest.mark.asyncio
    async def test_concrete_executor_methods(self):
        class TestExecutor(TradeExecutor):
            venue = "test"
            
            async def get_quote(self, symbol, side, amount):
                return Quote(symbol=symbol, side=side, price=50.0, venue=self.venue, size=amount)
            
            async def execute_trade(self, symbol, side, amount, *, order_type="market", price=None, metadata=None):
                return TradeResult(success=True, venue=self.venue, symbol=symbol, side=side, size=amount, price=50.0)
            
            async def get_positions(self):
                return [Position(symbol="BTC", size=1.0, entry_price=50000.0, pnl=0.0, venue=self.venue)]
        
        executor = TestExecutor()
        
        quote = await executor.get_quote("BTC", "buy", 1.0)
        assert quote.price == 50.0
        
        result = await executor.execute_trade("BTC", "buy", 1.0)
        assert result.success is True
        
        positions = await executor.get_positions()
        assert len(positions) == 1
