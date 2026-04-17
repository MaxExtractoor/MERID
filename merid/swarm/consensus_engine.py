"""Consensus Engine Core — Task 1

Formalizes the TradeProposal -> OrderIntent pipeline.
Runs weighted voting, checks risk vetoes, emits structured Explainability events,
and outputs Kalshi-ready OrderIntents.
"""

import threading
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from merid.pipeline.proposal import TradeProposal, ProposalStatus, OrderSide
from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.agents.coordination import ConsensusCoordinatorAgent, AgentVote, ExplainabilityAgent, ConsensusResult
from utils.logger import get_logger

logger = get_logger("merid.swarm.consensus_engine")


# Thread-safe singleton globals
_engine_instance: Optional["SwarmConsensusEngine"] = None
_engine_lock = threading.Lock()


class SwarmConsensusEngine:
    """Sits between agents and execution.
    Takes TradeProposals and AgentVotes, runs consensus, emits explanations,
    and returns OrderIntents ready for the Kalshi execution router.
    """

    def __init__(self, approval_threshold: float = 0.6):
        self.coordinator = ConsensusCoordinatorAgent(approval_threshold=approval_threshold)
        self.explainer = ExplainabilityAgent()
        self._history: List[Any] = []

    async def run_consensus(
        self, 
        proposals: List[TradeProposal], 
        votes: Dict[str, List[AgentVote]]
    ) -> List[OrderIntent]:
        """Run the consensus protocol over a batch of proposals and votes."""
        logger.info(f"Running consensus on {len(proposals)} proposals")
        
        # 1. Aggregate votes using the coordinator
        context = {"proposals": proposals, "votes": votes}
        output = await self.coordinator._execute(context)
        results = output.payload.get("results", [])
        
        approved_intents: List[OrderIntent] = []
        
        for res_dict in results:
            prop_id = res_dict["proposal_id"]
            decision = res_dict["decision"]
            rationale = res_dict["rationale"]
            vetoed_by = res_dict.get("vetoed_by")
            votes_list = res_dict.get("votes", [])
            
            # Find the corresponding proposal
            prop = next((p for p in proposals if p.proposal_id == prop_id), None)
            if not prop:
                continue
                
            # 2. Emit structured explainability event
            vote_summary = ", ".join([f"{v['agent_id']}:{v['decision']}({v['weight']})" for v in votes_list])
            
            event_data = {
                "id": f"cons-{prop_id}",
                "type": "consensus",
                "proposal": prop.to_dict(),
                "what": f"Consensus {decision.upper()} for {prop.side.value} {prop.qty} {prop.instrument_id}",
                "why": f"{rationale} Votes: [{vote_summary}]",
                "why_now": "Swarm cycle evaluation",
                "data_sources": ["agent_votes", "risk_context"],
                "risk_factors": [f"Vetoed by {vetoed_by}"] if vetoed_by else []
            }
            explanation = self.explainer.explain(event_data)
            self._history.append(explanation)
            
            # Fire to event bus
            try:
                from core.event_bus import event_stream
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(event_stream.publish("consensus:explanation", explanation.to_dict()))
            except Exception as e:
                logger.debug(f"Event bus publish error: {e}")
            
            # 3. Translate approved proposals to normalized Kalshi OrderIntents
            if decision == "approved":
                prop.approve()
                
                # Convert MERID internal side/action to Kalshi yes/no + buy/sell
                # For Kalshi, usually we buy YES or buy NO.
                kalshi_side = "yes" if prop.side == OrderSide.BUY else "no"
                kalshi_action = "buy" # We assume agents are always taking positions, scaling out handled separately
                
                _edge = float(prop.metadata.get("edge_pct", 0.0)) if prop.metadata else 0.0
                intent = OrderIntent(
                    ticker=prop.instrument_id,
                    side=kalshi_side,
                    action=kalshi_action,
                    price_cents=int((prop.price or 0) * 100),
                    count=int(prop.qty),
                    mode=None,
                    order_type=prop.order_type.value,
                    time_in_force="gtc",
                    edge_pct=_edge,
                    source=f"consensus_{prop_id}",
                    decision_trace_id=new_decision_trace_id("swarm"),
                    sentiment_driven=True,
                )
                approved_intents.append(intent)
            else:
                prop.reject(rationale)
                
        return approved_intents


def get_swarm_consensus_engine() -> SwarmConsensusEngine:
    """Get or create the thread-safe SwarmConsensusEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = SwarmConsensusEngine()
    return _engine_instance


get_consensus_engine = get_swarm_consensus_engine

