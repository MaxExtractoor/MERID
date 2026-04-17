"""Stable decision trace IDs for audit: swarm → sizer → order → fill."""

from __future__ import annotations

import uuid


def new_decision_trace_id(prefix: str = "ta") -> str:
    """Return a new opaque trace id (prefix + full hex for low collision risk)."""
    p = (prefix or "ta").strip() or "ta"
    return f"{p}-{uuid.uuid4().hex}"
