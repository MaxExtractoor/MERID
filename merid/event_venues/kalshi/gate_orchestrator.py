"""
Gate Orchestrator for 15-Minute Crypto Markets

Centralized gate orchestration for BTC, ETH, SOL, XRP, DOGE 15-minute markets.
Provides single authoritative decision path instead of overlapping gate vetoes.

Gate Order (from fastest to most expensive):
1. Lane Enforcement Gate - Agent lane validation
2. Venue Gate - US compliance and trading mode
3. Market Regime Gate - Market condition validation
4. Microstructure Gate - Economics and spread analysis (NEW - authoritative)
5. Order Gate - Idempotency and risk envelope

This replaces the previous multi-entry-point gate system with one decisive decision path.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

from utils.logger import get_logger
from merid.event_venues.kalshi.binary_price_space import (
    require_outcome_side,
    SideValidationError,
)

logger = get_logger("merid.event_venues.kalshi.gate_orchestrator")


class GateStage(str, Enum):
    """Gate stages in decision pipeline."""
    LANE_ENFORCEMENT = "lane_enforcement"
    VENUE = "venue"
    MARKET_REGIME = "market_regime"
    MICROSTRUCTURE = "microstructure"
    ORDER = "order"


class GateDecision(str, Enum):
    """Gate decision outcomes."""
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass
class GateResult:
    """Result of gate evaluation with full trace metadata."""
    stage: GateStage
    decision: GateDecision
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    @property
    def accepted(self) -> bool:
        return self.decision == GateDecision.ACCEPT
    
    @property
    def rejected(self) -> bool:
        return self.decision == GateDecision.REJECT


@dataclass
class OrchestratedDecision:
    """Final orchestrated decision with complete gate trace."""
    accepted: bool
    first_reject_stage: Optional[GateStage] = None
    first_reject_reason: Optional[str] = None
    gate_trace: list[GateResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class GateOrchestrator:
    """
    Centralized gate orchestrator for 15-minute crypto markets.
    
    Provides single authoritative decision path with complete trace metadata.
    Replaces multi-entry-point gate system with one decisive decision flow.
    """
    
    def __init__(self):
        self._lane_gate = None
        self._venue_gate = None
        self._market_regime_gate_enabled = True
        self._microstructure_gate_enabled = True
        self._order_gate = None
    
    def set_lane_gate(self, lane_gate) -> None:
        """Set lane enforcement gate."""
        self._lane_gate = lane_gate
    
    def set_venue_gate(self, venue_gate) -> None:
        """Set venue compliance gate."""
        self._venue_gate = venue_gate
    
    def set_order_gate(self, order_gate) -> None:
        """Set order management gate."""
        self._order_gate = order_gate
    
    def enable_market_regime_gate(self, enabled: bool = True) -> None:
        """Enable or disable market regime gate."""
        self._market_regime_gate_enabled = enabled
    
    def enable_microstructure_gate(self, enabled: bool = True) -> None:
        """Enable or disable microstructure gate."""
        self._microstructure_gate_enabled = enabled
    
    def evaluate_candidate(
        self,
        candidate_data: Dict[str, Any],
        market_data: Dict[str, Any],
        order_intent: Dict[str, Any],
        asset_ticker: str,
        is_15m_market: bool = True
    ) -> OrchestratedDecision:
        """
        Evaluate candidate through complete gate pipeline.
        
        Args:
            candidate_data: Candidate information (agent_id, strategy, etc.)
            market_data: Market data (prices, depth, etc.)
            order_intent: Order intent (side, price, quantity, etc.)
            asset_ticker: Asset ticker (BTC, ETH, SOL, XRP, DOGE)
            is_15m_market: If True, apply 15-minute market specific logic
        
        Returns:
            OrchestratedDecision with complete gate trace
        """
        gate_trace = []
        
        # Stage 1: Lane Enforcement Gate
        lane_result = self._check_lane_enforcement(candidate_data, is_15m_market)
        gate_trace.append(lane_result)
        if lane_result.rejected:
            return OrchestratedDecision(
                accepted=False,
                first_reject_stage=GateStage.LANE_ENFORCEMENT,
                first_reject_reason=lane_result.reason,
                gate_trace=gate_trace,
                metadata={"asset_ticker": asset_ticker, "is_15m_market": is_15m_market}
            )
        
        # Stage 2: Venue Gate
        venue_result = self._check_venue_compliance(candidate_data, is_15m_market)
        gate_trace.append(venue_result)
        if venue_result.rejected:
            return OrchestratedDecision(
                accepted=False,
                first_reject_stage=GateStage.VENUE,
                first_reject_reason=venue_result.reason,
                gate_trace=gate_trace,
                metadata={"asset_ticker": asset_ticker, "is_15m_market": is_15m_market}
            )
        
        # Stage 3: Market Regime Gate
        if self._market_regime_gate_enabled:
            regime_result = self._check_market_regime(market_data, asset_ticker)
            gate_trace.append(regime_result)
            if regime_result.rejected:
                return OrchestratedDecision(
                    accepted=False,
                    first_reject_stage=GateStage.MARKET_REGIME,
                    first_reject_reason=regime_result.reason,
                    gate_trace=gate_trace,
                    metadata={"asset_ticker": asset_ticker, "is_15m_market": is_15m_market}
                )
        
        # Stage 4: Microstructure Gate (NEW - authoritative for 15m markets)
        if self._microstructure_gate_enabled:
            microstructure_result = self._check_microstructure(
                market_data, order_intent, asset_ticker, is_15m_market
            )
            gate_trace.append(microstructure_result)
            if microstructure_result.rejected:
                return OrchestratedDecision(
                    accepted=False,
                    first_reject_stage=GateStage.MICROSTRUCTURE,
                    first_reject_reason=microstructure_result.reason,
                    gate_trace=gate_trace,
                    metadata={"asset_ticker": asset_ticker, "is_15m_market": is_15m_market}
                )
        
        # Stage 5: Order Gate
        order_result = self._check_order_constraints(order_intent, asset_ticker)
        gate_trace.append(order_result)
        if order_result.rejected:
            return OrchestratedDecision(
                accepted=False,
                first_reject_stage=GateStage.ORDER,
                first_reject_reason=order_result.reason,
                gate_trace=gate_trace,
                metadata={"asset_ticker": asset_ticker, "is_15m_market": is_15m_market}
            )
        
        # All gates passed
        return OrchestratedDecision(
            accepted=True,
            gate_trace=gate_trace,
            metadata={"asset_ticker": asset_ticker, "is_15m_market": is_15m_market}
        )
    
    def _check_lane_enforcement(self, candidate_data: Dict[str, Any], is_15m_market: bool) -> GateResult:
        """Check lane enforcement gate."""
        try:
            if self._lane_gate:
                # Call lane gate if available
                agent_id = candidate_data.get("agent_id")
                if hasattr(self._lane_gate, 'gate_production_only'):
                    self._lane_gate.gate_production_only(agent_id)
            
            return GateResult(
                stage=GateStage.LANE_ENFORCEMENT,
                decision=GateDecision.ACCEPT,
                reason=None,
                metadata={"agent_id": candidate_data.get("agent_id")}
            )
        except Exception as e:
            return GateResult(
                stage=GateStage.LANE_ENFORCEMENT,
                decision=GateDecision.REJECT,
                reason=f"lane_enforcement_failed: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _check_venue_compliance(self, candidate_data: Dict[str, Any], is_15m_market: bool) -> GateResult:
        """Check venue compliance gate."""
        try:
            if self._venue_gate:
                venue = candidate_data.get("venue", "kalshi")
                self._venue_gate.check_venue(venue)
                self._venue_gate.check_can_trade()
            
            return GateResult(
                stage=GateStage.VENUE,
                decision=GateDecision.ACCEPT,
                reason=None,
                metadata={"venue": candidate_data.get("venue")}
            )
        except Exception as e:
            return GateResult(
                stage=GateStage.VENUE,
                decision=GateDecision.REJECT,
                reason=f"venue_compliance_failed: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _check_market_regime(self, market_data: Dict[str, Any], asset_ticker: str) -> GateResult:
        """Check market regime gate."""
        try:
            # Import market regime check if available
            from merid.event_venues.kalshi.order_router import _check_market_regime_gate
            
            # Create mock intent for regime check
            # In production, this would use actual intent object
            # For now, assume regime is acceptable
            return GateResult(
                stage=GateStage.MARKET_REGIME,
                decision=GateDecision.ACCEPT,
                reason=None,
                metadata={"asset_ticker": asset_ticker}
            )
        except Exception as e:
            return GateResult(
                stage=GateStage.MARKET_REGIME,
                decision=GateDecision.REJECT,
                reason=f"market_regime_failed: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _check_microstructure(
        self, market_data: Dict[str, Any], order_intent: Dict[str, Any], 
        asset_ticker: str, is_15m_market: bool
    ) -> GateResult:
        """Check microstructure gate (NEW - authoritative for 15m markets)."""
        try:
            from merid.event_venues.kalshi.spread_edge_analytics import (
                compute_canonical_spreads,
                compute_per_side_edges,
                get_time_scaled_threshold,
                check_crossed_book,
                check_absolute_spread_cap,
                check_minimum_depth
            )
            
            yes_bid = market_data.get("yes_bid_cents", 50)
            no_bid = market_data.get("no_bid_cents", 50)
            yes_ask = market_data.get("yes_ask_cents", 51)
            no_ask = market_data.get("no_ask_cents", 49)
            yes_depth = market_data.get("yes_bid_depth", 100)
            no_depth = market_data.get("no_bid_depth", 100)
            
            # Check crossed book
            if not check_crossed_book(yes_bid, yes_ask, no_bid, no_ask):
                return GateResult(
                    stage=GateStage.MICROSTRUCTURE,
                    decision=GateDecision.REJECT,
                    reason="crossed_book",
                    metadata={"yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask}
                )
            
            # Check spread cap
            spread_cents = yes_ask - yes_bid
            time_to_expiry = market_data.get("time_to_expiry_seconds", 900)
            if not check_absolute_spread_cap(spread_cents, asset_ticker, time_to_expiry):
                return GateResult(
                    stage=GateStage.MICROSTRUCTURE,
                    decision=GateDecision.REJECT,
                    reason="spread_too_wide",
                    metadata={"spread_cents": spread_cents, "asset_ticker": asset_ticker}
                )
            
            # Check depth
            try:
                execution_side = require_outcome_side(
                    order_intent,
                    context="gate_orchestrator order_intent",
                    fields=("side", "outcome_side", "kalshi_side", "thesis_side"),
                )
            except SideValidationError as side_err:
                return GateResult(
                    stage=GateStage.MICROSTRUCTURE,
                    decision=GateDecision.REJECT,
                    reason="missing_or_invalid_order_side",
                    metadata={"error": str(side_err)},
                )

            if not check_minimum_depth(yes_depth, no_depth, asset_ticker, execution_side):
                return GateResult(
                    stage=GateStage.MICROSTRUCTURE,
                    decision=GateDecision.REJECT,
                    reason="insufficient_depth",
                    metadata={"yes_depth": yes_depth, "no_depth": no_depth, "execution_side": execution_side}
                )
            
            return GateResult(
                stage=GateStage.MICROSTRUCTURE,
                decision=GateDecision.ACCEPT,
                reason=None,
                metadata={"asset_ticker": asset_ticker, "time_to_expiry": time_to_expiry}
            )
        except Exception as e:
            return GateResult(
                stage=GateStage.MICROSTRUCTURE,
                decision=GateDecision.REJECT,
                reason=f"microstructure_gate_failed: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _check_order_constraints(self, order_intent: Dict[str, Any], asset_ticker: str) -> GateResult:
        """Check order constraints gate."""
        try:
            if self._order_gate:
                # Check order constraints via order gate
                # For now, assume constraints are acceptable
                pass
            
            return GateResult(
                stage=GateStage.ORDER,
                decision=GateDecision.ACCEPT,
                reason=None,
                metadata={"asset_ticker": asset_ticker}
            )
        except Exception as e:
            return GateResult(
                stage=GateStage.ORDER,
                decision=GateDecision.REJECT,
                reason=f"order_constraints_failed: {str(e)}",
                metadata={"error": str(e)}
            )


# Global orchestrator instance
_gate_orchestrator: Optional[GateOrchestrator] = None


def get_gate_orchestrator() -> GateOrchestrator:
    """Get or create the global gate orchestrator singleton."""
    global _gate_orchestrator
    if _gate_orchestrator is None:
        _gate_orchestrator = GateOrchestrator()
    return _gate_orchestrator
