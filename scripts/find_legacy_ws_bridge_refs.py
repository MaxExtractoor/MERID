#!/usr/bin/env python
import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # assumes scripts/ at repo root

LEGACY_MODULE = "merid.event_venues.kalshi.ws_bridge"

# Patterns to catch imports and dynamic uses
PATTERNS = [
    re.compile(rf"\bfrom\s+{re.escape(LEGACY_MODULE)}\s+import\b"),
    re.compile(rf"\bimport\s+{re.escape(LEGACY_MODULE)}\b"),
    re.compile(rf"{re.escape(LEGACY_MODULE)}"),
    re.compile(r'importlib\.import_module\(\s*[\'"]' + re.escape(LEGACY_MODULE) + r'[\'"]\s*\)'),
]

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
}

def scan_file(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat in PATTERNS:
            if pat.search(line):
                hits.append((lineno, line.strip()))
                break
    return hits

def main():
    legacy_refs = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # prune directories
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

        for fname in filenames:
            if not fname.endswith((".py", ".pyi", ".md", ".yaml", ".yml", ".json")):
                continue
            fpath = Path(dirpath) / fname
            hits = scan_file(fpath)
            if hits:
                legacy_refs.append((fpath, hits))

    if not legacy_refs:
        print(f"No references to {LEGACY_MODULE} found.")
        sys.exit(0)

    print(f"Found references to {LEGACY_MODULE} in:")
    for fpath, hits in legacy_refs:
        print(f"\n{fpath}:")
        for lineno, line in hits:
            print(f"  {lineno}: {line}")

    # Non-zero exit so CI can fail
    sys.exit(1)

if __name__ == "__main__":
    main()
