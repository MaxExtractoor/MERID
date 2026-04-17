"""Quick import-chain check for newly-registered routers."""
import ast
import re
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
api_dir = ROOT / "web" / "api"

# The 12 newly-registered routers
NEW_ROUTERS = [
    "agents_health", "risk_metrics", "observability", "websocket_health",
    "modes", "markets_data", "risk_metrics_api", "swarm_routes",
    "agents_real", "ws_dedicated_streams", "ws_paper",
    "consensus_api", "reflection",
]

IMPORT_RE = re.compile(r'^(?:from|import)\s+([\w.]+)', re.MULTILINE)

def check_router(name):
    p = api_dir / (name + ".py")
    if not p.exists():
        return [f"FILE MISSING: {name}.py"]
    content = p.read_text(encoding="utf-8", errors="ignore")
    issues = []
    for m in IMPORT_RE.finditer(content):
        mod = m.group(1).split(".")[0]
        # Only check project-local imports (not stdlib/third-party)
        if mod in ("fastapi", "pydantic", "typing", "collections", "asyncio",
                   "time", "os", "re", "json", "uuid", "datetime", "enum",
                   "dataclasses", "functools", "threading", "abc", "math",
                   "pathlib", "itertools", "copy", "traceback"):
            continue
        # Check if the module exists
        candidates = [
            ROOT / (m.group(1).replace(".", "/") + ".py"),
            ROOT / (m.group(1).replace(".", "/") + "/__init__.py"),
        ]
        if not any(c.exists() for c in candidates):
            issues.append(f"  ? unresolved: {m.group(1)}")
    return issues

print("=== IMPORT CHAIN CHECK FOR NEWLY-REGISTERED ROUTERS ===\n")
for name in NEW_ROUTERS:
    issues = check_router(name)
    if issues:
        print(f"⚠  {name}.py:")
        for i in issues[:5]:
            print(i)
    else:
        print(f"✅ {name}.py")
