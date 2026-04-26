"""Tests for signal_router — ensuring signal-only agents can route to trading_agent.

SINGLE EXECUTOR PRINCIPLE: Only trading_agent can execute trades.
Signal-only agents must use signal_router to send signals downstream.
"""

import pytest
import asyncio
from datetime import datetime, timezone

from merid.event_venues.kalshi.signal_router import (
    AgentSignal,
    SignalRouter,
    get_signal_router,
    submit_signal,
)


class TestAgentSignal:
    """Test AgentSignal dataclass."""
    
    def test_agent_signal_creation(self):
        """AgentSignal should be created with required fields."""
        signal = AgentSignal(
            agent_id="lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            side="yes",
            size=10,
            price_cents=52,
            confidence=0.75,
            edge=0.05,
            reasoning="Bullish breakout",
        )
        
        assert signal.agent_id == "lane_001"
        assert signal.agent_type == "btc15m_lane"
        assert signal.market_id == "KXBTC-15M-250102"
        assert signal.action == "buy"
        assert signal.side == "yes"
        assert signal.size == 10
        assert signal.price_cents == 52
        assert signal.confidence == 0.75
        assert signal.edge == 0.05
        assert signal.reasoning == "Bullish breakout"
        assert signal.signal_id.startswith("sig-")
        assert isinstance(signal.timestamp, datetime)
    
    def test_agent_signal_to_dict(self):
        """AgentSignal should serialize to dict."""
        signal = AgentSignal(
            agent_id="lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            side="yes",
            size=10,
            price_cents=52,
            confidence=0.75,
            edge=0.05,
            reasoning="Bullish breakout",
        )
        
        d = signal.to_dict()
        assert d["agent_id"] == "lane_001"
        assert d["agent_type"] == "btc15m_lane"
        assert d["market_id"] == "KXBTC-15M-250102"
        assert d["action"] == "buy"
        assert d["side"] == "yes"
        assert d["size"] == 10
        assert d["price_cents"] == 52
        assert d["confidence"] == 0.75
        assert d["edge"] == 0.05
        assert d["reasoning"] == "Bullish breakout"
        assert "signal_id" in d
        assert "timestamp" in d


class TestSignalRouter:
    """Test SignalRouter pub/sub functionality."""
    
    @pytest.fixture
    def router(self):
        """Fresh router instance."""
        return SignalRouter()
    
    @pytest.fixture
    def sample_signal(self):
        """Sample signal for testing."""
        return AgentSignal(
            agent_id="lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            side="yes",
            size=10,
            price_cents=52,
            confidence=0.75,
            edge=0.05,
            reasoning="Bullish breakout",
        )
    
    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, router, sample_signal):
        """Subscribers should receive published signals."""
        received = []
        
        def callback(signal):
            received.append(signal)
        
        router.subscribe(callback)
        result = await router.publish_signal(sample_signal)
        
        assert result is True
        assert len(received) == 1
        assert received[0].signal_id == sample_signal.signal_id
    
    @pytest.mark.asyncio
    async def test_async_subscriber(self, router, sample_signal):
        """Async subscribers should work."""
        received = []
        
        async def async_callback(signal):
            received.append(signal)
        
        router.subscribe(async_callback)
        result = await router.publish_signal(sample_signal)
        
        assert result is True
        assert len(received) == 1
    
    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, router, sample_signal):
        """Multiple subscribers should all receive signals."""
        received1 = []
        received2 = []
        
        def callback1(signal):
            received1.append(signal)
        
        def callback2(signal):
            received2.append(signal)
        
        router.subscribe(callback1)
        router.subscribe(callback2)
        result = await router.publish_signal(sample_signal)
        
        assert result is True
        assert len(received1) == 1
        assert len(received2) == 1
    
    @pytest.mark.asyncio
    async def test_no_subscribers(self, router, sample_signal):
        """Publishing with no subscribers should return False and warn."""
        result = await router.publish_signal(sample_signal)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self, router, sample_signal):
        """Unsubscribing should stop signal delivery."""
        received = []
        
        def callback(signal):
            received.append(signal)
        
        router.subscribe(callback)
        router.unsubscribe(callback)
        result = await router.publish_signal(sample_signal)
        
        assert result is False
        assert len(received) == 0
    
    @pytest.mark.asyncio
    async def test_signal_log(self, router, sample_signal):
        """Router should log signals for audit."""
        def callback(signal):
            pass
        
        router.subscribe(callback)
        await router.publish_signal(sample_signal)
        
        recent = router.get_recent_signals(count=10)
        assert len(recent) == 1
        assert recent[0].signal_id == sample_signal.signal_id
    
    def test_get_stats(self, router):
        """Stats should report subscriber count."""
        stats = router.get_stats()
        assert stats["subscriber_count"] == 0
        assert stats["signal_log_size"] == 0
        
        def callback(signal):
            pass
        
        router.subscribe(callback)
        stats = router.get_stats()
        assert stats["subscriber_count"] == 1


class TestSubmitSignal:
    """Test submit_signal convenience function."""
    
    def test_submit_signal_returns_signal(self):
        """submit_signal should return AgentSignal."""
        signal = submit_signal(
            agent_id="lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            side="yes",
            size=10,
            price_cents=52,
            confidence=0.75,
            edge=0.05,
            reasoning="Bullish breakout",
        )
        
        assert isinstance(signal, AgentSignal)
        assert signal.agent_id == "lane_001"
        assert signal.agent_type == "btc15m_lane"
    
    def test_submit_signal_with_metadata(self):
        """submit_signal should accept metadata."""
        metadata = {"source": "technical_analysis", "indicator": "rsi"}
        signal = submit_signal(
            agent_id="lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            metadata=metadata,
        )
        
        assert signal.metadata == metadata


class TestSignalRouterSingleton:
    """Test that get_signal_router returns singleton."""
    
    def test_singleton(self):
        """get_signal_router should return same instance."""
        router1 = get_signal_router()
        router2 = get_signal_router()
        assert router1 is router2


class TestSignalFlowIntegration:
    """Integration test showing signal flow from agent to trading_agent."""
    
    @pytest.mark.asyncio
    async def test_full_signal_flow(self):
        """Simulate full signal flow from lane to trading_agent."""
        router = SignalRouter()
        
        # Simulate trading_agent subscription
        trading_agent_signals = []
        
        def trading_agent_callback(signal):
            """Mock trading_agent signal handler."""
            trading_agent_signals.append({
                "signal_id": signal.signal_id,
                "agent_type": signal.agent_type,
                "market_id": signal.market_id,
                "action": signal.action,
                "received_at": datetime.now(timezone.utc).isoformat(),
            })
            # In real implementation, trading_agent would:
            # 1. Validate signal
            # 2. Run risk checks
            # 3. Potentially execute via route_order_async
        
        router.subscribe(trading_agent_callback)
        
        # Simulate signal-only agent submitting signal
        signal = AgentSignal(
            agent_id="btc15m_lane_001",
            agent_type="btc15m_lane",
            market_id="KXBTC-15M-250102",
            action="buy",
            side="yes",
            size=10,
            price_cents=52,
            confidence=0.75,
            edge=0.05,
            reasoning="Bullish breakout pattern detected",
            metadata={"rsi": 75, "volume": "above_average"},
        )
        
        # Publish signal
        result = await router.publish_signal(signal)
        
        # Verify signal reached trading_agent
        assert result is True
        assert len(trading_agent_signals) == 1
        assert trading_agent_signals[0]["agent_type"] == "btc15m_lane"
        assert trading_agent_signals[0]["market_id"] == "KXBTC-15M-250102"
        assert trading_agent_signals[0]["action"] == "buy"
