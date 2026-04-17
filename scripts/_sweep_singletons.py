"""Sweep for unguarded singletons: 'if _x is None: _x = ...' without a nearby lock."""
import os, re

skip = {'__pycache__', '.git', 'archive', 'node_modules', 'deep_archive'}
findings = []

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in skip]
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        try:
            src = open(path, encoding='utf-8').read()
        except Exception:
            continue
        # Look for bare double-check pattern WITHOUT an enclosing lock
        # Pattern: 'if _varname is None:' followed by assignment on next line
        for m in re.finditer(r'(if (_\w+) is None:\s*\n\s+\2 =)', src):
            varname = m.group(2)
            # Check if a lock guards it (within 5 lines before)
            start = max(0, m.start() - 400)
            context = src[start:m.start()]
            # If there's a 'with _..._lock' or 'Lock()' in preceding context, it's guarded
            if not re.search(r'with \w+_lock\b|_singleton_lock|_\w+_lock\b', context):
                line_no = src[:m.start()].count('\n') + 1
                findings.append((path, line_no, varname))

for path, ln, var in sorted(findings):
    print(f"{path}:{ln}  var={var}")

print(f"\n--- {len(findings)} unguarded singletons found ---")
