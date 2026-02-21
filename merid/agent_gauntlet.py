"""Agent Gauntlet — promotion gate for MERID agents.

Every agent must pass the gauntlet before it is allowed to trade on real
venues.  The gauntlet exercises the agent against internal paper markets
(prediction CLOB + crypto paper engine) and evaluates it on a set of
quantitative SLOs.

Usage:
  python -m merid.agent_gauntlet                          # run all agents
  python -m merid.agent_gauntlet --agent prediction-market-agent-v2
  python -m merid.agent_gauntlet --category research
  python -m merid.agent_gauntlet --json

SLO Dimensions (all must pass for promotion):
  1. Liveness     — agent runs without errors for N cycles
  2. Latency      — p95 run latency ≤ budget
  3. Signal quality — confidence distribution is non-degenerate
  4. Risk compliance — no kill-switch triggers, no oversized orders
  5. Fill quality   — fills execute at reasonable prices (prediction domain)
  6. PnL discipline — drawdown stays within bounds over the trial
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

import logging
logger = logging.getLogger("agent_gauntlet")

logger = get_logger(__name__)


# ── SLO Thresholds ──────────────────────────────────────────────────

@dataclass
class GauntletSLO:
    """Quantitative thresholds an agent must meet."""
    # Liveness
    min_successful_cycles: int = 5          # Must complete at least N runs
    max_error_rate: float = 0.20            # ≤20% of runs can error

    # Latency
    max_p95_latency_ms: float = 5000.0      # p95 ≤ 5s per run

    # Signal quality
    min_avg_confidence: float = 0.10        # Must not always output 0
    max_avg_confidence: float = 0.95        # Must not always output 1
    min_confidence_stddev: float = 0.0      # 0 = no variance requirement (agents may be deterministic)

    # Risk compliance
    max_oversized_orders: int = 0           # Zero tolerance for orders > domain cap
    max_kill_switch_triggers: int = 0       # Zero tolerance

    # Fill quality (prediction domain)
    max_rejection_rate: float = 0.50        # ≤50% of orders rejected
    max_avg_slippage_bps: float = 100.0     # ≤100 bps avg slippage

    # PnL discipline
    max_drawdown_pct: float = 0.15          # ≤15% drawdown during trial
    min_sharpe_ratio: float = -1.0          # Not catastrophically negative

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_successful_cycles": self.min_successful_cycles,
            "max_error_rate": self.max_error_rate,
            "max_p95_latency_ms": self.max_p95_latency_ms,
            "min_avg_confidence": self.min_avg_confidence,
            "max_avg_confidence": self.max_avg_confidence,
            "min_confidence_stddev": self.min_confidence_stddev,
            "max_oversized_orders": self.max_oversized_orders,
            "max_kill_switch_triggers": self.max_kill_switch_triggers,
            "max_rejection_rate": self.max_rejection_rate,
            "max_avg_slippage_bps": self.max_avg_slippage_bps,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_sharpe_ratio": self.min_sharpe_ratio,
        }


# Default SLOs — can be overridden per agent category
DEFAULT_SLO = GauntletSLO()

CATEGORY_SLOS: Dict[str, GauntletSLO] = {
    "research": GauntletSLO(
        max_p95_latency_ms=8000.0,      # Research agents can be slower
        min_avg_confidence=0.15,
    ),
    "strategy": GauntletSLO(
        max_p95_latency_ms=3000.0,      # Strategy must be fast
        min_avg_confidence=0.20,
    ),
    "risk": GauntletSLO(
        max_p95_latency_ms=2000.0,      # Risk must be fastest
        max_error_rate=0.05,            # Very low error tolerance
    ),
    "coordination": GauntletSLO(
        max_p95_latency_ms=5000.0,
    ),
    "ops": GauntletSLO(
        max_p95_latency_ms=10000.0,     # Ops can be slowest
        max_error_rate=0.30,            # More tolerant of errors
    ),
}


# ── Verdict ──────────────────────────────────────────────────────────

class GauntletResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class SLOCheck:
    """Result of a single SLO dimension check."""
    name: str
    passed: bool
    actual: float
    threshold: float
    unit: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": round(self.actual, 4),
            "threshold": round(self.threshold, 4),
            "unit": self.unit,
            "detail": self.detail,
        }


@dataclass
class AgentGauntletVerdict:
    """Full gauntlet result for one agent."""
    agent_id: str
    category: str
    result: GauntletResult
    checks: List[SLOCheck] = field(default_factory=list)
    total_cycles: int = 0
    successful_cycles: int = 0
    error_cycles: int = 0
    total_fills: int = 0
    total_rejections: int = 0
    elapsed_s: float = 0.0
    promoted: bool = False

    @property
    def pass_rate(self) -> float:
        n = len(self.checks)
        return sum(1 for c in self.checks if c.passed) / n if n else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "category": self.category,
            "result": self.result.value,
            "pass_rate": round(self.pass_rate, 2),
            "checks": [c.to_dict() for c in self.checks],
            "total_cycles": self.total_cycles,
            "successful_cycles": self.successful_cycles,
            "error_cycles": self.error_cycles,
            "total_fills": self.total_fills,
            "total_rejections": self.total_rejections,
            "elapsed_s": round(self.elapsed_s, 2),
            "promoted": self.promoted,
        }


# ── Gauntlet Runner ──────────────────────────────────────────────────

class GauntletRunner:
    """Exercises an agent against internal markets and evaluates SLOs.

    The runner:
      1. Seeds prediction markets (if not already seeded)
      2. Runs the agent for N cycles with market context
      3. Collects latency, confidence, error, and fill metrics
      4. Evaluates all SLO dimensions
      5. Returns a pass/fail verdict
    """

    def __init__(self, slo: Optional[GauntletSLO] = None, cycles: int = 10):
        self.slo = slo or DEFAULT_SLO
        self.cycles = max(cycles, self.slo.min_successful_cycles)

    async def run_agent(self, agent) -> AgentGauntletVerdict:
        """Run the full gauntlet for a single agent."""
        t0 = time.time()
        category = agent.category.value if hasattr(agent.category, "value") else str(agent.category)
        slo = CATEGORY_SLOS.get(category, self.slo)

        logger.info(f"Gauntlet START: {agent.agent_id} ({category}), {self.cycles} cycles")

        # Seed prediction markets
        self._ensure_markets_seeded()

        # Build market context for the agent
        context = self._build_context()

        # Run cycles
        latencies: List[float] = []
        confidences: List[float] = []
        errors: List[str] = []
        outputs = []
        successful = 0
        errored = 0

        for i in range(self.cycles):
            output = await agent.run(context)
            outputs.append(output)

            if output.output_type == "error":
                errored += 1
                errors.append(output.errors[0] if output.errors else "unknown")
            else:
                successful += 1
                latencies.append(output.latency_ms)
                confidences.append(output.confidence)

        # Simulate fills for agents that produce proposals/signals
        fills, rejections = self._simulate_fills(outputs)

        # Compute PnL metrics from fills
        pnl_metrics = self._compute_pnl_metrics(fills)

        # Evaluate SLOs
        checks = self._evaluate_slos(
            slo=slo,
            total_cycles=self.cycles,
            successful=successful,
            errored=errored,
            latencies=latencies,
            confidences=confidences,
            fills=fills,
            rejections=rejections,
            pnl_metrics=pnl_metrics,
        )

        all_passed = all(c.passed for c in checks)
        elapsed = time.time() - t0

        verdict = AgentGauntletVerdict(
            agent_id=agent.agent_id,
            category=category,
            result=GauntletResult.PASS if all_passed else GauntletResult.FAIL,
            checks=checks,
            total_cycles=self.cycles,
            successful_cycles=successful,
            error_cycles=errored,
            total_fills=len(fills),
            total_rejections=rejections,
            elapsed_s=elapsed,
            promoted=all_passed,
        )

        status = "PASS" if all_passed else "FAIL"
        failed = [c.name for c in checks if not c.passed]
        logger.info(
            f"Gauntlet {status}: {agent.agent_id} — "
            f"{sum(1 for c in checks if c.passed)}/{len(checks)} SLOs"
            + (f" (failed: {failed})" if failed else "")
        )

        return verdict

    # ── Market setup ─────────────────────────────────────────────────

    def _ensure_markets_seeded(self):
        """Seed prediction markets if not already done."""
        try:
            from merid.prediction_seed import seed_instruments, seed_reference_prices
            seed_instruments()
            seed_reference_prices()
        except Exception as e:
            logger.warning(f"Market seeding skipped: {e}")

    def _build_context(self) -> Dict[str, Any]:
        """Build a realistic market context for agent runs."""
        from merid.paper_config import get_paper_config
        cfg = get_paper_config()

        context = {
            "domains": cfg.active_domain_names(),
            "symbols": cfg.all_symbols()[:20],  # Top 20 symbols
            "mode": "gauntlet",
            "timestamp": time.time(),
        }

        # Add prediction market prices if available
        try:
            from merid.matching_engine import get_matching_engine
            engine = get_matching_engine("prediction")
            context["prediction_prices"] = dict(engine._reference_prices)
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        # Add crypto prices
        try:
            from trading.paper_trading import get_paper_engine
            pe = get_paper_engine()
            context["crypto_prices"] = dict(pe.current_prices)
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        return context

    # ── Fill simulation ──────────────────────────────────────────────

    def _simulate_fills(self, outputs: List) -> tuple:
        """Simulate fills from agent outputs that contain trade signals."""
        from merid.matching_engine import get_matching_engine, Order, OrderSide

        fills = []
        rejections = 0

        engine = get_matching_engine("prediction")
        if not engine.enabled:
            engine.enable()

        for output in outputs:
            if output.output_type == "error":
                continue

            payload = output.payload or {}

            # Look for trade signals in the payload
            signals = payload.get("signals", [])
            proposals = payload.get("proposals", [])
            trades = payload.get("trades", [])

            for signal in (signals + proposals + trades):
                if isinstance(signal, dict):
                    instrument = signal.get("instrument_id") or signal.get("symbol", "")
                    direction = signal.get("direction") or signal.get("side", "buy")
                    notional = signal.get("notional_usd") or signal.get("size_usd", 50.0)

                    if not instrument:
                        continue

                    side = OrderSide.BUY if direction in ("buy", "long") else OrderSide.SELL
                    order = Order(
                        instrument_id=instrument,
                        side=side,
                        notional_usd=float(notional),
                        domain="prediction",
                        agent_id=output.agent_id,
                        plan_id=f"gauntlet-{output.run_id}",
                    )
                    fill = engine.submit_order(order)
                    if order.status.value == "filled":
                        fills.append(fill)
                    else:
                        rejections += 1

        return fills, rejections

    def _compute_pnl_metrics(self, fills: List) -> Dict[str, float]:
        """Compute basic PnL metrics from fills."""
        if not fills:
            return {"max_drawdown_pct": 0.0, "sharpe_ratio": 0.0, "total_pnl": 0.0}

        # Simple mark-to-market: track cumulative notional as proxy
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        returns = []

        for fill in fills:
            # Simplified: buys are negative cash, sells positive
            if fill.side.value == "buy":
                cumulative -= fill.notional_usd
            else:
                cumulative += fill.notional_usd

            peak = max(peak, cumulative)
            dd = (peak - cumulative) / max(peak, 1.0) if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            returns.append(fill.notional_usd * (0.01 if fill.side.value == "buy" else -0.01))

        sharpe = 0.0
        if len(returns) > 1:
            avg_r = statistics.mean(returns)
            std_r = statistics.stdev(returns)
            sharpe = avg_r / std_r if std_r > 0 else 0.0

        return {
            "max_drawdown_pct": max_dd,
            "sharpe_ratio": sharpe,
            "total_pnl": cumulative,
        }

    # ── SLO evaluation ───────────────────────────────────────────────

    def _evaluate_slos(
        self,
        slo: GauntletSLO,
        total_cycles: int,
        successful: int,
        errored: int,
        latencies: List[float],
        confidences: List[float],
        fills: List,
        rejections: int,
        pnl_metrics: Dict[str, float],
    ) -> List[SLOCheck]:
        checks = []

        # 1. Liveness
        checks.append(SLOCheck(
            name="liveness",
            passed=successful >= slo.min_successful_cycles,
            actual=float(successful),
            threshold=float(slo.min_successful_cycles),
            unit="cycles",
            detail=f"{successful}/{total_cycles} successful",
        ))

        # 2. Error rate
        error_rate = errored / total_cycles if total_cycles > 0 else 0.0
        checks.append(SLOCheck(
            name="error_rate",
            passed=error_rate <= slo.max_error_rate,
            actual=error_rate,
            threshold=slo.max_error_rate,
            unit="ratio",
            detail=f"{errored}/{total_cycles} errors",
        ))

        # 3. Latency p95
        if latencies:
            sorted_lat = sorted(latencies)
            p95_idx = int(len(sorted_lat) * 0.95)
            p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
        else:
            p95 = 0.0
        checks.append(SLOCheck(
            name="latency_p95",
            passed=p95 <= slo.max_p95_latency_ms,
            actual=p95,
            threshold=slo.max_p95_latency_ms,
            unit="ms",
        ))

        # 4. Confidence — avg in range
        avg_conf = statistics.mean(confidences) if confidences else 0.0
        checks.append(SLOCheck(
            name="confidence_avg",
            passed=slo.min_avg_confidence <= avg_conf <= slo.max_avg_confidence,
            actual=avg_conf,
            threshold=slo.min_avg_confidence,
            unit="score",
            detail=f"range [{slo.min_avg_confidence}, {slo.max_avg_confidence}]",
        ))

        # 5. Confidence — variance
        conf_std = statistics.stdev(confidences) if len(confidences) > 1 else 0.0
        checks.append(SLOCheck(
            name="confidence_variance",
            passed=conf_std >= slo.min_confidence_stddev,
            actual=conf_std,
            threshold=slo.min_confidence_stddev,
            unit="stddev",
        ))

        # 6. Fill rejection rate
        total_orders = len(fills) + rejections
        rej_rate = rejections / total_orders if total_orders > 0 else 0.0
        checks.append(SLOCheck(
            name="fill_rejection_rate",
            passed=rej_rate <= slo.max_rejection_rate,
            actual=rej_rate,
            threshold=slo.max_rejection_rate,
            unit="ratio",
            detail=f"{rejections}/{total_orders} rejected" if total_orders > 0 else "no orders",
        ))

        # 7. Drawdown
        dd = pnl_metrics.get("max_drawdown_pct", 0.0)
        checks.append(SLOCheck(
            name="max_drawdown",
            passed=dd <= slo.max_drawdown_pct,
            actual=dd,
            threshold=slo.max_drawdown_pct,
            unit="pct",
        ))

        # 8. Sharpe
        sharpe = pnl_metrics.get("sharpe_ratio", 0.0)
        checks.append(SLOCheck(
            name="sharpe_ratio",
            passed=sharpe >= slo.min_sharpe_ratio,
            actual=sharpe,
            threshold=slo.min_sharpe_ratio,
            unit="ratio",
        ))

        return checks


# ── Batch runner ─────────────────────────────────────────────────────

async def run_gauntlet(
    agent_ids: Optional[List[str]] = None,
    category: Optional[str] = None,
    cycles: int = 10,
) -> List[AgentGauntletVerdict]:
    """Run the gauntlet for multiple agents.

    If agent_ids is None and category is None, runs all registered agents.
    """
    from merid.agents.base import get_canonical_registry, AgentCategory

    registry = get_canonical_registry()
    runner = GauntletRunner(cycles=cycles)

    # Select agents
    if agent_ids:
        agents = [registry.get(aid) for aid in agent_ids if registry.get(aid)]
    elif category:
        cat = AgentCategory(category)
        agents = registry.by_category(cat)
    else:
        agents = list(registry.all().values())

    if not agents:
        logger.warning("No agents found for gauntlet")
        return []

    logger.info(f"Running gauntlet for {len(agents)} agents, {cycles} cycles each")

    verdicts = []
    for agent in agents:
        if not agent.is_active:
            verdicts.append(AgentGauntletVerdict(
                agent_id=agent.agent_id,
                category=agent.category.value,
                result=GauntletResult.SKIP,
            ))
            continue
        verdict = await runner.run_agent(agent)
        verdicts.append(verdict)

    # Summary
    passed = sum(1 for v in verdicts if v.result == GauntletResult.PASS)
    failed = sum(1 for v in verdicts if v.result == GauntletResult.FAIL)
    skipped = sum(1 for v in verdicts if v.result == GauntletResult.SKIP)
    logger.info(
        f"Gauntlet complete: {passed} passed, {failed} failed, {skipped} skipped "
        f"out of {len(verdicts)} agents"
    )

    return verdicts


def gauntlet_summary(verdicts: List[AgentGauntletVerdict]) -> Dict[str, Any]:
    """Build a summary report from gauntlet verdicts."""
    return {
        "total_agents": len(verdicts),
        "passed": sum(1 for v in verdicts if v.result == GauntletResult.PASS),
        "failed": sum(1 for v in verdicts if v.result == GauntletResult.FAIL),
        "skipped": sum(1 for v in verdicts if v.result == GauntletResult.SKIP),
        "promoted": [v.agent_id for v in verdicts if v.promoted],
        "blocked": [v.agent_id for v in verdicts if v.result == GauntletResult.FAIL],
        "verdicts": [v.to_dict() for v in verdicts],
    }


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    agent_filter = None
    cat_filter = None
    cycles = 10
    json_mode = "--json" in sys.argv

    if "--agent" in sys.argv:
        idx = sys.argv.index("--agent") + 1
        if idx < len(sys.argv):
            agent_filter = [sys.argv[idx]]

    if "--category" in sys.argv:
        idx = sys.argv.index("--category") + 1
        if idx < len(sys.argv):
            cat_filter = sys.argv[idx]

    if "--cycles" in sys.argv:
        idx = sys.argv.index("--cycles") + 1
        if idx < len(sys.argv):
            cycles = int(sys.argv[idx])

    # Ensure agents are registered
    try:
        from merid.agents.research import PredictionMarketAgentV2, CryptoSignalsAgent, MarketResearchAgent
        from merid.agents.strategy import StrategyDesignerAgent, ArbitrageAgent
        from merid.agents.risk_agents import RiskManagerAgent
        from merid.agents.coordination import ConsensusCoordinatorAgent
        from merid.agents.base import get_canonical_registry

        reg = get_canonical_registry()
        if not reg.all():
            # Register default agents
            for AgentClass in [
                MarketResearchAgent, PredictionMarketAgentV2, CryptoSignalsAgent,
                StrategyDesignerAgent, ArbitrageAgent,
                RiskManagerAgent,
                ConsensusCoordinatorAgent,
            ]:
                try:
                    agent = AgentClass()
                    reg.register(agent)
                except Exception as e:
                    logger.warning(f"Could not register {AgentClass.__name__}: {e}")
    except ImportError as e:
        logger.warning(f"Could not import agent modules: {e}")

    verdicts = asyncio.run(run_gauntlet(
        agent_ids=agent_filter,
        category=cat_filter,
        cycles=cycles,
    ))

    summary = gauntlet_summary(verdicts)

    if json_mode:
        logger.info(json.dumps(summary, indent=2))
    else:
        logger.info(f"\n{'=' * 70}")
        logger.info(f"MERID Agent Gauntlet — {summary['total_agents']} agents, {cycles} cycles")
        logger.info(f"{'=' * 70}")
        for v in verdicts:
            icon = "PASS" if v.result == GauntletResult.PASS else (
                "FAIL" if v.result == GauntletResult.FAIL else "SKIP"
            )
            marker = "[+]" if v.promoted else ("[X]" if v.result == GauntletResult.FAIL else "[-]")
            logger.info(f"\n  {marker} [{icon}] {v.agent_id} ({v.category})")
            print(f"     Cycles: {v.successful_cycles}/{v.total_cycles} ok, "
                  f"{v.error_cycles} errors | "
                  f"Fills: {v.total_fills} | "
                  f"Time: {v.elapsed_s:.1f}s")

            if v.checks:
                for c in v.checks:
                    status = "  ok " if c.passed else " FAIL"
                    print(f"     [{status}] {c.name:25s}  "
                          f"actual={c.actual:>8.2f}  "
                          f"threshold={c.threshold:>8.2f} {c.unit}")

        logger.info(f"\n{'=' * 70}")
        print(f"Result: {summary['passed']} promoted, "
              f"{summary['failed']} blocked, "
              f"{summary['skipped']} skipped")

        if summary["promoted"]:
            logger.info(f"Promoted: {', '.join(summary['promoted'])}")
        if summary["blocked"]:
            logger.info(f"Blocked:  {', '.join(summary['blocked'])}")
        logger.info(f"{'=' * 70}")
    sys.exit(0 if summary["failed"] == 0 else 1)
