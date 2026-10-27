"""
Find which test file, when imported, registers a broken 'core' or 'merid'
namespace package in sys.modules before test_dev_swarm.py is collected.

Run: py scripts/find_namespace_poisoner.py
"""
import subprocess, sys, os, json
from pathlib import Path

ROOT = Path(r"c:\Dev\MERID")
TESTS = ROOT / "tests"

# Collect all test files in collection order (approximated alphabetically)
test_files = sorted(TESTS.rglob("test_*.py"))

PROBE = """
import sys, importlib

# Simulate what conftest does
import types, contextvars, logging as _log
if "utils.logger" not in sys.modules:
    _ul = types.ModuleType("utils.logger")
    _ul.get_logger = _log.getLogger
    _ul.correlation_id_var = contextvars.ContextVar("c", default=None)
    _ul.get_correlation_id = lambda: None
    _ul.set_correlation_id = lambda x: None
    _ul._task_venue_var = contextvars.ContextVar("v", default=None)
    _ul._task_agent_id_var = contextvars.ContextVar("a", default=None)
    _ul._task_mode_var = contextvars.ContextVar("m", default=None)
    _ul._task_env_var = contextvars.ContextVar("e", default=None)
    _ul._task_tick_var = contextvars.ContextVar("t", default=None)
    sys.modules["utils.logger"] = _ul

sys.path.insert(0, r"c:\\Dev\\MERID")

# Import the suspect file
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_suspect", r"{file}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
except Exception:
    pass

# Check what 'core' and 'merid' resolve to
issues = []
for name in ("core", "merid", "core.dev_swarm", "merid.metrics", "merid.metrics.calibration"):
    m = sys.modules.get(name)
    if m is not None:
        loc = getattr(m, "__file__", None) or getattr(m, "__path__", None)
        loc_str = str(loc) if loc else "NO_FILE"
        if "tests" in loc_str.replace("\\\\", "/"):
            issues.append(f"  POISONED: {name!r} -> {loc_str}")
        elif loc is None:
            issues.append(f"  NAMESPACE: {name!r} -> no __file__ (namespace pkg)")

if issues:
    print("POISONER: {file}")
    for i in issues:
        print(i)
"""

print("Scanning test files for namespace poisoners...")
print("(This checks each file in isolation for sys.modules contamination)\n")

poisoners = []
for tf in test_files:
    rel = tf.relative_to(ROOT)
    script = PROBE.format(file=str(tf).replace("\\", "\\\\"))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(ROOT),
        timeout=15
    )
    output = (result.stdout + result.stderr).strip()
    if output:
        print(output)
        poisoners.append(str(rel))

print(f"\n=== Found {len(poisoners)} poisoner(s) ===")
for p in poisoners:
    print(" ", p)
