"""
Meta-cognitive layer for 15m Lean Stack.

Thin coordination and sanity layer that:
- Watches the relationship between startup and the loop
- Ensures config/profile/mode alignment end-to-end
- Detects "this looks like construction/test" in a live process
- Exposes meta-health surface and optional auto-correction
"""

from merid.meta_cognition.meta_invariants import (
    MetaSnapshot,
    MetaViolation,
    evaluate_meta_invariants,
)
from merid.meta_cognition.meta_monitor import build_meta_snapshot, run_meta_check
from merid.meta_cognition.self_awareness import detect_construction_artifacts

__all__ = [
    "MetaSnapshot",
    "MetaViolation",
    "evaluate_meta_invariants",
    "build_meta_snapshot",
    "run_meta_check",
    "detect_construction_artifacts",
]
