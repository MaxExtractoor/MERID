from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Dict, Optional, Set

from utils.logger import get_logger

logger = get_logger("core.runtime")


class SystemMode(Enum):
    """High-level runtime mode for MERID."""

    BOOTING = "booting"
    WARMUP = "warmup"
    OBSERVE_ONLY = "observe_only"
    LIVE_TRADING = "live_trading"
    DEGRADED = "degraded"
    SHUTTING_DOWN = "shutting_down"


class Subsystem(Enum):
    """Subsystems started from the production lifespan."""

    PRICE_PUBLISHER = "price_publisher"
    PORTFOLIO_PUBLISHER = "portfolio_publisher"
    PRICE_FEED = "price_feed"
    CONSENSUS = "consensus"
    EXECUTION = "execution"
    HEALTH = "health_monitor"
    AGENT_MESH = "agent_mesh"
    ORCHESTRATOR = "agent_orchestrator"
    MINER = "simulation_miner"
    AUDIT = "audit_trail"
    PREDICTION = "prediction_aggregator"
    ALERTS = "alerts"
    NEWS_INTELLIGENCE = "news_intelligence"
    API_PRICE = "api_price_feed"
    WS_BRIDGE = "kalshi_ws_bridge"
    ORCHESTRATOR_MANAGER = "orchestrator_manager"
    PORTFOLIO_RISK = "portfolio_risk_agent"


class SubsystemStatus(Enum):
    """Lifecycle status of a subsystem."""

    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ManagedTask:
    """Metadata for a background task."""

    name: str
    task: asyncio.Task
    stop: Optional[Callable[[], Awaitable[None] | None]] = None
    critical: bool = True
    failure: Optional[str] = None


class TaskManager:
    """Tracks background tasks and orchestrates shutdown."""

    def __init__(self):
        self._tasks: Dict[str, ManagedTask] = {}

    def create_task(
        self,
        name: str,
        coro: Awaitable,
        *,
        stop: Optional[Callable[[], Awaitable[None] | None]] = None,
        critical: bool = True,
    ) -> asyncio.Task:
        task = asyncio.create_task(self._wrap_task(name, coro), name=name)
        self._tasks[name] = ManagedTask(name=name, task=task, stop=stop, critical=critical)
        return task

    async def _wrap_task(self, name: str, coro: Awaitable):
        try:
            return await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            managed = self._tasks.get(name)
            if managed:
                managed.failure = str(exc)
            logger.error("Task %s failed: %s", name, exc, exc_info=True)
            raise

    async def stop_all(self, timeout: float = 10.0):
        """Invoke stop callbacks then cancel remaining tasks."""
        # Stop callbacks in reverse registration order
        for name, managed in reversed(list(self._tasks.items())):
            if managed.stop:
                try:
                    result = managed.stop()
                    if inspect.isawaitable(result):
                        await asyncio.wait_for(result, timeout=timeout)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Error stopping %s: %s", name, exc)

        # Cancel any still-running tasks
        pending = [m.task for m in self._tasks.values() if not m.task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def failed_tasks(self) -> Dict[str, str]:
        """Return tasks that recorded failures."""
        return {name: m.failure for name, m in self._tasks.items() if m.failure}


class SystemController:
    """Central readiness and trading-gate controller."""

    def __init__(self, critical: Optional[Set[Subsystem]] = None):
        self.mode: SystemMode = SystemMode.BOOTING
        self._status: Dict[Subsystem, SubsystemStatus] = {
            subsystem: SubsystemStatus.STARTING for subsystem in Subsystem
        }
        self._failures: Dict[Subsystem, str] = {}
        self._ready_events: Dict[Subsystem, asyncio.Event] = {
            subsystem: asyncio.Event() for subsystem in Subsystem
        }
        self._critical: Set[Subsystem] = critical or {
            Subsystem.PRICE_FEED,
            Subsystem.CONSENSUS,
            Subsystem.EXECUTION,
            Subsystem.HEALTH,
            Subsystem.PORTFOLIO_RISK,
        }
        self._execution_guard = None

    def attach_execution_guard(self, guard) -> None:
        """Link to ExecutionGuard for system-wide gating."""
        self._execution_guard = guard
        if guard:
            try:
                guard.set_system_block("system booting")
            except Exception:
                logger.debug("Execution guard system block not available")

    def mark_ready(self, subsystem: Subsystem) -> None:
        previous = self._status.get(subsystem)
        self._status[subsystem] = SubsystemStatus.READY
        self._ready_events[subsystem].set()
        if previous != SubsystemStatus.READY:
            logger.info("Subsystem %s ready", subsystem.value)

    def mark_failed(self, subsystem: Subsystem, reason: str) -> None:
        self._status[subsystem] = SubsystemStatus.FAILED
        self._failures[subsystem] = reason
        self._ready_events[subsystem].set()
        logger.error("Subsystem %s failed: %s", subsystem.value, reason)
        self.set_mode(SystemMode.DEGRADED)
        self.block_trading(f"{subsystem.value} failed: {reason}")

    def mark_stopped(self, subsystem: Subsystem) -> None:
        self._status[subsystem] = SubsystemStatus.STOPPED
        logger.info("Subsystem %s stopped", subsystem.value)

    def set_mode(self, mode: SystemMode) -> None:
        if mode != self.mode:
            logger.info("System mode transition: %s → %s", self.mode.value, mode.value)
        self.mode = mode

    def block_trading(self, reason: str) -> None:
        if self._execution_guard:
            try:
                self._execution_guard.set_system_block(reason)
            except Exception:
                logger.debug("Execution guard system block failed")

    def allow_trading(self) -> None:
        if self._execution_guard:
            try:
                self._execution_guard.clear_system_block()
            except Exception:
                logger.debug("Execution guard system block clear failed")

    async def watch_readiness(
        self, subsystem: Subsystem, event: asyncio.Event, timeout: float = 15.0
    ):
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            self.mark_ready(subsystem)
        except asyncio.TimeoutError:
            self.mark_failed(subsystem, f"readiness timeout after {timeout}s")

    async def wait_for_critical(self, timeout: float = 15.0) -> bool:
        """Wait for critical subsystems to report ready."""
        events = [self._ready_events[subsystem].wait() for subsystem in self._critical]
        try:
            await asyncio.wait_for(asyncio.gather(*events), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            missing = [s.value for s in self._critical if not self._ready_events[s].is_set()]
            logger.error("Critical subsystems not ready within timeout: %s", ", ".join(missing))
            return False

    def snapshot(self) -> Dict[str, Dict[str, str]]:
        return {
            "mode": self.mode.value,
            "status": {subsystem.value: status.value for subsystem, status in self._status.items()},
            "failures": {k.value: v for k, v in self._failures.items()},
        }
