from __future__ import annotations

"""Stage 10 Hardening: chaos diagnostics and audit summaries."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from backtesting.replay import run_backtest
from core.state import state


@dataclass
class HardeningReport:
    automation_failures: int
    automation_total: int
    pending_validations: int
    backlog_hours: float
    avg_consensus: float
    avg_validation_score: float
    notes: List[str]

    def asdict(self) -> Dict[str, Any]:
        return asdict(self)


async def build_hardening_report(limit: int = 50) -> HardeningReport:
    automation_feed = await state.list_automation_events(limit)
    validations = await state.list_validations(limit)
    snapshot = run_backtest(limit)

    automation_failures = sum(1 for item in automation_feed if item.get("status") == "failed")
    automation_total = len(automation_feed)
    pending_validations = sum(1 for item in validations if item.get("verdict", {}).get("status") == "pending")

    backlog_hours = 0.0
    if validations:
        newest = validations[0].get("recorded_at")
        if newest:
            try:
                recorded = datetime.fromisoformat(newest.replace("Z", "+00:00"))
                backlog_hours = max(
                    (datetime.now(timezone.utc) - recorded).total_seconds() / 3600.0,
                    0.0,
                )
            except ValueError:
                backlog_hours = 0.0

    notes: List[str] = []
    if automation_failures:
        notes.append(f"{automation_failures} automation dispatches failed in last {limit}.")
    if pending_validations:
        notes.append(f"{pending_validations} validations still pending.")
    if backlog_hours > 1.5:
        notes.append(f"Validation backlog {backlog_hours:.1f}h exceeds threshold.")

    if not notes:
        notes.append("Chaos sweep clean — all systems nominal.")

    return HardeningReport(
        automation_failures=automation_failures,
        automation_total=automation_total,
        pending_validations=pending_validations,
        backlog_hours=backlog_hours,
        avg_consensus=snapshot.avg_consensus,
        avg_validation_score=snapshot.avg_validation_score,
        notes=notes,
    )
