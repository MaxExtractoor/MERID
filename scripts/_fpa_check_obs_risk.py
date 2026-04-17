"""Verify observability_manager and risk.get_agent_metrics_tracker."""
from pathlib import Path
import re

ROOT = Path(r"c:\Dev\MERID")

checks = [
    (ROOT / "core" / "observability_manager.py",  "get_observability_manager"),
    (ROOT / "risk" / "__init__.py",                "get_agent_metrics_tracker"),
    (ROOT / "risk" / "agent_metrics.py",           "get_agent_metrics_tracker"),
]

for path, sym in checks:
    exists = path.exists()
    if exists:
        c = path.read_text(encoding="utf-8", errors="ignore")
        has_sym = sym in c
        print(f"{path.relative_to(ROOT)}: exists={exists}, has '{sym}': {has_sym}")
    else:
        print(f"{path.relative_to(ROOT)}: EXISTS=FALSE")
