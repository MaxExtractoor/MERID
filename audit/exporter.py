from __future__ import annotations

"""Stage 12 Audit Exporter: bundles validation + automation logs for compliance."""

from typing import Any, Dict

from core.state import state
from core.time_authority import current_time


async def export_trail(limit: int = 200) -> Dict[str, Any]:
    validations = await state.list_validations(limit)
    automation = await state.list_automation_events(limit)
    audits = await state.list_audits(limit)

    return {
        "generated_at": current_time()["utc_iso"],
        "validations": validations,
        "automation": automation,
        "audits": audits,
    }
