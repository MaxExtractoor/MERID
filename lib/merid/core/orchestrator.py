"""Minimal MeridCore orchestrator used by the FastAPI server for SSE streaming.

This is a lightweight, well-documented stub that yields deterministic dict
updates. Replace with richer orchestration logic as we implement agents,
strategy evaluation, and execution in later tasks.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Dict


class MeridCore:
    """Small orchestrator placeholder to support integration and tests.

    Public surface:
      - async run_cycle_stream(energy: dict) -> AsyncIterator[dict]
      - run_cycle(energy: dict) -> dict
    """

    def __init__(self, queue=None):
        self.queue = queue

    async def run_cycle_stream(self, energy: Dict[str, object]) -> AsyncIterator[Dict[str, object]]:
        """Yield progress updates for a processing cycle.

        The function yields at least three updates: a 'started' update, at least
        one 'processing' update, and a final 'done' update containing a simple
        result dict. This provides a stable contract for `web/main.py` SSE.
        """
        # Starting update
        yield {"status": "started", "energy": energy}

        # Simulate a short processing pipeline with staged updates
        await asyncio.sleep(0.01)
        yield {"status": "processing", "progress": 50}

        # Final result produced by synchronous runner (so tests can call it directly)
        if self.queue is not None:
            # Offload heavy processing to background queue
            fut = self.queue.submit_sync(self.run_cycle, energy)
            result = await fut
        else:
            result = self.run_cycle(energy)

        await asyncio.sleep(0.01)
        yield {"status": "done", "result": result}

    def run_cycle(self, energy: Dict[str, object]) -> Dict[str, object]:
        """Synchronous pass-through runner returning a final result dict.

        Real logic should validate data, call agents, and produce an audited
        result; for now this returns a predictable summary used in tests.
        """
        return {"summary": f"Processed input from {energy.get('source')}", "ok": True}
