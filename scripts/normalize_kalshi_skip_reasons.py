"""Normalize pytest.skip reasons in tests/event_venues/kalshi to the machine-readable
P[0-3]-<AREA>: TRACKER-XXX: ... format defined in SKIP_TRACKER.md.

Usage:
    py -3.11 scripts/normalize_kalshi_skip_reasons.py

WARNING: This script rewrites test files in place. Review the diff before committing.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO / "tests" / "event_venues" / "kalshi"
TRACKER_FILE = TESTS_DIR / "SKIP_TRACKER.md"


_TRACKER_LINE_RE = re.compile(
    r"\|\s*(TRACKER-\d{3,})\s*\|\s*(P[0-3]-[A-Z0-9_]+)\s*\|\s*[`\"]?([^`\n|]+)[`\"]?\s*\|\s*([^|]+)\|\s*([^|]+)"
)


def _load_tracker_map() -> Dict[str, Tuple[str, str, str]]:
    mapping: Dict[str, Tuple[str, str, str, str]] = {}
    if not TRACKER_FILE.exists():
        print(f"Tracker file not found: {TRACKER_FILE}", file=sys.stderr)
        return mapping
    for line in TRACKER_FILE.read_text(encoding="utf-8").splitlines():
        m = _TRACKER_LINE_RE.search(line)
        if m:
            tracker, priority, module_raw, action, notes = m.groups()
            module = module_raw.strip().strip("`")
            mapping[module] = (tracker, priority, action.strip(), notes.strip())
    return mapping


def _build_reason(tracker: str, priority: str, notes: str) -> str:
    return f"{priority}: {tracker}: {notes}"


def _match_module_to_key(filename: str, mapping: Dict[str, Tuple[str, str, str, str]]) -> Optional[Tuple[str, str, str, str]]:
    for key, value in mapping.items():
        if key in filename or filename in key:
            return value
    return None


def _rewrite_file(path: Path, mapping: Dict[str, Tuple[str, str, str, str]]) -> bool:
    """Rewrite a single test file with standardized skip reasons."""
    original = path.read_text(encoding="utf-8")
    changed = False
    filename = path.name
    matched = _match_module_to_key(filename, mapping)
    if not matched:
        return False
    tracker, priority, _action, notes = matched
    new_reason = _build_reason(tracker, priority, notes)

    # Replace module-level pytestmark with the new reason
    module_mark_re = re.compile(
        r'^(pytestmark\s*=\s*pytest\.mark\.skip\s*\(\s*reason\s*=\s*)["\'].*?["\']\s*\)',
        re.MULTILINE,
    )

    def _sub_module(match: re.Match) -> str:
        nonlocal changed
        changed = True
        return f'{match.group(1)}"{new_reason}")'

    text = module_mark_re.sub(_sub_module, original)

    # Replace @pytest.mark.skip decorators in the file with the same reason
    decorator_re = re.compile(
        r'(@pytest\.mark\.skip\s*\(\s*reason\s*=\s*)["\'].*?["\']\s*\)',
        re.MULTILINE,
    )

    def _sub_decorator(match: re.Match) -> str:
        nonlocal changed
        changed = True
        return f'{match.group(1)}"{new_reason}")'

    text = decorator_re.sub(_sub_decorator, text)

    if changed:
        # Ensure only the expected test files are touched
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            print(f"SKIP (syntax error would be introduced): {path} ({exc})", file=sys.stderr)
            return False
        path.write_text(text, encoding="utf-8")
    return changed


def main() -> int:
    mapping = _load_tracker_map()
    if not mapping:
        return 1
    changed = []
    for py_file in sorted(TESTS_DIR.rglob("*.py")):
        if py_file.name == "conftest.py" or py_file.name == "SKIP_TRACKER.md":
            continue
        if _rewrite_file(py_file, mapping):
            changed.append(py_file.name)
    if changed:
        print(f"Normalized skip reasons in {len(changed)} files:")
        for name in changed:
            print(f"  - {name}")
    else:
        print("No files changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
