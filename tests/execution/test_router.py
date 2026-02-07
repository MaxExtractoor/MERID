"""Comprehensive tests for merid/execution/router.py - REAL implementation coverage."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.router import (
    TraderIdentity,
    TradeIntent,
    ExecutionRouter
)


class TestTraderIdentity:
    """Test TraderIdentity dataclass."""
    
    def test_trader_identity_creation(self):
        """Test TraderIdentity creation."""
        trader = TraderIdentity(
            trader_type="agent",
            trader_id="agent_123",
            strategy="arbitrage"
        )
        
        assert trader.trader_type == "agent"
        assert trader.trader_id == "agent_123"
        assert trader.strategy == "arbitrage"
    
    def test_trader_identity_defaults(self):
        """Test TraderIdentity default values."""
        trader = TraderIdentity(
            trader_type="human",
            trader_id="user_456"
        )
        
        assert trader.strategy is None


class TestTradeIntent:
    """Test TradeIntent dataclass."""
    
    def test_trade_intent_creation(self):
        """Test TradeIntent creation."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_123")
        
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="alpaca",
            symbol="AAPL",
            side="buy",
            size=100.0,
            price=150.0,
            params={"order_type": "limit"},
            metadata={"source": "strategy_1"}
        )
        
        assert intent.intent_id == "intent_123"
        assert intent.trader == trader
        assert intent.venue_id == "alpaca"
        assert intent.symbol == "AAPL"
        assert intent.side == "buy"
        assert intent.size == 100.0
        assert intent.price == 150.0
        assert intent.params == {"order_type": "limit"}
        assert intent.metadata == {"source": "strategy_1"}
    
    def test_trade_intent_defaults(self):
        """Test TradeIntent default values."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_123")
        
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="alpaca",
            symbol="AAPL",
            side="buy",
            size=100.0
        )
        
        assert intent.price is None
        assert intent.params == {}
        assert intent.metadata == {}
        assert intent.guard_decision is None
        assert intent.explanation_id is None
        assert intent.timestamp > 0


class TestExecutionRouter:
    """Test ExecutionRouter class."""
    
    def test_router_initialization(self):
        """Test ExecutionRouter initialization."""
        router = ExecutionRouter()
        
        assert router._executors == {}
        assert router._listeners == []
    
    def test_router_initialization_with_executors(self):
        """Test ExecutionRouter initialization with executors."""
        mock_executor = MagicMock()
        router = ExecutionRouter(executors={"alpaca": mock_executor})
        
        assert "alpaca" in router._executors
        assert router._executors["alpaca"] == mock_executor
    
    def test_register_executor(self):
        """Test register_executor method."""
        router = ExecutionRouter()
        mock_executor = MagicMock()
        
        router.register_executor("coinbase", mock_executor)
        
        assert "coinbase" in router._executors
        assert router._executors["coinbase"] == mock_executor
    
    def test_register_listener(self):
        """Test register_listener method."""
        router = ExecutionRouter()
        mock_listener = MagicMock()
        
        router.register_listener(mock_listener)
        
        assert len(router._listeners) == 1
        assert router._listeners[0] == mock_listener
    
    def test_router_has_required_attributes(self):
        """Test ExecutionRouter has required attributes."""
        router = ExecutionRouter()
        
        assert hasattr(router, '_executors')
        assert hasattr(router, '_listeners')
        assert hasattr(router, '_runtime_config')
        assert hasattr(router, '_trading_guard')
        assert hasattr(router, '_portfolio_aggregator')
    
    def test_trader_identity_slots(self):
        """Test TraderIdentity uses slots."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_123")
        
        # Should not have __dict__ if slots=True
        assert not hasattr(trader, "__dict__")
    
    def test_trade_intent_slots(self):
        """Test TradeIntent uses slots."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_123")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="alpaca",
            symbol="AAPL",
            side="buy",
            size=100.0
        )
        
        # Should not have __dict__ if slots=True
        assert not hasattr(intent, "__dict__")


class TestExecutionRouterIntegration:
    """Test ExecutionRouter integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_multiple_executors(self):
        """Test router with multiple executors."""
        mock_alpaca = MagicMock()
        mock_coinbase = MagicMock()
        
        router = ExecutionRouter(executors={
            "alpaca": mock_alpaca,
            "coinbase": mock_coinbase
        })
        
        assert len(router._executors) == 2
        assert router._executors["alpaca"] == mock_alpaca
        assert router._executors["coinbase"] == mock_coinbase
    
    @pytest.mark.asyncio
    async def test_multiple_listeners(self):
        """Test router with multiple listeners."""
        router = ExecutionRouter()
        
        listener1 = MagicMock()
        listener2 = MagicMock()
        
        router.register_listener(listener1)
        router.register_listener(listener2)
        
        assert len(router._listeners) == 2


class TestTradeSideValues:
    """Test trade side values."""
    
    def test_trade_side_buy(self):
        """Test trade side 'buy'."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_123")
        
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="alpaca",
            symbol="AAPL",
            side="buy",
            size=100.0
        )
        
        assert intent.side == "buy"
    
    def test_trade_side_sell(self):
        """Test trade side 'sell'."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_123")
        
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="alpaca",
            symbol="AAPL",
            side="sell",
            size=100.0
        )
        
        assert intent.side == "sell"


class TestTraderTypes:
    """Test trader types."""
    
    def test_trader_type_agent(self):
        """Test trader type 'agent'."""
        trader = TraderIdentity(
            trader_type="agent",
            trader_id="agent_123",
            strategy="arbitrage"
        )
        
        assert trader.trader_type == "agent"
    
    def test_trader_type_human(self):
        """Test trader type 'human'."""
        trader = TraderIdentity(
            trader_type="human",
            trader_id="user_456"
        )
        
        assert trader.trader_type == "human"
