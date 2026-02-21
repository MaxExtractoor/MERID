"""Safeguard policy gates for runtime and CI enforcement."""

from merid.safeguards.swarm_integrity_guard import (
    IntegrityReport,
    UNVERIFIED_DATA_MESSAGE,
    evaluate_swarm_integrity,
    load_safeguard_policy,
    load_swarm_snapshot,
    run_swarm_integrity_gate,
)

__all__ = [
    "IntegrityReport",
    "UNVERIFIED_DATA_MESSAGE",
    "evaluate_swarm_integrity",
    "load_safeguard_policy",
    "load_swarm_snapshot",
    "run_swarm_integrity_gate",
]
