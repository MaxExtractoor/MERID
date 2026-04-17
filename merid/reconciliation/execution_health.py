"""Unified execution health — merges paper-truth and Kalshi venue reconciliation.

``core.execution_gate`` consumes this so a single assessment drives gating
decisions, while still surfacing **source_divergence** when the two
reconciliation layers disagree (useful outside Kalshi demo / kalshi-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from utils.logger import get_logger

logger = get_logger("merid.reconciliation.execution_health")

@dataclass
class ExecutionHealth:
    """Single snapshot of cross-layer reconciliation health."""

    paper_reconciliation_blocks: bool
    paper_has_ever_completed: bool
    kalshi_venue_blocks: bool
    kalshi_reconciliation_has_run: bool
    source_divergence: bool
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "paper_reconciliation_blocks": self.paper_reconciliation_blocks,
            "paper_has_ever_completed": self.paper_has_ever_completed,
            "kalshi_venue_blocks": self.kalshi_venue_blocks,
            "kalshi_reconciliation_has_run": self.kalshi_reconciliation_has_run,
            "source_divergence": self.source_divergence,
            "details": self.details,
        }


def _paper_flags() -> Tuple[bool, bool]:
    """Returns (blocks_execution, has_ever_completed) for the legacy paper-truth layer.

    The old ``trading.reconciliation`` package is removed; venue truth in
    ``merid.reconciliation`` drives gating. Paper-only flags stay false so
    ``assess_execution_health`` does not invent blocks or divergence from a dead layer.
    """
    return False, False


def _kalshi_flags() -> Tuple[bool, bool]:
    """Returns (blocks_execution, has_ever_run).

    Resolves ``merid.reconciliation`` via ``sys.modules`` when present so unit
    tests that use ``patch.dict(sys.modules, {\"merid.reconciliation\": mock})``
    are not bypassed by a subsequent ``import`` returning a cached real package.
    """
    import sys

    try:
        if "merid.reconciliation" not in sys.modules:
            import merid.reconciliation  # noqa: F401 — populate sys.modules
        mr = sys.modules["merid.reconciliation"]
        blocks = mr.has_critical_discrepancies()
        try:
            raw_ts = mr.get_last_reconciliation_ts()
            ts = float(raw_ts) if raw_ts is not None else 0.0
        except (TypeError, ValueError, ArithmeticError):
            ts = 0.0
        return blocks, ts > 0.0
    except Exception as exc:
        logger.debug("execution_health kalshi venue lookup failed: %s", exc)
        return True, False


def assess_execution_health(*, kalshi_demo_mode: bool = False) -> ExecutionHealth:
    """Assess merged health. When *kalshi_demo_mode* is True, Kalshi venue
    discrepancies are treated as non-blocking for divergence semantics (same as
    execution_gate demo behavior).
    """
    paper_blocks, paper_done = _paper_flags()
    kalshi_blocks, kalshi_done = _kalshi_flags()

    divergence = False
    details_parts: List[str] = []
    if paper_done and kalshi_done and not kalshi_demo_mode:
        divergence = paper_blocks != kalshi_blocks
        if divergence:
            details_parts.append(
                f"paper_blocks={paper_blocks} kalshi_blocks={kalshi_blocks}"
            )
            logger.warning(
                "reconciliation_source_divergence paper_blocks=%s kalshi_blocks=%s",
                paper_blocks,
                kalshi_blocks,
            )

    return ExecutionHealth(
        paper_reconciliation_blocks=paper_blocks,
        paper_has_ever_completed=paper_done,
        kalshi_venue_blocks=kalshi_blocks,
        kalshi_reconciliation_has_run=kalshi_done,
        source_divergence=divergence,
        details="; ".join(details_parts),
    )
