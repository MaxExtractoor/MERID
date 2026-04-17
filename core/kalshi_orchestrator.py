"""
Kalshi Core Orchestrator - Specialized for 15m Crypto Lane Operations

This core is specifically designed for Kalshi 15m crypto lane operations,
replacing generic energy processing with market-aware consensus and validation.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional

from agents.trading_registry import load_trading_agents  # Load trading-specific agents
from agents.reflection_layer import reflection_layer
from core.event_bus import event_stream
from core.settings import CONSENSUS_THRESHOLD
from core.state import state as global_state
from db.neo4j import memory
from core.validation.engine import validation_engine
from interfaces.automation import broadcast_reality
from memory.store import reality_memory
from swarm.performance import performance_ledger
from swarm.spawner import SwarmSpawner
from utils.logger import get_logger

from core.kalshi_energy import KalshiEnergy, KalshiValidationResult, create_validation_result_from_settlement
from core.consensus_engine import get_consensus_engine, ConsensusOutcome
from schemas.consensus import KalshiContext, RiskDecisionContext


def _vote_positive(vote) -> bool:
    """Check if a vote is positive for Kalshi trades."""
    if vote is None:
        return False
    if isinstance(vote, (int, float)):
        return vote > 0
    if isinstance(vote, str):
        return vote.lower() in ("accept", "approve", "yes", "true", "1")
    return bool(vote)


class KalshiCore:
    """
    Specialized orchestrator for Kalshi 15m crypto lane operations.
    
    This core processes structured KalshiEnergy packets and delegates
    to the Kalshi-aware consensus engine instead of generic blind voting.
    """

    def __init__(self) -> None:
        self.logger = get_logger("core.kalshi_orchestrator")
        self.state = global_state
        self.spawner = SwarmSpawner(performance_ledger)
        
        # Load trading-specific agents (not generic chat agents)
        base_agents = load_trading_agents()
        self.agents = self.spawner.bootstrap(base_agents)
        
        # Initialize Kalshi consensus engine
        self.consensus_engine = get_consensus_engine()
        
        self.logger.info("KALSHI CORE INITIALIZED — %d trading agents active", len(self.agents))
        for agent in self.agents:
            self.logger.info("  • %s → %s", agent.agent_id, agent.model_name)

    async def run_cycle(self, energy: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run a Kalshi-specific reasoning cycle.
        
        Args:
            energy: KalshiEnergy dictionary or legacy energy
            
        Returns:
            Consensus result with Kalshi + RCK context
        """
        # Convert to KalshiEnergy if needed
        if "lane_id" in energy and "symbol" in energy:
            kalshi_energy = KalshiEnergy.from_dict(energy)
        else:
            # Legacy energy - try to extract Kalshi fields
            kalshi_energy = self._extract_kalshi_energy(energy)
        
        energy_id = kalshi_energy.energy_id
        lane_id = kalshi_energy.lane_id
        market_id = kalshi_energy.market_id
        
        # Enhanced logging with Kalshi context
        self.logger.info(
            "Processing Kalshi energy %s | lane=%s market=%s | %s",
            energy_id, lane_id, market_id, kalshi_energy.get_summary()
        )
        
        await event_stream.publish(
            "kalshi:energy_received",
            {
                "energy_id": energy_id,
                "lane_id": lane_id,
                "market_id": market_id,
                "symbol": kalshi_energy.symbol,
                "direction": kalshi_energy.direction,
                "edge_bps": kalshi_energy.edge_bps,
            },
        )

        if memory:
            memory.log_energy(kalshi_energy.to_dict())

        # Execute agents with Kalshi energy
        agent_tasks = [self._execute_agent(agent, kalshi_energy.to_dict()) for agent in self.agents]
        responses = await asyncio.gather(*agent_tasks)

        # Use Kalshi consensus engine instead of blind voting
        consensus_result = await self._run_kalshi_consensus(kalshi_energy, responses)

        # Record votes with Kalshi context
        vote_records = self._build_vote_records(responses, kalshi_energy)

        if memory:
            memory.log_votes(energy_id, vote_records)
        
        performance_ledger.record_cycle(vote_records, consensus_result["approved"])

        await event_stream.publish(
            "kalshi:consensus_complete",
            {
                "energy_id": energy_id,
                "lane_id": lane_id,
                "market_id": market_id,
                "consensus": consensus_result["consensus"],
                "approved": consensus_result["approved"],
                "direction": kalshi_energy.direction,
                "edge_bps": kalshi_energy.edge_bps,
            },
        )

        if consensus_result["approved"]:
            # Handle approved energy with Kalshi context
            await self._handle_approved_kalshi_energy(kalshi_energy, consensus_result, responses)
            
            # Validate with Kalshi-specific validation
            validation_result = await self._validate_kalshi_reality(kalshi_energy, consensus_result)

            # Record outcome for reflection layer
            # KalshiValidationResult is a @dataclass — use attribute access, not .get()
            reality_gap = validation_result.reality_gap
            validated = validation_result.validated
            reflection_layer.record_outcome(energy_id, validated, reality_gap)
        else:
            self.logger.info(
                "Kalshi energy %s dissipated (consensus %.3f < %.2f)",
                energy_id,
                consensus_result["consensus"],
                CONSENSUS_THRESHOLD,
            )
            # Record rejection outcome
            reflection_layer.record_outcome(energy_id, validated=False)

        self.agents = self.spawner.refresh_population()
        return consensus_result

    async def _run_kalshi_consensus(self, kalshi_energy: KalshiEnergy, responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run Kalshi-specific consensus using the consensus engine.
        
        Args:
            kalshi_energy: Structured Kalshi energy
            responses: Agent responses
            
        Returns:
            Consensus result with Kalshi + RCK context
        """
        try:
            # Create Kalshi and RCK contexts for consensus engine
            kalshi_context = KalshiContext(
                market_id=kalshi_energy.market_id,
                market_ticker=kalshi_energy.market_ticker,
                series_ticker=kalshi_energy.series_ticker,
                symbol=kalshi_energy.symbol,
                timeframe=kalshi_energy.timeframe,
                yes_bid_cents=kalshi_energy.yes_bid_cents,
                yes_ask_cents=kalshi_energy.yes_ask_cents,
                no_bid_cents=kalshi_energy.no_bid_cents,
                no_ask_cents=kalshi_energy.no_ask_cents,
                p_yes_implied=kalshi_energy.p_yes_implied,
                p_yes_devig=kalshi_energy.p_yes_devig,
                settlement_time=kalshi_energy.settlement_time,
            )
            
            risk_context = RiskDecisionContext(
                p_true=kalshi_energy.p_true,
                p_implied=kalshi_energy.p_implied,
                edge_bps=kalshi_energy.edge_bps,
                kelly_fraction_full=kalshi_energy.kelly_fraction_full,
                kelly_fraction_rck=kalshi_energy.kelly_fraction_rck,
                kelly_fraction_used=kalshi_energy.kelly_fraction_used,
                target_drawdown=kalshi_energy.target_drawdown,
                drawdown_probability=kalshi_energy.drawdown_probability,
                safety_factor=kalshi_energy.safety_factor,
                direction=kalshi_energy.direction,
                size_contracts=kalshi_energy.size_contracts,
                bankroll_before=kalshi_energy.bankroll_before,
                bankroll_after=kalshi_energy.bankroll_after,
            )
            
            # Create votes from agent responses.
            # IMPORTANT: Always build fresh Vote objects keyed to this market — never
            # reuse pending_votes from a prior cycle.  The pending_votes dict is keyed
            # by agent_id without a market dimension, so a stale vote from market A
            # would silently contaminate the consensus for market B.
            from core.consensus_engine import Vote
            votes = []
            proposal_key = f"trade_{kalshi_energy.market_id}"
            for agent, response in zip(self.agents, responses):
                vote = Vote(
                    agent_id=agent.agent_id,
                    proposal=proposal_key,
                    signal=response.get("vote", "neutral"),
                    confidence=response.get("confidence", 0.5),
                    trust=self.consensus_engine.trust_scores.get(agent.agent_id, 1.0),
                )
                # Overwrite any stale entry for this agent so the dict stays coherent
                # for other consumers of consensus_engine.pending_votes.
                self.consensus_engine.pending_votes[agent.agent_id] = vote
                votes.append(vote)
            
            # Create consensus result with Kalshi context
            from core.consensus_engine import ConsensusResult
            consensus_block = ConsensusResult(
                decision="APPROVE" if kalshi_energy.edge_bps > 30 else "REJECT",
                signal="bullish" if kalshi_energy.direction == "YES" else "bearish",
                confidence=sum(v.confidence for v in votes) / len(votes) if votes else 0.0,
                votes=votes,
                quorum_met=len(votes) >= self.consensus_engine.min_votes,
            )
            
            # Calculate consensus score
            consensus_score = sum(v.weight for v in votes) / len(votes) if votes else 0.0
            approved = consensus_score >= CONSENSUS_THRESHOLD and kalshi_energy.edge_bps > 30
            
            return {
                "approved": approved,
                "consensus": consensus_score,
                "block_id": kalshi_energy.energy_id,
                "block": consensus_block,
                "summaries": self._build_agent_summaries(responses),
            }
            
        except Exception as exc:
            self.logger.error("Kalshi consensus failed: %s", exc)
            return {
                "approved": False,
                "consensus": 0.0,
                "error": str(exc),
            }

    async def _execute_agent(self, agent, energy: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent with Kalshi energy."""
        try:
            result = await agent.process(energy, phase="kalshi_reasoning")
            return result
        except Exception as exc:
            self.logger.error("[%s] Kalshi agent failure: %s", agent.agent_id, exc)
            
            # Publish structured error event
            await event_stream.publish(
                "kalshi:agent:error",
                {
                    "agent_id": agent.agent_id,
                    "energy_id": energy["energy_id"],
                    "lane_id": energy.get("lane_id"),
                    "error": str(exc),
                },
            )
            
            # Return structured fallback response
            return {
                "agent_id": agent.agent_id,
                "vote": "abstain",
                "confidence": 0.0,
                "reasoning": f"Kalshi agent error: {str(exc)[:200]}",
                "trust": getattr(agent, "trust", 1.0),
            }

    def _build_vote_records(self, responses: List[Dict[str, Any]], kalshi_energy: KalshiEnergy) -> List[Dict[str, Any]]:
        """Build vote records with Kalshi context."""
        return [
            {
                "agent_id": agent.agent_id,
                "vote": response.get("vote"),
                "confidence": response.get("confidence"),
                "reasoning": response.get("reasoning", ""),
                "lane_id": kalshi_energy.lane_id,
                "market_id": kalshi_energy.market_id,
                "symbol": kalshi_energy.symbol,
                "direction": kalshi_energy.direction,
                "edge_bps": kalshi_energy.edge_bps,
            }
            for agent, response in zip(self.agents, responses)
        ]

    def _build_agent_summaries(self, responses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build agent summaries for consensus."""
        return [
            {
                "agent": response.get("agent_id", "unknown"),
                "vote": response.get("vote", "neutral"),
                "confidence": response.get("confidence", 0.0),
                "reasoning": response.get("reasoning", ""),
            }
            for response in responses
        ]

    async def _handle_approved_kalshi_energy(
        self,
        kalshi_energy: KalshiEnergy,
        vote_result: Dict[str, Any],
        responses: List[Dict[str, Any]],
    ) -> None:
        """Handle approved Kalshi energy with market context."""
        energy_id = kalshi_energy.energy_id
        consensus = vote_result["consensus"]
        block = vote_result.get("block")

        # Record top pick with Kalshi context
        await self.state.record_top_pick(
            energy_id=energy_id,
            payload=kalshi_energy.get_summary(),
            consensus=consensus,
            source="kalshi_lane",
            curator=[s["agent"] for s in vote_result.get("summaries", []) if _vote_positive(s.get("vote"))],
            # NEW: Kalshi-specific fields
            lane_id=kalshi_energy.lane_id,
            symbol=kalshi_energy.symbol,
            market_id=kalshi_energy.market_id,
            direction=kalshi_energy.direction,
            p_true=kalshi_energy.p_true,
            p_implied=kalshi_energy.p_implied,
            edge_bps=kalshi_energy.edge_bps,
            kelly_fraction_used=kalshi_energy.kelly_fraction_used,
            size_contracts=kalshi_energy.size_contracts,
            target_drawdown=kalshi_energy.target_drawdown,
            safety_factor=kalshi_energy.safety_factor,
        )

        # Log reality with Kalshi context
        if memory and block:
            memory.log_reality(
                energy_id,
                vote_result,
                [{"agent_id": a.agent_id, "vote": r.get("vote")} for a, r in zip(self.agents, responses)],
                kalshi_context=block.kalshi.to_dict() if hasattr(block, 'kalshi') else {},
                risk_decision=block.risk_decision.to_dict() if hasattr(block, 'risk_decision') else {},
            )

        # Create Kalshi-specific alert
        alert_lines = [
            "KALSHI TRADE CONFIRMED",
            f"Lane: {kalshi_energy.lane_id}",
            f"Market: {kalshi_energy.market_id}",
            f"Decision: {kalshi_energy.direction} @ {kalshi_energy.yes_price_cents}c",
            f"Edge: {kalshi_energy.edge_bps} bps",
            f"Kelly: {kalshi_energy.kelly_fraction_used:.3f}",
            f"Size: {kalshi_energy.size_contracts} contracts",
            f"Consensus: {consensus:.1%}",
            "",
            "Agent Agreement:",
        ]
        alert_lines.extend([
            f"• {summary['agent']}: {summary['reasoning'][:150]}..."
            for summary in vote_result.get("summaries", [])
            if _vote_positive(summary.get("vote"))
        ])

        await self._dispatch_alert("\n".join(alert_lines))
        await event_stream.publish(
            "kalshi:trade_confirmed",
            {
                "energy_id": energy_id,
                "lane_id": kalshi_energy.lane_id,
                "market_id": kalshi_energy.market_id,
                "consensus": consensus,
                "direction": kalshi_energy.direction,
                "edge_bps": kalshi_energy.edge_bps,
                "size_contracts": kalshi_energy.size_contracts,
            },
        )
        self.logger.info(
            "Kalshi trade confirmed for %s at %.2f%% consensus | %s",
            energy_id, consensus * 100, kalshi_energy.get_summary()
        )

    async def _validate_kalshi_reality(self, kalshi_energy: KalshiEnergy, vote_result: Dict[str, Any]) -> KalshiValidationResult:
        """Validate Kalshi trade with market-specific logic."""
        # For now, create a basic validation result
        # In production, this would check actual settlement data
        validation_result = KalshiValidationResult(
            status="confirmed",
            validated=True,
            score=1.0,
            reality_gap=0.0,
            settlement_correct=True,
            rck_constraints_met=True,
        )
        
        # Record validation
        await self.state.record_validation(
            kalshi_energy.to_dict(), 
            validation_result.to_dict(), 
            vote_result
        )
        
        await event_stream.publish(
            "kalshi:validation_complete",
            {
                "energy_id": kalshi_energy.energy_id,
                "lane_id": kalshi_energy.lane_id,
                "validation": validation_result.to_dict(),
            },
        )
        
        self.logger.info(
            "Kalshi validation recorded for %s: status=%s score=%.2f",
            kalshi_energy.energy_id,
            validation_result.status,
            validation_result.score,
        )
        
        return validation_result

    async def _dispatch_alert(self, message: str) -> None:
        """Dispatch Kalshi-specific alert."""
        try:
            from interfaces.telegram import send_alert
            await send_alert(message)
        except Exception as exc:
            self.logger.error("Failed to dispatch Kalshi Telegram alert: %s", exc)

    def _extract_kalshi_energy(self, energy: Dict[str, Any]) -> KalshiEnergy:
        """Extract KalshiEnergy from legacy energy format."""
        # This is a fallback for legacy energy formats
        return KalshiEnergy(
            energy_id=energy["energy_id"],
            lane_id=energy.get("lane_id", "UNKNOWN"),
            symbol=energy.get("symbol", "UNKNOWN"),
            market_id=energy.get("market_id", ""),
            yes_price_cents=energy.get("yes_price_cents", 50),
            no_price_cents=energy.get("no_price_cents", 50),
            p_true=energy.get("p_true", 0.5),
            p_implied=energy.get("p_implied", 0.5),
            edge_bps=energy.get("edge_bps", 0.0),
            direction=energy.get("direction", "FLAT"),
            kelly_fraction_used=energy.get("kelly_fraction_used", 0.0),
            size_contracts=energy.get("size_contracts", 0),
        )


# Singleton instance for Kalshi core
_KALSHI_CORE_INSTANCE: Optional[KalshiCore] = None
_KALSHI_CORE_LOCK = threading.Lock()


def get_kalshi_core() -> KalshiCore:
    """Get the singleton Kalshi core instance."""
    global _KALSHI_CORE_INSTANCE
    if _KALSHI_CORE_INSTANCE is None:
        with _KALSHI_CORE_LOCK:
            if _KALSHI_CORE_INSTANCE is None:
                _KALSHI_CORE_INSTANCE = KalshiCore()
    return _KALSHI_CORE_INSTANCE
