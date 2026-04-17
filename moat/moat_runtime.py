from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from core.event_bus import event_stream
from moat.moat_orchestrator import (
    FeatureProposal,
    MoatOrchestrator,
    MoatPillar,
    get_moat_orchestrator,
)
from social.social_aware_quant import get_social_bot_health_monitor


class MoatRuntimeStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class MoatRuntimeService:
    """Background service that continuously measures and reports moat strength."""

    orchestrator: MoatOrchestrator = field(default_factory=get_moat_orchestrator)
    component_name: str = "moat_runtime"

    def __post_init__(self) -> None:
        self._status: MoatRuntimeStatus = MoatRuntimeStatus.STOPPED
        self._loop_task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._interval: float = 300.0
        self._lock = asyncio.Lock()
        self._cycle_count = 0
        self._last_measurement: Optional[datetime] = None
        self._last_metrics: Dict[str, Any] = {}
        self._last_risks: List[Dict[str, Any]] = []
        self._health = get_social_bot_health_monitor()
        self._health.register_component(
            self.component_name,
            component_type="moat",
            auto_recover=True,
            heartbeat_interval=self._interval,
        )

    @property
    def status(self) -> MoatRuntimeStatus:
        return self._status

    async def start(self, interval: float = 300.0) -> None:
        """Start runtime loop."""
        if self._status == MoatRuntimeStatus.RUNNING:
            return
        self._status = MoatRuntimeStatus.STARTING
        self._interval = interval
        self._stop_event.clear()
        loop = asyncio.get_running_loop()
        self._loop_task = loop.create_task(self._run_loop())
        self._health.update_heartbeat(self.component_name, status="running")

    async def stop(self) -> None:
        """Stop runtime loop."""
        if self._loop_task:
            self._stop_event.set()
            await self._loop_task
            self._loop_task = None
        self._status = MoatRuntimeStatus.STOPPED
        self._health.update_heartbeat(self.component_name, status="stopped")

    async def measure_now(self) -> Dict[str, Any]:
        """Trigger immediate measurement."""
        async with self._lock:
            await self._run_cycle()
        return self.get_status_payload()

    async def _run_loop(self) -> None:
        self._status = MoatRuntimeStatus.RUNNING
        while True:
            if self._stop_event.is_set():
                break
            start = datetime.utcnow()
            try:
                async with self._lock:
                    await self._run_cycle()
                self._health.update_heartbeat(
                    self.component_name,
                    metadata={
                        "cycle": self._cycle_count,
                        "last_measurement": self._last_measurement.isoformat() if self._last_measurement else None,
                    },
                )
            except Exception as exc:  # pragma: no cover
                self._status = MoatRuntimeStatus.ERROR
                self._health.record_failure(self.component_name, f"moat_cycle_error:{exc}")
            elapsed = (datetime.utcnow() - start).total_seconds()
            wait_time = max(5.0, self._interval - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_time)
                break
            except asyncio.TimeoutError:
                continue
        self._status = MoatRuntimeStatus.STOPPED

    async def _run_cycle(self) -> None:
        self._cycle_count += 1
        metrics = self.orchestrator.measure_moat_strength()
        risks = self.orchestrator.detect_erosion_risks()
        self._last_measurement = datetime.utcnow()
        self._last_metrics = {
            pillar.value: {
                "strength": metric.strength.value,
                "advantage_ratio": metric.advantage_ratio,
                "trend": metric.trend,
            }
            for pillar, metric in metrics.items()
        }
        self._last_risks = [
            {
                "pillar": risk.pillar.value,
                "risk_type": risk.risk_type,
                "risk_level": risk.risk_level,
                "description": risk.description,
                "mitigation_actions": risk.mitigation_actions,
            }
            for risk in risks
        ]
        await event_stream.publish(
            "moat_measurement",
            {
                "cycle": self._cycle_count,
                "metrics": self._last_metrics,
                "risks": self._last_risks,
                "timestamp": self._last_measurement.isoformat(),
            },
        )

    def get_status_payload(self) -> Dict[str, Any]:
        return {
            "status": self._status.value,
            "cycle_count": self._cycle_count,
            "interval": self._interval,
            "last_measurement": self._last_measurement.isoformat() if self._last_measurement else None,
            "metrics": self._last_metrics,
            "risks": self._last_risks,
        }

    def submit_feature_proposal(self, name: str, description: str) -> FeatureProposal:
        return self.orchestrator.validate_feature_proposal(name, description)


_moat_runtime_service: Optional[MoatRuntimeService] = None


def get_moat_runtime_service() -> MoatRuntimeService:
    global _moat_runtime_service
    if _moat_runtime_service is None:
        _moat_runtime_service = MoatRuntimeService()
    return _moat_runtime_service
