from __future__ import annotations

"""Stage 12 deterministic replay helpers."""

import uuid
from copy import deepcopy
from typing import Any, Dict

from core.energy import create_energy


def _clone_energy(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    payload = snapshot.get("payload", "")
    source = snapshot.get("source", "replay")
    fresh = create_energy(source, payload)
    fresh["energy_id"] = f"{snapshot.get('energy_id', 'unknown')}-replay-{uuid.uuid4().hex[:6]}"
    fresh["metadata"] = deepcopy(snapshot.get("metadata", {}))
    return fresh


async def run_deterministic_replay(merid_core, validation_entry: Dict[str, Any]) -> Dict[str, Any]:
    original_energy = validation_entry.get("energy") or {}
    if not original_energy:
        raise ValueError("Stored validation entry missing energy snapshot.")

    replay_energy = _clone_energy({**original_energy, "energy_id": validation_entry.get("energy_id")})
    replay_result = await merid_core.run_cycle(replay_energy)

    original_vote = validation_entry.get("vote_result", {})

    matches = (
        replay_result.get("approved") == original_vote.get("approved")
        and abs(replay_result.get("consensus", 0) - original_vote.get("consensus", 0)) < 0.05
    )

    return {
        "original": original_vote,
        "replay": replay_result,
        "matches": matches,
        "replay_energy_id": replay_energy["energy_id"],
    }
