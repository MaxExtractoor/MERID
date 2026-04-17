"""Final broad sweep — startup wiring, merid loop, web startup_agents, swarm charters."""
import re
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
SKIP = {"archive", "docs_archive", ".git", "__pycache__", "tools", ".venv", "tests", "scripts"}


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ── 1. web/startup_agents.py — does every agent it starts actually exist? ────
print("=" * 60)
print("1. web/startup_agents.py — agent class references")
print("=" * 60)
sa = ROOT / "web" / "startup_agents.py"
if sa.exists():
    content = read(sa)
    # Find class instantiations or imports
    imports = re.findall(r'^from ([\w.]+) import (\w+)', content, re.MULTILINE)
    missing = []
    for mod, cls in imports:
        rel = mod.replace(".", "/") + ".py"
        pkg = mod.replace(".", "/") + "/__init__.py"
        if not (ROOT / rel).exists() and not (ROOT / pkg).exists():
            missing.append(f"  MISSING: from {mod} import {cls}")
    if missing:
        for m in missing:
            print(m)
    else:
        print("  ✅ All imports in startup_agents.py resolve")

print()

# ── 2. merid/loop.py — does it import everything it needs? ───────────────────
print("=" * 60)
print("2. merid/loop.py — import chain integrity")
print("=" * 60)
loop = ROOT / "merid" / "loop.py"
if loop.exists():
    content = read(loop)
    imports = re.findall(r'^from ([\w.]+) import', content, re.MULTILINE)
    missing = []
    for mod in imports:
        if mod.startswith(("__future__", "typing", "asyncio", "time", "os",
                           "collections", "dataclasses", "enum", "abc",
                           "threading", "functools")):
            continue
        rel = mod.replace(".", "/") + ".py"
        pkg = mod.replace(".", "/") + "/__init__.py"
        if not (ROOT / rel).exists() and not (ROOT / pkg).exists():
            missing.append(f"  MISSING: from {mod}")
    if missing:
        for m in sorted(set(missing)):
            print(m)
    else:
        print("  ✅ All loop.py imports resolve")
else:
    print("  ❌ merid/loop.py MISSING")

print()

# ── 3. swarm/agents/charters.py — charter keys used in main.py ───────────────
print("=" * 60)
print("3. swarm CHARTER_REGISTRY keys vs references in main.py")
print("=" * 60)
charters_f = ROOT / "swarm" / "agents" / "charters.py"
if charters_f.exists():
    charters_content = read(charters_f)
    keys = re.findall(r'"([\w_-]+)"\s*:', charters_content)
    main_content = read(ROOT / "web" / "main.py")
    for k in keys:
        if k in main_content:
            print(f"  ✅ charter '{k}' referenced in main.py")
    unreferenced = [k for k in keys if k not in main_content]
    if unreferenced:
        print(f"  ⚠  Unreferenced charters: {unreferenced[:10]}")
    else:
        print("  ✅ All charters referenced")
else:
    print("  ❌ charters.py MISSING")

print()

# ── 4. merid/execution/__init__.py — exports check ───────────────────────────
print("=" * 60)
print("4. merid/execution/__init__.py exports")
print("=" * 60)
exec_init = ROOT / "merid" / "execution" / "__init__.py"
if exec_init.exists():
    c = read(exec_init)
    if c.strip():
        exports = re.findall(r'^(?:class|def|async def|from) ', c, re.MULTILINE)
        print(f"  Lines: {len(c.splitlines())}, exports/imports: {len(exports)}")
    else:
        print("  ⚠  EMPTY __init__.py")
else:
    print("  ❌ MISSING")

print()

# ── 5. Check for eval() / exec() calls in production code (RCE risk) ─────────
print("=" * 60)
print("5. eval()/exec() calls in production code")
print("=" * 60)
dangerous = []
for py in ROOT.rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    c = read(py)
    for m in re.finditer(r'\beval\s*\(|\bexec\s*\(', c):
        line_no = c[:m.start()].count("\n") + 1
        line = c.splitlines()[line_no - 1].strip()
        if "# noqa" not in line and "# safe" not in line.lower():
            dangerous.append(f"  {py.relative_to(ROOT)}:{line_no}  {line[:80]}")

if dangerous:
    for d in sorted(dangerous)[:15]:
        print(d)
else:
    print("  ✅ No dangerous eval()/exec() found")

print()

# ── 6. Hardcoded secrets / API keys in source ────────────────────────────────
print("=" * 60)
print("6. HARDCODED SECRETS (common patterns)")
print("=" * 60)
SECRET_RE = re.compile(
    r'(?:api_key|secret|password|token|private_key)\s*=\s*["\']([A-Za-z0-9+/=_\-]{16,})["\']',
    re.IGNORECASE
)
SAFE_VALUES = {"change_me", "your_api_key_here", "your-secret-key", "placeholder", "test",
               "none", "null", "false", "true", "default", "example", "dummy", "fake"}
secrets_found = []
for py in ROOT.rglob("*.py"):
    if any(d in py.parts for d in SKIP):
        continue
    c = read(py)
    for m in SECRET_RE.finditer(c):
        val = m.group(1).lower()
        if not any(s in val for s in SAFE_VALUES) and len(m.group(1)) >= 20:
            line_no = c[:m.start()].count("\n") + 1
            secrets_found.append(f"  {py.relative_to(ROOT)}:{line_no}  {m.group(0)[:60]}")

if secrets_found:
    for s in sorted(secrets_found)[:10]:
        print(s)
else:
    print("  ✅ No obvious hardcoded secrets")

print()
print("=" * 60)
print("FINAL SWEEP COMPLETE")
print("=" * 60)
