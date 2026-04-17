"""Verify imports of swarm_routes, ws_paper, agents_real."""
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")

CHECKS = {
    "swarm_routes.py": [
        ("observability", "swarm_telemetry"),
        ("execution", "execution_coordinator"),
        ("consensus", "consensus_coordinator"),
        ("agents", "watchdog_agents"),
        ("schemas", "swarm_events"),
    ],
    "ws_paper.py": [
        ("trading", "mode_controller"),
        ("core", "agent_orchestrator"),
    ],
    "agents_real.py": [
        ("agents", "agent_mesh"),
        ("core", "agent_orchestrator"),
    ],
}

for router, deps in CHECKS.items():
    print(f"\n{router}:")
    for pkg, mod in deps:
        path = ROOT / pkg / (mod + ".py")
        if path.exists():
            print(f"  ✅ {pkg}.{mod}")
        else:
            print(f"  ❌ MISSING: {pkg}/{mod}.py")
