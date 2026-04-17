from __future__ import annotations

"""Stage 13 Readiness report aggregating MERID health signals."""

from dataclasses import asdict, dataclass
from typing import Any, Dict

from backtesting.replay import run_backtest
from hardening.chaos import build_hardening_report
from core.state import state


@dataclass
class ReadinessReport:
    total_realities: int
    avg_consensus: float
    avg_validation_score: float
    automation_failure_rate: float
    pending_validations: int
    notes: list[str]

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)


async def build_readiness_report(limit: int = 100) -> ReadinessReport:
    snapshot = run_backtest(limit)
    hardening = await build_hardening_report(limit)
    automation_feed = await state.list_automation_events(limit)
    failures = sum(1 for item in automation_feed if item.get("status") == "failed")
    failure_rate = (failures / len(automation_feed)) if automation_feed else 0.0

    notes = list(hardening.notes)
    if failure_rate > 0.1:
        notes.append("Automation failure rate exceeds 10%.")

    pending = hardening.pending_validations

    return ReadinessReport(
        total_realities=snapshot.total_realities,
        avg_consensus=snapshot.avg_consensus,
        avg_validation_score=snapshot.avg_validation_score,
        automation_failure_rate=failure_rate,
        pending_validations=pending,
        notes=notes,
    )
