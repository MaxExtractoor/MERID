"""
Meta-monitor for 15m Lean Stack.

Watches the relationship between startup and the loop,
builds meta-snapshots from real state, and runs meta-invariants.
"""

from merid.meta_cognition.meta_invariants import MetaSnapshot, evaluate_meta_invariants
from merid.meta_cognition.self_awareness import detect_construction_artifacts


def build_meta_snapshot(app) -> MetaSnapshot:
    """
    Build a meta-snapshot from the current application state.
    
    Connects to actual objects:
    - settings for profile and mode
    - startup_state for startup lifecycle
    - app.state.loop_15m for loop state
    - self_awareness for construction flags
    """
    from merid.settings import settings
    
    # Get startup state from app
    startup_state = getattr(app.state, "startup_state", None)
    
    # Get loop state
    loop = getattr(app.state, "loop_15m", None)
    loop_status = "stopped"
    loop_profile = None
    loop_is_live = None
    
    if loop is not None:
        loop_status = "running" if loop.is_running else "stopped"
        # Try to get loop's view of profile/mode
        loop_profile = getattr(loop, "_profile", None)
        loop_is_live = getattr(loop, "_is_live", None)
    
    # Get mode info from Kalshi client if available
    is_demo = False
    is_live = False
    try:
        kalshi_client = getattr(app.state, "kalshi_client", None)
        if kalshi_client:
            is_demo = kalshi_client.is_demo
            is_live = kalshi_client.is_live
    except (AttributeError, RuntimeError):
        pass
    
    # Get legacy modules
    legacy_modules = []
    try:
        import sys
        legacy_module_names = [
            "core.paper_session",
            "swarm.agent_registry",
            "agents.reflection.integration",
            "merid.event_venues.kalshi.deployment",
        ]
        for mod_name in legacy_module_names:
            if mod_name in sys.modules:
                legacy_modules.append(mod_name)
    except Exception:
        pass
    
    # Get construction flags
    construction_flags = detect_construction_artifacts()
    
    # Get startup lifecycle state
    startup_started = False
    startup_completed = False
    startup_failed = False
    
    if startup_state is not None:
        startup_started = getattr(startup_state, "started", False)
        startup_completed = getattr(startup_state, "completed", False)
        startup_failed = getattr(startup_state, "failed", False)
    
    # Build snapshot
    return MetaSnapshot(
        profile=settings.MERID_PROFILE,
        is_live=is_live,
        startup_started=startup_started,
        startup_completed=startup_completed,
        startup_failed=startup_failed,
        loop_status=loop_status,
        loop_profile=loop_profile or settings.MERID_PROFILE,
        loop_is_live=bool(loop_is_live if loop_is_live is not None else is_live),
        legacy_modules_loaded=legacy_modules,
        construction_flags=construction_flags,
    )


def run_meta_check(app):
    """
    Run a meta-cognitive check on the application.
    
    Returns:
        tuple: (snapshot, violations)
    """
    snapshot = build_meta_snapshot(app)
    violations = evaluate_meta_invariants(snapshot)
    return snapshot, violations
