"""Loop health summary helper for the 8-stage trading loop.

Provides a per-(asset, timeframe) snapshot of every loop stage:
  discover → analyze → consensus → size → execute → monitor → promote → protect

Usage::

    from merid.loop_health import build_loop_health_summary
    summaries = build_loop_health_summary()
    for s in summaries:
        print(s.to_dict())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.loop_health")


@dataclass
class SeriesHealthSummary:
    """Health snapshot for one (asset, timeframe) series."""

    asset: str
    timeframe: str

    # ── Discover ──────────────────────────────────────────────────────
    discovered_markets: int = 0

    # ── Analyze (opinions) ───────────────────────────────────────────
    opinions_count: int = 0
    opinions_missing_symbol_timeframe: int = 0

    # ── Consensus ─────────────────────────────────────────────────────
    # "trade" | "no_trade" | "quorum_failed" | "conflicted" | "unknown"
    consensus_result: str = "unknown"

    # ── Size ──────────────────────────────────────────────────────────
    sizing_result: float = 0.0
    sizing_zero_reason: Optional[str] = None

    # ── Execute (gate) ────────────────────────────────────────────────
    # "allowed" | "blocked" | "dry_run" | "unknown"
    gate_result: str = "unknown"
    gate_block_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "discovered_markets": self.discovered_markets,
            "opinions_count": self.opinions_count,
            "opinions_missing_symbol_timeframe": self.opinions_missing_symbol_timeframe,
            "consensus_result": self.consensus_result,
            "sizing_result": self.sizing_result,
            "sizing_zero_reason": self.sizing_zero_reason,
            "gate_result": self.gate_result,
            "gate_block_reason": self.gate_block_reason,
        }


def build_loop_health_summary(
    grid: Optional[List[Tuple[str, str]]] = None,
    markets_by_series: Optional[Dict[str, int]] = None,
    opinions_by_series: Optional[Dict[str, List[Any]]] = None,
    consensus_by_series: Optional[Dict[str, str]] = None,
    sizing_by_series: Optional[Dict[str, Tuple[float, Optional[str]]]] = None,
    gate_by_series: Optional[Dict[str, Tuple[str, Optional[str]]]] = None,
) -> List[SeriesHealthSummary]:
    """Build a loop health summary for each (asset, timeframe) pair.

    All parameters are optional; omitting them yields a zero-filled baseline.

    Args:
        grid: List of (asset, timeframe) pairs.  Defaults to the full 25-pair
              universe from ``config.crypto_universe``.
        markets_by_series: Mapping of ``"{asset}_{timeframe}"`` → discovered
              market count.
        opinions_by_series: Mapping of series key → list of opinion objects.
              Each object is inspected for ``symbol`` / ``timeframe`` attrs.
        consensus_by_series: Mapping of series key → consensus result string
              (``"trade"``, ``"no_trade"``, ``"quorum_failed"``, ``"conflicted"``).
        sizing_by_series: Mapping of series key → ``(size_float, reason_or_None)``.
        gate_by_series: Mapping of series key →
              ``("allowed"|"blocked"|"dry_run", reason_or_None)``.

    Returns:
        List of :class:`SeriesHealthSummary`, one per (asset, timeframe) pair.
    """
    from config.crypto_universe import get_full_grid

    if grid is None:
        grid = get_full_grid()

    summaries: List[SeriesHealthSummary] = []

    for asset, timeframe in grid:
        key = f"{asset}_{timeframe}"

        # ── Discover ──────────────────────────────────────────────────
        markets = (markets_by_series or {}).get(key, 0)

        # ── Analyze ───────────────────────────────────────────────────
        opinions: List[Any] = (opinions_by_series or {}).get(key, [])
        missing_st = sum(
            1
            for op in opinions
            if not getattr(op, "symbol", None) or not getattr(op, "timeframe", None)
        )

        # ── Consensus ─────────────────────────────────────────────────
        consensus = (consensus_by_series or {}).get(key, "unknown")

        # ── Sizing ────────────────────────────────────────────────────
        sizing_info = (sizing_by_series or {}).get(key, (0.0, None))
        sizing_size: float = sizing_info[0] if sizing_info else 0.0
        sizing_reason: Optional[str] = (
            sizing_info[1] if sizing_info and len(sizing_info) > 1 else None
        )

        # ── Gate ──────────────────────────────────────────────────────
        gate_info = (gate_by_series or {}).get(key, ("unknown", None))
        gate_result: str = gate_info[0] if gate_info else "unknown"
        gate_reason: Optional[str] = (
            gate_info[1] if gate_info and len(gate_info) > 1 else None
        )

        summaries.append(
            SeriesHealthSummary(
                asset=asset,
                timeframe=timeframe,
                discovered_markets=markets,
                opinions_count=len(opinions),
                opinions_missing_symbol_timeframe=missing_st,
                consensus_result=consensus,
                sizing_result=sizing_size,
                sizing_zero_reason=sizing_reason,
                gate_result=gate_result,
                gate_block_reason=gate_reason,
            )
        )

    logger.info(
        "loop_health_summary_built: total=%d markets=%d trade=%d allowed=%d blocked=%d",
        len(summaries),
        sum(1 for s in summaries if s.discovered_markets > 0),
        sum(1 for s in summaries if s.consensus_result == "trade"),
        sum(1 for s in summaries if s.gate_result == "allowed"),
        sum(1 for s in summaries if s.gate_result == "blocked"),
    )
    return summaries
