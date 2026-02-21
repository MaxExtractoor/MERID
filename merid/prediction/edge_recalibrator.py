"""Edge Threshold Recalibrator — Sprint G.

Uses realized edge data from ``merid/metrics/realized_edge.py`` to
dynamically adjust the edge thresholds in ``StrategyConfig``.

If agents are systematically over-estimating edge (predicted > realized),
thresholds should increase.  If under-estimating, thresholds can decrease
slightly — but never below a safety floor.

Usage::

    recalibrator = get_edge_recalibrator()
    recalibrator.recalibrate()  # Updates StrategyConfig in-place

The recalibrator runs periodically (default: every 30 min) as a background
task started by AgentGrid alongside the OutcomeResolver.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.edge_recalibrator")

# Safety floors — thresholds never drop below these
MIN_EDGE_FLOOR = Decimal("0.015")   # 1.5% absolute minimum edge
MAX_EDGE_CEILING = Decimal("0.15")  # 15% — don't require absurd edges

# How aggressively to adjust (0 = no change, 1 = full correction)
ADJUSTMENT_RATE = Decimal("0.2")

# Minimum trade count before we trust the data
MIN_TRADES_FOR_RECALIBRATION = 20


@dataclass
class RecalibrationResult:
    """Result of a single recalibration pass."""
    timestamp: float
    trade_count: int
    avg_predicted_edge: float
    avg_realized_edge: float
    edge_bias: float              # positive = over-estimating
    adjustments: Dict[str, str]   # phase -> "old -> new"
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "trade_count": self.trade_count,
            "avg_predicted_edge": round(self.avg_predicted_edge, 4),
            "avg_realized_edge": round(self.avg_realized_edge, 4),
            "edge_bias": round(self.edge_bias, 4),
            "adjustments": self.adjustments,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


class EdgeRecalibrator:
    """Dynamically adjusts strategy edge thresholds based on realized edge data.

    Computes the systematic bias between predicted and realized edge,
    then nudges thresholds proportionally.
    """

    def __init__(self, interval_seconds: int = 1800):
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._history: List[RecalibrationResult] = []
        self._max_history = 100

    async def start(self) -> None:
        """Start the periodic recalibration loop."""
        self._shutdown.clear()
        self._task = asyncio.create_task(
            self._run_loop(), name="edge-recalibrator"
        )
        logger.info(f"Edge recalibrator started (interval={self._interval}s)")

    async def stop(self) -> None:
        """Stop the recalibration loop."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Edge recalibrator stopped")

    async def _run_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                result = self.recalibrate()
                if result and not result.skipped:
                    logger.info(
                        f"Edge recalibration: bias={result.edge_bias:+.4f}, "
                        f"trades={result.trade_count}, adjustments={len(result.adjustments)}"
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Edge recalibration error: {exc}")

            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._interval)
                break
            except asyncio.TimeoutError:
                pass

    def recalibrate(self) -> RecalibrationResult:
        """Run a single recalibration pass.

        Reads realized edge stats from RealizedEdgeStore, computes bias,
        and adjusts StrategyConfig thresholds.
        """
        now = time.time()

        # Get realized edge data
        try:
            from merid.metrics.realized_edge import get_realized_edge_store
            store = get_realized_edge_store()
            stats = store.get_summary()
        except Exception as exc:
            result = RecalibrationResult(
                timestamp=now, trade_count=0,
                avg_predicted_edge=0, avg_realized_edge=0,
                edge_bias=0, adjustments={},
                skipped=True, skip_reason=f"RealizedEdgeStore unavailable: {exc}",
            )
            self._record(result)
            return result

        trade_count = stats.get("trade_count", 0)
        if trade_count < MIN_TRADES_FOR_RECALIBRATION:
            result = RecalibrationResult(
                timestamp=now, trade_count=trade_count,
                avg_predicted_edge=0, avg_realized_edge=0,
                edge_bias=0, adjustments={},
                skipped=True,
                skip_reason=f"Insufficient trades ({trade_count} < {MIN_TRADES_FOR_RECALIBRATION})",
            )
            self._record(result)
            return result

        avg_predicted = stats.get("avg_predicted_edge", 0.0)
        avg_realized = stats.get("avg_realized_edge", 0.0)
        edge_bias = avg_predicted - avg_realized

        # Get strategy config
        try:
            from merid.prediction.strategy import StrategyConfig
            # Access the singleton or default config
            config = self._get_strategy_config()
        except Exception:
            result = RecalibrationResult(
                timestamp=now, trade_count=trade_count,
                avg_predicted_edge=avg_predicted, avg_realized_edge=avg_realized,
                edge_bias=edge_bias, adjustments={},
                skipped=True, skip_reason="StrategyConfig unavailable",
            )
            self._record(result)
            return result

        # Compute adjustments for each phase threshold
        adjustments = {}
        bias_dec = Decimal(str(edge_bias))

        phase_attrs = [
            ("early", "min_edge_early"),
            ("mid", "min_edge_mid"),
            ("late", "min_edge_late"),
            ("terminal", "min_edge_terminal"),
        ]

        for phase_name, attr_name in phase_attrs:
            old_val = getattr(config, attr_name)
            # If over-estimating (bias > 0), increase threshold
            # If under-estimating (bias < 0), decrease threshold (cautiously)
            adjustment = bias_dec * ADJUSTMENT_RATE
            new_val = old_val + adjustment

            # Clamp to safety bounds
            new_val = max(MIN_EDGE_FLOOR, min(MAX_EDGE_CEILING, new_val))
            new_val = new_val.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

            if new_val != old_val:
                setattr(config, attr_name, new_val)
                adjustments[phase_name] = f"{old_val} -> {new_val}"

        result = RecalibrationResult(
            timestamp=now,
            trade_count=trade_count,
            avg_predicted_edge=avg_predicted,
            avg_realized_edge=avg_realized,
            edge_bias=edge_bias,
            adjustments=adjustments,
        )
        self._record(result)
        return result

    def _get_strategy_config(self):
        """Get the active StrategyConfig singleton."""
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            if grid and grid._agents:
                return grid._agents[0]._strategy._config
        except Exception:
            pass
        # Fallback: return default config
        from merid.prediction.strategy import StrategyConfig
        return StrategyConfig()

    def _record(self, result: RecalibrationResult) -> None:
        """Store result in history."""
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    @property
    def history(self) -> List[RecalibrationResult]:
        return self._history.copy()

    @property
    def latest(self) -> Optional[RecalibrationResult]:
        return self._history[-1] if self._history else None


# ── Singleton ────────────────────────────────────────────────────────────

_recalibrator: Optional[EdgeRecalibrator] = None


def get_edge_recalibrator() -> EdgeRecalibrator:
    """Get or create the singleton EdgeRecalibrator."""
    global _recalibrator
    if _recalibrator is None:
        _recalibrator = EdgeRecalibrator()
    return _recalibrator
