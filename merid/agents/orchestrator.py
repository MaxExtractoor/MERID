"""§3 Orchestrator Loop — Scheduled agent runs with output piping.

Runs agents in dependency order:
1. RESEARCH agents → produce theses, signals, opportunities
2. STRATEGY agents → consume research, produce strategies + proposals
3. RISK agents → evaluate proposals, produce verdicts
4. COORDINATION agents → consensus voting, governance, explainability
5. OPS agents → runbook actions, backtest

Each phase feeds its outputs as context into the next phase.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from merid.agents.base import (
    AgentCategory,
    AgentOutput,
    CanonicalAgent,
    CanonicalAgentRegistry,
    get_canonical_registry,
)

from merid.tick_events import TickContext, get_tick_bus
from utils.logger import get_logger

logger = get_logger("merid.agents.orchestrator")


# ── Pipeline phase definitions ───────────────────────────────────────

PHASE_ORDER = [
    AgentCategory.RESEARCH,
    AgentCategory.STRATEGY,
    AgentCategory.RISK,
    AgentCategory.COORDINATION,
    AgentCategory.OPS,
]


@dataclass
class PhaseResult:
    """Result of running one orchestrator phase."""
    phase: str
    outputs: List[AgentOutput] = field(default_factory=list)
    latency_ms: float = 0.0
    agents_run: int = 0
    agents_skipped: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "agents_run": self.agents_run,
            "agents_skipped": self.agents_skipped,
            "latency_ms": round(self.latency_ms, 2),
            "errors": self.errors,
            "output_count": len(self.outputs),
        }


@dataclass
class CycleResult:
    """Result of a full orchestrator cycle (all phases)."""
    cycle_id: str = ""
    phases: List[PhaseResult] = field(default_factory=list)
    total_latency_ms: float = 0.0
    total_outputs: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "phases": [p.to_dict() for p in self.phases],
            "total_latency_ms": round(self.total_latency_ms, 2),
            "total_outputs": self.total_outputs,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Context builder ──────────────────────────────────────────────────

def _build_phase_context(
    base_context: Dict[str, Any],
    previous_outputs: List[AgentOutput],
) -> Dict[str, Any]:
    """Build context for the next phase from previous phase outputs."""
    ctx = dict(base_context)

    # Group outputs by type for downstream consumption
    theses = []
    signals = []
    opportunities = []
    proposals = []
    verdicts = []
    consensus_results = []
    explanations = []

    for out in previous_outputs:
        payload = out.payload
        otype = out.output_type

        if otype == "theses":
            theses.extend(payload.get("theses", []))
        elif otype == "pm_opportunities":
            opportunities.extend(payload.get("opportunities", []))
        elif otype == "crypto_signals":
            signals.extend(payload.get("signals", []))
        elif otype == "strategy_definitions":
            ctx.setdefault("strategies", []).extend(payload.get("strategies", []))
        elif otype == "arb_opportunities":
            opportunities.extend(payload.get("opportunities", []))
        elif otype == "execution_plans":
            ctx.setdefault("execution_plans", []).extend(payload.get("plans", []))
        elif otype in ("risk_verdicts", "risk_check"):
            verdicts.extend(payload.get("verdicts", []))
        elif otype == "allocation_plan":
            ctx["allocation"] = payload
        elif otype == "anomalies":
            ctx.setdefault("anomalies", []).extend(payload.get("anomalies", []))
        elif otype == "consensus_results":
            consensus_results.extend(payload.get("results", []))
        elif otype == "explanations":
            explanations.extend(payload.get("explanations", []))
        elif otype == "governance_verdicts":
            ctx.setdefault("governance_verdicts", []).extend(payload.get("verdicts", []))

    if theses:
        ctx["theses"] = theses
    if signals:
        ctx["signals"] = signals
    if opportunities:
        ctx["opportunities"] = opportunities
    if proposals:
        ctx["proposals"] = proposals
    if verdicts:
        ctx["verdicts"] = verdicts
    if consensus_results:
        ctx["consensus_results"] = consensus_results
    if explanations:
        ctx["explanations"] = explanations

    return ctx


# ── Orchestrator ─────────────────────────────────────────────────────

class AgentOrchestrator:
    """Runs canonical agents in phased dependency order.

    Usage::

        orch = AgentOrchestrator(registry)
        result = await orch.run_cycle({"market_data": [...]})
        # result.phases[0] = research outputs
        # result.phases[1] = strategy outputs (fed by research)
        # ...

    Scheduling::

        await orch.run_loop(interval_seconds=60, max_cycles=10)
    """

    def __init__(
        self,
        registry: Optional[CanonicalAgentRegistry] = None,
        phases: Optional[List[AgentCategory]] = None,
    ):
        self._registry = registry
        self.phases = phases or list(PHASE_ORDER)
        self._cycle_count: int = 0
        self._history: List[CycleResult] = []
        self._running: bool = False

    @property
    def registry(self) -> CanonicalAgentRegistry:
        if self._registry is None:
            self._registry = get_canonical_registry()
        return self._registry

    # ── Single cycle ─────────────────────────────────────────────────

    async def run_cycle(self, context: Dict[str, Any] = None) -> CycleResult:
        """Run one full orchestrator cycle through all phases."""
        self._cycle_count += 1
        cycle_id = f"cycle-{self._cycle_count}-{uuid.uuid4().hex[:8]}"
        cycle_start = time.perf_counter()
        base_context = context or {}

        _tick = TickContext(
            agent_id="orchestrator",
            cycle_number=self._cycle_count,
            mode="paper",
        )
        _bus = get_tick_bus()
        _bus.emit(_tick.emit_started())

        all_outputs: List[AgentOutput] = []
        phase_results: List[PhaseResult] = []

        try:
            for category in self.phases:
                phase_ctx = _build_phase_context(base_context, all_outputs)
                phase_result = await self._run_phase(category, phase_ctx)
                phase_results.append(phase_result)
                all_outputs.extend(phase_result.outputs)
                _bus.emit(_tick.emit_agent_cycle(
                    signals_evaluated=phase_result.agents_run,
                    signals_actionable=phase_result.agents_run - phase_result.agents_skipped,
                    signals_consensus_blocked=len(phase_result.errors),
                ))
        except Exception as _exc:
            _bus.emit(_tick.emit_error(str(_exc)))
            raise
        finally:
            total_latency = (time.perf_counter() - cycle_start) * 1000
            _bus.emit(_tick.finalise())

        result = CycleResult(
            cycle_id=cycle_id,
            phases=phase_results,
            total_latency_ms=total_latency,
            total_outputs=len(all_outputs),
        )
        self._history.append(result)
        logger.info(
            f"Cycle {cycle_id}: {len(all_outputs)} outputs in {total_latency:.0f}ms "
            f"across {len(self.phases)} phases"
        )
        return result

    async def _run_phase(self, category: AgentCategory, context: Dict[str, Any]) -> PhaseResult:
        """Run all active agents in a single phase."""
        start = time.perf_counter()
        agents = self.registry.by_category(category)
        outputs: List[AgentOutput] = []
        errors: List[str] = []
        skipped = 0

        for agent in agents:
            if not agent.is_active:
                skipped += 1
                continue
            try:
                output = await agent.run(context)
                outputs.append(output)
                if output.errors:
                    errors.extend(output.errors)
            except Exception as exc:
                errors.append(f"{agent.agent_id}: {exc}")

        return PhaseResult(
            phase=category.value,
            outputs=outputs,
            latency_ms=(time.perf_counter() - start) * 1000,
            agents_run=len(outputs),
            agents_skipped=skipped,
            errors=errors,
        )

    # ── Scheduled loop ───────────────────────────────────────────────

    async def run_loop(
        self,
        interval_seconds: float = 60.0,
        max_cycles: int = 0,
        context: Dict[str, Any] = None,
    ) -> List[CycleResult]:
        """Run the orchestrator in a loop.

        Args:
            interval_seconds: Seconds between cycles.
            max_cycles: Max cycles to run (0 = infinite).
            context: Base context for each cycle.

        Returns:
            List of CycleResults from all cycles.
        """
        self._running = True
        results: List[CycleResult] = []
        cycles = 0

        logger.info(
            f"Orchestrator loop starting: interval={interval_seconds}s, "
            f"max_cycles={max_cycles or 'infinite'}"
        )

        while self._running:
            try:
                result = await self.run_cycle(context)
                results.append(result)
                cycles += 1

                if max_cycles and cycles >= max_cycles:
                    break

                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Orchestrator cycle failed: {exc}")
                await asyncio.sleep(interval_seconds)

        self._running = False
        logger.info(f"Orchestrator loop stopped after {cycles} cycles")
        return results

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle."""
        self._running = False

    # ── History / summary ────────────────────────────────────────────

    def get_history(self, limit: int = 10) -> List[CycleResult]:
        return self._history[-limit:]

    def summary(self) -> dict:
        return {
            "cycle_count": self._cycle_count,
            "running": self._running,
            "phases": [p.value for p in self.phases],
            "registered_agents": len(self.registry.all()),
            "active_agents": len(self.registry.active()),
            "history_count": len(self._history),
        }
