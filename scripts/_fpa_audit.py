"""Forward-Progression Audit (FPA) — run from repo root."""
import os
import re
import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
API_DIR = ROOT / "web" / "api"
SKIP = {"archive", "docs_archive", ".git", "__pycache__", "tools", ".venv", "node_modules"}


def _read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ── 1. Duplicate route prefixes ──────────────────────────────────────────────
print("=" * 60)
print("1. DUPLICATE ROUTE PREFIXES in web/api/")
print("=" * 60)
prefixes = defaultdict(list)
for fn in API_DIR.glob("*.py"):
    content = _read(fn)
    for m in re.finditer(r'prefix\s*=\s*["\'](/[^"\']+)["\']', content):
        prefixes[m.group(1)].append(fn.name)

dupes = {k: v for k, v in prefixes.items() if len(v) > 1}
if dupes:
    for prefix, files in sorted(dupes.items()):
        print(f"  DUPLICATE {prefix}: {files}")
else:
    print("  ✅ No duplicates")

# ── 2. Missing imported modules in web/main.py ───────────────────────────────
print()
print("=" * 60)
print("2. MISSING MODULES imported in web/main.py")
print("=" * 60)
main_content = _read(ROOT / "web" / "main.py")
imported = re.findall(r"^from ([\w.]+) import", main_content, re.MULTILINE)
missing_imports = []
for mod in set(imported):
    rel_path = mod.replace(".", os.sep) + ".py"
    full = ROOT / rel_path
    if not full.exists():
        # Try __init__.py
        pkg = ROOT / mod.replace(".", os.sep) / "__init__.py"
        if not pkg.exists():
            missing_imports.append(mod)
if missing_imports:
    for m in sorted(missing_imports):
        print(f"  ❌ MISSING: {m}")
else:
    print("  ✅ All top-level imports resolve")

# ── 3. NotImplementedError in non-abstract, non-test code ────────────────────
print()
print("=" * 60)
print("3. NotImplementedError in PRODUCTION (non-abstract) code")
print("=" * 60)
skip_dirs = {"archive", "docs_archive", ".git", "__pycache__", "tools", ".venv", "tests"}
not_impl = []
for py in ROOT.rglob("*.py"):
    skip = any(d in py.parts for d in skip_dirs)
    if skip:
        continue
    content = _read(py)
    if "raise NotImplementedError" not in content:
        continue
    # Skip if it's inside an @abstractmethod block (acceptable)
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "raise NotImplementedError" in line:
            # Look back 5 lines for @abstractmethod
            context = "\n".join(lines[max(0, i - 5):i])
            if "@abstractmethod" not in context and "abstract" not in context.lower():
                not_impl.append(f"  {py.relative_to(ROOT)}:{i+1}  {line.strip()}")

if not_impl:
    for item in sorted(not_impl)[:30]:
        print(item)
else:
    print("  ✅ None found outside abstract methods")

# ── 4. TODO/FIXME/HACK in critical execution paths ───────────────────────────
print()
print("=" * 60)
print("4. TODO/FIXME/HACK in CRITICAL paths")
print("=" * 60)
critical_dirs = [
    ROOT / "merid" / "execution",
    ROOT / "merid" / "risk",
    ROOT / "merid" / "pipeline",
    ROOT / "merid" / "event_venues" / "kalshi",
    ROOT / "trading",
    ROOT / "core",
    ROOT / "web" / "api",
]
todos_found = []
for cdir in critical_dirs:
    for py in Path(cdir).rglob("*.py") if cdir.exists() else []:
        content = _read(py)
        for i, line in enumerate(content.splitlines()):
            if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line, re.IGNORECASE):
                todos_found.append(f"  {py.relative_to(ROOT)}:{i+1}  {line.strip()}")

if todos_found:
    for t in todos_found[:40]:
        print(t)
else:
    print("  ✅ None found in critical dirs")

# ── 5. Broken cross-module refs: from X import Y where Y may not exist ────────
print()
print("=" * 60)
print("5. BROKEN INTRA-PROJECT from-imports (quick check)")
print("=" * 60)
broken = []
check_dirs = [ROOT / "merid", ROOT / "trading", ROOT / "core", ROOT / "web" / "api"]
for cdir in check_dirs:
    for py in Path(cdir).rglob("*.py") if cdir.exists() else []:
        skip = any(d in py.parts for d in skip_dirs)
        if skip:
            continue
        content = _read(py)
        for m in re.finditer(r"^from (merid\.\w+(?:\.\w+)*) import", content, re.MULTILINE):
            mod = m.group(1)
            rel = mod.replace(".", os.sep) + ".py"
            pkg = mod.replace(".", os.sep) + os.sep + "__init__.py"
            if not (ROOT / rel).exists() and not (ROOT / pkg).exists():
                broken.append(f"  {py.relative_to(ROOT)}: from {mod}")

if broken:
    for b in sorted(set(broken))[:30]:
        print(b)
else:
    print("  ✅ No obvious broken merid.* imports")

# ── 6. Singleton / global state without lock protection ──────────────────────
print()
print("=" * 60)
print("6. UNPROTECTED GLOBALS (mutation without lock, quick heuristic)")
print("=" * 60)
unprotected = []
for cdir in [ROOT / "merid", ROOT / "trading", ROOT / "core"]:
    for py in Path(cdir).rglob("*.py") if cdir.exists() else []:
        skip = any(d in py.parts for d in skip_dirs)
        if skip:
            continue
        content = _read(py)
        # Pattern: module-level _var = None  BUT the file never uses threading.Lock
        has_global_none = bool(re.search(r"^_\w+\s*[=:]\s*None\s*$", content, re.MULTILINE))
        has_lock = "threading.Lock" in content or "asyncio.Lock" in content or "_lock" in content
        has_mutation = bool(re.search(r"^\s*global\s+_\w+", content, re.MULTILINE))
        if has_global_none and has_mutation and not has_lock:
            unprotected.append(f"  {py.relative_to(ROOT)}")

if unprotected:
    for u in sorted(unprotected)[:20]:
        print(u)
else:
    print("  ✅ No obvious unprotected globals found")

# ── 7. Dead imported routers (imported but never include_router'd) ────────────
print()
print("=" * 60)
print("7. IMPORTED ROUTERS NOT REGISTERED in web/main.py")
print("=" * 60)
router_imports = re.findall(r"^from \S+ import .* as (\w+_router)\b", main_content, re.MULTILINE)
router_imports += re.findall(r"^from \S+ import .* as (\w+_api_router)\b", main_content, re.MULTILINE)
dead_routers = []
for rname in router_imports:
    if rname not in main_content.split("# Mock")[0]:  # exclude commented section
        pass
    include_pattern = f"include_router({rname}"
    if include_pattern not in main_content:
        dead_routers.append(rname)

if dead_routers:
    for r in sorted(dead_routers):
        print(f"  ⚠️  {r}")
else:
    print("  ✅ All imported routers are registered")

print()
print("=" * 60)
print("FPA AUDIT COMPLETE")
print("=" * 60)
