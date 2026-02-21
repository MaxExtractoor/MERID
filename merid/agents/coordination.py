"""§4 Coordination, Oversight, and Explainability Agents.

- ConsensusCoordinatorAgent: manage voting/aggregation among domain agents.
- ExplainabilityAgent: turn internal state into human-readable rationale.
- GovernanceAgent: enforce non-negotiable constraints (compliance, bans).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent
from merid.pipeline.proposal import TradeProposal

from utils.logger import get_logger

logger = get_logger("merid.agents.coordination")


# ======================================================================
# ConsensusCoordinatorAgent
# ======================================================================

@dataclass
class AgentVote:
    """A single agent's vote on a proposal."""
    agent_id: str
    decision: str  # "approve", "reject", "abstain"
    confidence: float = 0.5
    reasoning: str = ""
    weight: float = 1.0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "decision": self.decision,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "weight": self.weight,
        }


@dataclass
class ConsensusResult:
    """Aggregated consensus decision."""
    proposal_id: str
    decision: str  # "approved", "rejected", "no_quorum"
    approval_score: float = 0.0
    rejection_score: float = 0.0
    votes: List[AgentVote] = field(default_factory=list)
    vetoed_by: Optional[str] = None
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "decision": self.decision,
            "approval_score": round(self.approval_score, 3),
            "rejection_score": round(self.rejection_score, 3),
            "votes": [v.to_dict() for v in self.votes],
            "vetoed_by": self.vetoed_by,
            "rationale": self.rationale,
        }


class ConsensusCoordinatorAgent(CanonicalAgent):
    """Manages voting/aggregation among domain agents.

    Runs a weighted consensus protocol:
    1. Collect votes from all participating agents.
    2. Apply confidence-weighted scoring.
    3. Check for vetoes (risk, governance agents can hard-veto).
    4. Produce a single approved/rejected decision.
    """

    def __init__(
        self,
        agent_id: str = "consensus-coordinator-01",
        approval_threshold: float = 0.6,
        veto_agents: Optional[List[str]] = None,
    ):
        super().__init__(agent_id, AgentCategory.COORDINATION)
        self.approval_threshold = approval_threshold
        self.veto_agents = set(veto_agents or ["risk-manager-01", "governance-01"])
        self._history: List[ConsensusResult] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Run consensus on proposals with provided votes.

        Context:
            proposals: List[TradeProposal]
            votes: Dict[proposal_id, List[AgentVote]]
        """
        proposals = context.get("proposals", [])
        all_votes = context.get("votes", {})
        results = []

        for p in proposals:
            pid = p.proposal_id if hasattr(p, "proposal_id") else str(p)
            votes = all_votes.get(pid, [])
            result = self.aggregate(pid, votes)
            results.append(result)
            self._history.append(result)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="consensus_results",
            payload={
                "results": [r.to_dict() for r in results],
                "approved": sum(1 for r in results if r.decision == "approved"),
                "rejected": sum(1 for r in results if r.decision == "rejected"),
            },
            confidence=0.9,
        )

    def aggregate(
        self,
        proposal_id: str,
        votes: List[AgentVote],
        risk_context: Optional["RiskContext"] = None,
    ) -> ConsensusResult:
        """Aggregate votes into a consensus decision.

        If *risk_context* is supplied, the effective approval threshold is
        raised by ``risk_context.approval_threshold_boost``.  This makes the
        swarm more conservative when system state is stressed (poor CQI,
        elevated drawdown, high exposure).
        """
        if not votes:
            return ConsensusResult(
                proposal_id=proposal_id, decision="no_quorum",
                rationale="No votes received.",
            )

        # Check for vetoes
        for v in votes:
            if v.agent_id in self.veto_agents and v.decision == "reject":
                return ConsensusResult(
                    proposal_id=proposal_id, decision="rejected",
                    votes=votes, vetoed_by=v.agent_id,
                    rationale=f"Vetoed by {v.agent_id}: {v.reasoning}",
                )

        # Weighted scoring
        approve_score = 0.0
        reject_score = 0.0
        total_weight = 0.0

        for v in votes:
            w = v.weight * v.confidence
            total_weight += w
            if v.decision == "approve":
                approve_score += w
            elif v.decision == "reject":
                reject_score += w

        if total_weight == 0:
            return ConsensusResult(
                proposal_id=proposal_id, decision="no_quorum",
                votes=votes, rationale="Zero total weight.",
            )

        approval_pct = approve_score / total_weight
        rejection_pct = reject_score / total_weight

        # Apply RiskContext threshold boost (system-level stress)
        effective_threshold = self.approval_threshold
        boost = 0.0
        if risk_context is not None and risk_context.approval_threshold_boost > 0:
            boost = risk_context.approval_threshold_boost
            effective_threshold = min(
                self.approval_threshold + boost, 0.95
            )

        decision = "approved" if approval_pct >= effective_threshold else "rejected"
        rationale = f"Approval: {approval_pct:.1%}, threshold: {effective_threshold:.1%}."
        if boost > 0:
            rationale += f" (base {self.approval_threshold:.1%} + risk boost {boost:.1%})"
        return ConsensusResult(
            proposal_id=proposal_id, decision=decision,
            approval_score=approval_pct, rejection_score=rejection_pct,
            votes=votes,
            rationale=rationale,
        )


# ======================================================================
# ExplainabilityAgent
# ======================================================================

@dataclass
class Explanation:
    """Structured explanation for a trade or risk event."""
    event_id: str
    event_type: str  # "trade", "risk_event", "anomaly", "consensus"
    what: str = ""
    why: str = ""
    why_now: str = ""
    data_sources: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    confidence: float = 0.5
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "what": self.what,
            "why": self.why,
            "why_now": self.why_now,
            "data_sources": self.data_sources,
            "risk_factors": self.risk_factors,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_human_readable(self) -> str:
        lines = [
            f"Event: {self.event_type} ({self.event_id})",
            f"What: {self.what}",
            f"Why: {self.why}",
            f"Why now: {self.why_now}",
        ]
        if self.risk_factors:
            lines.append(f"Risk factors: {', '.join(self.risk_factors)}")
        return "\n".join(lines)


class ExplainabilityAgent(CanonicalAgent):
    """Turns internal state and logs into human-readable rationale.

    For every executed trade or risk event, produces a structured
    explanation answering "why this?" and "why now?".
    """

    def __init__(self, agent_id: str = "explainability-01"):
        super().__init__(agent_id, AgentCategory.COORDINATION)
        self._explanations: List[Explanation] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        events = context.get("events", [])
        explanations = []
        for event in events:
            exp = self.explain(event)
            explanations.append(exp)
            self._explanations.append(exp)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="explanations",
            payload={
                "explanations": [e.to_dict() for e in explanations],
                "count": len(explanations),
            },
            confidence=0.7,
        )

    def explain(self, event: Dict[str, Any]) -> Explanation:
        """Generate an explanation for a single event."""
        event_type = event.get("type", "unknown")
        event_id = event.get("id", "")

        what = event.get("what", event.get("summary", ""))
        why = event.get("why", event.get("rationale", ""))
        why_now = event.get("why_now", event.get("trigger", ""))
        sources = event.get("data_sources", [])
        risks = event.get("risk_factors", [])

        # Auto-generate if missing
        if not what and "proposal" in event:
            p = event["proposal"]
            what = f"{p.get('side', '?')} {p.get('qty', '?')} {p.get('instrument_id', '?')} on {p.get('venue', '?')}"
        if not why:
            why = event.get("reason", "No rationale provided.")
        if not why_now:
            why_now = "Triggered by agent scan cycle."

        return Explanation(
            event_id=event_id, event_type=event_type,
            what=what, why=why, why_now=why_now,
            data_sources=sources, risk_factors=risks,
            confidence=event.get("confidence", 0.5),
        )

    def get_explanations(self, limit: int = 50) -> List[Explanation]:
        return self._explanations[-limit:]


# ======================================================================
# GovernanceAgent
# ======================================================================

@dataclass
class GovernanceVerdict:
    """Result of a governance check."""
    proposal_id: str
    compliant: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "compliant": self.compliant,
            "violations": self.violations,
            "warnings": self.warnings,
        }


# ======================================================================
# DebateCoordinatorAgent
# ======================================================================

class DebateCoordinatorAgent(CanonicalAgent):
    """Orchestrates structured multi-agent debates on prediction instruments.

    Protocol per instrument:
      1. Proposer agent submits an opinion with explanation.
      2. Challenger agent generates a counter-opinion and counter-explanation.
      3. Arbiter agent synthesizes a revised team opinion from both arguments.
      4. Pre-debate and post-debate probabilities are recorded for debate lift.

    Integrates with DebateStore for persistence and metrics.
    """

    def __init__(
        self,
        agent_id: str = "debate-coordinator-01",
        max_rounds: int = 3,
        min_disagreement: float = 0.03,
    ):
        super().__init__(agent_id, AgentCategory.COORDINATION)
        self.max_rounds = max_rounds
        self.min_disagreement = min_disagreement
        self._debate_history: List[Dict[str, Any]] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Run debate sessions for instruments provided in context.

        Context:
            instruments: List[dict] with symbol, ticker, market_prob, category
            proposer_strategy: str (strategy name for proposer)
            challenger_strategy: str (strategy name for challenger, default "challenger")
            proposer_agent_id: str
            challenger_agent_id: str
        """
        instruments = context.get("instruments", [])
        results = []

        # W5: Build a MarketState snapshot and call observe() + analyze() on all
        # registered canonical agents so they can enrich the debate context with
        # their latest market observations before the debate round begins.
        agent_analyses: Dict[str, Any] = {}
        try:
            import time as _time
            from agents.interface import MarketState
            from merid.agents.base import get_canonical_registry

            market_state = MarketState(
                timestamp=_time.time(),
                prices={inst.get("ticker", inst.get("symbol", "")): inst.get("market_prob", 0.5)
                        for inst in instruments},
                volumes={},
                funding_rates={},
                news_sentiment=context.get("news_sentiment", 0.0),
                volatility_index=context.get("volatility_index", 0.5),
                metadata={"source": "debate_coordinator", "instrument_count": len(instruments)},
            )
            registry = get_canonical_registry()
            for agent in registry.all().values():
                try:
                    await agent.observe(market_state)
                    analysis = await agent.analyze()
                    if analysis:
                        agent_analyses[agent.agent_id] = analysis
                except Exception as _ae:
                    self.logger.debug("observe/analyze skipped for %s: %s", agent.agent_id, _ae)

            if agent_analyses:
                context = {**context, "agent_analyses": agent_analyses}
        except Exception as exc:
            self.logger.debug("W5 observe/analyze phase skipped: %s", exc)

        for inst in instruments:
            result = self.run_debate(inst, context)
            if result:
                results.append(result)
                self._debate_history.append(result)

                # W5: Call reflect() on all canonical agents with the debate outcome
                # so they can update learned patterns and adjust future behaviour.
                try:
                    from agents.interface import Outcome
                    import uuid as _uuid
                    outcome = Outcome(
                        outcome_id=str(_uuid.uuid4()),
                        proposal_id=result.get("debate_id", ""),
                        result="debate_complete",
                        actual_value=result.get("post_debate_prob"),
                        predicted_value=result.get("market_prob"),
                        timestamp=_time.time(),
                        metadata={
                            "symbol": result.get("symbol"),
                            "disagreement_width": result.get("disagreement_width"),
                            "debate_suppressed": result.get("debate_suppressed"),
                        },
                    )
                    for agent in registry.all().values():
                        try:
                            await agent.reflect(outcome)
                        except Exception as _re:
                            self.logger.debug("reflect skipped for %s: %s", agent.agent_id, _re)
                except Exception as exc:
                    self.logger.debug("W5 reflect phase skipped: %s", exc)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="debate_results",
            payload={
                "debates": results,
                "count": len(results),
            },
            confidence=0.8 if results else 0.3,
        )

    def run_debate(
        self,
        instrument: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Run a single debate session for an instrument.

        Returns a dict with debate session details, arguments, and post-debate opinion.
        """
        from merid.prediction.opinion_strategy import get_strategy
        from merid.prediction.debate import (
            DebateSession, DebateArgument, DebateStore, get_debate_store,
        )

        symbol = instrument.get("symbol", "")
        ticker = instrument.get("ticker", "")
        market_prob = instrument.get("market_prob", 0.5)
        category = instrument.get("category", "")

        proposer_strategy_name = context.get("proposer_strategy", "mean_reversion")
        arbiter_strategy_name = context.get("arbiter_strategy", "arbiter")
        proposer_agent_id = context.get("proposer_agent_id", "proposer-01")
        challenger_agent_id = context.get("challenger_agent_id", "challenger-01")
        arbiter_agent_id = context.get("arbiter_agent_id", self.agent_id)
        team_id = context.get("team_id", "")

        try:
            proposer_strategy = get_strategy(proposer_strategy_name)
            challenger_strategy = get_strategy("challenger")
            arbiter_strategy = get_strategy(arbiter_strategy_name)
        except Exception as exc:
            logger.warning(f"Debate strategy init failed: {exc}")
            return None

        # Step 1: Proposer generates opinion
        proposer_estimate = proposer_strategy.estimate(
            agent_id=proposer_agent_id,
            ticker=ticker,
            market_prob=market_prob,
            category=category,
            context=context,
        )
        if proposer_estimate is None:
            return None

        # Step 2: Challenger generates counter-opinion
        challenge_context = {
            **context,
            "proposer_prob": proposer_estimate.agent_prob,
            "proposer_rationale": proposer_estimate.reasoning_tag,
        }
        challenger_estimate = challenger_strategy.estimate(
            agent_id=challenger_agent_id,
            ticker=ticker,
            market_prob=market_prob,
            category=category,
            context=challenge_context,
        )

        # Quality gate: suppress arbiter if disagreement is too low
        challenger_prob = challenger_estimate.agent_prob if challenger_estimate else market_prob
        disagreement_width = abs(proposer_estimate.agent_prob - challenger_prob)
        debate_suppressed = disagreement_width < self.min_disagreement

        arbiter_estimate = None
        if not debate_suppressed:
            # Step 3: Arbiter synthesizes
            arbiter_context = {
                **context,
                "proposer_prob": proposer_estimate.agent_prob,
                "proposer_confidence": proposer_estimate.confidence,
                "challenger_prob": challenger_prob,
                "challenger_confidence": challenger_estimate.confidence if challenger_estimate else 0.3,
            }
            arbiter_estimate = arbiter_strategy.estimate(
                agent_id=arbiter_agent_id,
                ticker=ticker,
                market_prob=market_prob,
                category=category,
                context=arbiter_context,
            )
        else:
            logger.info(f"Debate suppressed for {symbol}: disagreement_width={disagreement_width:.4f} < min={self.min_disagreement}")

        post_debate_prob = arbiter_estimate.agent_prob if arbiter_estimate else proposer_estimate.agent_prob

        # Persist to DebateStore
        debate_id = ""
        try:
            store = get_debate_store()
            session = DebateSession(
                symbol=symbol,
                team_id=team_id,
                pre_debate_prob=market_prob,
                post_debate_prob=post_debate_prob,
                rounds=3,
            )
            store.create_debate(session)
            debate_id = session.id

            # Record arguments
            prop_arg = DebateArgument(
                debate_id=session.id,
                agent_id=proposer_agent_id,
                role="proposer",
                probability=proposer_estimate.agent_prob,
                confidence=proposer_estimate.confidence,
                rationale=proposer_estimate.reasoning_tag,
                explanation=proposer_estimate.explanation.to_dict() if proposer_estimate.explanation else None,
            )
            store.add_argument(prop_arg)

            if challenger_estimate:
                chal_arg = DebateArgument(
                    debate_id=session.id,
                    agent_id=challenger_agent_id,
                    role="challenger",
                    probability=challenger_estimate.agent_prob,
                    confidence=challenger_estimate.confidence,
                    rationale=challenger_estimate.reasoning_tag,
                    explanation=challenger_estimate.explanation.to_dict() if challenger_estimate.explanation else None,
                )
                store.add_argument(chal_arg)

            if arbiter_estimate:
                arb_arg = DebateArgument(
                    debate_id=session.id,
                    agent_id=arbiter_agent_id,
                    role="arbiter",
                    probability=arbiter_estimate.agent_prob,
                    confidence=arbiter_estimate.confidence,
                    rationale=arbiter_estimate.reasoning_tag,
                    explanation=arbiter_estimate.explanation.to_dict() if arbiter_estimate.explanation else None,
                )
                store.add_argument(arb_arg)

        except Exception as exc:
            logger.warning(f"Debate persistence failed for {symbol}: {exc}")

        return {
            "debate_id": debate_id,
            "symbol": symbol,
            "market_prob": round(market_prob, 4),
            "proposer": {
                "agent_id": proposer_agent_id,
                "strategy": proposer_strategy_name,
                "prob": proposer_estimate.agent_prob,
                "confidence": proposer_estimate.confidence,
                "rationale": proposer_estimate.reasoning_tag,
            },
            "challenger": {
                "agent_id": challenger_agent_id,
                "prob": challenger_estimate.agent_prob if challenger_estimate else None,
                "confidence": challenger_estimate.confidence if challenger_estimate else None,
                "rationale": challenger_estimate.reasoning_tag if challenger_estimate else None,
            },
            "arbiter": {
                "agent_id": arbiter_agent_id,
                "strategy": arbiter_strategy_name,
                "prob": arbiter_estimate.agent_prob if arbiter_estimate else None,
                "confidence": arbiter_estimate.confidence if arbiter_estimate else None,
            },
            "post_debate_prob": round(post_debate_prob, 4),
            "disagreement_width": round(disagreement_width, 4),
            "debate_suppressed": debate_suppressed,
        }


# ======================================================================
# GovernanceAgent
# ======================================================================

class GovernanceAgent(CanonicalAgent):
    """Enforces non-negotiable constraints (compliance, forbidden venues, ethical rules).

    Hard veto on violations, with explanations.
    Policies:
    - No illegal venues (Polymarket, Augur for US).
    - Leverage limits per domain.
    - Venue-specific bans.
    """

    # Forbidden venues for US compliance
    FORBIDDEN_VENUES = {"polymarket", "augur", "predictit"}
    MAX_LEVERAGE = {"crypto": 3.0, "equity": 2.0, "prediction": 1.0}

    def __init__(self, agent_id: str = "governance-01"):
        super().__init__(agent_id, AgentCategory.COORDINATION)
        self._verdicts: List[GovernanceVerdict] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        proposals = context.get("proposals", [])
        verdicts = []
        for p in proposals:
            v = self.check(p)
            verdicts.append(v)
            self._verdicts.append(v)

        compliant = sum(1 for v in verdicts if v.compliant)
        violations = len(verdicts) - compliant

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="governance_verdicts",
            payload={
                "verdicts": [v.to_dict() for v in verdicts],
                "compliant": compliant,
                "violations": violations,
            },
            confidence=1.0,
        )

    def check(self, proposal: TradeProposal) -> GovernanceVerdict:
        """Check a proposal against governance policies."""
        violations = []
        warnings = []

        # Venue compliance
        venue = proposal.venue.lower() if proposal.venue else ""
        if venue in self.FORBIDDEN_VENUES:
            violations.append(
                f"Venue '{venue}' is forbidden for US compliance."
            )

        # Domain-specific leverage (if metadata includes leverage)
        leverage = proposal.metadata.get("leverage", 1.0)
        domain = proposal.domain.value if hasattr(proposal.domain, "value") else str(proposal.domain)
        max_lev = self.MAX_LEVERAGE.get(domain, 1.0)
        if leverage > max_lev:
            violations.append(
                f"Leverage {leverage}x exceeds max {max_lev}x for {domain}."
            )

        # Prediction market venue check
        if domain == "prediction" and venue and venue != "kalshi":
            violations.append(
                f"Only Kalshi is allowed for prediction markets. Got: {venue}."
            )

        # Confidence warning
        if proposal.confidence < Decimal("0.3"):
            warnings.append("Very low confidence (<30%). Consider reviewing.")

        return GovernanceVerdict(
            proposal_id=proposal.proposal_id,
            compliant=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )
