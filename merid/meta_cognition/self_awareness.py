"""
Construction/testing artifact detection for 15m Lean Stack.

Static and env-based checks to detect when the process is running
in a construction/testing mode while being treated as production.
"""

import os
import sys


def detect_construction_artifacts() -> dict[str, bool]:
    """
    Detect construction/testing artifacts in the current process.
    
    Returns a dictionary of flag names to boolean values indicating
    whether each artifact is present.
    """
    flags = {}

    # CI/test detection (explicit environment model; no test-runner artifacts)
    flags["TEST_ENVIRONMENT"] = os.getenv("MERID_ENV", "").strip().lower() in (
        "testing",
        "test",
    )
    flags["CI_ENVIRONMENT"] = bool(os.environ.get("CI"))

    # Debug / dry-run modes
    flags["DEBUG_MODE"] = os.environ.get("MERID_DEBUG", "false").lower() == "true"
    flags["DRY_RUN"] = os.environ.get("MERID_DRY_RUN", "false").lower() == "true"

    # Imports that shouldn't exist in lean 15m process
    flags["PAPER_SESSION_IMPORTED"] = "core.paper_session" in sys.modules
    flags["AGENT_REGISTRY_IMPORTED"] = "swarm.agent_registry" in sys.modules
    flags["REFLECTION_IMPORTED"] = "agents.reflection.integration" in sys.modules
    flags["KALSHI_DEPLOYMENT_IMPORTED"] = "merid.event_venues.kalshi.deployment" in sys.modules

    return flags
