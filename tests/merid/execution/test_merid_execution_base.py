"""Tests for merid/execution/base.py."""
import pytest
from dataclasses import dataclass
from merid.execution.base import Quote, Position, TradeResult, TradeExecutor, TradeSideLiteral


class TestQuote:
    """Test Quote dataclass."""

    def test_creation(self):
        """Test Quote creation."""
        quote = Quote(
            symbol="BTC-USD",
            side="buy",
            price=50000.0,
            venue="coinbase",
            size=1.0,
            latency_ms=100.0,
            metadata={"source": "api"}
        )
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 50000.0
        assert quote.venue == "coinbase"
        assert quote.size == 1.0
        assert quote.latency_ms == 100.0
        assert quote.metadata == {"source": "api"}

    def test_default_metadata(self):
        """Test Quote with default metadata."""
        quote = Quote(
            symbol="ETH-USD",
            side="sell",
            price=3000.0,
            venue="kraken",
            size=2.0
        )
        assert quote.metadata == {}
        assert quote.latency_ms is None


class TestPosition:
    """Test Position dataclass."""

    def test_creation(self):
        """Test Position creation."""
        position = Position(
            symbol="BTC-USD",
            size=1.5,
            entry_price=45000.0,
            pnl=5000.0,
            venue="coinbase",
            leverage=2.0,
            metadata={"opened_at": "2024-01-01"}
        )
        assert position.symbol == "BTC-USD"
        assert position.size == 1.5
        assert position.entry_price == 45000.0
        assert position.pnl == 5000.0
        assert position.venue == "coinbase"
        assert position.leverage == 2.0
        assert position.metadata == {"opened_at": "2024-01-01"}

    def test_optional_fields(self):
        """Test Position with optional fields defaulted."""
        position = Position(
            symbol="ETH-USD",
            size=10.0,
            entry_price=2000.0,
            pnl=-500.0,
            venue="kraken"
        )
        assert position.leverage is None
        assert position.metadata == {}


class TestTradeResult:
    """Test TradeResult dataclass."""

    def test_success_result(self):
        """Test successful trade result."""
        result = TradeResult(
            success=True,
            venue="coinbase",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
            price=50000.0,
            tx_id="tx_123",
            metadata={"order_id": "ord_456"}
        )
        assert result.success is True
        assert result.venue == "coinbase"
        assert result.tx_id == "tx_123"
        assert result.error is None

    def test_failed_result(self):
        """Test failed trade result."""
        result = TradeResult(
            success=False,
            venue="kraken",
            symbol="ETH-USD",
            side="sell",
            size=2.0,
            price=0.0,
            error="Insufficient funds",
            explanation_id="exp_789"
        )
        assert result.success is False
        assert result.error == "Insufficient funds"
        assert result.explanation_id == "exp_789"


class TestTradeExecutor:
    """Test TradeExecutor abstract class."""

    def test_cannot_instantiate(self):
        """Test TradeExecutor cannot be instantiated directly."""
        with pytest.raises(TypeError):
            TradeExecutor()

    def test_subclass_must_implement(self):
        """Test subclass must implement abstract methods."""
        class IncompleteExecutor(TradeExecutor):
            venue = "test"

        with pytest.raises(TypeError):
            IncompleteExecutor()
