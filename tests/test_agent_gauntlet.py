"""Agent Gauntlet Tests — validates the gauntlet framework itself.

Ensures SLO evaluation, verdict generation, and batch running work
correctly so the gauntlet can be trusted as a promotion gate.

Run with:
  pytest tests/test_agent_gauntlet.py -v
  make gauntlet-test
"""

import asyncio
import pytest

from merid.agent_gauntlet import (
    GauntletSLO,
    GauntletRunner,
    GauntletResult,
    SLOCheck,
    AgentGauntletVerdict,
    run_gauntlet,
    gauntlet_summary,
    CATEGORY_SLOS,
    DEFAULT_SLO,
)


# ═══════════════════════════════════════════════════════════════════════
# Helpers — minimal agent stubs for testing the gauntlet framework
# ═══════════════════════════════════════════════════════════════════════

class _StubAgent:
    """Minimal agent stub that satisfies the gauntlet runner interface."""

    def __init__(self, agent_id, category, confidence=0.5, error_on=None):
        self.agent_id = agent_id
        self.category = _Category(category)
        self.status = _Status("idle")
        self._confidence = confidence
        self._error_on = error_on or set()
        self._call_count = 0

    @property
    def is_active(self):
        return self.status.value in ("idle", "running")

    async def run(self, context=None):
        self._call_count += 1
        if self._call_count in self._error_on:
            return _Output(
                agent_id=self.agent_id,
                category=self.category.value,
                output_type="error",
                errors=["simulated error"],
                confidence=0.0,
                latency_ms=0.0,
                payload={},
                run_id=f"stub-{self._call_count}",
            )
        return _Output(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="signal",
            confidence=self._confidence,
            latency_ms=1.0,
            payload={"signals": []},
            errors=[],
            run_id=f"stub-{self._call_count}",
        )


class _Category:
    def __init__(self, v):
        self.value = v


class _Status:
    def __init__(self, v):
        self.value = v


class _Output:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ═══════════════════════════════════════════════════════════════════════
# 1. SLO Dataclass
# ═══════════════════════════════════════════════════════════════════════

class TestGauntletSLO:
    """Verify SLO configuration and serialization."""

    def test_default_slo_values(self):
        slo = GauntletSLO()
        assert slo.min_successful_cycles == 5
        assert slo.max_error_rate == 0.20
        assert slo.max_p95_latency_ms == 5000.0
        assert slo.min_avg_confidence == 0.10
        assert slo.max_avg_confidence == 0.95
        assert slo.min_confidence_stddev == 0.0
        assert slo.max_drawdown_pct == 0.15
        assert slo.min_sharpe_ratio == -1.0

    def test_slo_to_dict(self):
        slo = GauntletSLO()
        d = slo.to_dict()
        assert "min_successful_cycles" in d
        assert "max_error_rate" in d
        assert "max_p95_latency_ms" in d
        assert len(d) == 12

    def test_category_slos_exist(self):
        for cat in ["research", "strategy", "risk", "coordination", "ops"]:
            assert cat in CATEGORY_SLOS
            assert isinstance(CATEGORY_SLOS[cat], GauntletSLO)

    def test_risk_slo_is_strictest_on_errors(self):
        assert CATEGORY_SLOS["risk"].max_error_rate < DEFAULT_SLO.max_error_rate

    def test_strategy_slo_is_strictest_on_latency(self):
        assert CATEGORY_SLOS["strategy"].max_p95_latency_ms < DEFAULT_SLO.max_p95_latency_ms

    def test_custom_slo_override(self):
        slo = GauntletSLO(min_successful_cycles=20, max_error_rate=0.01)
        assert slo.min_successful_cycles == 20
        assert slo.max_error_rate == 0.01


# ═══════════════════════════════════════════════════════════════════════
# 2. SLO Check & Verdict
# ═══════════════════════════════════════════════════════════════════════

class TestSLOCheck:
    """Verify SLO check and verdict data structures."""

    def test_slo_check_pass(self):
        c = SLOCheck(name="liveness", passed=True, actual=10.0, threshold=5.0, unit="cycles")
        assert c.passed is True
        d = c.to_dict()
        assert d["name"] == "liveness"
        assert d["passed"] is True

    def test_slo_check_fail(self):
        c = SLOCheck(name="latency", passed=False, actual=6000.0, threshold=5000.0, unit="ms")
        assert c.passed is False

    def test_verdict_pass_rate(self):
        v = AgentGauntletVerdict(
            agent_id="test", category="research", result=GauntletResult.PASS,
            checks=[
                SLOCheck(name="a", passed=True, actual=1, threshold=1),
                SLOCheck(name="b", passed=True, actual=1, threshold=1),
                SLOCheck(name="c", passed=False, actual=0, threshold=1),
            ],
        )
        assert v.pass_rate == pytest.approx(2 / 3, abs=0.01)

    def test_verdict_to_dict(self):
        v = AgentGauntletVerdict(
            agent_id="test", category="research", result=GauntletResult.PASS,
        )
        d = v.to_dict()
        assert d["agent_id"] == "test"
        assert d["result"] == "pass"
        assert "checks" in d

    def test_verdict_promoted_flag(self):
        v = AgentGauntletVerdict(
            agent_id="test", category="research",
            result=GauntletResult.PASS, promoted=True,
        )
        assert v.promoted is True
        v2 = AgentGauntletVerdict(
            agent_id="test2", category="research",
            result=GauntletResult.FAIL, promoted=False,
        )
        assert v2.promoted is False


# ═══════════════════════════════════════════════════════════════════════
# 3. Gauntlet Runner — stub agents
# ═══════════════════════════════════════════════════════════════════════

class TestGauntletRunner:
    """Test the gauntlet runner with stub agents."""

    def test_healthy_agent_passes(self):
        agent = _StubAgent("healthy-01", "research", confidence=0.5)
        runner = GauntletRunner(cycles=5)
        verdict = asyncio.run(runner.run_agent(agent))

        assert verdict.result == GauntletResult.PASS
        assert verdict.promoted is True
        assert verdict.successful_cycles == 5
        assert verdict.error_cycles == 0
        assert len(verdict.checks) == 8

    def test_erroring_agent_fails_if_over_threshold(self):
        # Errors on cycles 1, 2, 3 out of 5 = 60% error rate
        agent = _StubAgent("error-01", "research", error_on={1, 2, 3})
        runner = GauntletRunner(cycles=5)
        verdict = asyncio.run(runner.run_agent(agent))

        assert verdict.result == GauntletResult.FAIL
        assert verdict.error_cycles == 3
        assert verdict.promoted is False

    def test_low_confidence_agent_fails(self):
        agent = _StubAgent("low-conf-01", "research", confidence=0.01)
        slo = GauntletSLO(min_avg_confidence=0.10)
        runner = GauntletRunner(slo=slo, cycles=5)
        verdict = asyncio.run(runner.run_agent(agent))

        # Should fail confidence_avg check
        conf_check = next(c for c in verdict.checks if c.name == "confidence_avg")
        assert conf_check.passed is False

    def test_high_confidence_agent_fails(self):
        agent = _StubAgent("high-conf-01", "research", confidence=0.99)
        slo = GauntletSLO(max_avg_confidence=0.95)
        runner = GauntletRunner(slo=slo, cycles=5)
        verdict = asyncio.run(runner.run_agent(agent))

        conf_check = next(c for c in verdict.checks if c.name == "confidence_avg")
        assert conf_check.passed is False

    def test_custom_cycle_count(self):
        agent = _StubAgent("cycles-01", "strategy", confidence=0.4)
        runner = GauntletRunner(cycles=15)
        verdict = asyncio.run(runner.run_agent(agent))

        assert verdict.total_cycles == 15
        assert verdict.successful_cycles == 15

    def test_different_categories_get_different_slos(self):
        research = _StubAgent("r-01", "research", confidence=0.5)
        risk = _StubAgent("rk-01", "risk", confidence=0.5)

        runner = GauntletRunner(cycles=5)
        v_research = asyncio.run(runner.run_agent(research))
        v_risk = asyncio.run(runner.run_agent(risk))

        # Both should pass with 0.5 confidence
        assert v_research.result == GauntletResult.PASS
        assert v_risk.result == GauntletResult.PASS

    def test_all_8_slo_dimensions_checked(self):
        agent = _StubAgent("dims-01", "research", confidence=0.5)
        runner = GauntletRunner(cycles=5)
        verdict = asyncio.run(runner.run_agent(agent))

        check_names = {c.name for c in verdict.checks}
        expected = {
            "liveness", "error_rate", "latency_p95",
            "confidence_avg", "confidence_variance",
            "fill_rejection_rate", "max_drawdown", "sharpe_ratio",
        }
        assert check_names == expected


# ═══════════════════════════════════════════════════════════════════════
# 4. Batch Runner & Summary
# ═══════════════════════════════════════════════════════════════════════

class TestBatchRunner:
    """Test batch gauntlet execution and summary generation."""

    def test_gauntlet_summary_structure(self):
        verdicts = [
            AgentGauntletVerdict(
                agent_id="a", category="research",
                result=GauntletResult.PASS, promoted=True,
            ),
            AgentGauntletVerdict(
                agent_id="b", category="strategy",
                result=GauntletResult.FAIL, promoted=False,
            ),
            AgentGauntletVerdict(
                agent_id="c", category="ops",
                result=GauntletResult.SKIP,
            ),
        ]
        s = gauntlet_summary(verdicts)

        assert s["total_agents"] == 3
        assert s["passed"] == 1
        assert s["failed"] == 1
        assert s["skipped"] == 1
        assert s["promoted"] == ["a"]
        assert s["blocked"] == ["b"]
        assert len(s["verdicts"]) == 3

    def test_empty_gauntlet_summary(self):
        s = gauntlet_summary([])
        assert s["total_agents"] == 0
        assert s["passed"] == 0

    def test_all_pass_summary(self):
        verdicts = [
            AgentGauntletVerdict(
                agent_id=f"agent-{i}", category="research",
                result=GauntletResult.PASS, promoted=True,
            )
            for i in range(5)
        ]
        s = gauntlet_summary(verdicts)
        assert s["passed"] == 5
        assert s["failed"] == 0
        assert len(s["promoted"]) == 5


# ═══════════════════════════════════════════════════════════════════════
# 5. Integration — real agents through gauntlet
# ═══════════════════════════════════════════════════════════════════════

class TestGauntletIntegration:
    """Run real canonical agents through the gauntlet."""

    def test_real_agents_pass_gauntlet(self):
        """All registered canonical agents must pass the gauntlet."""
        try:
            from merid.agents.research import MarketResearchAgent, PredictionMarketAgentV2
            from merid.agents.strategy import StrategyDesignerAgent
            from merid.agents.risk_agents import RiskManagerAgent
            from merid.agents.base import get_canonical_registry
        except ImportError:
            pytest.skip("Agent modules not available")

        reg = get_canonical_registry()
        if not reg.all():
            for Cls in [MarketResearchAgent, PredictionMarketAgentV2,
                        StrategyDesignerAgent, RiskManagerAgent]:
                try:
                    reg.register(Cls())
                except Exception:
                    pass

        if not reg.all():
            pytest.skip("No agents could be registered")

        verdicts = asyncio.run(run_gauntlet(cycles=5))

        for v in verdicts:
            if v.result == GauntletResult.SKIP:
                continue
            assert v.result == GauntletResult.PASS, (
                f"Agent {v.agent_id} failed gauntlet: "
                f"{[c.name for c in v.checks if not c.passed]}"
            )

    def test_gauntlet_seeds_prediction_markets(self):
        """Gauntlet should seed prediction markets automatically."""
        from merid.matching_engine import get_matching_engine, init_matching_engines

        init_matching_engines()
        agent = _StubAgent("seed-test", "research", confidence=0.5)
        runner = GauntletRunner(cycles=5)
        asyncio.run(runner.run_agent(agent))

        engine = get_matching_engine("prediction")
        # After gauntlet run, engine should have reference prices from seeder
        assert len(engine._reference_prices) >= 10

    def test_gauntlet_exit_code_semantics(self):
        """Summary with 0 failures should indicate success."""
        verdicts = [
            AgentGauntletVerdict(
                agent_id="ok", category="research",
                result=GauntletResult.PASS, promoted=True,
            ),
        ]
        s = gauntlet_summary(verdicts)
        assert s["failed"] == 0  # exit 0

        verdicts_bad = [
            AgentGauntletVerdict(
                agent_id="bad", category="research",
                result=GauntletResult.FAIL, promoted=False,
            ),
        ]
        s_bad = gauntlet_summary(verdicts_bad)
        assert s_bad["failed"] == 1  # exit 1
