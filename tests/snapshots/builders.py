"""Deterministic snapshot builders for regression testing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Sequence

from swarm.performance import SwarmPerformanceLedger


@dataclass
class VoteBatch:
    approved: bool
    votes: Sequence[Dict[str, object]]


class DeterministicClock:
    """Callable that mimics core.time_authority.current_time deterministically."""

    def __init__(self, *, start: datetime, step: timedelta) -> None:
        self._current = start
        self._step = step

    def __call__(self) -> Dict[str, object]:
        payload = {
            "utc_iso": self._current.isoformat().replace("+00:00", "Z"),
            "unix": int(self._current.timestamp()),
        }
        self._current = self._current + self._step
        return payload


def build_swarm_performance_snapshot(*, log_path: Path) -> Dict[str, object]:
    """Produce deterministic leaderboard/best-parent snapshot data."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    batches: Iterable[VoteBatch] = (
        VoteBatch(
            approved=True,
            votes=[
                {"agent_id": "alpha", "vote": "accept"},
                {"agent_id": "beta", "vote": "reject"},
                {"agent_id": "gamma", "vote": "accept"},
            ],
        ),
        VoteBatch(
            approved=False,
            votes=[
                {"agent_id": "alpha", "vote": "reject"},
                {"agent_id": "beta", "vote": "reject"},
                {"agent_id": "gamma", "vote": "accept"},
                {"agent_id": "delta", "vote": "accept"},
            ],
        ),
        VoteBatch(
            approved=True,
            votes=[
                {"agent_id": "alpha", "vote": "accept"},
                {"agent_id": "beta", "vote": "accept"},
                {"agent_id": "gamma", "vote": "reject"},
                {"agent_id": "delta", "vote": "accept"},
            ],
        ),
        VoteBatch(
            approved=True,
            votes=[
                {"agent_id": "alpha", "vote": "accept"},
                {"agent_id": "beta", "vote": "reject"},
                {"agent_id": "gamma", "vote": "accept"},
                {"agent_id": "delta", "vote": "accept"},
            ],
        ),
    )

    clock = DeterministicClock(
        start=datetime(2026, 1, 20, 20, 0, 0, tzinfo=timezone.utc),
        step=timedelta(minutes=7),
    )
    ledger = SwarmPerformanceLedger(
        decay_window_hours=3,
        decay_rate=0.9,
        min_decay_weight=0.3,
        log_path=log_path,
        now_provider=clock,
    )

    for batch in batches:
        ledger.record_cycle(list(batch.votes), approved=batch.approved)

    return {
        "leaderboard": ledger.leaderboard(limit=5),
        "best_parent": ledger.best_parent(min_score=0.5, min_votes=2),
    }
