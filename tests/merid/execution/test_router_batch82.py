"""Tests for merid/execution/router.py - Batch 82."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.router import (
    TraderIdentity, TradeIntent, ExecutionRouter
)


class TestTraderIdentity:
    """Tests for TraderIdentity dataclass."""

    def test_trader_identity_creation(self):
        """Test TraderIdentity creation."""
        identity = TraderIdentity(
            trader_type="human",
            trader_id="trader123",
            strategy="momentum"
        )
        assert identity.trader_type == "human"
        assert identity.trader_id == "trader123"
        assert identity.strategy == "momentum"


class TestTradeIntent:
    """Tests for TradeIntent dataclass."""

    def test_trade_intent_creation(self):
        """Test TradeIntent creation."""
        trader = TraderIdentity("agent", "agent456")
        intent = TradeIntent(
            intent_id="intent789",
            trader=trader,
            venue_id="binance",
            symbol="BTC-USD",
            side="buy",
            size=1.0
        )
        assert intent.intent_id == "intent789"
        assert intent.venue_id == "binance"
        assert intent.symbol == "BTC-USD"
        assert intent.side == "buy"
        assert intent.size == 1.0


class TestExecutionRouter:
    """Tests for ExecutionRouter."""

    def test_init_default(self):
        """Test initialization."""
        router = ExecutionRouter()
        assert router._executors == {}

    def test_register_executor(self):
        """Test register_executor."""
        router = ExecutionRouter()
        mock_executor = MagicMock()
        
        router.register_executor("binance", mock_executor)
        
        assert router._executors["binance"] is mock_executor

    def test_register_listener(self):
        """Test register_listener."""
        router = ExecutionRouter()
        mock_listener = MagicMock()
        
        router.register_listener(mock_listener)
        
        assert len(router._listeners) == 1
        assert router._listeners[0] is mock_listener
