"""Targeted scan of core/ for unprotected singletons and broken wiring."""
import re
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
core_dir = ROOT / "core"

SKIP = {"__pycache__", "tests"}

# Pattern: module-level `_var = None` + `global _var` but no threading.Lock
unprotected = []
for py in core_dir.rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    c = py.read_text(encoding="utf-8", errors="ignore")
    has_global_none = bool(re.search(r"^_\w+\s*=\s*None\s*$", c, re.MULTILINE))
    has_mutation = bool(re.search(r"^\s*global\s+_\w+", c, re.MULTILINE))
    has_lock = "threading.Lock" in c or "asyncio.Lock" in c or "_lock" in c
    if has_global_none and has_mutation and not has_lock:
        unprotected.append(str(py.relative_to(ROOT)))

print(f"Unprotected globals in core/ ({len(unprotected)}):")
for u in sorted(unprotected)[:20]:
    print(f"  {u}")

print()

# Check for duplicate function/class names within the same file in core/
print("Duplicate def/class names in core/ files:")
shadow_found = []
for py in core_dir.rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    c = py.read_text(encoding="utf-8", errors="ignore")
    defs = re.findall(r"^(?:async )?def (\w+)\s*\(", c, re.MULTILINE)
    classes = re.findall(r"^class (\w+)\s*[:(]", c, re.MULTILINE)
    for names in (defs, classes):
        seen = set()
        for n in names:
            if n in seen and n not in ("__init__", "__str__", "__repr__", "test"):
                shadow_found.append(f"  {py.relative_to(ROOT)}: DUPLICATE '{n}'")
            seen.add(n)

if shadow_found:
    for s in sorted(set(shadow_found))[:15]:
        print(s)
else:
    print("  None found")

print()

# Missing __init__.py in core/ subdirs that are used as packages
print("core/ subdirs missing __init__.py:")
for subdir in sorted(core_dir.iterdir()):
    if subdir.is_dir() and not subdir.name.startswith("__"):
        init = subdir / "__init__.py"
        if not init.exists():
            # Check if anything imports from this subdir as package
            pkg_name = f"core.{subdir.name}"
            uses = []
            for py in ROOT.rglob("*.py"):
                if "__pycache__" in py.parts:
                    continue
                try:
                    c2 = py.read_text(encoding="utf-8", errors="ignore")
                    if pkg_name in c2:
                        uses.append(str(py.relative_to(ROOT)))
                except Exception:
                    pass
            if uses:
                print(f"  MISSING __init__.py: {subdir.name}/ (imported by {len(uses)} files)")
            else:
                print(f"  (unused) {subdir.name}/")
