"""Comprehensive tests for agent wiring, hybrid bridge, orchestrator, and integration flow.

LEGACY: This module tests CanonicalAgentRegistry, which is not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack uses agent_grid_15m for agent management.

Covers:
§1 Wiring: WiredPredictionMarketAgent, WiredCryptoSignalsAgent, WiredMarketResearchAgent
§2 Hybrid: HybridBridge, LLMEnhancement, HybridCanonicalAgent
§3 Orchestrator: AgentOrchestrator, phased execution, context piping
§4 Integration: full signal → proposal → consensus → risk → venue flow
"""

import pytest

pytestmark = pytest.mark.legacy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from merid.agents.base import (
    AgentCategory,
    AgentOutput,
    AgentStatus,
    CanonicalAgent,
    CanonicalAgentRegistry,
)
from merid.agents.research import (
    CryptoSignalsAgent,
    MarketResearchAgent,
    PredictionMarketAgentV2,
    ResearchThesis,
    ThesisDirection,
)
from merid.agents.strategy import (
    ArbitrageAgent,
    ArbOpportunity,
    ExecutionOptimizerAgent,
    StrategyDesignerAgent,
)
from merid.agents.risk_agents import (
    RiskManagerAgent,
    CapitalAllocatorAgent,
    AnomalyDetectorAgent,
)
from merid.agents.coordination import (
    ConsensusCoordinatorAgent,
    ExplainabilityAgent,
    GovernanceAgent,
    AgentVote,
)
from merid.agents.ops import OpsRunbookAgent, BacktestAgent
from merid.agents.hybrid import (
    HybridBridge,
    HybridCanonicalAgent,
    LLMEnhancement,
)
from merid.agents.orchestrator import (
    AgentOrchestrator,
    PhaseResult,
    CycleResult,
    _build_phase_context,
    PHASE_ORDER,
)
from merid.agents.wiring import (
    WiredPredictionMarketAgent,
    WiredCryptoSignalsAgent,
    WiredMarketResearchAgent,
)
from merid.pipeline.proposal import TradeDomain, TradeProposal, OrderSide
from merid.pipeline.risk_manager import GlobalRiskManager


# ======================================================================
# §1 Wiring Tests
# ======================================================================

class TestWiredPredictionMarketAgent:

    @pytest.mark.asyncio
    async def test_run_without_client(self):
        """Should gracefully return empty when Kalshi client unavailable."""
        agent = WiredPredictionMarketAgent()
        out = await agent.run()
        assert out.output_type == "pm_opportunities"
        assert out.payload["opportunities"] == []

    def test_agent_id(self):
        agent = WiredPredictionMarketAgent()
        assert agent.agent_id == "pm-research-live"
        assert agent.venue == "kalshi"


class TestWiredCryptoSignalsAgent:

    @pytest.mark.asyncio
    async def test_run_without_ccxt(self):
        """Should gracefully return empty when ccxt unavailable."""
        agent = WiredCryptoSignalsAgent()
        out = await agent.run()
        assert out.output_type == "crypto_signals"

    def test_agent_id(self):
        agent = WiredCryptoSignalsAgent()
        assert agent.agent_id == "crypto-signals-live"


class TestWiredMarketResearchAgent:

    @pytest.mark.asyncio
    async def test_run_without_alpaca(self):
        """Should gracefully return empty when Alpaca unavailable."""
        agent = WiredMarketResearchAgent()
        out = await agent.run()
        assert out.output_type == "theses"
        assert out.payload["count"] == 0

    def test_agent_id(self):
        agent = WiredMarketResearchAgent()
        assert agent.agent_id == "market-research-live"


# ======================================================================
# §2 Hybrid Bridge Tests
# ======================================================================

class TestLLMEnhancement:

    def test_to_dict(self):
        e = LLMEnhancement(vote="accept", confidence=0.8, reasoning="Looks good")
        d = e.to_dict()
        assert d["vote"] == "accept"
        assert d["confidence"] == 0.8

    def test_default_values(self):
        e = LLMEnhancement()
        assert e.vote == "abstain"
        assert e.success is False


class TestHybridBridge:

    @pytest.mark.asyncio
    async def test_enhance_without_base_agent(self):
        """Should return error when BaseAgent unavailable."""
        bridge = HybridBridge()
        output = AgentOutput(
            agent_id="test", category="research",
            output_type="theses", confidence=0.7,
        )
        result = await bridge.enhance(output)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_enhance_output_without_llm(self):
        """Should preserve original output when LLM unavailable."""
        bridge = HybridBridge()
        output = AgentOutput(
            agent_id="test", category="research",
            output_type="theses", confidence=0.7,
            payload={"theses": []},
        )
        result = await bridge.enhance_output(output)
        assert "llm_reasoning" in result.payload
        # Confidence should be unchanged since LLM failed
        assert result.confidence == 0.7


class TestHybridCanonicalAgent:

    @pytest.mark.asyncio
    async def test_run_without_llm(self):
        """HybridCanonicalAgent with llm_enabled=False should behave normally."""
        class _TestHybrid(HybridCanonicalAgent):
            async def _execute(self, context):
                return AgentOutput(
                    agent_id=self.agent_id, category=self.category.value,
                    output_type="test", confidence=0.8,
                )

        agent = _TestHybrid("test-hybrid", AgentCategory.RESEARCH, llm_enabled=False)
        out = await agent.run()
        assert out.output_type == "test"
        assert out.confidence == 0.8
        assert "llm_reasoning" not in out.payload

    @pytest.mark.asyncio
    async def test_run_with_llm_enabled_but_unavailable(self):
        """Should still produce output even when LLM is unavailable."""
        class _TestHybrid(HybridCanonicalAgent):
            async def _execute(self, context):
                return AgentOutput(
                    agent_id=self.agent_id, category=self.category.value,
                    output_type="test", confidence=0.8,
                    payload={"data": "test"},
                )

        agent = _TestHybrid("test-hybrid", AgentCategory.RESEARCH, llm_enabled=True)
        out = await agent.run()
        assert out.output_type == "test"
        # LLM enhancement attempted but failed gracefully
        assert "llm_reasoning" in out.payload


# ======================================================================
# §3 Orchestrator Tests
# ======================================================================

class _StubResearchAgent(CanonicalAgent):
    async def _execute(self, context):
        return AgentOutput(
            agent_id=self.agent_id, category=self.category.value,
            output_type="theses",
            payload={
                "theses": [{"instrument": "BTC-USD", "direction": "long", "domain": "crypto"}],
                "count": 1,
            },
            confidence=0.8,
        )


class _StubStrategyAgent(CanonicalAgent):
    async def _execute(self, context):
        theses = context.get("theses", [])
        return AgentOutput(
            agent_id=self.agent_id, category=self.category.value,
            output_type="strategy_definitions",
            payload={
                "strategies": [{"strategy_id": "s1", "domain": "crypto"}] if theses else [],
                "total_strategies": 1 if theses else 0,
            },
            confidence=0.7,
        )


class _StubRiskAgent(CanonicalAgent):
    async def _execute(self, context):
        return AgentOutput(
            agent_id=self.agent_id, category=self.category.value,
            output_type="risk_verdicts",
            payload={"verdicts": [{"approved": True}], "approved": 1, "rejected": 0},
            confidence=0.9,
        )


class _StubCoordAgent(CanonicalAgent):
    async def _execute(self, context):
        return AgentOutput(
            agent_id=self.agent_id, category=self.category.value,
            output_type="consensus_results",
            payload={"results": [{"decision": "approved"}], "count": 1},
            confidence=0.85,
        )


class _StubOpsAgent(CanonicalAgent):
    async def _execute(self, context):
        return AgentOutput(
            agent_id=self.agent_id, category=self.category.value,
            output_type="runbook_actions",
            payload={"count": 0},
            confidence=0.5,
        )


class TestBuildPhaseContext:

    def test_empty(self):
        ctx = _build_phase_context({}, [])
        assert ctx == {}

    def test_theses_piped(self):
        outputs = [
            AgentOutput(
                agent_id="r1", category="research", output_type="theses",
                payload={"theses": [{"instrument": "BTC"}]},
            ),
        ]
        ctx = _build_phase_context({}, outputs)
        assert "theses" in ctx
        assert len(ctx["theses"]) == 1

    def test_signals_piped(self):
        outputs = [
            AgentOutput(
                agent_id="s1", category="research", output_type="crypto_signals",
                payload={"signals": [{"pair": "BTC-USD"}]},
            ),
        ]
        ctx = _build_phase_context({}, outputs)
        assert "signals" in ctx

    def test_multiple_types(self):
        outputs = [
            AgentOutput(agent_id="r1", category="research", output_type="theses",
                        payload={"theses": [{"x": 1}]}),
            AgentOutput(agent_id="r2", category="research", output_type="pm_opportunities",
                        payload={"opportunities": [{"y": 2}]}),
        ]
        ctx = _build_phase_context({}, outputs)
        assert len(ctx["theses"]) == 1
        assert len(ctx["opportunities"]) == 1

    def test_base_context_preserved(self):
        ctx = _build_phase_context({"market_data": [1, 2, 3]}, [])
        assert ctx["market_data"] == [1, 2, 3]


class TestPhaseResult:

    def test_to_dict(self):
        pr = PhaseResult(phase="research", agents_run=3, latency_ms=150.0)
        d = pr.to_dict()
        assert d["phase"] == "research"
        assert d["agents_run"] == 3


class TestCycleResult:

    def test_to_dict(self):
        cr = CycleResult(cycle_id="c1", total_outputs=5, total_latency_ms=500.0)
        d = cr.to_dict()
        assert d["cycle_id"] == "c1"
        assert d["total_outputs"] == 5


class TestAgentOrchestrator:

    def _build_registry(self):
        reg = CanonicalAgentRegistry()
        reg.register(_StubResearchAgent("r1", AgentCategory.RESEARCH))
        reg.register(_StubStrategyAgent("s1", AgentCategory.STRATEGY))
        reg.register(_StubRiskAgent("risk1", AgentCategory.RISK))
        reg.register(_StubCoordAgent("coord1", AgentCategory.COORDINATION))
        reg.register(_StubOpsAgent("ops1", AgentCategory.OPS))
        return reg

    @pytest.mark.asyncio
    async def test_run_cycle(self):
        reg = self._build_registry()
        orch = AgentOrchestrator(registry=reg)
        result = await orch.run_cycle()
        assert len(result.phases) == 5
        assert result.total_outputs == 5
        assert result.total_latency_ms > 0

    @pytest.mark.asyncio
    async def test_phase_order(self):
        reg = self._build_registry()
        orch = AgentOrchestrator(registry=reg)
        result = await orch.run_cycle()
        phase_names = [p.phase for p in result.phases]
        assert phase_names == ["research", "strategy", "risk", "coordination", "ops"]

    @pytest.mark.asyncio
    async def test_context_piping(self):
        """Strategy agent should receive theses from research phase."""
        reg = CanonicalAgentRegistry()
        reg.register(_StubResearchAgent("r1", AgentCategory.RESEARCH))

        # Strategy agent that checks for theses in context
        class _CheckCtx(CanonicalAgent):
            received_theses = False
            async def _execute(self, context):
                if context.get("theses"):
                    _CheckCtx.received_theses = True
                return AgentOutput(
                    agent_id=self.agent_id, category=self.category.value,
                    output_type="test", confidence=0.5,
                )

        reg.register(_CheckCtx("s1", AgentCategory.STRATEGY))
        orch = AgentOrchestrator(registry=reg)
        await orch.run_cycle()
        assert _CheckCtx.received_theses is True

    @pytest.mark.asyncio
    async def test_paused_agent_skipped(self):
        reg = CanonicalAgentRegistry()
        agent = _StubResearchAgent("r1", AgentCategory.RESEARCH)
        agent.pause()
        reg.register(agent)
        orch = AgentOrchestrator(registry=reg)
        result = await orch.run_cycle()
        research_phase = result.phases[0]
        assert research_phase.agents_skipped == 1
        assert research_phase.agents_run == 0

    @pytest.mark.asyncio
    async def test_run_loop_max_cycles(self):
        reg = self._build_registry()
        orch = AgentOrchestrator(registry=reg)
        results = await orch.run_loop(interval_seconds=0.01, max_cycles=3)
        assert len(results) == 3
        assert orch._cycle_count == 3

    def test_stop(self):
        orch = AgentOrchestrator()
        orch._running = True
        orch.stop()
        assert orch._running is False

    def test_summary(self):
        reg = self._build_registry()
        orch = AgentOrchestrator(registry=reg)
        s = orch.summary()
        assert s["registered_agents"] == 5
        assert s["cycle_count"] == 0

    def test_get_history_empty(self):
        orch = AgentOrchestrator()
        assert orch.get_history() == []

    @pytest.mark.asyncio
    async def test_get_history_after_cycle(self):
        reg = self._build_registry()
        orch = AgentOrchestrator(registry=reg)
        await orch.run_cycle()
        history = orch.get_history()
        assert len(history) == 1
        assert history[0].cycle_id == "cycle-1"


# ======================================================================
# §4 Integration Tests — Full Signal → Proposal → Consensus → Risk → Venue
# ======================================================================

class TestFullPipelineIntegration:
    """End-to-end integration test using real canonical agents."""

    def _build_full_registry(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        reg = CanonicalAgentRegistry()

        # §1 Research
        reg.register(MarketResearchAgent())
        reg.register(PredictionMarketAgentV2())
        reg.register(CryptoSignalsAgent())

        # §2 Strategy
        reg.register(StrategyDesignerAgent())
        reg.register(ArbitrageAgent())
        reg.register(ExecutionOptimizerAgent())

        # §3 Risk
        reg.register(RiskManagerAgent(risk_manager=rm))
        reg.register(CapitalAllocatorAgent(risk_manager=rm))
        reg.register(AnomalyDetectorAgent())

        # §4 Coordination
        reg.register(ConsensusCoordinatorAgent())
        reg.register(ExplainabilityAgent())
        reg.register(GovernanceAgent())

        # §5 Ops
        reg.register(OpsRunbookAgent())
        reg.register(BacktestAgent())

        return reg

    @pytest.mark.asyncio
    async def test_full_cycle_all_14_agents(self):
        """Run all 14 canonical agents through the orchestrator."""
        reg = self._build_full_registry()
        orch = AgentOrchestrator(registry=reg)
        result = await orch.run_cycle()

        assert result.total_outputs == 14
        assert len(result.phases) == 5

        # Verify each phase ran
        phase_map = {p.phase: p for p in result.phases}
        assert phase_map["research"].agents_run == 3
        assert phase_map["strategy"].agents_run == 3
        assert phase_map["risk"].agents_run == 3
        assert phase_map["coordination"].agents_run == 3
        assert phase_map["ops"].agents_run == 2

    @pytest.mark.asyncio
    async def test_signal_to_proposal_flow(self):
        """Test that research outputs feed into strategy agents."""
        reg = CanonicalAgentRegistry()

        # Research agent that produces a thesis
        class _LiveResearch(CanonicalAgent):
            async def _execute(self, context):
                return AgentOutput(
                    agent_id=self.agent_id, category=self.category.value,
                    output_type="theses",
                    payload={
                        "theses": [{
                            "instrument": "BTC-USD", "direction": "long",
                            "domain": "crypto", "confidence": 0.8,
                        }],
                        "count": 1,
                    },
                    confidence=0.8,
                )

        reg.register(_LiveResearch("r1", AgentCategory.RESEARCH))
        reg.register(StrategyDesignerAgent())

        orch = AgentOrchestrator(registry=reg, phases=[AgentCategory.RESEARCH, AgentCategory.STRATEGY])
        result = await orch.run_cycle()

        # Strategy should have received the thesis and produced a strategy
        strategy_phase = result.phases[1]
        assert strategy_phase.agents_run == 1
        strategy_output = strategy_phase.outputs[0]
        assert strategy_output.payload["total_strategies"] == 1

    @pytest.mark.asyncio
    async def test_proposal_to_risk_flow(self):
        """Test that proposals get risk-checked."""
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        reg = CanonicalAgentRegistry()

        # Strategy agent that produces a proposal
        class _ProposalAgent(CanonicalAgent):
            async def _execute(self, context):
                proposals = [
                    TradeProposal(
                        domain=TradeDomain.CRYPTO, venue="binance",
                        notional_usd=Decimal("1000"), side=OrderSide.BUY,
                    ),
                ]
                return AgentOutput(
                    agent_id=self.agent_id, category=self.category.value,
                    output_type="proposals",
                    payload={"proposals": proposals},
                    confidence=0.7,
                )

        reg.register(_ProposalAgent("strat1", AgentCategory.STRATEGY))
        reg.register(RiskManagerAgent(risk_manager=rm))

        orch = AgentOrchestrator(
            registry=reg,
            phases=[AgentCategory.STRATEGY, AgentCategory.RISK],
        )
        result = await orch.run_cycle()

        risk_phase = result.phases[1]
        assert risk_phase.agents_run == 1

    @pytest.mark.asyncio
    async def test_consensus_voting_flow(self):
        """Test consensus voting on proposals."""
        reg = CanonicalAgentRegistry()
        coordinator = ConsensusCoordinatorAgent()

        # Simulate votes
        proposal = TradeProposal(domain=TradeDomain.CRYPTO)
        votes = [
            AgentVote(agent_id="a1", decision="approve", confidence=0.9),
            AgentVote(agent_id="a2", decision="approve", confidence=0.8),
        ]
        result = coordinator.aggregate(proposal.proposal_id, votes)
        assert result.decision == "approved"

    @pytest.mark.asyncio
    async def test_governance_blocks_prohibited_venue(self):
        """Test that governance blocks polymarket."""
        gov = GovernanceAgent()
        p = TradeProposal(domain=TradeDomain.PREDICTION, venue="polymarket")
        verdict = gov.check(p)
        assert verdict.compliant is False

    @pytest.mark.asyncio
    async def test_risk_blocks_oversized_order(self):
        """Test that risk manager blocks oversized orders."""
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        risk_agent = RiskManagerAgent(risk_manager=rm)
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("10000"),  # Exceeds single order max
        )
        verdict = risk_agent.evaluate(p)
        assert verdict.approved is False

    @pytest.mark.asyncio
    async def test_multi_cycle_loop(self):
        """Test running multiple cycles."""
        reg = self._build_full_registry()
        orch = AgentOrchestrator(registry=reg)
        results = await orch.run_loop(interval_seconds=0.01, max_cycles=2)
        assert len(results) == 2
        assert all(r.total_outputs == 14 for r in results)

    @pytest.mark.asyncio
    async def test_explainability_in_flow(self):
        """Test that explainability agent produces explanations."""
        agent = ExplainabilityAgent()
        events = [{"id": "e1", "type": "trade", "what": "Buy BTC on Binance"}]
        out = await agent.run({"events": events})
        assert out.output_type == "explanations"
        assert out.payload["count"] == 1
