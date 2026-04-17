from __future__ import annotations

"""Stage 11 Self-healing watchdog: monitors automation failures and validation backlog."""

import asyncio
from typing import Optional, Set

from core.state import state
from interfaces.automation import broadcast_reality
from utils.logger import get_logger

logger = get_logger("hardening.watchdog")


class _Watchdog:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._retried: Set[str] = set()

    def ensure_running(self) -> None:
        if self._task and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run())
        logger.info("Watchdog loop started.")

    async def trigger_manual_retry(self, energy_id: str) -> bool:
        validation = await state.get_validation(energy_id)
        success = await self._retry_entry(energy_id, validation)
        await state.record_automation_event(
            channel="watchdog",
            status="sent" if success else "failed",
            message=f"Manual retry {'succeeded' if success else 'failed'} for energy {energy_id}",
            energy_id=energy_id,
        )
        return success

    async def _run(self) -> None:
        while True:
            try:
                await self._check_pending_validations()
                await self._retry_failed_automation()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Watchdog tick failed: %s", exc)
            await asyncio.sleep(90)

    async def _check_pending_validations(self) -> None:
        pending = [
            entry
            for entry in await state.list_validations(12)
            if entry.get("verdict", {}).get("status") == "pending"
        ]
        if len(pending) >= 3:
            await state.record_automation_event(
                channel="watchdog",
                status="notice",
                message=f"{len(pending)} validations pending — investigate validator lag.",
            )

    async def _retry_failed_automation(self) -> None:
        failures = [
            entry
            for entry in await state.list_automation_events(20)
            if entry.get("status") == "failed"
            and entry.get("energy_id")
            and entry["energy_id"] not in self._retried
        ]
        for failure in failures[:3]:
            energy_id = failure["energy_id"]
            validation = await state.get_validation(energy_id)
            await self._retry_entry(energy_id, validation)

    async def _retry_entry(self, energy_id: str, validation: dict) -> bool:
        if not validation:
            return False
        verdict = validation.get("verdict", {})
        vote_result = validation.get("vote_result")
        energy = validation.get("energy")
        if not energy or verdict.get("status") != "confirmed" or not vote_result:
            return False
        logger.info("Retrying automation for energy %s", energy_id)
        await broadcast_reality(energy, vote_result, verdict)
        self._retried.add(energy_id)
        return True


watchdog = _Watchdog()
