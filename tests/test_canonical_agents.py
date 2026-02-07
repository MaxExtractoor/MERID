"""Comprehensive test suite for merid.agents — Canonical agent roster.

Covers all 5 categories:
§1 Research: MarketResearchAgent, PredictionMarketAgentV2, CryptoSignalsAgent
§2 Strategy: StrategyDesignerAgent, ArbitrageAgent, ExecutionOptimizerAgent
§3 Risk: RiskManagerAgent, CapitalAllocatorAgent, AnomalyDetectorAgent
§4 Coordination: ConsensusCoordinatorAgent, ExplainabilityAgent, GovernanceAgent
§5 Ops: OpsRunbookAgent, BacktestAgent
+ Base: CanonicalAgent, CanonicalAgentRegistry
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict

from merid.agents.base import (
    AgentCategory,
    AgentOutput,
    AgentStatus,
    CanonicalAgent,
    CanonicalAgentRegistry,
)
from merid.agents.research import (
    MarketResearchAgent,
    PredictionMarketAgentV2,
    CryptoSignalsAgent,
    ResearchThesis,
    ThesisDirection,
)
from merid.agents.strategy import (
    StrategyDesignerAgent,
    ArbitrageAgent,
    ArbOpportunity,
    ExecutionOptimizerAgent,
    ExecutionPlan,
    StrategyDefinition,
)
from merid.agents.risk_agents import (
    RiskManagerAgent,
    CapitalAllocatorAgent,
    AnomalyDetectorAgent,
    Anomaly,
    RiskVerdict,
)
from merid.agents.coordination import (
    ConsensusCoordinatorAgent,
    ExplainabilityAgent,
    GovernanceAgent,
    AgentVote,
    ConsensusResult,
    Explanation,
    GovernanceVerdict,
)
from merid.agents.ops import (
    OpsRunbookAgent,
    BacktestAgent,
    RunbookAction,
    BacktestResult,
)
from merid.pipeline.proposal import (
    TradeDomain,
    TradeProposal,
    OrderSide,
    OrderType,
)
from merid.pipeline.risk_manager import GlobalRiskManager


# ======================================================================
# Base Agent Tests
# ======================================================================

class _TestAgent(CanonicalAgent):
    """Concrete test agent."""
    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="test",
            payload={"echo": context.get("msg", "")},
            confidence=0.9,
        )


class _FailAgent(CanonicalAgent):
    """Agent that always fails."""
    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        raise RuntimeError("Intentional failure")


class TestCanonicalAgentBase:

    @pytest.mark.asyncio
    async def test_run_produces_output(self):
        agent = _TestAgent("test-01", AgentCategory.RESEARCH)
        out = await agent.run({"msg": "hello"})
        assert out.output_type == "test"
        assert out.payload["echo"] == "hello"
        assert out.latency_ms > 0

    @pytest.mark.asyncio
    async def test_run_increments_count(self):
        agent = _TestAgent("test-02", AgentCategory.RESEARCH)
        await agent.run()
        await agent.run()
        assert agent._run_count == 2

    @pytest.mark.asyncio
    async def test_paused_agent_skips(self):
        agent = _TestAgent("test-03", AgentCategory.RESEARCH)
        agent.pause()
        out = await agent.run()
        assert out.output_type == "skipped"
        assert agent.status == AgentStatus.PAUSED

    @pytest.mark.asyncio
    async def test_retired_agent_skips(self):
        agent = _TestAgent("test-04", AgentCategory.RESEARCH)
        agent.retire()
        out = await agent.run()
        assert out.output_type == "skipped"

    @pytest.mark.asyncio
    async def test_resume_after_pause(self):
        agent = _TestAgent("test-05", AgentCategory.RESEARCH)
        agent.pause()
        agent.resume()
        assert agent.is_active is True
        out = await agent.run()
        assert out.output_type == "test"

    @pytest.mark.asyncio
    async def test_error_handling(self):
        agent = _FailAgent("fail-01", AgentCategory.RESEARCH)
        out = await agent.run()
        assert out.output_type == "error"
        assert len(out.errors) == 1
        assert agent.status == AgentStatus.ERROR
        assert agent._error_count == 1

    def test_summary(self):
        agent = _TestAgent("test-06", AgentCategory.STRATEGY)
        s = agent.summary()
        assert s["agent_id"] == "test-06"
        assert s["category"] == "strategy"
        assert s["status"] == "idle"

    def test_output_to_dict(self):
        out = AgentOutput(
            agent_id="x", category="research",
            output_type="test", confidence=0.8,
        )
        d = out.to_dict()
        assert d["agent_id"] == "x"
        assert d["confidence"] == 0.8


class TestCanonicalAgentRegistry:

    @pytest.mark.asyncio
    async def test_register_and_get(self):
        reg = CanonicalAgentRegistry()
        agent = _TestAgent("reg-01", AgentCategory.RESEARCH)
        reg.register(agent)
        assert reg.get("reg-01") is agent
        assert reg.get("nonexistent") is None

    def test_by_category(self):
        reg = CanonicalAgentRegistry()
        reg.register(_TestAgent("a", AgentCategory.RESEARCH))
        reg.register(_TestAgent("b", AgentCategory.STRATEGY))
        reg.register(_TestAgent("c", AgentCategory.RESEARCH))
        assert len(reg.by_category(AgentCategory.RESEARCH)) == 2

    def test_active(self):
        reg = CanonicalAgentRegistry()
        a = _TestAgent("a", AgentCategory.RESEARCH)
        b = _TestAgent("b", AgentCategory.RESEARCH)
        b.pause()
        reg.register(a)
        reg.register(b)
        assert len(reg.active()) == 1

    @pytest.mark.asyncio
    async def test_run_all(self):
        reg = CanonicalAgentRegistry()
        reg.register(_TestAgent("a", AgentCategory.RESEARCH))
        reg.register(_TestAgent("b", AgentCategory.STRATEGY))
        outputs = await reg.run_all({"msg": "batch"})
        assert len(outputs) == 2

    @pytest.mark.asyncio
    async def test_run_category(self):
        reg = CanonicalAgentRegistry()
        reg.register(_TestAgent("a", AgentCategory.RESEARCH))
        reg.register(_TestAgent("b", AgentCategory.STRATEGY))
        outputs = await reg.run_category(AgentCategory.RESEARCH)
        assert len(outputs) == 1

    def test_summary(self):
        reg = CanonicalAgentRegistry()
        reg.register(_TestAgent("a", AgentCategory.RESEARCH))
        s = reg.summary()
        assert len(s) == 1


# ======================================================================
# §1 Research Agent Tests
# ======================================================================

class TestMarketResearchAgent:

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = MarketResearchAgent()
        out = await agent.run()
        assert out.output_type == "theses"
        assert out.payload["count"] == 0

    def test_thesis_to_dict(self):
        t = ResearchThesis(
            thesis_id="t1", domain="crypto", instrument="BTC-USD",
            direction=ThesisDirection.LONG, confidence=0.8,
            drivers=["macro", "on-chain"],
        )
        d = t.to_dict()
        assert d["direction"] == "long"
        assert d["confidence"] == 0.8

    def test_get_theses(self):
        agent = MarketResearchAgent()
        assert agent.get_theses() == []


class TestPredictionMarketAgentV2:

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = PredictionMarketAgentV2()
        out = await agent.run()
        assert out.output_type == "pm_opportunities"

    def test_watch_unwatch(self):
        agent = PredictionMarketAgentV2()
        agent.watch("FED-25DEC")
        assert "FED-25DEC" in agent._watched_markets
        agent.unwatch("FED-25DEC")
        assert "FED-25DEC" not in agent._watched_markets


class TestCryptoSignalsAgent:

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = CryptoSignalsAgent()
        out = await agent.run()
        assert out.output_type == "crypto_signals"

    def test_watch_pair(self):
        agent = CryptoSignalsAgent()
        agent.watch_pair("DOGE-USD")
        assert "DOGE-USD" in agent._watched_pairs


# ======================================================================
# §2 Strategy Agent Tests
# ======================================================================

class TestStrategyDesignerAgent:

    @pytest.mark.asyncio
    async def test_run_with_theses(self):
        agent = StrategyDesignerAgent()
        theses = [
            {"instrument": "BTC-USD", "direction": "long", "domain": "crypto"},
            {"instrument": "ETH-USD", "direction": "neutral", "domain": "crypto"},
        ]
        out = await agent.run({"theses": theses})
        assert out.output_type == "strategy_definitions"
        # Only BTC-USD should produce a strategy (ETH is neutral)
        assert out.payload["total_strategies"] == 1

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = StrategyDesignerAgent()
        out = await agent.run()
        assert out.payload["total_strategies"] == 0

    def test_list_strategies(self):
        agent = StrategyDesignerAgent()
        assert agent.list_strategies() == []

    def test_strategy_definition_to_dict(self):
        sd = StrategyDefinition(strategy_id="test", domain="crypto")
        d = sd.to_dict()
        assert d["strategy_id"] == "test"


class TestArbitrageAgent:

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = ArbitrageAgent()
        out = await agent.run()
        assert out.output_type == "arb_opportunities"
        assert out.payload["count"] == 0

    def test_to_proposals(self):
        agent = ArbitrageAgent()
        opp = ArbOpportunity(
            arb_id="arb-1", arb_type="cross_exchange", domain="crypto",
            buy_venue="binance", sell_venue="coinbase",
            instrument="BTC-USD",
            buy_price=Decimal("50000"), sell_price=Decimal("50200"),
            spread_pct=Decimal("0.004"),
        )
        proposals = agent.to_proposals(opp, Decimal("0.1"))
        assert len(proposals) == 2
        assert proposals[0].side == OrderSide.BUY
        assert proposals[1].side == OrderSide.SELL

    def test_arb_opportunity_to_dict(self):
        opp = ArbOpportunity(arb_id="a1", instrument="BTC-USD")
        d = opp.to_dict()
        assert d["arb_id"] == "a1"


class TestExecutionOptimizerAgent:

    def test_optimize_small_limit(self):
        agent = ExecutionOptimizerAgent()
        p = TradeProposal(
            venue="binance", notional_usd=Decimal("500"),
            order_type=OrderType.LIMIT,
        )
        plan = agent.optimize(p)
        assert plan.order_type == "limit"
        assert plan.slices == 1
        assert plan.fee_tier == "maker"

    def test_optimize_large_order_sliced(self):
        agent = ExecutionOptimizerAgent()
        p = TradeProposal(
            venue="binance", notional_usd=Decimal("8000"),
            order_type=OrderType.LIMIT,
        )
        plan = agent.optimize(p)
        assert plan.slices >= 2

    def test_optimize_market_order(self):
        agent = ExecutionOptimizerAgent()
        p = TradeProposal(
            venue="coinbase", notional_usd=Decimal("500"),
            order_type=OrderType.MARKET,
        )
        plan = agent.optimize(p)
        assert plan.order_type == "market"
        assert plan.fee_tier == "taker"

    @pytest.mark.asyncio
    async def test_run_with_proposals(self):
        agent = ExecutionOptimizerAgent()
        proposals = [
            TradeProposal(venue="binance", notional_usd=Decimal("1000")),
        ]
        out = await agent.run({"proposals": proposals})
        assert out.output_type == "execution_plans"
        assert out.payload["count"] == 1

    def test_execution_plan_to_dict(self):
        ep = ExecutionPlan(proposal_id="p1", order_type="limit")
        d = ep.to_dict()
        assert d["order_type"] == "limit"


# ======================================================================
# §3 Risk Agent Tests
# ======================================================================

class TestRiskManagerAgent:

    @pytest.mark.asyncio
    async def test_run_approves(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        agent = RiskManagerAgent(risk_manager=rm)
        proposals = [
            TradeProposal(
                domain=TradeDomain.CRYPTO, venue="binance",
                notional_usd=Decimal("1000"),
            ),
        ]
        out = await agent.run({"proposals": proposals})
        assert out.payload["approved"] == 1

    @pytest.mark.asyncio
    async def test_run_rejects_over_limit(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        agent = RiskManagerAgent(risk_manager=rm)
        proposals = [
            TradeProposal(
                domain=TradeDomain.CRYPTO, venue="binance",
                notional_usd=Decimal("10000"),  # exceeds single order max
            ),
        ]
        out = await agent.run({"proposals": proposals})
        assert out.payload["rejected"] == 1

    def test_evaluate_single(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        agent = RiskManagerAgent(risk_manager=rm)
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("1000"),
        )
        v = agent.evaluate(p)
        assert v.approved is True

    def test_halt_resume_domain(self):
        rm = GlobalRiskManager()
        agent = RiskManagerAgent(risk_manager=rm)
        agent.halt_domain("crypto", "test")
        assert rm.is_domain_halted("crypto")
        agent.resume_domain("crypto")
        assert not rm.is_domain_halted("crypto")

    def test_risk_verdict_to_dict(self):
        v = RiskVerdict(proposal_id="p1", approved=True, reason="OK")
        d = v.to_dict()
        assert d["approved"] is True


class TestCapitalAllocatorAgent:

    @pytest.mark.asyncio
    async def test_run(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        agent = CapitalAllocatorAgent(risk_manager=rm)
        out = await agent.run()
        assert out.output_type == "allocation_plan"
        assert "allocations" in out.payload

    def test_compute_allocation(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        agent = CapitalAllocatorAgent(risk_manager=rm)
        plan = agent.compute_allocation()
        assert plan.total_capital_usd == Decimal("50000")
        assert "crypto" in plan.allocations

    def test_rebalance_detection(self):
        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        rm.record_fill("binance", "crypto", Decimal("24000"))  # way over 50% target
        agent = CapitalAllocatorAgent(risk_manager=rm)
        plan = agent.compute_allocation()
        assert plan.rebalance_needed is True


class TestAnomalyDetectorAgent:

    @pytest.mark.asyncio
    async def test_run_no_data(self):
        agent = AnomalyDetectorAgent()
        out = await agent.run()
        assert out.output_type == "anomalies"
        assert out.payload["count"] == 0

    @pytest.mark.asyncio
    async def test_detect_stale_data(self):
        agent = AnomalyDetectorAgent(stale_threshold_seconds=30)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        data = [{"instrument": "BTC-USD", "venue": "binance", "price": 50000, "bid": 49990, "ask": 50010, "timestamp": old_ts}]
        out = await agent.run({"market_data": data})
        anomalies = out.payload["anomalies"]
        assert any(a["anomaly_type"] == "stale_data" for a in anomalies)

    @pytest.mark.asyncio
    async def test_detect_price_spike(self):
        agent = AnomalyDetectorAgent(spike_threshold_pct=0.05)
        # First tick
        data1 = [{"instrument": "BTC-USD", "venue": "binance", "price": 50000, "bid": 49990, "ask": 50010}]
        await agent.run({"market_data": data1})
        # Second tick with 15% spike
        data2 = [{"instrument": "BTC-USD", "venue": "binance", "price": 57500, "bid": 57490, "ask": 57510}]
        out = await agent.run({"market_data": data2})
        anomalies = out.payload["anomalies"]
        assert any(a["anomaly_type"] == "price_spike" for a in anomalies)

    @pytest.mark.asyncio
    async def test_detect_spread_anomaly(self):
        agent = AnomalyDetectorAgent()
        data = [{"instrument": "BTC-USD", "venue": "binance", "price": 50000, "bid": 45000, "ask": 55000}]
        out = await agent.run({"market_data": data})
        anomalies = out.payload["anomalies"]
        assert any(a["anomaly_type"] == "spread_anomaly" for a in anomalies)

    def test_anomaly_to_dict(self):
        a = Anomaly(anomaly_type="stale_data", venue="binance", instrument="BTC-USD")
        d = a.to_dict()
        assert d["anomaly_type"] == "stale_data"


# ======================================================================
# §4 Coordination Agent Tests
# ======================================================================

class TestConsensusCoordinatorAgent:

    def test_aggregate_approved(self):
        agent = ConsensusCoordinatorAgent()
        votes = [
            AgentVote(agent_id="a1", decision="approve", confidence=0.9, weight=1.0),
            AgentVote(agent_id="a2", decision="approve", confidence=0.8, weight=1.0),
            AgentVote(agent_id="a3", decision="reject", confidence=0.5, weight=1.0),
        ]
        result = agent.aggregate("p1", votes)
        assert result.decision == "approved"
        assert result.approval_score > 0.6

    def test_aggregate_rejected(self):
        agent = ConsensusCoordinatorAgent()
        votes = [
            AgentVote(agent_id="a1", decision="reject", confidence=0.9, weight=1.0),
            AgentVote(agent_id="a2", decision="reject", confidence=0.8, weight=1.0),
        ]
        result = agent.aggregate("p1", votes)
        assert result.decision == "rejected"

    def test_veto_overrides(self):
        agent = ConsensusCoordinatorAgent(veto_agents=["risk-manager-01"])
        votes = [
            AgentVote(agent_id="a1", decision="approve", confidence=0.9, weight=1.0),
            AgentVote(agent_id="risk-manager-01", decision="reject", confidence=0.9, weight=1.0),
        ]
        result = agent.aggregate("p1", votes)
        assert result.decision == "rejected"
        assert result.vetoed_by == "risk-manager-01"

    def test_no_quorum(self):
        agent = ConsensusCoordinatorAgent()
        result = agent.aggregate("p1", [])
        assert result.decision == "no_quorum"

    @pytest.mark.asyncio
    async def test_run(self):
        agent = ConsensusCoordinatorAgent()
        p = TradeProposal(domain=TradeDomain.CRYPTO)
        votes = {
            p.proposal_id: [
                AgentVote(agent_id="a1", decision="approve", confidence=0.9),
            ]
        }
        out = await agent.run({"proposals": [p], "votes": votes})
        assert out.output_type == "consensus_results"

    def test_consensus_result_to_dict(self):
        r = ConsensusResult(proposal_id="p1", decision="approved")
        d = r.to_dict()
        assert d["decision"] == "approved"

    def test_agent_vote_to_dict(self):
        v = AgentVote(agent_id="a1", decision="approve")
        d = v.to_dict()
        assert d["decision"] == "approve"


class TestExplainabilityAgent:

    def test_explain_trade(self):
        agent = ExplainabilityAgent()
        event = {
            "id": "e1", "type": "trade",
            "what": "Buy 0.1 BTC on Binance",
            "why": "Cross-exchange arb opportunity",
            "why_now": "Spread exceeded 0.3%",
        }
        exp = agent.explain(event)
        assert exp.what == "Buy 0.1 BTC on Binance"
        assert exp.why_now == "Spread exceeded 0.3%"

    def test_explain_auto_generates(self):
        agent = ExplainabilityAgent()
        event = {
            "id": "e2", "type": "trade",
            "proposal": {"side": "buy", "qty": "10", "instrument_id": "AAPL", "venue": "alpaca"},
        }
        exp = agent.explain(event)
        assert "AAPL" in exp.what

    @pytest.mark.asyncio
    async def test_run(self):
        agent = ExplainabilityAgent()
        events = [{"id": "e1", "type": "trade", "what": "test"}]
        out = await agent.run({"events": events})
        assert out.output_type == "explanations"
        assert out.payload["count"] == 1

    def test_explanation_to_dict(self):
        e = Explanation(event_id="e1", event_type="trade", what="test")
        d = e.to_dict()
        assert d["event_type"] == "trade"

    def test_explanation_human_readable(self):
        e = Explanation(event_id="e1", event_type="trade", what="Buy BTC", why="Arb", why_now="Spread")
        text = e.to_human_readable()
        assert "Buy BTC" in text


class TestGovernanceAgent:

    def test_compliant_proposal(self):
        agent = GovernanceAgent()
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("1000"),
        )
        v = agent.check(p)
        assert v.compliant is True

    def test_forbidden_venue(self):
        agent = GovernanceAgent()
        p = TradeProposal(
            domain=TradeDomain.PREDICTION, venue="polymarket",
        )
        v = agent.check(p)
        assert v.compliant is False
        assert any("forbidden" in viol for viol in v.violations)

    def test_prediction_non_kalshi(self):
        agent = GovernanceAgent()
        p = TradeProposal(
            domain=TradeDomain.PREDICTION, venue="augur",
        )
        v = agent.check(p)
        assert v.compliant is False

    def test_leverage_violation(self):
        agent = GovernanceAgent()
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            metadata={"leverage": 5.0},
        )
        v = agent.check(p)
        assert v.compliant is False
        assert any("Leverage" in viol for viol in v.violations)

    def test_low_confidence_warning(self):
        agent = GovernanceAgent()
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            confidence=Decimal("0.2"),
        )
        v = agent.check(p)
        assert v.compliant is True  # warning, not violation
        assert len(v.warnings) > 0

    @pytest.mark.asyncio
    async def test_run(self):
        agent = GovernanceAgent()
        proposals = [
            TradeProposal(domain=TradeDomain.CRYPTO, venue="binance"),
            TradeProposal(domain=TradeDomain.PREDICTION, venue="polymarket"),
        ]
        out = await agent.run({"proposals": proposals})
        assert out.payload["compliant"] == 1
        assert out.payload["violations"] == 1

    def test_governance_verdict_to_dict(self):
        v = GovernanceVerdict(proposal_id="p1", compliant=True)
        d = v.to_dict()
        assert d["compliant"] is True


# ======================================================================
# §5 Ops Agent Tests
# ======================================================================

class TestOpsRunbookAgent:

    def test_map_connectivity_alert(self):
        agent = OpsRunbookAgent()
        alert = {"type": "connectivity_loss", "venue": "binance"}
        action = agent.map_alert(alert)
        assert action is not None
        assert action.action_type == "pause_domain"
        assert action.severity == "critical"

    def test_map_stale_data_alert(self):
        agent = OpsRunbookAgent()
        alert = {"type": "stale_data", "venue": "kraken"}
        action = agent.map_alert(alert)
        assert action is not None
        assert action.auto_executable is True

    def test_map_unknown_alert(self):
        agent = OpsRunbookAgent()
        alert = {"type": "unknown_thing", "venue": "x"}
        action = agent.map_alert(alert)
        assert action is None

    @pytest.mark.asyncio
    async def test_run(self):
        agent = OpsRunbookAgent()
        alerts = [
            {"type": "connectivity_loss", "venue": "binance"},
            {"type": "high_latency", "venue": "coinbase"},
        ]
        out = await agent.run({"alerts": alerts})
        assert out.output_type == "runbook_actions"
        assert out.payload["count"] == 2

    def test_runbook_action_to_dict(self):
        a = RunbookAction(action_id="rb-1", action_type="pause_domain")
        d = a.to_dict()
        assert d["action_type"] == "pause_domain"


class TestBacktestAgent:

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = BacktestAgent()
        out = await agent.run()
        assert out.output_type == "backtest_results"
        assert out.payload["count"] == 0

    @pytest.mark.asyncio
    async def test_run_with_strategies(self):
        agent = BacktestAgent()
        strategies = [
            {"strategy_id": "s1", "domain": "crypto", "period": "30d"},
            {"strategy_id": "s2", "domain": "prediction", "period": "7d"},
        ]
        out = await agent.run({"strategies": strategies})
        assert out.payload["count"] == 2

    def test_backtest_result_to_dict(self):
        r = BacktestResult(strategy_id="s1", domain="crypto", win_rate=0.65)
        d = r.to_dict()
        assert d["win_rate"] == 0.65
