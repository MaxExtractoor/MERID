"""Deep forward-progression scan: __init__ export gaps, circular refs, dead code."""
import re
import ast
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
SKIP = {"archive", "docs_archive", ".git", "__pycache__", "tools", ".venv", "tests", "scripts"}


def _read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ── 1. __init__.py that exist but are EMPTY (no exports) in key packages ──────
print("=" * 60)
print("1. EMPTY __init__.py in key packages (no exports)")
print("=" * 60)
KEY_PKGS = [
    ROOT / "merid" / "execution",
    ROOT / "merid" / "risk",
    ROOT / "merid" / "prediction",
    ROOT / "merid" / "agents",
    ROOT / "merid" / "event_venues" / "kalshi",
    ROOT / "merid" / "pipeline",
    ROOT / "merid_core" / "kalshi",
    ROOT / "consensus",
    ROOT / "trading" / "adapters",
    ROOT / "core" / "venues",
    ROOT / "ratelimit",
]
for pkg in KEY_PKGS:
    init = pkg / "__init__.py"
    if not pkg.exists():
        print(f"  ❌ PKG MISSING: {pkg.relative_to(ROOT)}")
        continue
    if not init.exists():
        print(f"  ⚠  NO __init__.py: {pkg.relative_to(ROOT)}")
        continue
    content = _read(init).strip()
    if not content:
        print(f"  ⚠  EMPTY __init__.py: {init.relative_to(ROOT)}")

print()

# ── 2. from X import Y where Y is not defined in X ──────────────────────────
print("=" * 60)
print("2. LIKELY BROKEN: from X import Y — Y not found in X")
print("=" * 60)
INTRA_RE = re.compile(r'^from (merid[\w.]*|core[\w.]*|trading[\w.]*|consensus[\w.]*) import (.+)', re.MULTILINE)
BROKEN_INTRA = []

CRITICAL_DIRS = [
    ROOT / "merid" / "execution",
    ROOT / "merid" / "prediction",
    ROOT / "merid" / "event_venues" / "kalshi",
    ROOT / "merid_core" / "kalshi",
    ROOT / "trading" / "adapters",
    ROOT / "web" / "api",
]
for cdir in CRITICAL_DIRS:
    for py in (cdir.rglob("*.py") if cdir.exists() else []):
        if any(d in py.parts for d in SKIP):
            continue
        content = _read(py)
        for m in INTRA_RE.finditer(content):
            mod_path = m.group(1)
            names = [n.strip().split(" as ")[0] for n in m.group(2).split(",")]
            rel = mod_path.replace(".", "/") + ".py"
            pkg = mod_path.replace(".", "/") + "/__init__.py"
            mod_file = ROOT / rel
            pkg_file = ROOT / pkg
            if mod_file.exists():
                mod_content = _read(mod_file)
                for name in names:
                    if name and name != "*" and f"def {name}" not in mod_content \
                       and f"class {name}" not in mod_content \
                       and f"{name} =" not in mod_content \
                       and f"{name}:" not in mod_content:
                        BROKEN_INTRA.append(
                            f"  {py.relative_to(ROOT)}: from {mod_path} import {name}"
                        )

if BROKEN_INTRA:
    for b in sorted(set(BROKEN_INTRA))[:30]:
        print(b)
else:
    print("  ✅ No broken intra-project imports found")

print()

# ── 3. Functions decorated with @app.on_event / @router but never called ──────
print("=" * 60)
print("3. STARTUP/SHUTDOWN hooks that reference missing functions")
print("=" * 60)
startup_issues = []
for py in (ROOT / "web").rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    c = _read(py)
    for m in re.finditer(r'(?:on_event|lifespan).*?\n.*?async def (\w+)', c):
        fn = m.group(1)
        if fn not in c:
            startup_issues.append(f"  {py.relative_to(ROOT)}: {fn}")
if startup_issues:
    for s in startup_issues:
        print(s)
else:
    print("  ✅ No missing startup/shutdown handlers")

print()

# ── 4. Duplicate function/class names in same module ─────────────────────────
print("=" * 60)
print("4. DUPLICATE def/class in SAME FILE (shadowing risk)")
print("=" * 60)
shadow_found = []
for cdir in CRITICAL_DIRS:
    for py in (cdir.rglob("*.py") if cdir.exists() else []):
        if any(d in py.parts for d in SKIP):
            continue
        content = _read(py)
        defs = re.findall(r'^(?:async )?def (\w+)\s*\(', content, re.MULTILINE)
        classes = re.findall(r'^class (\w+)\s*[:(]', content, re.MULTILINE)
        for names in (defs, classes):
            seen = set()
            for n in names:
                if n in seen:
                    shadow_found.append(f"  {py.relative_to(ROOT)}: DUPLICATE '{n}'")
                seen.add(n)
if shadow_found:
    for s in sorted(set(shadow_found))[:20]:
        print(s)
else:
    print("  ✅ No duplicates found in critical dirs")

print()

# ── 5. Singleton getters that exist in multiple modules (divergence risk) ─────
print("=" * 60)
print("5. MULTIPLE definitions of the SAME singleton getter")
print("=" * 60)
getter_map = {}
for py in ROOT.rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    c = _read(py)
    for m in re.finditer(r'^def (get_\w+)\s*\(\)', c, re.MULTILINE):
        getter_map.setdefault(m.group(1), []).append(str(py.relative_to(ROOT)))

dupes = {k: v for k, v in getter_map.items() if len(v) > 2}
if dupes:
    for fn, files in sorted(dupes.items()):
        print(f"  {fn}: {len(files)} definitions")
        for f in files[:3]:
            print(f"    {f}")
else:
    print("  ✅ No massively-duplicated getters")

print()
print("=" * 60)
print("DEEP SCAN COMPLETE")
print("=" * 60)
