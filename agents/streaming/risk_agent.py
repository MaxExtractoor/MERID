"""
Risk Agent - Streaming implementation.

Subscribes to MARKET_DATA and AGENT_OUTPUT channels.
Monitors exposure, liquidation risk, and can VETO decisions.
"""

# DEPRECATION NOTICE:
# This module is part of the legacy LLM/mesh risk system.
# It is NOT used in the kalshi_crypto_15m_v2 profile and MUST NOT
# be wired into any production trading or execution path.
LEGACY_EXPERIMENTAL_ONLY = True

from __future__ import annotations

from typing import Dict, Any, Optional
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class RiskAgent(StreamingAgent):
    """
    Autonomous risk manager with VETO power.
    
    Monitors:
    - Price volatility
    - Position exposure
    - Liquidation proximity
    - Agent consensus quality
    """
    
    def __init__(self, agent_id: str = "risk-agent-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.MARKET_DATA, EventChannel.AGENT_OUTPUT],
            model="merid-interface:latest"
        )
        
        # Risk thresholds
        self.max_volatility = 0.05  # 5% volatility threshold
        self.max_drawdown = 0.10    # 10% max drawdown
        self.min_confidence = 0.60  # Minimum confidence for approval
        
        # State tracking
        self.price_history: Dict[str, list] = {}
        self.pending_proposals: Dict[str, Dict] = {}
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Analyze events for risk.
        
        Can emit:
        - risk_assessment: Normal risk evaluation
        - risk_veto: VETO a proposal (blocks execution)
        - risk_warning: High risk alert
        """
        if event.channel == EventChannel.MARKET_DATA:
            return await self._analyze_market_risk(event)
        elif event.channel == EventChannel.AGENT_OUTPUT:
            return await self._analyze_proposal_risk(event)
        return None
    
    async def _analyze_market_risk(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """Analyze market data for risk signals."""
        if event.event_type != "ticker":
            return None
        
        data = event.data
        symbol = data.get("symbol")
        price = data.get("price")
        
        if not symbol or not price:
            return None
        
        # Track price history
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        
        self.price_history[symbol].append(price)
        
        # Keep bounded
        if len(self.price_history[symbol]) > 30:
            self.price_history[symbol].pop(0)
        
        # Need history to calculate volatility
        if len(self.price_history[symbol]) < 5:
            return None
        
        # Calculate volatility
        prices = self.price_history[symbol]
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        volatility = sum(abs(r) for r in returns) / len(returns)
        
        # Emit warning if high volatility
        if volatility > self.max_volatility:
            return {
                "type": "risk_warning",
                "symbol": symbol,
                "volatility": volatility,
                "threshold": self.max_volatility,
                "severity": "high",
                "reasoning": f"{symbol} volatility {volatility:.2%} exceeds threshold {self.max_volatility:.2%}",
                "recommendation": "REDUCE_EXPOSURE"
            }
        
        return None
    
    async def _analyze_proposal_risk(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """Analyze agent proposals for risk. Can VETO."""
        data = event.data
        
        # Only analyze trading signals/proposals
        if event.event_type not in ["price_signal", "trade_proposal", "consensus_proposal"]:
            return None
        
        confidence = data.get("confidence", 0)
        signal = data.get("signal", "")
        
        # VETO if confidence too low
        if confidence < self.min_confidence:
            return {
                "type": "risk_veto",
                "vetoed_proposal": event.source,
                "reason": "insufficient_confidence",
                "confidence": confidence,
                "threshold": self.min_confidence,
                "reasoning": f"Confidence {confidence:.2%} below minimum {self.min_confidence:.2%}",
                "action": "VETO"
            }
        
        # Risk assessment (not veto)
        risk_score = self._calculate_risk_score(data)
        
        if risk_score > 0.7:
            return {
                "type": "risk_assessment",
                "proposal_source": event.source,
                "risk_score": risk_score,
                "risk_level": "high",
                "confidence": confidence,
                "reasoning": f"High risk score {risk_score:.2f} - proceed with caution",
                "recommendation": "REDUCE_SIZE"
            }
        
        return None
    
    def _calculate_risk_score(self, data: Dict) -> float:
        """Calculate risk score for a proposal."""
        score = 0.0
        
        # Lower confidence = higher risk
        confidence = data.get("confidence", 0.5)
        score += (1 - confidence) * 0.4
        
        # Bearish signals in volatile markets = higher risk
        signal = data.get("signal", "").lower()
        if signal == "bearish":
            score += 0.2
        
        # Large price changes = higher risk
        change_pct = abs(data.get("change_pct", 0))
        if change_pct > 2:
            score += 0.2
        
        return min(score, 1.0)
