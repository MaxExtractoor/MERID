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

import threading
import time
import uuid
from typing import Any, Dict, Optional

from merid.prediction.strategy import StrategySignal, SignalAction
from merid.event_venues.base import EventMarket
from utils.logger import get_logger

logger = get_logger("merid.prediction.consensus_bridge")

# Consensus thresholds - wired to StrategyConfig for alignment
# These are read from strategy config to ensure ANALYZE and CONSENSUS stages agree
def _get_consensus_thresholds():
    """Load consensus thresholds from strategy config for cross-stage alignment.
    
    Returns dict with:
    - accept_edge_pct: minimum edge % to accept (default 3.0)
    - accept_confidence: minimum confidence to accept (default 0.5)
    - abstain_edge_pct: edge % below which to abstain (default 1.0)
    - abstain_confidence: confidence below which to abstain (default 0.3)
    """
    try:
        from merid.prediction.strategy import StrategyConfig
        cfg = StrategyConfig()
        # Map strategy min_edge to consensus thresholds
        # Strategy uses Decimal fractions (0.08), consensus uses percent (8.0)
        min_edge_frac = float(cfg.min_edge_early)  # Use early phase as baseline
        thresholds = {
            "accept_edge_pct": max(3.0, min_edge_frac * 100.0),  # At least 3% or min_edge
            "accept_confidence": float(cfg.min_confidence),
            "abstain_edge_pct": max(1.0, min_edge_frac * 50.0),   # Half of accept threshold
            "abstain_confidence": 0.3,
        }
        
        # Audit log threshold configuration (for change detection)
        try:
            from core.risk_audit_chain import get_risk_audit_chain
            get_risk_audit_chain().log_event("consensus.threshold_changed", {
                "accept_edge_pct": thresholds["accept_edge_pct"],
                "accept_confidence": thresholds["accept_confidence"],
                "abstain_edge_pct": thresholds["abstain_edge_pct"],
                "source": "StrategyConfig",
                "min_edge_early": str(cfg.min_edge_early),
            })
        except Exception:
            pass  # Audit failure non-critical
        
        return thresholds
    except Exception as _e:
        logger.debug("Could not load strategy config for consensus thresholds: %s", _e)
        # Fail-safe defaults (conservative)
        return {
            "accept_edge_pct": 3.0,
            "accept_confidence": 0.5,
            "abstain_edge_pct": 1.0,
            "abstain_confidence": 0.3,
        }


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
    
    def _action_to_direction(self, action) -> str:
        """Map SignalAction to consensus direction vocabulary ("yes"/"no"/"neutral")."""
        from merid.prediction.strategy import SignalAction
        _map = {
            SignalAction.BUY_YES: "yes",
            SignalAction.BUY_NO: "no",
            SignalAction.SELL_YES: "no",   # selling YES = bearish
            SignalAction.SELL_NO: "yes",   # selling NO  = bullish
            SignalAction.HOLD: "neutral",
            SignalAction.QUOTE: "neutral",
        }
        return _map.get(action, "neutral")
    
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
        if "24h" in ticker_lower or "daily" in ticker_lower:
            return "24h"
        if "weekly" in ticker_lower or "week" in ticker_lower:
            return "weekly"
        if "hourly" in ticker_lower or "1h" in ticker_lower:
            return "1h"
        return "unknown"
    
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
        
        Rules (wired to StrategyConfig for cross-stage alignment):
        - NO_ACTION or HOLD → "abstain" (checked first)
        - Edge >= accept_edge_pct AND confidence >= accept_confidence → "accept"
        - Edge < abstain_edge_pct OR confidence < abstain_confidence → "abstain"
        - Otherwise → "reject"
        """
        # Load thresholds from strategy config (wired alignment)
        thresholds = _get_consensus_thresholds()
        
        # Check action type first - if it's NO_ACTION or HOLD, abstain
        action = intent.get("action", "")
        if action in ("NO_ACTION", "HOLD"):
            return "abstain"
        
        edge_pct = edge * 100
        
        # Log thresholds for traceability
        logger.debug(
            "[CONSENSUS_THRESHOLD] edge=%.2f%% (accept>=%.1f%%), confidence=%.2f (accept>=%.2f)",
            edge_pct, thresholds["accept_edge_pct"],
            confidence, thresholds["accept_confidence"]
        )
        
        # Strong signal: accept
        if edge_pct >= thresholds["accept_edge_pct"] and confidence >= thresholds["accept_confidence"]:
            return "accept"
        
        # Weak signal: abstain
        if edge_pct < thresholds["abstain_edge_pct"] or confidence < thresholds["abstain_confidence"]:
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
    
    # ── Signal → AgentProposal ────────────────────────────────────────────

    def signal_to_proposal(
        self,
        signal: "StrategySignal",
        agent_id: str,
        asset: str,
        timeframe: str,
        archetype: str = "directional",
        live_markets: Optional[list] = None,
        track_record: Optional[Dict[str, float]] = None,
    ) -> "AgentProposal":
        """Convert a StrategySignal into an AgentProposal for SwarmConsensusAggregator.

        Args:
            signal: StrategySignal from KalshiStrategy.
            agent_id: Unique agent identifier (e.g. "kalshi-btc_15m").
            asset: Asset symbol (e.g. "BTC").
            timeframe: Timeframe string (e.g. "15m").
            archetype: Agent archetype from AgentConfig (e.g. "directional").
            live_markets: List[KalshiMarketView] from CryptoSurfaceLoader (Wire 1).
                          If empty or None, market_data field will be None.
            track_record: Optional dict with "win_rate", "sharpe", "avg_edge_cents".

        Returns:
            AgentProposal ready for submit_proposal().
        """
        from merid.swarm.consensus_aggregator import AgentProposal
        from datetime import datetime, timezone

        direction = self._action_to_direction(signal.action)

        # Extract edge from StrategySignal.edge (EdgeEstimate) — the canonical source.
        # Fallback to legacy ad-hoc attributes for backward compat with older callers.
        _raw_edge_pct = 0.0
        _raw_confidence = 0.5
        if signal.edge is not None:
            _raw_edge_pct = float(signal.edge.net_edge) * 100.0
            _raw_confidence = float(getattr(signal.edge, "confidence", 0.5))
        else:
            _raw_edge_pct = float(getattr(signal, "edge_pct", 0.0))
            _raw_confidence = float(getattr(signal, "confidence", 0.5))

        edge_contribution = min(abs(_raw_edge_pct) / 100.0 * 0.5, 0.45)
        if direction == "yes":
            probability = min(0.95, max(0.05, 0.5 + edge_contribution))
        elif direction == "no":
            probability = min(0.95, max(0.05, 0.5 - edge_contribution))
        else:
            probability = 0.5

        confidence = _raw_confidence
        edge_cents = _raw_edge_pct * 100.0

        # Size preference based on confidence
        if confidence >= 0.8:
            size_preference = "large"
        elif confidence >= 0.6:
            size_preference = "base"
        elif confidence >= 0.4:
            size_preference = "reduced"
        else:
            size_preference = "small"

        # Populate market_data from the top live market (Wire 1 output)
        market_data = None
        if live_markets:
            top = live_markets[0]
            market_data = {
                "top_market_id": getattr(top, "market_id", None),
                "target_price": getattr(top, "target_price", None),
                "distance_pct": getattr(top, "distance_pct", None),
                "yes_price_cents": getattr(top, "yes_price", None),
                "no_price_cents": getattr(top, "no_price", None),
                "spread_bps": getattr(top, "spread_bps", None),
                "open_interest": getattr(top, "open_interest", None),
                "markets_in_band": len(live_markets),
            }

        return AgentProposal(
            agent_id=agent_id,
            asset=asset,
            timeframe=timeframe,
            direction=direction,
            probability=probability,
            confidence=confidence,
            size_preference=size_preference,
            rationale=f"{archetype} signal: {direction} @ conf={confidence:.2f} edge={edge_cents:.1f}c",
            edge_estimate=edge_cents,
            timestamp=datetime.now(timezone.utc),
            agent_archetype=archetype,
            agent_track_record=track_record,
            market_data=market_data,
        )

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
_adapter_lock = threading.Lock()


def get_kalshi_consensus_adapter() -> KalshiConsensusAdapter:
    """Get or create the singleton KalshiConsensusAdapter."""
    global _adapter
    if _adapter is None:
        with _adapter_lock:
            if _adapter is None:
                _adapter = KalshiConsensusAdapter()
    return _adapter


def reset_kalshi_consensus_adapter() -> None:
    """Reset singleton (for testing)."""
    global _adapter
    _adapter = None
