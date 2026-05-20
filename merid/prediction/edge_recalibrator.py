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

import threading
import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.edge_recalibrator")

# Safety floors — thresholds never drop below these
MIN_EDGE_FLOOR = Decimal("0.050")   # 5.0% absolute minimum edge (conservative "sure bet" mode)
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
            finally:
                self._task = None
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
                logger.debug("silent catch in edge_recalibrator:119")

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
            all_stats = store.get_all_edge_stats()
        except Exception as exc:
            result = RecalibrationResult(
                timestamp=now, trade_count=0,
                avg_predicted_edge=0, avg_realized_edge=0,
                edge_bias=0, adjustments={},
                skipped=True, skip_reason=f"RealizedEdgeStore unavailable: {exc}",
            )
            self._record(result)
            return result

        # Aggregate across all (forecaster, bucket) pairs
        trade_count = sum(s.resolved_count for s in all_stats)
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

        avg_predicted = sum(s.sum_est_edge for s in all_stats) / trade_count
        avg_realized = sum(s.sum_realized_edge for s in all_stats) / trade_count
        edge_bias = avg_predicted - avg_realized

        # Get strategy configs for ALL agents (BUG-4: was only agents[0])
        try:
            configs = self._get_strategy_configs()
        except Exception:
            result = RecalibrationResult(
                timestamp=now, trade_count=trade_count,
                avg_predicted_edge=avg_predicted, avg_realized_edge=avg_realized,
                edge_bias=edge_bias, adjustments={},
                skipped=True, skip_reason="StrategyConfig unavailable",
            )
            self._record(result)
            return result

        # Compute adjustments for each phase threshold and apply to every config
        adjustments = {}
        bias_dec = Decimal(str(edge_bias))

        phase_attrs = [
            ("early", "min_edge_early"),
            ("mid", "min_edge_mid"),
            ("late", "min_edge_late"),
            ("terminal", "min_edge_terminal"),
        ]

        for phase_name, attr_name in phase_attrs:
            for config in configs:
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
                    # Record once per phase (all configs receive the same delta)
                    if phase_name not in adjustments:
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

    def _get_strategy_configs(self) -> list:
        """Return the StrategyConfig for every active agent in the grid.

        Previously only agents[0] was returned, leaving all other agents with
        uncalibrated thresholds after a regime shift (BUG-4).
        """
        configs = []
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            if grid and grid.agents:
                for agent in grid.agents:
                    try:
                        cfg = agent._strategy._config
                        if cfg not in configs:
                            configs.append(cfg)
                    except Exception as _ae:
                        logger.debug("Could not read config for agent %s: %s", agent.config.name, _ae)
        except Exception as _cfg_exc:
            logger.debug("Strategy config lookup failed, using default: %s", _cfg_exc)

        if not configs:
            from merid.prediction.strategy import StrategyConfig
            configs = [StrategyConfig()]
        return configs

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
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _recalibrator_lock = threading.Lock()
_recalibrator_lock = None  # Disabled to prevent startup hang


def get_edge_recalibrator() -> EdgeRecalibrator:
    """Get or create the singleton EdgeRecalibrator."""
    global _recalibrator
    if _recalibrator is None:
        if _recalibrator_lock is not None:
            with _recalibrator_lock:
                if _recalibrator is None:
                    _recalibrator = EdgeRecalibrator()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _recalibrator = EdgeRecalibrator()
    return _recalibrator
