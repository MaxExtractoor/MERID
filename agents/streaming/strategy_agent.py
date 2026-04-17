"""
Strategy Agent - Streaming implementation.

Converts synthesis proposals into executable trade plans.
Uses Kelly Criterion and volatility-adjusted position sizing.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from collections import deque
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class StrategyAgent(StreamingAgent):
    """
    Trade strategy structuring agent.
    
    Takes synthesis proposals and converts them into
    executable trade plans with entry, exit, and sizing.
    Uses Kelly Criterion for optimal position sizing.
    """
    
    def __init__(self, agent_id: str = "strategy-agent-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.AGENT_OUTPUT, EventChannel.MARKET_DATA],
            model="merid-strategist:latest"
        )
        
        # Strategy parameters
        self.base_position_size = 0.02  # 2% of portfolio
        self.max_position_size = 0.10   # 10% max
        self.max_leverage = 10
        self.min_leverage = 1
        
        # Risk parameters
        self.risk_per_trade = 0.02  # 2% risk per trade
        self.reward_risk_ratio = 2.0  # Target 2:1 R:R
        
        # Track volatility for dynamic stops
        self.price_history: Dict[str, deque] = {}
        self.volatility: Dict[str, float] = {}
        
        # Track win rate for Kelly
        self.wins = 0
        self.losses = 0
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Convert synthesis proposals into trade plans.
        
        Emits:
        - trade_plan: Executable trade structure
        """
        # Track market data for volatility
        if event.channel == EventChannel.MARKET_DATA and event.event_type == "ticker":
            self._update_volatility(event.data)
            return None
        
        # Only process synthesis proposals
        if event.event_type != "synthesis_proposal":
            return None
        
        data = event.data
        signal = data.get("signal", "neutral")
        confidence = data.get("confidence", 0)
        signal_strength = data.get("signal_strength", 0.5)
        
        # Don't create plans for neutral signals or low confidence
        if signal == "neutral" or confidence < 0.5:
            return None
        
        # Determine symbol from context or default to top swarm-eligible asset
        symbol = data.get("symbol")
        if not symbol:
            try:
                from data.asset_universe import get_swarm_eligible
                _eligible = [a.symbol for a in get_swarm_eligible()
                             if "/" in a.symbol and ":" not in a.symbol]
                symbol = _eligible[0] if _eligible else "BTC/USDT"
            except Exception:
                symbol = "BTC/USDT"
        
        # Get volatility-adjusted stops
        volatility = self.volatility.get(symbol, 0.02)
        stop_loss_pct = self._calculate_stop_loss(volatility, confidence)
        take_profit_pct = stop_loss_pct * self.reward_risk_ratio
        
        # Calculate position parameters using Kelly
        kelly_fraction = self._calculate_kelly(confidence)
        position_size = self._calculate_position_size(kelly_fraction, confidence)
        leverage = self._calculate_leverage(confidence, volatility)
        
        # Determine trade direction
        side = "long" if signal == "bullish" else "short"
        
        return {
            "type": "trade_plan",
            "action": f"OPEN_{side.upper()}",
            "side": side,
            "symbol": symbol,
            "position_size": round(position_size, 4),
            "leverage": leverage,
            "stop_loss_pct": round(stop_loss_pct, 4),
            "take_profit_pct": round(take_profit_pct, 4),
            "confidence": round(confidence, 3),
            "kelly_fraction": round(kelly_fraction, 4),
            "volatility": round(volatility, 4),
            "signal_strength": round(signal_strength, 3),
            "signal_source": event.source,
            "risk_reward": self.reward_risk_ratio,
            "reasoning": f"Strategy: {side.upper()} {symbol} | Size: {position_size:.2%} | Leverage: {leverage}x | SL: {stop_loss_pct:.2%} | TP: {take_profit_pct:.2%} | Kelly: {kelly_fraction:.2%}"
        }
    
    def _update_volatility(self, data: Dict) -> None:
        """Update volatility tracking for a symbol."""
        symbol = data.get("symbol")
        price = data.get("price")
        
        if not symbol or not price:
            return
        
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=20)
        
        self.price_history[symbol].append(price)
        
        # Calculate volatility as average absolute return
        prices = list(self.price_history[symbol])
        if len(prices) >= 5:
            returns = [abs((prices[i] - prices[i-1]) / prices[i-1]) for i in range(1, len(prices))]
            self.volatility[symbol] = sum(returns) / len(returns)
    
    def _calculate_kelly(self, confidence: float) -> float:
        """Calculate Kelly Criterion fraction."""
        # Estimate win probability from confidence
        win_prob = 0.5 + (confidence - 0.5) * 0.5  # Map confidence to win prob
        
        # Use historical win rate if available
        total_trades = self.wins + self.losses
        if total_trades >= 10:
            historical_win_rate = self.wins / total_trades
            win_prob = (win_prob + historical_win_rate) / 2  # Blend
        
        # Kelly formula: f = (bp - q) / b
        # b = reward/risk ratio, p = win prob, q = loss prob
        b = self.reward_risk_ratio
        p = win_prob
        q = 1 - p
        
        kelly = (b * p - q) / b
        
        # Use fractional Kelly (25%) for safety
        return max(0, min(kelly * 0.25, 0.25))
    
    def _calculate_position_size(self, kelly: float, confidence: float) -> float:
        """Calculate position size based on Kelly and confidence."""
        # Base size from Kelly
        size = max(kelly, self.base_position_size * 0.5)
        
        # Scale with confidence
        size *= (0.5 + confidence)
        
        # Bound to limits
        return max(self.base_position_size * 0.25, min(size, self.max_position_size))
    
    def _calculate_stop_loss(self, volatility: float, confidence: float) -> float:
        """Calculate volatility-adjusted stop loss."""
        # Base stop is 2x volatility
        base_stop = volatility * 2
        
        # Tighter stops for higher confidence
        confidence_factor = 1.5 - confidence * 0.5  # 1.0 to 1.5
        
        stop = base_stop * confidence_factor
        
        # Bound between 1% and 5%
        return max(0.01, min(stop, 0.05))
    
    def _calculate_leverage(self, confidence: float, volatility: float) -> int:
        """Calculate leverage based on confidence and volatility."""
        # Lower leverage for higher volatility
        vol_factor = max(0.5, 1 - volatility * 10)  # Reduce for high vol
        
        # Scale with confidence
        base_leverage = 2
        max_additional = (self.max_leverage - base_leverage) * vol_factor
        additional = int(max_additional * confidence)
        
        return max(self.min_leverage, min(base_leverage + additional, self.max_leverage))
    
    def record_trade_result(self, won: bool) -> None:
        """Record trade result for Kelly calculation."""
        if won:
            self.wins += 1
        else:
            self.losses += 1
