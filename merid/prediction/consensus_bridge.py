"""Kalshi Consensus Bridge — Wire Kalshi agents into MERID's consensus system.

Translates Kalshi-specific outputs (StrategySignal, order intents) into
MERID's core consensus format (energy packets, votes) for blind_vote integration.

Usage::

    adapter = get_kalshi_consensus_adapter()
    
    # Convert Kalshi signal to energy packet
    signal = agent.get_last_signal()
    energy = adapter.signal_to_energy(signal, market)
    
    # Submit to core orchestrator
    vote_result = await orchestrator.run_cycle(energy)
    
    # Or convert order intent to vote
    vote = adapter.order_intent_to_vote(order_intent, edge=0.05, confidence=0.7)
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from merid.prediction.strategy import StrategySignal, SignalAction
from merid.event_venues.base import EventMarket
from utils.logger import get_logger

logger = get_logger("merid.prediction.consensus_bridge")


class KalshiConsensusAdapter:
    """Translates Kalshi agent outputs into MERID consensus inputs.
    
    Bridges:
    - StrategySignal → Energy packet (for core orchestrator)
    - Order intent → Vote response (for blind_vote)
    - Kalshi market context → Consensus metadata
    """
    
    def __init__(self):
        self.logger = logger
    
    # ── Signal → Energy Packet ────────────────────────────────────────────
    
    def signal_to_energy(
        self,
        signal: StrategySignal,
        market: EventMarket,
        agent_id: str = "kalshi_agent",
    ) -> Dict[str, Any]:
        """Convert Kalshi StrategySignal into an energy packet.
        
        Energy packet format (for core/orchestrator.py):
        - energy_id: Unique identifier
        - source: "kalshi"
        - payload: Human-readable description
        - domain: "prediction"
        - venue: "kalshi"
        - metadata: Signal details for consensus
        
        Args:
            signal: StrategySignal from KalshiStrategy
            market: EventMarket this signal applies to
            agent_id: Agent that generated this signal
            
        Returns:
            Energy packet dict ready for orchestrator.run_cycle()
        """
        # Generate unique energy ID
        energy_id = f"kalshi-{market.market_id}-{int(time.time())}"
        
        # Extract action details
        action_str = self._action_to_string(signal.action)
        direction = self._action_to_direction(signal.action)
        
        # Build human-readable payload
        edge_pct = round(signal.edge.net_edge * 100, 2) if signal.edge else 0
        confidence = round(getattr(signal, 'confidence', 0.5), 2)
        
        payload = (
            f"{action_str} {signal.contracts} contracts on {market.market_id} "
            f"at {signal.limit_price_cents}¢ | Edge: {edge_pct}% | Confidence: {confidence}"
        )
        
        # Determine timeframe from market ID
        timeframe = self._extract_timeframe(market.market_id)
        asset = self._extract_asset(market.market_id)
        
        return {
            "energy_id": energy_id,
            "source": "kalshi",
            "payload": payload,
            "domain": "prediction",
            "venue": "kalshi",
            "timestamp": time.time(),
            "agent_id": agent_id,
            "metadata": {
                "market_id": market.market_id,
                "ticker": market.market_id,
                "asset": asset,
                "timeframe": timeframe,
                "question": market.question,
                "action": signal.action.value if hasattr(signal.action, 'value') else str(signal.action),
                "direction": direction,
                "side": "yes" if "yes" in signal.action.value.lower() else "no",
                "contracts": signal.contracts,
                "limit_price_cents": signal.limit_price_cents,
                "edge_pct": edge_pct,
                "confidence": confidence,
                "reasoning": getattr(signal, 'reasoning', '')[:200] if getattr(signal, 'reasoning', '') else "",
                # EXEC-3: Full decision trace for swarm-level auditability
                "decision_trace": self._build_decision_trace(signal, market),
            },
        }
    
    def _action_to_string(self, action: SignalAction) -> str:
        """Convert SignalAction enum to human-readable string."""
        mapping = {
            SignalAction.BUY_YES: "BUY YES",
            SignalAction.SELL_YES: "SELL YES",
            SignalAction.BUY_NO: "BUY NO",
            SignalAction.SELL_NO: "SELL NO",
            SignalAction.QUOTE: "QUOTE",
            SignalAction.HOLD: "HOLD",
            SignalAction.NO_ACTION: "NO ACTION",
        }
        return mapping.get(action, str(action))
    
    def _action_to_direction(self, action: SignalAction) -> str:
        """Convert SignalAction to directional intent."""
        if action in (SignalAction.BUY_YES, SignalAction.SELL_NO):
            return "long"  # Betting on YES
        elif action in (SignalAction.BUY_NO, SignalAction.SELL_YES):
            return "short"  # Betting on NO
        else:
            return "neutral"
    
    def _extract_asset(self, ticker: str) -> str:
        """Extract asset from Kalshi ticker."""
        ticker_upper = ticker.upper()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE", "PEPE", "WIF", "ADA"]:
            if asset in ticker_upper:
                return asset
        return "UNKNOWN"
    
    def _extract_timeframe(self, ticker: str) -> str:
        """Extract timeframe from Kalshi ticker."""
        ticker_lower = ticker.lower()
        if "15m" in ticker_lower:
            return "15m"
        if "24h" in ticker_lower or "daily" in ticker_lower:
            return "24h"
        if "weekly" in ticker_lower or "week" in ticker_lower:
            return "weekly"
        if "monthly" in ticker_lower or "month" in ticker_lower:
            return "monthly"
        if "hourly" in ticker_lower or "1h" in ticker_lower:
            return "1h"
        if "4h" in ticker_lower:
            return "4h"
        return "unknown"

    # ── EXEC-3: Decision trace builder ────────────────────────────────────

    def _build_decision_trace(
        self,
        signal: StrategySignal,
        market: EventMarket,
    ) -> Dict[str, Any]:
        """Build a rich decision trace for swarm-level post-mortem auditability.

        EXEC-3: Includes structural conviction components, regime flags,
        timeframe context, and asset tags for each energy packet.
        """
        trace: Dict[str, Any] = {
            "signal_ts": time.time(),
            "asset": self._extract_asset(market.market_id),
            "timeframe": self._extract_timeframe(market.market_id),
        }

        # Extract edge breakdown if available
        if signal.edge:
            trace["edge"] = {
                "raw": float(signal.edge.raw_edge) if hasattr(signal.edge, 'raw_edge') else None,
                "fee_drag": float(signal.edge.fee_drag) if hasattr(signal.edge, 'fee_drag') else None,
                "slippage": float(signal.edge.slippage_est) if hasattr(signal.edge, 'slippage_est') else None,
                "net": float(signal.edge.net_edge) if hasattr(signal.edge, 'net_edge') else None,
                "type": getattr(signal.edge, 'edge_type', 'unknown'),
            }

        # Extract structural filters and conviction components
        trace["structural"] = {
            "conviction_score": getattr(signal, 'conviction', None),
            "regime": getattr(signal, 'regime', None),
            "fvg_confluence": getattr(signal, 'fvg_confluence', None),
            "sentiment_bias": getattr(signal, 'sentiment_bias', None),
            "momentum_aligned": getattr(signal, 'momentum_aligned', None),
        }

        # Filter reasons (why gates were passed/failed)
        trace["filters"] = {
            "gate_results": getattr(signal, 'gate_results', {}),
            "skip_reasons": getattr(signal, 'skip_reasons', []),
        }

        return trace
    
    # ── Order Intent → Vote Response ──────────────────────────────────────
    
    def order_intent_to_vote(
        self,
        intent: Dict[str, Any],
        edge: float = 0.0,
        confidence: float = 0.5,
        reasoning: str = "",
    ) -> Dict[str, Any]:
        """Convert order intent into a consensus vote response.
        
        Vote response format (for blind_vote):
        - vote: "accept" / "reject" / "abstain"
        - confidence: 0.0 - 1.0
        - reasoning: Explanation text
        - simulation: Outcome description
        
        Args:
            intent: Order intent dict with action, contracts, price
            edge: Edge percentage (0-1, e.g., 0.05 = 5%)
            confidence: Confidence score (0-1)
            reasoning: Explanation for vote
            
        Returns:
            Vote response dict ready for blind_vote()
        """
        # Determine vote based on edge and confidence
        decision = self._compute_vote_decision(edge, confidence, intent)
        
        # Build reasoning if not provided
        if not reasoning:
            reasoning = self._generate_reasoning(intent, edge, confidence, decision)
        
        # Build simulation (predicted outcome)
        simulation = self._generate_simulation(intent, edge, decision)
        
        return {
            "vote": decision,
            "confidence": confidence,
            "reasoning": reasoning,
            "simulation": simulation,
            "metadata": {
                "edge": edge,
                "edge_pct": round(edge * 100, 2),
                "action": intent.get("action", "unknown"),
                "contracts": intent.get("contracts", 0),
                "market_id": intent.get("market_id", ""),
            },
        }
    
    def _compute_vote_decision(
        self,
        edge: float,
        confidence: float,
        intent: Dict[str, Any],
    ) -> str:
        """Compute vote decision based on edge and confidence.
        
        Rules:
        - NO_ACTION or HOLD → "abstain" (checked first)
        - Edge >= 3% AND confidence >= 0.5 → "accept"
        - Edge < 1% OR confidence < 0.3 → "abstain"
        - Otherwise → "reject"
        """
        # Check action type first - if it's NO_ACTION or HOLD, abstain
        action = intent.get("action", "")
        if action in ("NO_ACTION", "HOLD"):
            return "abstain"
        
        edge_pct = edge * 100
        
        # Strong signal: accept
        if edge_pct >= 3.0 and confidence >= 0.5:
            return "accept"
        
        # Weak signal: abstain
        if edge_pct < 1.0 or confidence < 0.3:
            return "abstain"
        
        # Medium signal but not strong enough
        return "reject"
    
    def _generate_reasoning(
        self,
        intent: Dict[str, Any],
        edge: float,
        confidence: float,
        decision: str,
    ) -> str:
        """Generate reasoning text for vote."""
        edge_pct = round(edge * 100, 2)
        market_id = intent.get("market_id", "unknown")
        action = intent.get("action", "unknown")
        contracts = intent.get("contracts", 0)
        
        if decision == "accept":
            return (
                f"Approving {action} {contracts} contracts on {market_id}. "
                f"Edge: {edge_pct}%, Confidence: {confidence:.2f}. "
                f"Signal meets actionability thresholds."
            )
        elif decision == "reject":
            return (
                f"Rejecting {action} on {market_id}. "
                f"Edge: {edge_pct}%, Confidence: {confidence:.2f}. "
                f"Signal does not meet minimum thresholds."
            )
        else:  # abstain
            return (
                f"Abstaining on {market_id}. "
                f"Edge: {edge_pct}%, Confidence: {confidence:.2f}. "
                f"Insufficient conviction to trade."
            )
    
    def _generate_simulation(
        self,
        intent: Dict[str, Any],
        edge: float,
        decision: str,
    ) -> str:
        """Generate simulation/outcome description."""
        if decision == "accept":
            edge_pct = round(edge * 100, 2)
            contracts = intent.get("contracts", 0)
            price_cents = intent.get("limit_price_cents", 50)
            
            # Calculate expected value
            ev_cents = contracts * edge_pct * price_cents / 100
            
            return (
                f"Expected outcome: ${ev_cents:.2f} profit from {contracts} contracts. "
                f"Market likely mispriced by {edge_pct}%."
            )
        elif decision == "reject":
            return "Order would not meet risk/reward criteria. Passing."
        else:
            return "Insufficient signal strength. Waiting for better opportunity."
    
    # ── Batch Conversion ──────────────────────────────────────────────────
    
    def signals_to_energy_batch(
        self,
        signals: list[tuple[StrategySignal, EventMarket, str]],
    ) -> list[Dict[str, Any]]:
        """Convert multiple (signal, market, agent_id) tuples to energy packets.
        
        Args:
            signals: List of (StrategySignal, EventMarket, agent_id) tuples
            
        Returns:
            List of energy packets
        """
        return [
            self.signal_to_energy(signal, market, agent_id)
            for signal, market, agent_id in signals
        ]
    
    def intents_to_votes_batch(
        self,
        intents: list[tuple[Dict[str, Any], float, float]],
    ) -> list[Dict[str, Any]]:
        """Convert multiple (intent, edge, confidence) tuples to votes.
        
        Args:
            intents: List of (intent_dict, edge, confidence) tuples
            
        Returns:
            List of vote response dicts
        """
        return [
            self.order_intent_to_vote(intent, edge, confidence)
            for intent, edge, confidence in intents
        ]


# ── Singleton ─────────────────────────────────────────────────────────────

_adapter: Optional[KalshiConsensusAdapter] = None


def get_kalshi_consensus_adapter() -> KalshiConsensusAdapter:
    """Get or create the singleton KalshiConsensusAdapter."""
    global _adapter
    if _adapter is None:
        _adapter = KalshiConsensusAdapter()
    return _adapter


def reset_kalshi_consensus_adapter() -> None:
    """Reset singleton (for testing)."""
    global _adapter
    _adapter = None
