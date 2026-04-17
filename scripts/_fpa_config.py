"""Scan for env-var gaps: os.getenv() calls that have no default and no entry in merid/settings.py."""
import re
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
SKIP = {"archive", "docs_archive", ".git", "__pycache__", "tools", ".venv", "tests", "scripts"}

settings_text = (ROOT / "merid" / "settings.py").read_text(encoding="utf-8", errors="ignore")
settings_vars = set(re.findall(r'(\w+)\s*:\s*\w+.*?=\s*Field\(', settings_text))

# Find all os.getenv("KEY") calls with no default
NO_DEFAULT_RE = re.compile(r'os\.getenv\(["\']([A-Z_][A-Z0-9_]+)["\'],?\s*\)')
WITH_DEFAULT_RE = re.compile(r'os\.getenv\(["\']([A-Z_][A-Z0-9_]+)["\'],\s*[^)]+\)')

ungated = {}  # key → files where it appears without a default
for py in ROOT.rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    try:
        c = py.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for m in NO_DEFAULT_RE.finditer(c):
        k = m.group(1)
        if k not in settings_vars:
            ungated.setdefault(k, []).append(str(py.relative_to(ROOT)))

print(f"=== UNGATED os.getenv() with NO DEFAULT and NOT in settings.py ({len(ungated)}) ===")
for k in sorted(ungated):
    files = ungated[k]
    print(f"  {k}: {files[:2]}{'...' if len(files)>2 else ''}")
