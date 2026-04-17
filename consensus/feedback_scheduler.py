"""Ledger Feedback Scheduler — triggers apply_ledger_feedback on schedule.

Supports:
  - Round-count based triggers (after N reconciled rounds)
  - Time-based triggers (every X minutes)
  - Comprehensive logging of feedback effects
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("consensus.feedback_scheduler")


@dataclass
class FeedbackScheduleConfig:
    """Configuration for feedback scheduling."""
    # Trigger every N reconciled rounds (0 to disable)
    rounds_interval: int = 10
    # Trigger every N seconds (0 to disable) - default 5 minutes
    time_interval_seconds: float = 300.0
    # Minimum rounds required before first feedback
    min_rounds_threshold: int = 5
    # Dry-run mode (log only, don't apply)
    dry_run: bool = False
    # Log level for feedback reports: "info" or "debug"
    log_level: str = "info"


class LedgerFeedbackScheduler:
    """Schedules and executes ledger feedback with comprehensive logging.
    
    Example:
        scheduler = LedgerFeedbackScheduler(coord)
        scheduler.start()
        ...
        scheduler.stop()
    """

    def __init__(self, coordinator, config: Optional[FeedbackScheduleConfig] = None):
        self.coord = coordinator
        self.config = config or FeedbackScheduleConfig()
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        self._reconciled_count = 0
        self._last_feedback_time = 0.0
        self._feedback_history: List[Dict[str, Any]] = []

    def record_reconciliation(self) -> None:
        """Call this after each successful reconciliation to count toward round-based triggers."""
        self._reconciled_count += 1

    def start(self) -> None:
        """Start the feedback scheduler loop."""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run_loop())
        logger.info("LedgerFeedbackScheduler started (rounds=%d, time=%.0fs, dry_run=%s)",
                    self.config.rounds_interval,
                    self.config.time_interval_seconds,
                    self.config.dry_run)

    def stop(self) -> None:
        """Stop the feedback scheduler."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("LedgerFeedbackScheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop — checks triggers periodically."""
        while not self._stopped:
            try:
                await self._check_and_trigger()
                # Check every 10 seconds
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Feedback scheduler error: %s", exc)
                await asyncio.sleep(30)

    async def _check_and_trigger(self) -> None:
        """Check if feedback should be triggered."""
        now = time.time()
        time_since_last = now - self._last_feedback_time

        # Check round-based trigger
        round_trigger = (
            self.config.rounds_interval > 0 and
            self._reconciled_count >= self.config.rounds_interval
        )

        # Check time-based trigger
        time_trigger = (
            self.config.time_interval_seconds > 0 and
            time_since_last >= self.config.time_interval_seconds
        )

        if round_trigger or time_trigger:
            await self._execute_feedback()

    async def _execute_feedback(self) -> None:
        """Execute feedback and log results comprehensively."""
        now = time.time()
        self._last_feedback_time = now
        reconciled_at_trigger = self._reconciled_count
        self._reconciled_count = 0  # Reset counter

        try:
            if self.config.dry_run:
                # Dry-run: compute but don't apply
                preview = self.coord.preview_ledger_feedback(
                    min_rounds=self.config.min_rounds_threshold
                )
                self._log_feedback_preview(preview, reconciled_at_trigger)
            else:
                # Actually apply
                adjusted = self.coord.apply_ledger_feedback(
                    min_rounds=self.config.min_rounds_threshold
                )
                self._log_feedback_applied(adjusted, reconciled_at_trigger)

        except Exception as exc:
            logger.error("Feedback execution failed: %s", exc)

    def _log_feedback_preview(self, preview: List[Dict[str, Any]], reconciled_count: int) -> None:
        """Log comprehensive preview of what would be adjusted."""
        increases = sum(1 for p in preview if p['delta'] > 0)
        decreases = sum(1 for p in preview if p['delta'] < 0)
        unchanged = sum(1 for p in preview if p['delta'] == 0)

        log_fn = logger.info if self.config.log_level == "info" else logger.debug

        log_fn(
            "[DRY-RUN] Feedback preview: %d agents (%d up, %d down, %d same) | "
            "Reconciled since last: %d",
            len(preview), increases, decreases, unchanged, reconciled_count
        )

        for p in preview:
            log_fn(
                "[DRY-RUN] %s: %.3f -> %.3f (Δ%.3f) | acc=%.2f%% cal=%.3f rounds=%d",
                p['agent_id'],
                p['current_weight'],
                p['new_weight'],
                p['delta'],
                p['accuracy'] * 100,
                p['calibration_error'],
                p['rounds']
            )

        # Record to history
        self._feedback_history.append({
            "timestamp": time.time(),
            "mode": "dry_run",
            "reconciled_count": reconciled_count,
            "agents_previewed": len(preview),
            "increases": increases,
            "decreases": decreases,
        })

    def _log_feedback_applied(self, adjusted: Dict[str, float], reconciled_count: int) -> None:
        """Log comprehensive feedback application results."""
        if not adjusted:
            logger.info("Feedback applied: no agents met criteria (reconciled=%d)", reconciled_count)
            return

        log_fn = logger.info if self.config.log_level == "info" else logger.debug

        log_fn(
            "Feedback applied to %d agents (reconciled since last: %d)",
            len(adjusted), reconciled_count
        )

        for agent_id, new_weight in adjusted.items():
            # Get history for this agent
            history = getattr(self.coord, '_weight_adjustment_history', [])
            agent_history = [h for h in history if h['agent_id'] == agent_id]
            if agent_history:
                last_adj = agent_history[-1]
                delta = last_adj['delta']
                log_fn(
                    "  %s: weight=%.3f (Δ%.3f)",
                    agent_id, new_weight, delta
                )
            else:
                log_fn("  %s: weight=%.3f", agent_id, new_weight)

        # Record to history
        self._feedback_history.append({
            "timestamp": time.time(),
            "mode": "applied",
            "reconciled_count": reconciled_count,
            "agents_adjusted": len(adjusted),
            "adjusted": adjusted,
        })

    def get_feedback_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get history of feedback runs."""
        return self._feedback_history[-limit:]

    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status."""
        now = time.time()
        return {
            "running": self._task is not None and not self._task.done(),
            "dry_run": self.config.dry_run,
            "reconciled_since_last": self._reconciled_count,
            "seconds_since_last_feedback": now - self._last_feedback_time,
            "rounds_interval": self.config.rounds_interval,
            "time_interval_seconds": self.config.time_interval_seconds,
            "feedback_runs": len(self._feedback_history),
        }


# Singleton instance
_feedback_scheduler: Optional[LedgerFeedbackScheduler] = None


def get_feedback_scheduler(coordinator=None) -> Optional[LedgerFeedbackScheduler]:
    """Get or create the global feedback scheduler."""
    global _feedback_scheduler
    if _feedback_scheduler is None and coordinator is not None:
        _feedback_scheduler = LedgerFeedbackScheduler(coordinator)
    return _feedback_scheduler


def start_feedback_scheduler(coordinator, config: Optional[FeedbackScheduleConfig] = None) -> LedgerFeedbackScheduler:
    """Create and start the feedback scheduler."""
    global _feedback_scheduler
    _feedback_scheduler = LedgerFeedbackScheduler(coordinator, config)
    _feedback_scheduler.start()
    return _feedback_scheduler
