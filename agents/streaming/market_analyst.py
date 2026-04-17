"""
Market Analyst Agent - Streaming implementation.

Subscribes to MARKET_DATA channel, analyzes price movements,
emits trading signals autonomously.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from collections import deque
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class MarketAnalystAgent(StreamingAgent):
    """
    Autonomous market analyst.
    
    Monitors price streams, identifies trends, emits signals.
    Uses technical indicators: SMA, momentum, RSI approximation.
    """
    
    def __init__(self, agent_id: str = "market-analyst-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.MARKET_DATA],
            model="merid-strategist:latest"
        )
        
        # Price tracking with deque for efficiency
        self.price_history: Dict[str, deque] = {}
        self.volume_history: Dict[str, deque] = {}
        self.max_history = 50
        
        # Technical indicator periods
        self.sma_short = 5
        self.sma_long = 20
        self.momentum_period = 10
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Analyze market data event with technical indicators.
        
        Detects:
        - Significant price movements (>1%)
        - SMA crossovers
        - Momentum shifts
        - Volume spikes
        """
        if event.event_type != "ticker":
            return None
        
        data = event.data
        symbol = data.get("symbol")
        price = data.get("price")
        volume = data.get("volume", 0)
        
        if not symbol or not price:
            return None
        
        # Initialize history
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.max_history)
            self.volume_history[symbol] = deque(maxlen=self.max_history)
        
        # Store data
        self.price_history[symbol].append(price)
        self.volume_history[symbol].append(volume)
        
        prices = list(self.price_history[symbol])
        
        # Need enough history for analysis
        if len(prices) < self.sma_long:
            return None
        
        # Calculate indicators
        sma_short = sum(prices[-self.sma_short:]) / self.sma_short
        sma_long = sum(prices[-self.sma_long:]) / self.sma_long
        
        # Momentum (rate of change)
        momentum = (prices[-1] - prices[-self.momentum_period]) / prices[-self.momentum_period] if len(prices) >= self.momentum_period else 0
        
        # Price change from previous
        prev_price = prices[-2]
        price_change = (price - prev_price) / prev_price
        
        # RSI approximation (simplified)
        gains = [prices[i] - prices[i-1] for i in range(1, len(prices)) if prices[i] > prices[i-1]]
        losses = [prices[i-1] - prices[i] for i in range(1, len(prices)) if prices[i] < prices[i-1]]
        avg_gain = sum(gains[-14:]) / 14 if gains else 0
        avg_loss = sum(losses[-14:]) / 14 if losses else 0.0001
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # Volume spike detection
        volumes = list(self.volume_history[symbol])
        avg_volume = sum(volumes) / len(volumes) if volumes else 1
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1
        
        # Generate signal based on multiple factors
        signals = []
        confidence_factors = []
        
        # SMA crossover signal
        if sma_short > sma_long * 1.005:  # Short above long by 0.5%
            signals.append("bullish")
            confidence_factors.append(0.3)
        elif sma_short < sma_long * 0.995:  # Short below long
            signals.append("bearish")
            confidence_factors.append(0.3)
        
        # Momentum signal
        if momentum > 0.02:  # 2% momentum
            signals.append("bullish")
            confidence_factors.append(min(momentum * 10, 0.4))
        elif momentum < -0.02:
            signals.append("bearish")
            confidence_factors.append(min(abs(momentum) * 10, 0.4))
        
        # RSI signal
        if rsi < 30:  # Oversold
            signals.append("bullish")
            confidence_factors.append(0.2)
        elif rsi > 70:  # Overbought
            signals.append("bearish")
            confidence_factors.append(0.2)
        
        # Only emit if we have signals
        if not signals:
            return None
        
        # Determine consensus signal
        bullish_count = signals.count("bullish")
        bearish_count = signals.count("bearish")
        
        if bullish_count > bearish_count:
            signal_type = "bullish"
        elif bearish_count > bullish_count:
            signal_type = "bearish"
        else:
            return None  # No clear signal
        
        # Calculate confidence
        base_confidence = sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.5
        volume_boost = min(volume_ratio * 0.1, 0.2) if volume_ratio > 1.5 else 0
        confidence = min(base_confidence + volume_boost, 0.95)
        
        return {
            "type": "price_signal",
            "symbol": symbol,
            "signal": signal_type,
            "price": price,
            "prev_price": prev_price,
            "change_pct": price_change * 100,
            "volume": volume,
            "volume_ratio": round(volume_ratio, 2),
            "indicators": {
                "sma_short": round(sma_short, 2),
                "sma_long": round(sma_long, 2),
                "momentum": round(momentum * 100, 2),
                "rsi": round(rsi, 1),
            },
            "confidence": round(confidence, 3),
            "signal_count": len(signals),
            "reasoning": f"{symbol}: {signal_type} signal ({len(signals)} indicators) - RSI:{rsi:.0f}, Momentum:{momentum*100:.1f}%"
        }
