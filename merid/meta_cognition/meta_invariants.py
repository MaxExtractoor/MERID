"""
Meta-level invariants for 15m Lean Stack.

Pure, side-effect-free checks that consume snapshots of state.
No network calls, no side effects - just logic.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MetaSnapshot:
    """Snapshot of system state for meta-invariant evaluation."""
    profile: str
    is_live: bool
    startup_started: bool
    startup_completed: bool
    startup_failed: bool
    loop_status: str  # "starting" | "running" | "stopped" | "error"
    loop_profile: str
    loop_is_live: bool
    legacy_modules_loaded: List[str]
    construction_flags: Dict[str, bool]


@dataclass
class MetaViolation:
    """A meta-invariant violation."""
    code: str  # e.g., "PROFILE_MISMATCH"
    severity: str  # "error" | "warning"
    message: str


def evaluate_meta_invariants(snapshot: MetaSnapshot) -> List[MetaViolation]:
    """
    Evaluate meta-invariants against a system snapshot.
    
    Returns a list of violations (empty if all invariants pass).
    """
    violations: List[MetaViolation] = []

    # 1) Startup/loop profile match
    if snapshot.profile != snapshot.loop_profile:
        violations.append(MetaViolation(
            code="PROFILE_MISMATCH",
            severity="error",
            message=f"Startup profile={snapshot.profile} but loop_profile={snapshot.loop_profile}",
        ))

    # 2) Mode (live/demo) match
    if snapshot.is_live != snapshot.loop_is_live:
        violations.append(MetaViolation(
            code="MODE_MISMATCH",
            severity="error",
            message=f"Startup is_live={snapshot.is_live} but loop_is_live={snapshot.loop_is_live}",
        ))

    # 3) Startup vs loop lifecycle
    if snapshot.startup_completed and snapshot.loop_status in ("stopped", "error"):
        violations.append(MetaViolation(
            code="LOOP_NOT_RUNNING_AFTER_STARTUP",
            severity="error",
            message=f"Startup completed but loop_status={snapshot.loop_status}",
        ))

    # 4) Legacy modules in a lean process
    if snapshot.legacy_modules_loaded:
        violations.append(MetaViolation(
            code="LEGACY_MODULES_LOADED",
            severity="error",
            message=f"Legacy modules loaded in lean 15m stack: {snapshot.legacy_modules_loaded}",
        ))

    # 5) Construction flags
    for name, enabled in snapshot.construction_flags.items():
        if enabled:
            violations.append(MetaViolation(
                code=f"CONSTRUCTION_FLAG_{name}",
                severity="warning",
                message=f"Construction/testing flag {name} is enabled in production process",
            ))

    return violations
