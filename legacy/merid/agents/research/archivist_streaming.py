"""
Archivist Agent - Streaming implementation.

State memory agent - tracks historical patterns and provides
retrieval vectors for decision context.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from collections import deque
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class ArchivistAgent(StreamingAgent):
    """
    Historical memory and pattern retrieval agent.
    
    Maintains:
    - Price history
    - Decision history
    - Pattern database
    """
    
    def __init__(self, agent_id: str = "archivist-agent-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.MARKET_DATA, EventChannel.CONSENSUS],
            model="gemma3:1b"
        )
        
        # Historical storage
        self.price_history: Dict[str, deque] = {}
        self.decision_history: deque = deque(maxlen=100)
        self.pattern_matches: List[Dict] = []
        
        self.history_size = 100
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Archive events and detect historical patterns.
        
        Emits:
        - pattern_match: When current conditions match historical pattern
        - context_retrieval: Historical context for decisions
        """
        if event.channel == EventChannel.MARKET_DATA:
            return await self._archive_market_data(event)
        elif event.channel == EventChannel.CONSENSUS:
            return await self._archive_decision(event)
        return None
    
    async def _archive_market_data(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """Archive market data and check for patterns."""
        if event.event_type != "ticker":
            return None
        
        data = event.data
        symbol = data.get("symbol")
        price = data.get("price")
        
        if not symbol or not price:
            return None
        
        # Initialize history for symbol
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.history_size)
        
        # Store price
        self.price_history[symbol].append({
            "price": price,
            "timestamp": event.timestamp
        })
        
        # Check for patterns (need enough history)
        if len(self.price_history[symbol]) < 20:
            return None
        
        pattern = self._detect_pattern(symbol)
        if pattern:
            return pattern
        
        return None
    
    async def _archive_decision(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """Archive consensus decisions."""
        self.decision_history.append({
            "type": event.event_type,
            "data": event.data,
            "timestamp": event.timestamp
        })
        
        # Provide context retrieval for significant decisions
        if len(self.decision_history) >= 5:
            return {
                "type": "context_retrieval",
                "recent_decisions": len(self.decision_history),
                "pattern_count": len(self.pattern_matches),
                "reasoning": f"Archived {len(self.decision_history)} decisions, {len(self.pattern_matches)} patterns detected"
            }
        
        return None
    
    def _detect_pattern(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Detect price patterns in history."""
        prices = [p["price"] for p in self.price_history[symbol]]
        
        # Simple pattern detection: consecutive moves in same direction
        if len(prices) < 10:
            return None
        
        recent = prices[-10:]
        
        # Count consecutive up/down moves
        up_moves = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
        down_moves = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        
        # Detect strong trend
        if up_moves >= 7:
            pattern = {
                "type": "pattern_match",
                "pattern": "strong_uptrend",
                "symbol": symbol,
                "consecutive_moves": up_moves,
                "confidence": up_moves / 9,
                "reasoning": f"{symbol} showing strong uptrend: {up_moves}/9 consecutive up moves"
            }
            self.pattern_matches.append(pattern)
            return pattern
        
        if down_moves >= 7:
            pattern = {
                "type": "pattern_match",
                "pattern": "strong_downtrend",
                "symbol": symbol,
                "consecutive_moves": down_moves,
                "confidence": down_moves / 9,
                "reasoning": f"{symbol} showing strong downtrend: {down_moves}/9 consecutive down moves"
            }
            self.pattern_matches.append(pattern)
            return pattern
        
        return None
