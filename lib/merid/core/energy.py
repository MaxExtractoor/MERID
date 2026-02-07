"""Utilities to normalize incoming "energy" (queries) into a structured dict.

This is intentionally minimal: it provides a deterministic shape that the orchestrator
and tests depend on. Add validation and richer metadata later (P1).
"""

from __future__ import annotations

from typing import Dict


def create_energy(source: str, payload: str) -> Dict[str, object]:
    """Create a normalized energy dict.

    Args:
        source: A short identifier for the originating source (e.g., "polymarket").
        payload: The raw payload or user query string.

    Returns:
        A dict with keys "source", "payload" and an empty "meta" dict.
    """
    return {"source": source, "payload": payload, "meta": {}}
