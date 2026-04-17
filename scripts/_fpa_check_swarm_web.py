"""Check which web/api files that use swarm singletons are registered."""
from pathlib import Path

main = Path(r"c:\Dev\MERID\web\main.py").read_text(encoding="utf-8", errors="ignore")
for mod in ["x_bot", "swarm", "rewards", "simulation", "unified_pipeline", "local_venue_validation"]:
    status = "REGISTERED" if f"web.api.{mod}" in main else "NOT registered"
    print(f"  {mod}: {status}")
